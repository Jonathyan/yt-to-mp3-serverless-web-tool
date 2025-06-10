#!/usr/bin/env python3
"""
Cookie Format Validator & Fixer
Fix cookie format issues voor AWS Secrets Manager
"""

import json
import sys
from datetime import datetime, timedelta


def validate_and_fix_cookies(input_file: str, output_file: str = None):
    """
    Validate en fix cookie format voor Secrets Manager.
    """
    try:
        with open(input_file, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error reading {input_file}: {e}")
        return False
    
    print(f"🔍 Analyzing cookies from {input_file}")
    
    # Extract cookies
    cookies = data.get('cookies', [])
    if isinstance(cookies, str):
        print("📝 Converting cookie string to objects...")
        cookies = parse_cookie_string(cookies)
    
    print(f"📊 Found {len(cookies)} cookies")
    
    # Filter and validate YouTube cookies
    youtube_cookies = []
    youtube_cookie_names = {
        'VISITOR_INFO1_LIVE', 'YSC', 'CONSENT', 'PREF', '__Secure-YEC',
        'SID', 'HSID', 'SSID', 'APISID', 'SAPISID', 'LOGIN_INFO', 'GPS'
    }
    
    for cookie in cookies:
        if isinstance(cookie, dict):
            name = cookie.get('name', '')
            value = cookie.get('value', '')
        else:
            continue
            
        # Skip empty cookies
        if not name or not value:
            print(f"⚠️  Skipping empty cookie: {name}")
            continue
            
        # Check if YouTube related
        is_youtube = (
            name in youtube_cookie_names or
            any(pattern in name.upper() for pattern in ['GOOGLE', 'YOUTUBE', 'YT_', '__SECURE-'])
        )
        
        if is_youtube:
            # Clean up cookie object
            clean_cookie = {
                'name': name,
                'value': value,
                'domain': cookie.get('domain', '.youtube.com'),
                'path': cookie.get('path', '/'),
                'secure': bool(cookie.get('secure', False)),
                'expires': int(cookie.get('expires', 
                    int((datetime.now() + timedelta(days=365)).timestamp())))
            }
            youtube_cookies.append(clean_cookie)
            print(f"✅ Keeping: {name}")
        else:
            print(f"🚫 Filtering out: {name}")
    
    print(f"\n📋 Final count: {len(youtube_cookies)} YouTube cookies")
    
    # Create fixed secret data
    fixed_data = {
        'cookies': youtube_cookies,
        'cookie_string': '; '.join([f"{c['name']}={c['value']}" for c in youtube_cookies]),
        'user_agent': data.get('user_agent', 
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'),
        'browser': data.get('browser', 'Unknown'),
        'extracted_at': datetime.now().isoformat(),
        'fixed_at': datetime.now().isoformat(),
        'cookie_count': len(youtube_cookies)
    }
    
    # Save fixed data
    output_file = output_file or input_file.replace('.json', '_fixed.json')
    
    with open(output_file, 'w') as f:
        json.dump(fixed_data, f, indent=2)
    
    print(f"\n💾 Fixed cookies saved to: {output_file}")
    
    # Show sample cookies
    print(f"\n🔑 Sample cookies:")
    for cookie in youtube_cookies[:5]:
        value_preview = cookie['value'][:20] + "..." if len(cookie['value']) > 20 else cookie['value']
        print(f"  {cookie['name']}: {value_preview}")
    
    # Generate upload command
    print(f"\n☁️  Upload to AWS Secrets Manager:")
    print(f"aws secretsmanager put-secret-value \\")
    print(f"    --secret-id mp3maker/youtube-cookies \\")
    print(f"    --secret-string file://{output_file}")
    
    return True


def parse_cookie_string(cookie_string: str) -> list:
    """
    Parse cookie string into objects.
    """
    cookies = []
    
    for pair in cookie_string.split(';'):
        pair = pair.strip()
        if '=' in pair:
            name, value = pair.split('=', 1)
            cookies.append({
                'name': name.strip(),
                'value': value.strip(),
                'domain': '.youtube.com',
                'path': '/',
                'secure': False,
                'expires': int((datetime.now() + timedelta(days=365)).timestamp())
            })
    
    return cookies


def create_netscape_format(cookies: list) -> str:
    """
    Create Netscape format string voor debugging.
    """
    lines = ["# Netscape HTTP Cookie File", "# Fixed format", ""]
    
    for cookie in cookies:
        domain = cookie.get('domain', '.youtube.com')
        if not domain.startswith('.'):
            domain = f".{domain}"
            
        secure = 'TRUE' if cookie.get('secure', False) else 'FALSE'
        expires = cookie.get('expires', 2147483647)
        
        line = f"{domain}\tTRUE\t/\t{secure}\t{expires}\t{cookie['name']}\t{cookie['value']}"
        lines.append(line)
    
    return '\n'.join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 cookie_fixer.py <input_cookies.json> [output_cookies.json]")
        print("\nExample:")
        print("  python3 cookie_fixer.py brave-youtube-cookies.json")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    print("🍪 Cookie Format Validator & Fixer")
    print("=" * 40)
    
    success = validate_and_fix_cookies(input_file, output_file)
    
    if success:
        print("\n🎉 Cookie fixing completed successfully!")
        print("\n💡 Next steps:")
        print("1. Review the fixed cookie file")
        print("2. Upload to AWS Secrets Manager")
        print("3. Test your Lambda function")
    else:
        print("\n❌ Cookie fixing failed")
        sys.exit(1)


if __name__ == '__main__':
    main()