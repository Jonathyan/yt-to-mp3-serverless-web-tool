import json
import os
import subprocess
import tempfile
import boto3
from datetime import datetime, timedelta
import uuid
import logging

# Import yt-dlp from layer
import yt_dlp

# Import ffmpeg path helper from layer
try:
    from ffmpeg_location import get_ffmpeg_path
    FFMPEG_PATH = get_ffmpeg_path()
except ImportError:
    FFMPEG_PATH = 'ffmpeg'  # Fallback

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3_client = boto3.client('s3')

# Environment variables
S3_BUCKET = os.environ.get('S3_BUCKET', 'preek-mp3-storage')
TEMP_DIR = '/tmp'  # Lambda's writable directory


def lambda_handler(event, context):
    """
    Lambda handler voor video processing.
    
    Expected event format:
    {
        "youtube_url": "https://youtube.com/watch?v=...",
        "start_time": "10:30",  # or seconds
        "end_time": "45:20",    # or seconds
        "bitrate": "96k"        # optional, default 96k
    }
    """
    logger.info(f"Event received: {json.dumps(event)}")
    
    try:
        # Parse input
        youtube_url = event['youtube_url']
        start_time = parse_time(event['start_time'])
        end_time = parse_time(event['end_time'])
        bitrate = event.get('bitrate', '96k')
        
        # Validate input
        if start_time >= end_time:
            raise ValueError("Start time must be before end time")
        
        # Generate unique filename
        request_id = str(uuid.uuid4())
        mp3_filename = f"preek_{request_id}.mp3"
        
        # Process video
        logger.info(f"Starting processing for: {youtube_url}")
        
        # Create paths in Lambda /tmp
        video_path = os.path.join(TEMP_DIR, f"{request_id}_video.mp4")
        mp3_path = os.path.join(TEMP_DIR, mp3_filename)
        
        # Download video
        download_success = download_video(youtube_url, video_path)
        if not download_success:
            raise Exception("Failed to download video")
        
        # Extract and convert audio
        extract_success = extract_audio(
            video_path, mp3_path, start_time, end_time, bitrate
        )
        if not extract_success:
            raise Exception("Failed to extract audio")
        
        # Upload to S3
        s3_key = f"mp3/{mp3_filename}"
        upload_to_s3(mp3_path, s3_key)
        
        # Clean up temp files
        cleanup_files([video_path, mp3_path])
        
        # Generate response
        result = {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Processing successful',
                'request_id': request_id,
                's3_bucket': S3_BUCKET,
                's3_key': s3_key,
                'filename': mp3_filename,
                'duration': end_time - start_time
            })
        }
        
        logger.info(f"Processing completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'message': 'Processing failed'
            })
        }


def parse_time(time_str):
    """Convert time string to seconds."""
    if isinstance(time_str, (int, float)):
        return int(time_str)
    
    parts = str(time_str).split(':')
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    else:
        return int(parts[0])


def download_video(url, output_path):
    """Download YouTube video using yt-dlp with anti-bot measures."""
    
    # Meerdere configuraties proberen
    configs = [
        # Config 1: Basis anti-bot
        {
            'format': 'best[height<=720]/best',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            },
            'sleep_interval': 2,
            'retries': 3,
        },
        # Config 2: Audio-only fallback
        {
            'format': 'bestaudio[ext=m4a]/bestaudio',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) rv:109.0'
            },
            'sleep_interval': 3,
            'retries': 5,
        },
        # Config 3: Minimale configuratie
        {
            'format': 'worst',
            'ignoreerrors': True,
            'no_check_certificate': True,
        }
    ]
    
    for i, config in enumerate(configs):
        logger.info(f"Trying download config {i+1}/3")
        
        # Basis configuratie
        ydl_opts = {
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            **config  # Merge specifieke config
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                
                # Check resultaat
                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path) / (1024 * 1024)
                    logger.info(f"Video downloaded successfully with config {i+1}: {file_size:.2f} MB")
                    return True
                    
        except yt_dlp.DownloadError as e:
            error_msg = str(e)
            logger.warning(f"Config {i+1} failed: {error_msg}")
            
            # Stop als het duidelijk een permanente error is
            if any(phrase in error_msg.lower() for phrase in ['private video', 'video unavailable', 'copyright']):
                logger.error(f"Permanent error detected: {error_msg}")
                return False
                
        except Exception as e:
            logger.warning(f"Config {i+1} exception: {str(e)}")
    
    logger.error("All download configurations failed")
    return False


def extract_audio(input_path, output_path, start_time, end_time, bitrate):
    """Extract audio segment, handle both video and audio-only inputs."""
    duration = end_time - start_time
    
    # Check input type
    probe_cmd = [FFMPEG_PATH, '-i', input_path, '-f', 'null', '-']
    try:
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        has_video = 'Video:' in probe_result.stderr
        logger.info(f"Input has video stream: {has_video}")
    except:
        has_video = True  # Assume video if probe fails
    
    # Build FFmpeg command
    cmd = [
        FFMPEG_PATH,
        '-ss', str(start_time),
        '-i', input_path,
        '-t', str(duration),
        '-acodec', 'libmp3lame',
        '-ab', bitrate,
        '-ac', '1',  # Mono
        '-ar', '44100',
        '-y',
        output_path
    ]
    
    # Add -vn only if input has video
    if has_video:
        cmd.insert(-2, '-vn')  # Insert before output path
    
    try:
        logger.info(f"Extracting audio: {start_time}s to {end_time}s ({duration}s)")
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path) / (1024 * 1024)
            logger.info(f"Audio extracted successfully: {file_size:.2f} MB")
            return True
        else:
            logger.error("MP3 file not found after extraction")
            return False
            
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Error extracting audio: {str(e)}")
        return False


def upload_to_s3(file_path, s3_key):
    """Upload file to S3."""
    try:
        # Add metadata
        metadata = {
            'created': datetime.utcnow().isoformat(),
            'content-type': 'audio/mpeg'
        }
        
        with open(file_path, 'rb') as f:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=f,
                Metadata=metadata,
                ContentType='audio/mpeg'
            )
        
        logger.info(f"File uploaded to S3: s3://{S3_BUCKET}/{s3_key}")
        
    except Exception as e:
        logger.error(f"Error uploading to S3: {str(e)}")
        raise


def cleanup_files(file_paths):
    """Clean up temporary files."""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Cleaned up: {path}")
        except Exception as e:
            logger.warning(f"Could not clean up {path}: {str(e)}")


# Test functie voor lokaal development
if __name__ == "__main__":
    # Test event
    test_event = {
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "start_time": "0:10",
        "end_time": "0:30",
        "bitrate": "96k"
    }
    
    # Simuleer Lambda context
    class Context:
        function_name = "test"
        request_id = "test-request"
    
    result = lambda_handler(test_event, Context())
    print(json.dumps(result, indent=2))