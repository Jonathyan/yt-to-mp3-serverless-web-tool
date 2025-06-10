"""
YouTube naar MP3 Preek Converter - Lambda Function
Enhanced version with cookie support and consistent configuration
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

# AWS clients - initialized once for efficiency
s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

# Environment variables - consistent with deploy-lambda.sh
S3_BUCKET = os.environ.get('S3_BUCKET')
COOKIES_SECRET_NAME = os.environ.get('COOKIES_SECRET_NAME', 'mp3maker/youtube-cookies')
TEMP_DIR = '/tmp'  # Lambda's writable directory

# Validate required environment variables
if not S3_BUCKET:
    raise ValueError("S3_BUCKET environment variable is required")

logger.info(f"Lambda initialized - S3 Bucket: {S3_BUCKET}, Cookies Secret: {COOKIES_SECRET_NAME}")


def lambda_handler(event, context):
    """
    Main Lambda handler voor YouTube naar MP3 conversie.
    
    Expected event format:
    {
        "youtube_url": "https://youtube.com/watch?v=...",
        "start_time": "10:30",  # HH:MM:SS, MM:SS, or seconds
        "end_time": "45:20",    # HH:MM:SS, MM:SS, or seconds  
        "bitrate": "96k"        # optional, default 96k
    }
    
    Returns:
    {
        "statusCode": 200|500,
        "body": "{json_response}"
    }
    """
    request_id = context.aws_request_id if context else str(uuid.uuid4())
    logger.info(f"Processing request {request_id}: {json.dumps(event, default=str)}")
    
    try:
        # 1. Validate and parse input
        youtube_url, start_time, end_time, bitrate = validate_and_parse_input(event)
        
        # 2. Generate unique identifiers
        mp3_filename = f"preek_{request_id[:8]}.mp3"
        video_path = os.path.join(TEMP_DIR, f"{request_id[:8]}_video")
        mp3_path = os.path.join(TEMP_DIR, mp3_filename)
        
        logger.info(f"Processing: {youtube_url} ({start_time}s-{end_time}s) → {mp3_filename}")
        
        # 3. Download video with cookie support
        if not download_video_with_cookies(youtube_url, video_path):
            raise Exception("Failed to download video from YouTube")
        
        # 4. Extract audio segment
        if not extract_audio_segment(video_path, mp3_path, start_time, end_time, bitrate):
            raise Exception("Failed to extract audio segment")
        
        # 5. Upload to S3
        s3_key = f"mp3/{mp3_filename}"
        upload_to_s3_with_metadata(mp3_path, s3_key, {
            'youtube_url': youtube_url,
            'start_time': str(start_time),
            'end_time': str(end_time),
            'duration': str(end_time - start_time),
            'bitrate': bitrate,
            'request_id': request_id
        })
        
        # 6. Cleanup temporary files
        cleanup_temporary_files([video_path, mp3_path])
        
        # 7. Return success response
        response = create_success_response(request_id, s3_key, mp3_filename, end_time - start_time)
        logger.info(f"Request {request_id} completed successfully")
        return response
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Request {request_id} failed: {error_msg}", exc_info=True)
        return create_error_response(error_msg, request_id)


def validate_and_parse_input(event: dict) -> Tuple[str, int, int, str]:
    """
    Validate and parse Lambda event input.
    
    Returns: (youtube_url, start_time_seconds, end_time_seconds, bitrate)
    """
    # Required fields
    if 'youtube_url' not in event:
        raise ValueError("Missing required field: youtube_url")
    if 'start_time' not in event:
        raise ValueError("Missing required field: start_time")  
    if 'end_time' not in event:
        raise ValueError("Missing required field: end_time")
    
    youtube_url = event['youtube_url'].strip()
    if not youtube_url:
        raise ValueError("youtube_url cannot be empty")
    
    # Validate YouTube URL format
    if not any(domain in youtube_url.lower() for domain in ['youtube.com', 'youtu.be']):
        raise ValueError("Invalid YouTube URL format")
    
    # Parse times
    start_time = parse_time_to_seconds(event['start_time'])
    end_time = parse_time_to_seconds(event['end_time'])
    
    if start_time >= end_time:
        raise ValueError(f"Start time ({start_time}s) must be before end time ({end_time}s)")
    
    if end_time - start_time > 7200:  # 2 hours max
        raise ValueError("Audio segment too long (max 2 hours)")
    
    # Optional bitrate
    bitrate = event.get('bitrate', '96k')
    if bitrate not in ['64k', '96k', '128k', '160k', '192k']:
        logger.warning(f"Unusual bitrate: {bitrate}, using anyway")
    
    return youtube_url, start_time, end_time, bitrate


def parse_time_to_seconds(time_input) -> int:
    """
    Convert time string or number to seconds.
    Supports: "HH:MM:SS", "MM:SS", "SS", or direct seconds as int/float
    """
    if isinstance(time_input, (int, float)):
        return int(time_input)
    
    time_str = str(time_input).strip()
    parts = time_str.split(':')
    
    try:
        if len(parts) == 3:  # HH:MM:SS
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:  # MM:SS
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
        elif len(parts) == 1:  # SS
            return int(parts[0])
        else:
            raise ValueError(f"Invalid time format: {time_str}")
    except ValueError as e:
        raise ValueError(f"Could not parse time '{time_str}': {e}")


def get_youtube_cookies() -> Optional[Dict]:
    """
    Retrieve YouTube cookies from AWS Secrets Manager.
    Returns None if cookies not found or error occurs.
    """
    try:
        logger.info(f"Retrieving cookies from Secrets Manager: {COOKIES_SECRET_NAME}")
        response = secrets_client.get_secret_value(SecretId=COOKIES_SECRET_NAME)
        secret_data = json.loads(response['SecretString'])
        logger.info("Successfully retrieved YouTube cookies from Secrets Manager")
        return secret_data
    except secrets_client.exceptions.ResourceNotFoundException:
        logger.info(f"Cookies secret not found: {COOKIES_SECRET_NAME} (this is optional)")
        return None
    except Exception as e:
        logger.warning(f"Could not retrieve cookies: {e}")
        return None


def create_cookie_file(cookies_data: Dict) -> Optional[str]:
    """
    Create a temporary cookie file in Netscape format for yt-dlp.
    """
    if not cookies_data or 'cookies' not in cookies_data:
        return None
    
    cookie_file_path = os.path.join(TEMP_DIR, f"cookies_{uuid.uuid4().hex[:8]}.txt")
    
    try:
        with open(cookie_file_path, 'w') as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# Generated by Lambda function\n\n")
            
            cookies = cookies_data['cookies']
            
            # Handle different cookie formats
            if isinstance(cookies, str):
                # Simple cookie string: "name1=value1; name2=value2"
                for cookie_pair in cookies.split(';'):
                    if '=' in cookie_pair:
                        name, value = cookie_pair.strip().split('=', 1)
                        # Netscape format: domain, flag, path, secure, expiration, name, value
                        f.write(f".youtube.com\tTRUE\t/\tFALSE\t9999999999\t{name}\t{value}\n")
                        
            elif isinstance(cookies, list):
                # List of cookie objects
                for cookie in cookies:
                    if isinstance(cookie, dict) and 'name' in cookie and 'value' in cookie:
                        domain = cookie.get('domain', '.youtube.com')
                        path = cookie.get('path', '/')
                        secure = 'TRUE' if cookie.get('secure', False) else 'FALSE'
                        expires = cookie.get('expires', 9999999999)
                        f.write(f"{domain}\tTRUE\t{path}\t{secure}\t{expires}\t{cookie['name']}\t{cookie['value']}\n")
        
        logger.info(f"Cookie file created: {cookie_file_path}")
        return cookie_file_path
        
    except Exception as e:
        logger.error(f"Failed to create cookie file: {e}")
        return None


def download_video_with_cookies(url: str, output_path: str) -> bool:
    """
    Download YouTube video using yt-dlp with multiple fallback strategies.
    """
    # Get cookies if available
    cookies_data = get_youtube_cookies()
    cookie_file_path = create_cookie_file(cookies_data) if cookies_data else None
    
    # Multiple download configurations with fallbacks
    configs = []
    
    # Config 1: With cookies (if available)
    if cookie_file_path:
        configs.append({
            'name': 'With Cookies',
            'options': {
                'format': 'best[height<=720]/best',
                'cookiefile': cookie_file_path,
                'http_headers': {
                    'User-Agent': cookies_data.get('user_agent', 
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                },
                'sleep_interval': 2,
                'retries': 3,
            }
        })
    
    # Config 2: Standard quality without cookies
    configs.append({
        'name': 'Standard Quality',
        'options': {
            'format': 'best[height<=480]/bestaudio[ext=m4a]/bestaudio',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.youtube.com/',
            },
            'sleep_interval': 3,
            'retries': 5,
        }
    })
    
    # Config 3: Lowest quality fallback
    configs.append({
        'name': 'Lowest Quality Fallback',
        'options': {
            'format': 'worst',
            'ignoreerrors': True,
            'no_check_certificate': True,
        }
    })
    
    # Try each configuration
    for i, config in enumerate(configs):
        logger.info(f"Attempting download with {config['name']} (attempt {i+1}/{len(configs)})")
        
        ydl_opts = {
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            **config['options']
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
                if os.path.exists(output_path):
                    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    logger.info(f"Download successful with {config['name']}: {file_size_mb:.2f} MB")
                    
                    # Cleanup cookie file
                    if cookie_file_path and os.path.exists(cookie_file_path):
                        os.remove(cookie_file_path)
                    
                    return True
                    
        except yt_dlp.DownloadError as e:
            error_msg = str(e).lower()
            logger.warning(f"{config['name']} failed: {e}")
            
            # Check for permanent errors
            if any(phrase in error_msg for phrase in 
                   ['private video', 'video unavailable', 'copyright', 'removed', 'deleted']):
                logger.error(f"Permanent error detected: {e}")
                break
                
        except Exception as e:
            logger.warning(f"{config['name']} exception: {e}")
    
    # Cleanup cookie file on failure
    if cookie_file_path and os.path.exists(cookie_file_path):
        os.remove(cookie_file_path)
    
    logger.error("All download configurations failed")
    return False


def extract_audio_segment(input_path: str, output_path: str, 
                         start_time: int, end_time: int, bitrate: str) -> bool:
    """
    Extract audio segment from video using FFmpeg.
    """
    duration = end_time - start_time
    
    # Build FFmpeg command for optimal performance
    cmd = [
        FFMPEG_PATH,
        '-ss', str(start_time),  # Seek to start (before input for speed)
        '-i', input_path,        # Input file
        '-t', str(duration),     # Duration to extract
        '-vn',                   # No video
        '-acodec', 'libmp3lame', # MP3 encoder
        '-ab', bitrate,          # Audio bitrate
        '-ac', '1',              # Mono (smaller file)
        '-ar', '44100',          # Sample rate
        '-avoid_negative_ts', 'make_zero',  # Handle timestamp issues
        '-y',                    # Overwrite output
        output_path
    ]
    
    try:
        logger.info(f"Extracting audio: {start_time}s to {end_time}s ({duration}s) at {bitrate}")
        
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            check=True,
            timeout=300  # 5 minute timeout
        )
        
        if os.path.exists(output_path):
            file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            logger.info(f"Audio extraction successful: {file_size_mb:.2f} MB")
            return True
        else:
            logger.error("MP3 file not created despite successful FFmpeg execution")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg extraction timed out after 5 minutes")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg failed with exit code {e.returncode}")
        logger.error(f"FFmpeg stderr: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during audio extraction: {e}")
        return False


def upload_to_s3_with_metadata(file_path: str, s3_key: str, metadata: dict):
    """
    Upload MP3 file to S3 with comprehensive metadata.
    """
    try:
        # Add timestamp and Lambda context
        upload_metadata = {
            'created-at': datetime.utcnow().isoformat(),
            'lambda-function': 'youtube-mp3-converter',
            **{k.replace('_', '-'): str(v) for k, v in metadata.items()}
        }
        
        with open(file_path, 'rb') as f:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=f,
                ContentType='audio/mpeg',
                Metadata=upload_metadata,
                ServerSideEncryption='AES256'  # Encrypt at rest
            )
        
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        logger.info(f"Successfully uploaded to S3: s3://{S3_BUCKET}/{s3_key} ({file_size_mb:.2f} MB)")
        
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        raise


def cleanup_temporary_files(file_paths: list):
    """
    Clean up temporary files created during processing.
    """
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Cleaned up temporary file: {path}")
        except Exception as e:
            logger.warning(f"Could not clean up {path}: {e}")


def create_success_response(request_id: str, s3_key: str, filename: str, duration: int) -> dict:
    """
    Create standardized success response.
    """
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
                'download_expires_in': '24 hours'
            }
        })
    }


def create_error_response(error_message: str, request_id: str = None) -> dict:
    """
    Create standardized error response.
    """
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
    # Test event
    test_event = {
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "start_time": "0:10",
        "end_time": "0:30",
        "bitrate": "96k"
    }
    
    # Mock context
    class MockContext:
        aws_request_id = "test-request-123"
        function_name = "test-function"
    
    # Set environment variables for testing
    os.environ['S3_BUCKET'] = 'test-bucket'
    os.environ['COOKIES_SECRET_NAME'] = 'test/cookies'
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))