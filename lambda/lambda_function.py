"""
YouTube naar MP3 Preek Converter - Optimized Lambda Function
Direct audio download met yt-dlp postprocessors (VEEL sneller!)
"""

import json
import os
import subprocess
import tempfile
import boto3
from datetime import datetime
import uuid
import logging
from typing import Dict, Optional, Tuple

# Import yt-dlp from layer
try:
    import yt_dlp
except ImportError:
    raise ImportError("yt-dlp not found. Make sure the Lambda Layer is attached.")

# Import ffmpeg path helper from layer
try:
    from ffmpeg_location import get_ffmpeg_path
    FFMPEG_PATH = get_ffmpeg_path()
except ImportError:
    FFMPEG_PATH = 'ffmpeg'  # Fallback to system ffmpeg
    logging.warning("ffmpeg_location module not found, using system ffmpeg")

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

# Environment variables
S3_BUCKET = os.environ.get('S3_BUCKET')
COOKIES_SECRET_NAME = os.environ.get('COOKIES_SECRET_NAME', 'mp3maker/youtube-cookies')
TEMP_DIR = '/tmp'

# Validate required environment variables
if not S3_BUCKET:
    raise ValueError("S3_BUCKET environment variable is required")

logger.info(f"Lambda initialized - S3 Bucket: {S3_BUCKET}, Cookies Secret: {COOKIES_SECRET_NAME}")


def lambda_handler(event, context):
    """
    Main Lambda handler voor YouTube naar MP3 conversie met direct audio download.
    """
    request_id = context.aws_request_id if context else str(uuid.uuid4())
    logger.info(f"Processing request {request_id}: {json.dumps(event, default=str)}")
    
    try:
        # 1. Validate and parse input
        youtube_url, start_time, end_time, bitrate = validate_and_parse_input(event)
        
        # 2. Generate unique identifiers
        mp3_filename = f"preek_{request_id[:8]}.mp3"
        temp_audio_path = os.path.join(TEMP_DIR, f"{request_id[:8]}_audio")
        final_mp3_path = os.path.join(TEMP_DIR, mp3_filename)
        
        logger.info(f"Processing: {youtube_url} ({start_time}s-{end_time}s) → {mp3_filename}")
        
        # 3. Download audio directly with segment extraction
        if not download_audio_segment_directly(youtube_url, final_mp3_path, start_time, end_time, bitrate):
            raise Exception("Failed to download and process audio from YouTube")
        
        # 4. Upload to S3
        s3_key = f"mp3/{mp3_filename}"
        upload_to_s3_with_metadata(final_mp3_path, s3_key, {
            'youtube_url': youtube_url,
            'start_time': str(start_time),
            'end_time': str(end_time),
            'duration': str(end_time - start_time),
            'bitrate': bitrate,
            'request_id': request_id,
            'method': 'direct_audio_download'
        })
        
        # 5. Cleanup
        cleanup_temporary_files([final_mp3_path])
        
        # 6. Return success response
        response = create_success_response(request_id, s3_key, mp3_filename, end_time - start_time)
        logger.info(f"Request {request_id} completed successfully")
        return response
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Request {request_id} failed: {error_msg}", exc_info=True)
        return create_error_response(error_msg, request_id)


def download_audio_segment_directly(url: str, output_path: str, start_time: int, end_time: int, bitrate: str) -> bool:
    """
    Download audio segment directly using yt-dlp with FFmpeg postprocessor.
    VEEL sneller dan eerst video downloaden!
    """
    # Get cookies if available
    cookies_data = get_youtube_cookies()
    cookie_file_path = create_cookie_file(cookies_data) if cookies_data else None
    
    duration = end_time - start_time
    
    # yt-dlp configuratie voor direct audio download met segment extractie
    configs = []
    
    # Config 1: Met cookies, direct audio download + segment
    if cookie_file_path:
        configs.append({
            'name': 'Direct Audio with Cookies',
            'options': {
                # Download alleen audio streams
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio',
                'cookiefile': cookie_file_path,
                'outtmpl': output_path.replace('.mp3', '.%(ext)s'),
                
                # FFmpeg postprocessor voor extractie en conversie
                'postprocessors': [
                    {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': bitrate.replace('k', ''),  # '96k' → '96'
                        'nopostoverwrites': False,
                    },
                    {
                        'key': 'FFmpegFixup',
                        'extracted_audio': True,
                    }
                ],
                
                # Segment extractie via FFmpeg
                'external_downloader': 'ffmpeg',
                'external_downloader_args': {
                    'ffmpeg': [
                        '-ss', str(start_time),  # Start tijd
                        '-t', str(duration),     # Duur
                        '-ac', '1',              # Mono
                        '-ar', '44100',          # Sample rate
                    ]
                },
                
                # Headers voor anti-bot
                'http_headers': {
                    'User-Agent': cookies_data.get('user_agent', 
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'),
                    'Accept': 'audio/webm,audio/ogg,audio/*,*/*;q=0.9',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                'sleep_interval': 2,
                'retries': 5,
            }
        })
    
    # Config 2: Zonder cookies, audio-only met segment
    configs.append({
        'name': 'Direct Audio without Cookies',
        'options': {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/worst',
            'outtmpl': output_path.replace('.mp3', '.%(ext)s'),
            
            # Postprocessors
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': bitrate.replace('k', ''),
                    'nopostoverwrites': False,
                }
            ],
            
            # Segment extractie
            'external_downloader': 'ffmpeg',
            'external_downloader_args': {
                'ffmpeg': [
                    '-ss', str(start_time),
                    '-t', str(duration),
                    '-ac', '1',
                    '-ar', '44100',
                ]
            },
            
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            },
            'sleep_interval': 3,
            'retries': 8,
        }
    })
    
    # Config 3: Fallback - download volledig audio bestand, dan segment
    configs.append({
        'name': 'Fallback Full Audio + Segment',
        'options': {
            'format': 'bestaudio/worst',
            'outtmpl': output_path.replace('.mp3', '_full.%(ext)s'),
            'extract_flat': False,
            'postprocessors': [],  # Geen direct processing
        }
    })
    
    # Probeer elke configuratie
    for i, config in enumerate(configs):
        logger.info(f"Attempting {config['name']} (attempt {i+1}/{len(configs)})")
        
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                **config['options']
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Starting download with {config['name']}...")
                ydl.download([url])
                
                # Check if direct output exists
                if os.path.exists(output_path):
                    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    logger.info(f"Direct audio download successful: {file_size_mb:.2f} MB")
                    
                    # Cleanup cookie file
                    if cookie_file_path and os.path.exists(cookie_file_path):
                        os.remove(cookie_file_path)
                    
                    return True
                
                # Check for alternative extensions and convert if needed
                temp_files = [f for f in os.listdir(TEMP_DIR) if f.startswith(request_id[:8])]
                for temp_file in temp_files:
                    temp_file_path = os.path.join(TEMP_DIR, temp_file)
                    if temp_file_path != output_path and os.path.exists(temp_file_path):
                        logger.info(f"Found intermediate file: {temp_file}")
                        
                        # For fallback config, we need to manually extract segment
                        if config['name'].startswith('Fallback'):
                            if extract_segment_with_ffmpeg(temp_file_path, output_path, start_time, end_time, bitrate):
                                os.remove(temp_file_path)  # Cleanup intermediate
                                if cookie_file_path and os.path.exists(cookie_file_path):
                                    os.remove(cookie_file_path)
                                return True
                        else:
                            # Rename/move file
                            os.rename(temp_file_path, output_path)
                            if cookie_file_path and os.path.exists(cookie_file_path):
                                os.remove(cookie_file_path)
                            return True
                
                logger.warning(f"{config['name']}: No output file found")
                    
        except yt_dlp.DownloadError as e:
            error_msg = str(e).lower()
            logger.warning(f"{config['name']} failed: {e}")
            
            # Check for permanent errors
            if any(phrase in error_msg for phrase in 
                   ['private video', 'video unavailable', 'copyright', 'removed']):
                logger.error(f"Permanent error detected: {e}")
                break
                
        except Exception as e:
            logger.warning(f"{config['name']} exception: {e}")
    
    # Cleanup cookie file on failure
    if cookie_file_path and os.path.exists(cookie_file_path):
        os.remove(cookie_file_path)
    
    logger.error("All audio download configurations failed")
    return False


def extract_segment_with_ffmpeg(input_path: str, output_path: str, start_time: int, end_time: int, bitrate: str) -> bool:
    """
    Fallback: Extract segment using FFmpeg directly.
    """
    duration = end_time - start_time
    
    cmd = [
        FFMPEG_PATH,
        '-i', input_path,
        '-ss', str(start_time),
        '-t', str(duration),
        '-acodec', 'libmp3lame',
        '-ab', bitrate,
        '-ac', '1',
        '-ar', '44100',
        '-y',
        output_path
    ]
    
    try:
        logger.info(f"FFmpeg segment extraction: {start_time}s-{end_time}s")
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
        
        if os.path.exists(output_path):
            file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            logger.info(f"FFmpeg extraction successful: {file_size_mb:.2f} MB")
            return True
        return False
        
    except Exception as e:
        logger.error(f"FFmpeg extraction failed: {e}")
        return False


# Helper functies (reuse from previous version)
def validate_and_parse_input(event: dict) -> Tuple[str, int, int, str]:
    """Validate and parse Lambda event input."""
    if 'youtube_url' not in event:
        raise ValueError("Missing required field: youtube_url")
    if 'start_time' not in event:
        raise ValueError("Missing required field: start_time")  
    if 'end_time' not in event:
        raise ValueError("Missing required field: end_time")
    
    youtube_url = event['youtube_url'].strip()
    if not youtube_url or not any(domain in youtube_url.lower() for domain in ['youtube.com', 'youtu.be']):
        raise ValueError("Invalid YouTube URL format")
    
    start_time = parse_time_to_seconds(event['start_time'])
    end_time = parse_time_to_seconds(event['end_time'])
    
    if start_time >= end_time:
        raise ValueError(f"Start time ({start_time}s) must be before end time ({end_time}s)")
    
    if end_time - start_time > 7200:  # 2 hours max
        raise ValueError("Audio segment too long (max 2 hours)")
    
    bitrate = event.get('bitrate', '96k')
    return youtube_url, start_time, end_time, bitrate


def parse_time_to_seconds(time_input) -> int:
    """Convert time string to seconds."""
    if isinstance(time_input, (int, float)):
        return int(time_input)
    
    time_str = str(time_input).strip()
    parts = time_str.split(':')
    
    try:
        if len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
        else:
            return int(parts[0])
    except ValueError as e:
        raise ValueError(f"Could not parse time '{time_str}': {e}")


def get_youtube_cookies() -> Optional[Dict]:
    """Retrieve YouTube cookies from AWS Secrets Manager."""
    try:
        logger.info(f"Retrieving cookies from Secrets Manager: {COOKIES_SECRET_NAME}")
        response = secrets_client.get_secret_value(SecretId=COOKIES_SECRET_NAME)
        secret_data = json.loads(response['SecretString'])
        logger.info("Successfully retrieved YouTube cookies")
        return secret_data
    except secrets_client.exceptions.ResourceNotFoundException:
        logger.info("Cookies secret not found (optional)")
        return None
    except Exception as e:
        logger.warning(f"Could not retrieve cookies: {e}")
        return None


def create_cookie_file(cookies_data: Dict) -> Optional[str]:
    """Create Netscape format cookie file."""
    if not cookies_data or 'cookies' not in cookies_data:
        return None
    
    cookie_file_path = os.path.join(TEMP_DIR, f"cookies_{uuid.uuid4().hex[:8]}.txt")
    
    try:
        with open(cookie_file_path, 'w') as f:
            f.write("# Netscape HTTP Cookie File\n# Generated for yt-dlp\n\n")
            
            cookies = cookies_data['cookies']
            
            if isinstance(cookies, str):
                for pair in cookies.split(';'):
                    if '=' in pair and pair.strip():
                        name, value = pair.strip().split('=', 1)
                        if name and value:
                            f.write(f".youtube.com\tTRUE\t/\tFALSE\t2147483647\t{name}\t{value}\n")
            
            elif isinstance(cookies, list):
                for cookie in cookies:
                    if isinstance(cookie, dict):
                        name = cookie.get('name', '')
                        value = cookie.get('value', '')
                        if name and value:
                            domain = cookie.get('domain', '.youtube.com')
                            if not domain.startswith('.'):
                                domain = f".{domain}"
                            secure = 'TRUE' if cookie.get('secure', False) else 'FALSE'
                            expires = cookie.get('expires', 2147483647)
                            f.write(f"{domain}\tTRUE\t/\t{secure}\t{expires}\t{name}\t{value}\n")
        
        logger.info(f"Cookie file created: {cookie_file_path}")
        return cookie_file_path
        
    except Exception as e:
        logger.error(f"Failed to create cookie file: {e}")
        return None


def upload_to_s3_with_metadata(file_path: str, s3_key: str, metadata: dict):
    """Upload MP3 file to S3 with metadata."""
    try:
        upload_metadata = {
            'created-at': datetime.utcnow().isoformat(),
            'lambda-function': 'youtube-mp3-converter-v2',
            **{k.replace('_', '-'): str(v) for k, v in metadata.items()}
        }
        
        with open(file_path, 'rb') as f:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=f,
                ContentType='audio/mpeg',
                Metadata=upload_metadata,
                ServerSideEncryption='AES256'
            )
        
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        logger.info(f"Successfully uploaded to S3: s3://{S3_BUCKET}/{s3_key} ({file_size_mb:.2f} MB)")
        
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        raise


def cleanup_temporary_files(file_paths: list):
    """Clean up temporary files."""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Cleaned up: {path}")
        except Exception as e:
            logger.warning(f"Could not clean up {path}: {e}")


def create_success_response(request_id: str, s3_key: str, filename: str, duration: int) -> dict:
    """Create success response."""
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'success': True,
            'message': 'Audio processing completed successfully',
            'data': {
                'request_id': request_id,
                's3_bucket': S3_BUCKET,
                's3_key': s3_key,
                'filename': filename,
                'duration_seconds': duration,
                'download_expires_in': '24 hours',
                'method': 'direct_audio_download'
            }
        })
    }


def create_error_response(error_message: str, request_id: str = None) -> dict:
    """Create error response."""
    return {
        'statusCode': 500,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'success': False,
            'error': error_message,
            'request_id': request_id,
            'message': 'Audio processing failed'
        })
    }


# For local testing
if __name__ == "__main__":
    test_event = {
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "start_time": "0:10",
        "end_time": "0:30",
        "bitrate": "96k"
    }
    
    class MockContext:
        aws_request_id = "test-request-123"
    
    os.environ['S3_BUCKET'] = 'test-bucket'
    os.environ['COOKIES_SECRET_NAME'] = 'test/cookies'
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))