#!/usr/bin/env python3
"""
YouTube naar MP3 Converter voor Preken
Lokaal ontwikkelscript voor Sprint 0
"""

import os
import sys
import subprocess
import argparse
from datetime import timedelta
import tempfile
import shutil
from pathlib import Path

# Probeer yt-dlp te importeren
try:
    import yt_dlp
except ImportError:
    print("ERROR: yt-dlp is niet geïnstalleerd. Installeer met: pip install yt-dlp")
    sys.exit(1)


def time_to_seconds(time_str):
    """
    Converteer tijd string (HH:MM:SS of MM:SS) naar seconden.
    """
    parts = time_str.split(':')
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    else:
        return int(parts[0])


def check_ffmpeg():
    """
    Controleer of FFmpeg geïnstalleerd is.
    """
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: FFmpeg is niet geïnstalleerd of niet in PATH.")
        print("Op macOS: brew install ffmpeg")
        return False


def download_youtube_video(url, output_path):
    """
    Download YouTube video naar opgegeven pad.
    """
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [download_progress_hook],
    }
    
    print(f"📥 Downloaden van YouTube video...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
            return True
        except Exception as e:
            print(f"ERROR bij downloaden: {e}")
            return False


def download_progress_hook(d):
    """
    Toon download voortgang.
    """
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', 'N/A')
        speed = d.get('_speed_str', 'N/A')
        print(f"\r⏬ Voortgang: {percent} - Snelheid: {speed}", end='', flush=True)
    elif d['status'] == 'finished':
        print("\n✅ Download voltooid!")


def extract_audio_segment(video_path, output_path, start_time, end_time, bitrate='96k'):
    """
    Extract audio segment van video en converteer naar MP3.
    
    Args:
        video_path: Pad naar input video
        output_path: Pad voor output MP3
        start_time: Start tijd in seconden
        end_time: Eind tijd in seconden
        bitrate: Audio bitrate (bijv. '64k', '96k', '128k')
    """
    duration = end_time - start_time
    
    # FFmpeg commando samenstellen
    # -ss voor start_time komt VOOR -i voor snellere seek
    # -t voor duration
    # -ac 1 voor mono (halveert bestandsgrootte)
    # -ar 44100 voor sample rate
    cmd = [
        'ffmpeg',
        '-ss', str(start_time),
        '-i', video_path,
        '-t', str(duration),
        '-vn',  # Geen video
        '-acodec', 'libmp3lame',
        '-ab', bitrate,
        '-ac', '1',  # Mono
        '-ar', '44100',  # Sample rate
        '-y',  # Overschrijf output
        output_path
    ]
    
    print(f"\n🎵 Audio extractie gestart...")
    print(f"   Start: {timedelta(seconds=start_time)}")
    print(f"   Eind: {timedelta(seconds=end_time)}")
    print(f"   Duur: {timedelta(seconds=duration)}")
    print(f"   Bitrate: {bitrate} (mono)")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("✅ Audio extractie voltooid!")
        
        # Toon bestandsgrootte
        file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
        print(f"📁 Bestandsgrootte: {file_size:.2f} MB")
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR bij audio extractie: {e}")
        print(f"FFmpeg stderr: {e.stderr}")
        return False


def main():
    """
    Hoofdfunctie voor het script.
    """
    parser = argparse.ArgumentParser(
        description='Converteer een deel van een YouTube video naar MP3 (voor preken)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Voorbeelden:
  %(prog)s https://youtube.com/watch?v=XXX 10:30 45:20
  %(prog)s https://youtube.com/watch?v=XXX 10:30 45:20 --bitrate 64k
  %(prog)s https://youtube.com/watch?v=XXX 1:10:30 1:45:20 --output preek_2024.mp3
        """
    )
    
    parser.add_argument('url', help='YouTube URL')
    parser.add_argument('start_time', help='Start tijd (MM:SS of HH:MM:SS)')
    parser.add_argument('end_time', help='Eind tijd (MM:SS of HH:MM:SS)')
    parser.add_argument('--output', '-o', default='preek.mp3', help='Output bestandsnaam (default: preek.mp3)')
    parser.add_argument('--bitrate', '-b', default='96k', 
                       choices=['64k', '96k', '128k'], 
                       help='Audio bitrate (default: 96k)')
    parser.add_argument('--keep-video', action='store_true', 
                       help='Behoud het gedownloade videobestand')
    
    args = parser.parse_args()
    
    # Controleer FFmpeg
    if not check_ffmpeg():
        return 1
    
    # Converteer tijden naar seconden
    start_seconds = time_to_seconds(args.start_time)
    end_seconds = time_to_seconds(args.end_time)
    
    if start_seconds >= end_seconds:
        print("ERROR: Start tijd moet voor eind tijd liggen!")
        return 1
    
    # Maak een tijdelijke directory
    with tempfile.TemporaryDirectory() as temp_dir:
        video_path = os.path.join(temp_dir, 'video.mp4')
        
        # Download video
        if not download_youtube_video(args.url, video_path):
            return 1
        
        # Extract audio
        output_path = os.path.abspath(args.output)
        if not extract_audio_segment(video_path, output_path, start_seconds, end_seconds, args.bitrate):
            return 1
        
        # Optioneel: behoud video
        if args.keep_video:
            video_output = output_path.replace('.mp3', '_video.mp4')
            shutil.copy2(video_path, video_output)
            print(f"📹 Video opgeslagen als: {video_output}")
    
    print(f"\n🎉 Klaar! MP3 opgeslagen als: {output_path}")
    return 0


def test_functions():
    """
    Test functie voor ontwikkeling - test de componenten los.
    """
    print("🧪 Test modus...")
    
    # Test 1: FFmpeg check
    print("\n1. FFmpeg check:")
    if check_ffmpeg():
        print("   ✅ FFmpeg gevonden")
    
    # Test 2: Tijd conversie
    print("\n2. Tijd conversie tests:")
    test_times = ["30", "1:30", "1:30:45"]
    for t in test_times:
        seconds = time_to_seconds(t)
        print(f"   {t} -> {seconds} seconden ({timedelta(seconds=seconds)})")
    
    # Test 3: yt-dlp info extract (zonder download)
    print("\n3. yt-dlp test (info only):")
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Rick Roll voor test
    
    ydl_opts = {'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(test_url, download=False)
            print(f"   Titel: {info.get('title', 'N/A')}")
            print(f"   Duur: {info.get('duration', 'N/A')} seconden")
            print("   ✅ yt-dlp werkt correct")
        except Exception as e:
            print(f"   ❌ yt-dlp error: {e}")


if __name__ == '__main__':
    # Uncomment voor test modus:
    # test_functions()
    # sys.exit(0)
    
    sys.exit(main())