#!/usr/bin/env python3
"""
Brave Browser Cookie Extractor voor YouTube
Extraheert cookies uit Brave browser op macOS
"""

import json
import sqlite3
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
from datetime import datetime


def find_brave_profile_paths():
    """
    Zoek alle Brave browser profile paden op macOS.
    """
    brave_base_path = Path.home() / "Library/Application Support/BraveSoftware/Brave-Browser"
    
    if not brave_base_path.exists():
        print("❌ Brave browser data folder not found")
        print(f"Expected path: {brave_base_path}")
        return []
    
    # Zoek alle profiles (Default, Profile 1, Profile 2, etc.)
    profiles = []
    
    # Default profile
    default_cookies = brave_base_path / "Default/Cookies"
    if default_cookies.exists():
        profiles.append(("Default", default_cookies))
    
    # Numbered profiles
    for i in range(1, 10):  # Check Profile 1-9
        profile_cookies = brave_base_path / f"Profile {i}/Cookies"
        if profile_cookies.exists():
            profiles.append((f"Profile {i}", profile_cookies))
    
    return profiles


def get_brave_cookies(profile_name, cookies_path):
    """
    Extract cookies from Brave browser profile.
    """
    print(f"📂 Extracting cookies from {profile_name}: {cookies_path}")
    
    # Copy database to avoid locking issues
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
        try:
            shutil.copy2(cookies_path, tmp_file.name)
            temp_db_path = tmp_file.name
        except Exception as e:
            print(f"❌ Could not copy cookies database: {e}")
            print("💡 Make sure Brave browser is closed")
            return None
    
    try:
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        
        # Query YouTube and Google cookies
        cursor.execute("""
            SELECT name, value, host_key, path, expires_utc, is_secure, is_httponly, creation_utc
            FROM cookies 
            WHERE (host_key LIKE '%youtube.com%' 
                   OR host_key LIKE '%google.com%'
                   OR host_key LIKE '%googlevideo.com%'
                   OR host_key LIKE '%ggpht.com%'
                   OR host_key LIKE '%ytimg.com%')
            ORDER BY creation_utc DESC
        """)
        
        cookies = []
        for row in cursor.fetchall():
            name, value, domain, path, expires, secure, httponly, creation = row
            
            # Convert Chrome timestamp to Unix timestamp
            # Chrome timestamps are microseconds since Jan 1, 1601
            expires_unix = (expires / 1000000) - 11644473600 if expires else 9999999999
            creation_unix = (creation / 1000000) - 11644473600 if creation else 0
            
            cookie = {
                'name': name,
                'value': value,
                'domain': domain,
                'path': path,
                'expires': int(expires_unix),
                'secure': bool(secure),
                'httponly': bool(httponly),
                'creation_time': int(creation_unix)
            }
            cookies.append(cookie)
        
        conn.close()
        os.unlink(temp_db_path)
        
        print(f"✅ Found {len(cookies)} cookies from {profile_name}")
        return cookies
        
    except Exception as e:
        print(f"❌ Error extracting cookies from {profile_name}: {e}")
        if os.path.exists(temp_db_path):
            os.unlink(temp_db_path)
        return None


def show_cookie_summary(cookies, profile_name):
    """
    Toon een samenvatting van de gevonden cookies.
    """
    if not cookies:
        return
    
    print(f"\n📊 Cookie Summary for {profile_name}:")
    print("-" * 50)
    
    # Groepeer cookies per domain
    domains = {}
    for cookie in cookies:
        domain = cookie['domain']
        if domain not in domains:
            domains[domain] = []
        domains[domain].append(cookie)
    
    for domain, domain_cookies in domains.items():
        print(f"🌐 {domain}: {len(domain_cookies)} cookies")
        
        # Toon belangrijke cookies
        important_names = ['CONSENT', 'VISITOR_INFO1_LIVE', '__Secure-YEC', 'PREF', 'SID', 'HSID', 'SSID']
        important_found = [c for c in domain_cookies if c['name'] in important_names]
        
        if important_found:
            for cookie in important_found[:3]:
                value_preview = cookie['value'][:30] + "..." if len(cookie['value']) > 30 else cookie['value']
                print(f"  🔑 {cookie['name']}: {value_preview}")


def cookies_to_netscape_format(cookies):
    """
    Convert cookies to Netscape format string.
    """
    lines = ["# Netscape HTTP Cookie File", "# This is a generated file! Do not edit.", ""]
    
    for cookie in cookies:
        # Netscape format: domain, flag, path, secure, expiration, name, value
        domain = cookie['domain']
        flag = "TRUE"  # domain flag
        path = cookie['path']
        secure = "TRUE" if cookie['secure'] else "FALSE"
        expiration = str(cookie['expires'])
        name = cookie['name']
        value = cookie['value']
        
        line = f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}"
        lines.append(line)
    
    return "\n".join(lines)


def save_cookies_for_aws(cookies, profile_name):
    """
    Save cookies in format for AWS Secrets Manager.
    """
    if not cookies:
        print("❌ No cookies to save")
        return
    
    # Prepare secret data
    secret_data = {
        'cookies': cookies,  # Full cookie objects
        'cookie_string': "; ".join([f"{c['name']}={c['value']}" for c in cookies]),  # Simple string format
        'netscape_format': cookies_to_netscape_format(cookies),  # Netscape format
        'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'browser': 'Brave',
        'profile': profile_name,
        'extracted_at': datetime.now().isoformat(),
        'cookie_count': len(cookies)
    }
    
    # Save to file
    filename = f'cookies/brave-youtube-cookies-{profile_name.lower().replace(" ", "-")}.json'
    with open(filename, 'w') as f:
        json.dump(secret_data, f, indent=2)
    
    print(f"💾 Cookies saved to: {filename}")
    
    # Also save Netscape format file (useful for other tools)
    netscape_filename = f'cookies/brave-cookies-{profile_name.lower().replace(" ", "-")}.txt'
    with open(netscape_filename, 'w') as f:
        f.write(secret_data['netscape_format'])
    
    print(f"💾 Netscape format saved to: {netscape_filename}")
    
    return filename


def upload_to_secrets_manager(filename):
    """
    Upload cookies to AWS Secrets Manager.
    """
    print(f"\n☁️  Upload to AWS Secrets Manager:")
    print("=" * 50)
    print("Run this command to upload:")
    print(f"aws secretsmanager put-secret-value \\")
    print(f"    --secret-id mp3maker/youtube-cookies \\")
    print(f"    --secret-string file://{filename}")
    
    print("\nOr create new secret:")
    print(f"aws secretsmanager create-secret \\")
    print(f"    --name mp3maker/youtube-cookies \\")
    print(f"    --description 'YouTube cookies from Brave browser' \\")
    print(f"    --secret-string file://{filename}")


def main():
    """
    Main function to extract Brave cookies.
    """
    print("🦁 Brave Browser Cookie Extractor for YouTube")
    print("=" * 50)
    
    # Find Brave profiles
    profiles = find_brave_profile_paths()
    
    if not profiles:
        print("❌ No Brave browser profiles found")
        print("\n💡 Troubleshooting:")
        print("1. Make sure Brave browser is installed")
        print("2. Make sure you've visited YouTube at least once")
        print("3. Check if Brave is running and close it")
        return
    
    print(f"🔍 Found {len(profiles)} Brave profile(s):")
    for i, (name, path) in enumerate(profiles):
        print(f"  {i+1}. {name}")
    
    # Extract cookies from each profile
    all_cookies = {}
    
    for profile_name, cookies_path in profiles:
        print(f"\n🍪 Processing {profile_name}...")
        cookies = get_brave_cookies(profile_name, cookies_path)
        
        if cookies:
            all_cookies[profile_name] = cookies
            show_cookie_summary(cookies, profile_name)
        else:
            print(f"❌ No cookies found in {profile_name}")
    
    if not all_cookies:
        print("\n❌ No cookies extracted from any profile")
        print("\n💡 Make sure:")
        print("1. Brave browser is completely closed")
        print("2. You've logged into YouTube in Brave")
        print("3. You have permission to read the cookies file")
        return
    
    # Let user choose which profile to use
    if len(all_cookies) == 1:
        profile_name = list(all_cookies.keys())[0]
        cookies = all_cookies[profile_name]
    else:
        print(f"\n🤔 Multiple profiles found. Which one to use?")
        profile_names = list(all_cookies.keys())
        for i, name in enumerate(profile_names):
            cookie_count = len(all_cookies[name])
            print(f"  {i+1}. {name} ({cookie_count} cookies)")
        
        try:
            choice = int(input("\nEnter choice (1-{}): ".format(len(profile_names)))) - 1
            if 0 <= choice < len(profile_names):
                profile_name = profile_names[choice]
                cookies = all_cookies[profile_name]
            else:
                print("❌ Invalid choice")
                return
        except ValueError:
            print("❌ Invalid input")
            return
    
    # Save cookies
    filename = save_cookies_for_aws(cookies, profile_name)
    
    # Show upload instructions
    upload_to_secrets_manager(filename)
    
    print(f"\n🎉 Success! Extracted {len(cookies)} cookies from {profile_name}")
    print(f"📁 Files created:")
    print(f"  - {filename}")
    print(f"  - brave-cookies-{profile_name.lower().replace(' ', '-')}.txt")


if __name__ == '__main__':
    main()