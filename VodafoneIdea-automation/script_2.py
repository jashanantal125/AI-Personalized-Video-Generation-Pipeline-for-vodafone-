#!/usr/bin/env python3

import os
import subprocess
import librosa
from google.cloud import texttospeech
import time
import mysql.connector
from mysql.connector import Error
import logging
import sys
import json
from datetime import datetime
import shutil

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Import database connection
from db_script import db_connection

# Set up Google Cloud credentials
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "svc.json"



def email_alert(subject, body):
    """
    Send email alert for errors or important events via Gmail SMTP
    
    Args:
        subject (str): Email subject line
        body (str): Email body content
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    # Email configuration
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    SENDER_EMAIL = "developer@ldttechnology.com"
    SENDER_PASSWORD = "YOUR_SMTP_APP_PASSWORD"  # App password (spaces removed)
    RECIPIENT_EMAILS = ["mahesh@ldttechnology.com", "snigdha.sharma@ldttechnology.com", "vishal.sharma@ecore.in", "pk@ldttechnology.com"]
    
    try:
        # Create message
        message = MIMEMultipart()
        message["From"] = SENDER_EMAIL
        message["To"] = ", ".join(RECIPIENT_EMAILS)
        message["Subject"] = f"[Vi Auto Alert] {subject}"
        
        # Attach body (Gmail will add timestamp automatically)
        message.attach(MIMEText(body, "plain"))
        
        # Connect to Gmail SMTP server
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()  # Enable TLS encryption
        
        # Login and send
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(message)
        server.quit()
        print("Email Sent Successfully.")
        
        return True
        
    except Exception as e:
        print(f"Failed to send email alert: {e}")
        return False

class VideoWorkerProcessor:
    def __init__(self, instance_id, total_instances):
        """Initialize the video worker processor"""
        self.instance_id = instance_id
        self.total_instances = total_instances
        self.setup_logging()
        self.connection = None
        self.cursor = None
        self.config = self.load_video_config()
        
    def setup_logging(self):
        """Setup logging configuration"""
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f'{log_dir}/video_worker_{self.instance_id}_{datetime.now().strftime("%Y%m%d")}.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Video Worker {self.instance_id} of {self.total_instances} initialized")
    
    def load_video_config(self):
        """Load video configuration from JSON file"""
        config_file = "video_config.json"
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            self.logger.info("Video configuration loaded successfully")
            return config
        except FileNotFoundError:
            self.logger.error(f"Configuration file {config_file} not found in vi_video/python/")
            # email_alert("Video Config Not Found", f"Configuration file {config_file} not found")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Failed to load video configuration: {e}")
            # email_alert("Video Config Load Failed", f"Failed to load video configuration: {e}")
            sys.exit(1)
    
    def get_circle_config(self, circle_name):
        """Get configuration for specific circle - NO DEFAULT VALUES"""
        # Normalize circle name (remove leading zeros, etc.)
        if circle_name and str(circle_name).isdigit():
            normalized_circle = str(int(circle_name))
        else:
            normalized_circle = str(circle_name) if circle_name else None
        
        if not normalized_circle:
            self.logger.error(f"Invalid circle name: {circle_name}")
            return None
        
        if normalized_circle in self.config['video_configs']:
            self.logger.info(f"Using configuration for circle: {normalized_circle}")
            return self.config['video_configs'][normalized_circle]
        else:
            # NO DEFAULT - return None if circle not found
            self.logger.error(f"Circle {normalized_circle} not found in video configuration")
            return None
    
    def normalize_circle_name(self, circle_name):
        """Normalize circle name by removing leading zeros"""
        if circle_name and str(circle_name).isdigit():
            return str(int(circle_name))
        else:
            return str(circle_name) if circle_name else None
    
    def is_circle_filtered(self, circle_name):
        """Check if a circle is in the filter list"""
        filter_circles = self.config['default_config'].get('filter_circles', [])
        
        if not filter_circles:  # Empty list or None
            return False
        
        normalized_circle = self.normalize_circle_name(circle_name)
        
        if not normalized_circle:
            return False
        
        # Normalize filter circles and check
        normalized_filters = [self.normalize_circle_name(fc) for fc in filter_circles]
        
        return normalized_circle in normalized_filters
    
    def connect_database(self):
        """Get database connection from external db_script with proper configuration"""
        try:
            self.connection = db_connection()
            if self.connection:
                self.cursor = self.connection.cursor()
                
                # Configure connection for real-time data access
                self.cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
                self.cursor.execute("SET autocommit = 1")  # Enable autocommit for immediate visibility
                
                # Test connection
                self.cursor.execute("SELECT 1")
                test_result = self.cursor.fetchone()
                
                # Log connection details for debugging
                self.cursor.execute("SHOW VARIABLES LIKE 'tx_isolation'")
                isolation_level = self.cursor.fetchone()
                self.logger.info(f"Database connection established for worker {self.instance_id}")
                self.logger.info(f"Transaction isolation level: {isolation_level}")
                
                return True
            else:
                self.logger.error("Failed to get database connection")
                email_alert("Database Connection Failed", f"Worker {self.instance_id}: Failed to get database connection")
                return False
        except Exception as e:
            self.logger.error(f"Database connection failed: {e}")
            email_alert("Database Connection Error", f"Worker {self.instance_id}: Database connection failed: {e}")
            return False
    
    def disconnect_database(self):
        """Close database connection"""
        try:
            if self.cursor:
                self.cursor.close()
            if self.connection:
                self.connection.close()
                self.logger.info(f"Database connection closed for worker {self.instance_id}")
        except Exception as e:
            self.logger.error(f"Error closing database connection: {e}")
    
    def reconnect_database(self):
        """Reconnect to database - useful for long-running processes"""
        self.logger.info(f"Worker {self.instance_id}: Reconnecting to database...")
        self.disconnect_database()
        time.sleep(2)
        success = self.connect_database()
        if not success:
            email_alert("Database Reconnection Failed", f"Worker {self.instance_id}: Failed to reconnect to database")
        return success
    
    def get_pending_users_for_instance_fresh(self):
        """Get pending users with a completely fresh database connection"""
        fresh_connection = None
        fresh_cursor = None
        
        try:
            # Create a completely fresh connection for this query
            fresh_connection = db_connection()
            if not fresh_connection:
                self.logger.error("Failed to create fresh database connection")
                email_alert("Fresh DB Connection Failed", f"Worker {self.instance_id}: Failed to create fresh database connection")
                return []
            
            # Use default cursor (returns tuples)
            fresh_cursor = fresh_connection.cursor()
            
            # Ensure we're reading the latest committed data
            fresh_cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            fresh_cursor.execute("SET autocommit = 1")
            
            query = """
            SELECT u.id, u.mobile, u.current_balance, u.validity_in_days, 
                   u.circle_name, c.campaign_name, c.id as campaign_id
            FROM users u 
            JOIN campaigns c ON u.campaign_id = c.id 
            WHERE u.status = 'pending' 
            AND c.status = 'ongoing'
            AND MOD(u.id, %s) = %s
            ORDER BY u.created_at ASC
            LIMIT 50
            """
            
            fresh_cursor.execute(query, (self.total_instances, self.instance_id))
            users = fresh_cursor.fetchall()
            
            self.logger.info(f"Worker {self.instance_id}: Found {len(users)} pending users (fresh connection)")
            
            # Enhanced debugging when no users found
            if len(users) == 0:
                # Check total pending users
                debug_query = "SELECT COUNT(*) FROM users u JOIN campaigns c ON u.campaign_id = c.id WHERE u.status = 'pending' AND c.status = 'ongoing'"
                fresh_cursor.execute(debug_query)
                result = fresh_cursor.fetchone()
                total_pending = result[0] if result else 0
                
                # Check recent records  
                debug_query2 = "SELECT COUNT(*), MAX(created_at) FROM users WHERE created_at >= DATE_SUB(NOW(), INTERVAL 10 MINUTE)"
                fresh_cursor.execute(debug_query2)
                result2 = fresh_cursor.fetchone()
                recent_count = result2[0] if result2 else 0
                latest_time = result2[1] if result2 else None
                
                # Check campaigns
                debug_query3 = "SELECT COUNT(*) FROM campaigns WHERE status = 'ongoing'"
                fresh_cursor.execute(debug_query3)
                result3 = fresh_cursor.fetchone()
                ongoing_campaigns = result3[0] if result3 else 0
                
                # Check this worker's assignment
                debug_query4 = """
                SELECT COUNT(*) FROM users u 
                JOIN campaigns c ON u.campaign_id = c.id 
                WHERE u.status = 'pending' AND c.status = 'ongoing'
                AND MOD(u.id, %s) = %s
                """
                fresh_cursor.execute(debug_query4, (self.total_instances, self.instance_id))
                result4 = fresh_cursor.fetchone()
                worker_assigned = result4[0] if result4 else 0
                
                self.logger.info(f"Worker {self.instance_id} Debug - Total pending: {total_pending}, Recent (10min): {recent_count}, Latest: {latest_time}")
                self.logger.info(f"Worker {self.instance_id} Debug - Ongoing campaigns: {ongoing_campaigns}, Assigned to worker: {worker_assigned}")
            
            return users
            
        except Exception as e:
            self.logger.error(f"Error fetching pending users with fresh connection: {e}")
            # email_alert("Error Fetching Users", f"Worker {self.instance_id}: Error fetching pending users: {e}")
            return []
            
        finally:
            # Always clean up the fresh connection
            if fresh_cursor:
                fresh_cursor.close()
            if fresh_connection:
                fresh_connection.close()
    
    def claim_user_for_processing(self, user_id):
        """Atomically claim a user for processing"""
        try:
            query = """
            UPDATE users 
            SET status = 'processing', 
                processing_started_at = NOW(),
                worker_id = %s
            WHERE id = %s 
            AND status = 'pending'
            """
            
            self.cursor.execute(query, (f"worker-{self.instance_id}", user_id))
            self.connection.commit()
            
            return self.cursor.rowcount > 0  # True if we updated the row
            
        except Error as e:
            self.logger.error(f"Error claiming user {user_id}: {e}")
            self.connection.rollback()
            return False
    
    def update_user_status(self, user_id, status):
        """Update user status and increment campaign processed_records"""
        try:
            query = "UPDATE users SET status = %s WHERE id = %s"
            self.cursor.execute(query, (status, user_id))
            
            # ALWAYS increment campaign processed_records for both 'processed' and 'failed' status
            if status in ['processed', 'failed']:
                campaign_query = """
                UPDATE campaigns c
                JOIN users u ON c.id = u.campaign_id  
                SET c.processed_records = c.processed_records + 1
                WHERE u.id = %s
                """
                self.cursor.execute(campaign_query, (user_id,))
            
            self.connection.commit()
            self.logger.info(f"User {user_id} status updated to '{status}'")
            return True
        except Error as e:
            self.logger.error(f"Error updating user status: {e}")
            self.connection.rollback()
            return False
    
    def insert_video_record(self, user_id, video_public_url, generation_status):
        """Insert record into videos_table"""
        try:
            query = """
                INSERT INTO videos_table (users_id, video_public_url, generation_status) 
                VALUES (%s, %s, %s)
            """
            self.cursor.execute(query, (user_id, video_public_url, generation_status))
            self.connection.commit()
            video_id = self.cursor.lastrowid
            self.logger.info(f"Video record inserted: ID {video_id}")
            return video_id
        except Error as e:
            self.logger.error(f"Error inserting video record: {e}")
            self.connection.rollback()
            return None
    
    def format_validity(self, validity_days):
        """Format validity days according to requirements - No leading zeros for single digits"""
        return str(validity_days)
    
    def format_amount(self, balance):
        """Format balance amount - remove decimal part"""
        try:
            return str(int(float(balance)))
        except (ValueError, TypeError):
            self.logger.error(f"Error formatting balance: {balance}")
            return "0"
    
    def should_use_empty_video(self, balance, validity_days):
        """Check if either balance or validity is zero (should use empty video)"""
        try:
            balance_zero = float(balance) < 5
            validity_zero = int(validity_days) < 5
            # validity_zero = True
            # Use empty video if ANY value is zero
            return balance_zero or validity_zero
        except (ValueError, TypeError):
            # If we can't parse the values, use empty video as safe fallback
            return True

    def get_static_video_url(self, circle_name):
        """Get the pre-existing static video URL for a circle without copying any files"""
        try:
            # Normalize circle name
            if circle_name and str(circle_name).isdigit():
                # Convert to int, then pad with leading zero if needed
                normalized_circle = f"{int(circle_name):02d}"
            else:
                # No default - return None if invalid
                self.logger.error(f"Invalid circle name for static video: {circle_name}")
                return None

            # Construct the static video URL
            public_url_base = self.config['default_config']['public_url_base']
            static_video_url = f"{public_url_base}/{normalized_circle}.mp4"

            self.logger.info(f"Using pre-existing static video URL: {static_video_url}")
            return static_video_url

        except Exception as e:
            self.logger.error(f"Error getting static video URL: {e}")
            return None
    
    def get_audio_duration(self, audio_file):
        """Get actual duration of generated audio file"""
        try:
            duration = librosa.get_duration(path=audio_file)
            return duration
        except Exception as e:
            self.logger.warning(f"librosa failed ({e}), using ffprobe fallback...")
            cmd = [
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of',
                'default=noprint_wrappers=1:nokey=1', audio_file
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                self.logger.error(f"Error getting audio duration: {result.stderr}")
                return 1.0
            return float(result.stdout.strip())
    
    def generate_audio_for_digits(self, text, output_file, circle_config):
        """Generate TTS audio with appropriate speaking rate based on digit count and circle-specific voice - NO DEFAULTS"""
        digit_count = len(str(text))
        
        # Get speaking rates from circle config - NO DEFAULT VALUES
        speaking_rates = circle_config.get('speaking_rates')
        if not speaking_rates:
            raise Exception(f"Missing 'speaking_rates' in circle configuration")
        
        speaking_rate = speaking_rates.get(str(digit_count))
        if speaking_rate is None:
            raise Exception(f"Missing speaking rate for {digit_count} digits in circle configuration")
        
        # Get language and voice from circle config - NO DEFAULT VALUES
        language_code = circle_config.get('language_code')
        if not language_code:
            raise Exception(f"Missing 'language_code' in circle configuration")
        
        tts_voice_name = circle_config.get('tts_voice_name')
        if not tts_voice_name:
            raise Exception(f"Missing 'tts_voice_name' in circle configuration")
        
        self.logger.info(f"Generating audio for '{text}' ({digit_count} digits) with speaking rate {speaking_rate}, language: {language_code}, voice: {tts_voice_name}")
        
        client = texttospeech.TextToSpeechClient()
        
        synthesis_input = texttospeech.SynthesisInput(text=str(text))
        
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=tts_voice_name
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate
        )
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        # Save original audio first
        temp_audio = output_file.replace('.mp3', '_temp.mp3')
        
        with open(temp_audio, "wb") as out:
            out.write(response.audio_content)
        
        # Reduce volume by 10%
        reduce_volume = 0.9
        cmd = [
            'ffmpeg', '-y', '-i', temp_audio,
            '-filter:a', f'volume={reduce_volume}',
            '-c:a', 'mp3', output_file
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        os.remove(temp_audio)
        
        actual_duration = self.get_audio_duration(output_file)
        self.logger.info(f"Generated audio: {output_file}, Duration: {actual_duration:.2f}s")
        
        return actual_duration

    def embed_audio_in_video(self, video_file, validity_audio, amount_audio, output_video, circle_config):
        """Embed audio files with WhatsApp-compatible encoding"""
        
        # Validate input files exist before proceeding
        if not os.path.exists(video_file):
            self.logger.error(f"Input video file does not exist: {video_file}")
            return False
        
        if not os.path.exists(validity_audio):
            self.logger.error(f"Validity audio file does not exist: {validity_audio}")
            return False
        
        if not os.path.exists(amount_audio):
            self.logger.error(f"Amount audio file does not exist: {amount_audio}")
            return False
        
        # Log file sizes for debugging
        self.logger.info(f"Input video size: {os.path.getsize(video_file)} bytes")
        self.logger.info(f"Validity audio size: {os.path.getsize(validity_audio)} bytes")
        self.logger.info(f"Amount audio size: {os.path.getsize(amount_audio)} bytes")
        
        validity_delay_ms = int(circle_config['validity_start_time'] * 1000)
        amount_delay_ms = int(circle_config['amount_start_time'] * 1000)
        
        cmd = [
            'ffmpeg', '-y',
            '-i', video_file,
            '-i', validity_audio,
            '-i', amount_audio,
            '-filter_complex',
            f'[1:a]adelay={validity_delay_ms}|{validity_delay_ms}[validity_delayed];' 
            f'[2:a]adelay={amount_delay_ms}|{amount_delay_ms}[amount_delayed];'       
            f'[0:a][validity_delayed][amount_delayed]amix=inputs=3:duration=longest:dropout_transition=0[audio_out]',
            '-map', '0:v',
            '-map', '[audio_out]',
            
            # WhatsApp Android compatibility settings
            '-c:v', 'libx264',
            '-profile:v', 'baseline',
            '-level', '3.1',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-movflags', '+faststart',
            '-f', 'mp4',
            '-shortest',
            output_video
        ]
        
        self.logger.info(f"Embedding audio with WhatsApp compatibility settings...")
        self.logger.info(f"Input video: {video_file}")
        self.logger.info(f"Validity audio: {validity_audio}")
        self.logger.info(f"Amount audio: {amount_audio}")
        self.logger.info(f"Output video: {output_video}")
        self.logger.info(f"Validity delay: {validity_delay_ms}ms, Amount delay: {amount_delay_ms}ms")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            self.logger.error(f"FFmpeg failed with return code: {result.returncode}")
            self.logger.error(f"FFmpeg stderr output:")
            self.logger.error(result.stderr)
            if result.stdout:
                self.logger.error(f"FFmpeg stdout output:")
                self.logger.error(result.stdout)
            self.logger.error(f"Full command that failed: {' '.join(cmd)}")
            return False
        
        # Verify output file was created
        if not os.path.exists(output_video):
            self.logger.error(f"Output video file was not created: {output_video}")
            self.logger.error("FFmpeg command completed but output file is missing")
            return False
        
        # Verify output file has content
        output_size = os.path.getsize(output_video)
        if output_size == 0:
            self.logger.error(f"Output video file is empty (0 bytes): {output_video}")
            return False
        
        # Check if output is reasonable size (should be similar to input video size)
        input_size = os.path.getsize(video_file)
        if output_size < (input_size * 0.5):  # Output shouldn't be less than 50% of input
            self.logger.warning(f"Output video size ({output_size} bytes) is significantly smaller than input ({input_size} bytes)")
            self.logger.warning("This might indicate a problem with the audio embedding")
        
        self.logger.info(f"Successfully embedded audio: {output_video}")
        self.logger.info(f"Output video size: {output_size} bytes")
        return True
        
    def get_available_font(self):
        """Get an available font for FFmpeg text overlay"""
        fonts_to_try = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        ]
        
        for font_path in fonts_to_try:
            if os.path.exists(font_path):
                self.logger.info(f"Using font: {font_path}")
                return font_path
        
        self.logger.warning("No system fonts found, using default font")
        return None

    def add_text_overlay(self, video_file, validity_text, amount_text, output_file, circle_config):
        """Add text overlays with WhatsApp-compatible encoding - Fixed font size of 40"""
        self.logger.info("Adding text overlays to video...")
        
        # Validate input video exists and has content
        if not os.path.exists(video_file):
            self.logger.error(f"Input video file does not exist: {video_file}")
            return False
        
        video_size = os.path.getsize(video_file)
        if video_size == 0:
            self.logger.error(f"Input video file is empty (0 bytes): {video_file}")
            return False
        
        self.logger.info(f"Input video file: {video_file} ({video_size} bytes)")
        
        validity_digits = len(str(validity_text))
        amount_digits = len(str(amount_text))
        
        # Fixed font size - NO dynamic sizing
        validity_font_size = 40
        amount_font_size = 40
        self.logger.info(f"Using fixed font sizing: validity={validity_font_size}, amount={amount_font_size}")
        
        max_digits = max(validity_digits, amount_digits)
        coordinates_validity = circle_config['coordinates_map'].get(str(max_digits), circle_config['coordinates_map']['4'])['validity']
        coordinates_amount = circle_config['coordinates_map'].get(str(max_digits), circle_config['coordinates_map']['4'])['amount']
        
        x1_1, y1_1, x2_1, y2_1 = coordinates_validity
        x1_2, y1_2, x2_2, y2_2 = coordinates_amount
        
        text_x1 = (x1_1 + x2_1) // 2
        text_y1 = (y1_1 + y2_1) // 2
        text_x2 = (x1_2 + x2_2) // 2
        text_y2 = (y1_2 + y2_2) // 2
        
        self.logger.info(f"Text positions - Validity: ({text_x1}, {text_y1}), Amount: ({text_x2}, {text_y2})")
        
        # Escape text properly for FFmpeg
        validity_escaped = str(validity_text).replace("'", "\\'").replace(":", "\\:")
        amount_escaped = str(amount_text).replace("'", "\\'").replace(":", "\\:")
        
        font_path = self.get_available_font()
        
        if font_path:
            self.logger.info(f"Using font: {font_path}")
            drawtext_filter = (
                f"drawtext=fontfile='{font_path}':text='{validity_escaped}':fontsize={validity_font_size}:fontcolor=white:"
                f"x={text_x1}:y={text_y1}:enable='between(t,{circle_config['val_text_start_time']},{circle_config['val_text_end_time']})',"
                f"drawtext=fontfile='{font_path}':text='{amount_escaped}':fontsize={amount_font_size}:fontcolor=white:"
                f"x={text_x2}:y={text_y2}:enable='between(t,{circle_config['amnt_text_start_time']},{circle_config['amnt_text_end_time']})'"
            )
        else:
            self.logger.warning("No font file found, using default font family")
            drawtext_filter = (
                f"drawtext=fontfamily=sans:text='{validity_escaped}':fontsize={validity_font_size}:fontcolor=white:"
                f"x={text_x1}:y={text_y1}:enable='between(t,{circle_config['val_text_start_time']},{circle_config['val_text_end_time']})',"
                f"drawtext=fontfamily=sans:text='{amount_escaped}':fontsize={amount_font_size}:fontcolor=white:"
                f"x={text_x2}:y={text_y2}:enable='between(t,{circle_config['amnt_text_start_time']},{circle_config['amnt_text_end_time']})'"
            )
        
        # Write to temp location first (same directory as temp video), then move to final destination
        # Extract filename from output_file path
        output_filename = os.path.basename(output_file)
        temp_dir = os.path.dirname(video_file)  # Same directory as the input temp video
        temp_output = os.path.join(temp_dir, f"final_{output_filename}")
        
        self.logger.info(f"Will write to temp location: {temp_output}")
        self.logger.info(f"Then move to final location: {output_file}")
        
        cmd = [
            'ffmpeg', '-y', '-i', video_file,
            '-vf', drawtext_filter,
            '-c:v', 'libx264',
            '-profile:v', 'baseline',
            '-level', '3.1', 
            '-pix_fmt', 'yuv420p',
            '-c:a', 'copy',
            '-movflags', '+faststart',
            '-f', 'mp4',
            temp_output  # Write to temp location
        ]
        
        self.logger.info(f"Running FFmpeg text overlay command...")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                self.logger.error(f"FFmpeg failed with return code: {result.returncode}")
                self.logger.error(f"FFmpeg stderr output:")
                self.logger.error(result.stderr)
                if result.stdout:
                    self.logger.error(f"FFmpeg stdout output:")
                    self.logger.error(result.stdout)
                self.logger.error(f"Full command that failed:")
                self.logger.error(f"{' '.join(cmd)}")
                return False
            
            # Verify temp output file was created
            if not os.path.exists(temp_output):
                self.logger.error(f"Temp output file was not created: {temp_output}")
                return False
            
            temp_size = os.path.getsize(temp_output)
            if temp_size == 0:
                self.logger.error(f"Temp output file is empty (0 bytes): {temp_output}")
                return False
            
            self.logger.info(f"Temp file created successfully: {temp_output} ({temp_size} bytes)")
            
            # Move temp file to final destination
            try:
                shutil.move(temp_output, output_file)
                self.logger.info(f"Successfully moved to final location: {output_file}")
            except Exception as e:
                self.logger.error(f"Failed to move temp file to final location: {e}")
                # Clean up temp file if move fails
                if os.path.exists(temp_output):
                    os.remove(temp_output)
                return False
            
            # Verify final file
            if not os.path.exists(output_file):
                self.logger.error(f"Final output file does not exist: {output_file}")
                return False
            
            output_size = os.path.getsize(output_file)
            if output_size == 0:
                self.logger.error(f"Final output file is empty (0 bytes): {output_file}")
                return False
            
            self.logger.info(f"Text overlay added successfully: {output_file} ({output_size} bytes)")
            return True
            
        except subprocess.TimeoutExpired:
            self.logger.error("FFmpeg text overlay command timed out after 120 seconds")
            # Clean up temp file if it exists
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except:
                    pass
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during text overlay: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            # Clean up temp file if it exists
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except:
                    pass
            return False
        
    def generate_video_for_user(self, user_id, mobile, balance, validity_days, circle_name, campaign_id):
        """Generate video for a specific user using circle-specific configuration - NO DEFAULT CIRCLE"""
        self.logger.info(f"Worker {self.instance_id}: Generating video for user {user_id} (mobile: {mobile}, circle: {circle_name})")
        
        # Get circle-specific configuration - NO DEFAULT
        circle_config = self.get_circle_config(circle_name)
        if not circle_config:
            self.logger.error(f"Worker {self.instance_id}: Circle configuration not found for circle {circle_name}, marking as failed")
            # Insert failed video record
            self.insert_video_record(user_id, "", 'failed')
            # Update user status to 'failed' (this will increment processed_records)
            self.update_user_status(user_id, 'failed')
            return False
        
        # Format values
        formatted_validity = self.format_validity(validity_days)
        formatted_amount = self.format_amount(balance)
        
        self.logger.info(f"Formatted values - Validity: {formatted_validity}, Amount: {formatted_amount}")
        
        # Final video name and path
        video_filename = f"{mobile}_{campaign_id}.mp4"
        video_output_dir = self.config['default_config']['video_output_dir']
        public_url_base = self.config['default_config']['public_url_base']
        final_video_path = os.path.join(video_output_dir, video_filename)
        public_url = f"{public_url_base}/{video_filename}"
        
        try:
            # Check if either value is zero - if so, use static video URL (no file copying)
            if self.should_use_empty_video(balance, validity_days):
                self.logger.info(f"Worker {self.instance_id}: Either balance ({balance}) or validity ({validity_days}) is low for user {user_id}, using static video URL")
                
                # Get the pre-existing static video URL (no file operations)
                static_video_url = self.get_static_video_url(circle_name)
                
                if not static_video_url:
                    raise Exception("Failed to get static video URL")
                
                # Update database records with the static video URL
                video_id = self.insert_video_record(user_id, static_video_url, 'completed')
                if not video_id:
                    raise Exception("Failed to insert video record")
                
                # Update user status to 'processed' (this will increment processed_records)
                if not self.update_user_status(user_id, 'processed'):
                    raise Exception("Failed to update user status")
                
                self.logger.info(f"Worker {self.instance_id}: Static video URL assigned for user {user_id}")
                self.logger.info(f"Static Video URL: {static_video_url}")
                
                return True
            
            # Create temporary file names with worker ID to avoid conflicts
            temp_dir = f"temp_worker_{self.instance_id}"
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir, exist_ok=True)
            
            validity_audio_file = f"{temp_dir}/validity_{mobile}_{campaign_id}.mp3"
            amount_audio_file = f"{temp_dir}/amount_{mobile}_{campaign_id}.mp3"
            temp_video_with_audio = f"{temp_dir}/video_{mobile}_{campaign_id}.mp4"
            
            # Step 1: Generate audio files
            self.logger.info("Step 1: Generating audio files")
            validity_duration = self.generate_audio_for_digits(formatted_validity, validity_audio_file, circle_config)
            amount_duration = self.generate_audio_for_digits(formatted_amount, amount_audio_file, circle_config)
            
            # Step 2: Embed audio into video
            self.logger.info("Step 2: Embedding audio into video")
            success_audio = self.embed_audio_in_video(
                circle_config['input_video_path'],
                validity_audio_file,
                amount_audio_file,
                temp_video_with_audio,
                circle_config
            )
            
            if not success_audio:
                raise Exception("Failed to embed audio into video")
            
            # Step 3: Add text overlays
            self.logger.info("Step 3: Adding text overlays")
            success_text = self.add_text_overlay(
                temp_video_with_audio,
                formatted_validity,
                formatted_amount,
                final_video_path,
                circle_config
            )
            
            if not success_text:
                raise Exception("Failed to add text overlays")
            
            # Step 4: Update database records
            self.logger.info("Step 4: Updating database records")
            
            # Insert video record
            video_id = self.insert_video_record(user_id, public_url, 'completed')
            if not video_id:
                raise Exception("Failed to insert video record")
            
            # Update user status to 'processed' (this will increment processed_records)
            if not self.update_user_status(user_id, 'processed'):
                raise Exception("Failed to update user status")
            
            self.logger.info(f"Worker {self.instance_id}: Video generation completed for user {user_id}")
            self.logger.info(f"Video saved at: {final_video_path}")
            self.logger.info(f"Public URL: {public_url}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Video generation failed for user {user_id}: {e}")
            # email_alert("Video Generation Failed", f"Worker {self.instance_id}: Video generation failed for user {user_id}: {e}")
            
            # Insert failed video record
            self.insert_video_record(user_id, "", 'failed')
            
            # Update user status to 'failed' (this will increment processed_records)
            self.update_user_status(user_id, 'failed')
            
            return False

        finally:
            # Clean up temporary files (only if they exist and we're not using static video)
            if not self.should_use_empty_video(balance, validity_days):
                temp_files = [
                    f"temp_worker_{self.instance_id}/validity_{mobile}_{campaign_id}.mp3",
                    f"temp_worker_{self.instance_id}/amount_{mobile}_{campaign_id}.mp3",
                    f"temp_worker_{self.instance_id}/video_{mobile}_{campaign_id}.mp4",
                    f"temp_worker_{self.instance_id}/final_{mobile}_{campaign_id}.mp4"
                ]
                for temp_file in temp_files:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                            self.logger.info(f"Cleaned up: {temp_file}")
                    except Exception as e:
                        self.logger.warning(f"Could not clean up {temp_file}: {e}")
    
    def check_dependencies(self):
        """Check if required dependencies are available"""
        self.logger.info(f"Worker {self.instance_id}: Checking dependencies...")
        
        # Check FFmpeg
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, check=True)
            self.logger.info("FFmpeg is available")
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.logger.error("FFmpeg not found! Please install FFmpeg first.")
            # email_alert("FFmpeg Not Found", f"Worker {self.instance_id}: FFmpeg not found")
            return False
        
        # Check Google Cloud credentials
        if not os.path.exists("svc.json"):
            self.logger.error("Google Cloud service account file 'svc.json' not found!")
            self.logger.error("Make sure svc.json is in vi_video/python/ directory")
            # email_alert("Google Cloud Credentials Missing", f"Worker {self.instance_id}: svc.json not found")
            return False
        else:
            self.logger.info("Google Cloud credentials file found")
        
        # Check video configuration
        if not os.path.exists("video_config.json"):
            self.logger.error("Video configuration file 'video_config.json' not found!")
            self.logger.error("Make sure video_config.json is in vi_video/python/ directory")
            # email_alert("Video Config Missing", f"Worker {self.instance_id}: video_config.json not found")
            return False
        
        # Check output directory
        video_output_dir = self.config['default_config']['video_output_dir']
        if not os.path.exists(video_output_dir):
            self.logger.info(f"Creating output directory: {video_output_dir}")
            try:
                os.makedirs(video_output_dir, exist_ok=True)
                self.logger.info(f"Output directory created: {video_output_dir}")
            except Exception as e:
                self.logger.error(f"Failed to create output directory: {e}")
                # email_alert("Output Directory Creation Failed", f"Worker {self.instance_id}: Failed to create output directory: {e}")
                return False
        
        # Check input videos exist for all configured circles
        missing_videos = []
        for circle, config in self.config['video_configs'].items():
            input_video = config['input_video_path']
            
            if not os.path.exists(input_video):
                missing_videos.append(f"Circle {circle}: {input_video}")
        
        if missing_videos:
            self.logger.warning(f"Missing input videos: {missing_videos}")
            self.logger.warning("Videos for some circles may fail to generate")
            # email_alert("Missing Input Videos", f"Worker {self.instance_id}: Missing input videos: {missing_videos}")
        
        # Note: We no longer check for empty_value_video_path since we're using pre-existing static URLs
        self.logger.info("Static video URLs will be used for low balance/validity (no file copying)")
        
        # Log filter_circles configuration
        filter_circles = self.config['default_config'].get('filter_circles', [])
        if filter_circles:
            self.logger.info(f"Circle filtering enabled. Filtered circles: {filter_circles}")
        else:
            self.logger.info("No circle filtering configured (filter_circles is empty or not set)")
        
        return True
    
    def worker_main_loop_with_fresh_connection(self):
        """Main worker loop using fresh database connections for queries"""
        self.logger.info(f"Worker {self.instance_id}: Starting main processing loop (fresh connection mode)")
        
        processed_count = 0
        loop_iterations = 0
        last_reconnect_time = time.time()
        
        while True:
            try:
                loop_iterations += 1
                current_time = time.time()
                
                # Reconnect database every 4 hours to prevent connection timeout
                if current_time - last_reconnect_time > 14400:  # 4 hours = 14400 seconds
                    self.logger.info(f"Worker {self.instance_id}: Reconnecting database (4-hour maintenance)")
                    if not self.reconnect_database():
                        self.logger.error(f"Worker {self.instance_id}: Failed to reconnect, will retry in 60 seconds")
                        time.sleep(60)
                        continue
                    last_reconnect_time = current_time
                
                # Use fresh connection to get pending users
                pending_users = self.get_pending_users_for_instance_fresh()
                
                if not pending_users:
                    self.logger.info(f"Worker {self.instance_id}: No pending users, sleeping... (iteration {loop_iterations})")
                    time.sleep(30)  # Wait 30 seconds when no work
                    continue
                
                # Process each user using the existing persistent connection
                for user_data in pending_users:
                    try:
                        # Handle both dictionary and tuple formats
                        if isinstance(user_data, dict):
                            # Dictionary format
                            user_id = int(user_data['id'])
                            mobile = str(user_data['mobile'])
                            current_balance = float(user_data['current_balance'])
                            validity_in_days = int(user_data['validity_in_days'])
                            circle_name = str(user_data['circle_name']) if user_data['circle_name'] else None
                            campaign_name = str(user_data['campaign_name'])
                            campaign_id = int(user_data['campaign_id'])
                        else:
                            # Tuple format
                            user_id = int(user_data[0])
                            mobile = str(user_data[1])
                            current_balance = float(user_data[2])
                            validity_in_days = int(user_data[3])
                            circle_name = str(user_data[4]) if user_data[4] else None
                            campaign_name = str(user_data[5])
                            campaign_id = int(user_data[6])
                        
                        self.logger.info(f"Worker {self.instance_id}: Attempting to process user {user_id} (mobile: {mobile}, circle: {circle_name})")
                        
                        # Try to claim this user atomically using persistent connection
                        if self.claim_user_for_processing(user_id):
                            self.logger.info(f"Worker {self.instance_id}: Successfully claimed user {user_id}")
                            
                            try:
                                # Check if circle is in filter list BEFORE processing
                                if self.is_circle_filtered(circle_name):
                                    self.logger.info(f"Worker {self.instance_id}: Circle '{circle_name}' is in filter list, marking user {user_id} as failed")
                                    
                                    # Insert failed video record
                                    self.insert_video_record(user_id, "", 'failed')
                                    
                                    # Update user status to 'failed' (this will increment processed_records)
                                    self.update_user_status(user_id, 'failed')
                                    
                                    self.logger.info(f"Worker {self.instance_id}: User {user_id} marked as failed due to filtered circle '{circle_name}'")
                                    continue  # Skip to next user
                                
                                # Generate video for this user (only if not filtered)
                                success = self.generate_video_for_user(
                                    user_id, mobile, current_balance, validity_in_days, 
                                    circle_name, campaign_id
                                )
                                
                                if success:
                                    processed_count += 1
                                    self.logger.info(f"Worker {self.instance_id}: Successfully processed user {user_id} (total: {processed_count})")
                                else:
                                    self.logger.error(f"Worker {self.instance_id}: Failed to process user {user_id}")
                            
                            except Exception as e:
                                self.logger.error(f"Worker {self.instance_id}: Unexpected error processing user {user_id}: {e}")
                                email_alert("Unexpected Processing Error", f"Worker {self.instance_id}: Unexpected error processing user {user_id}: {e}")
                                # Update user status to failed (this will increment processed_records)
                                self.update_user_status(user_id, 'failed')
                        
                        else:
                            self.logger.info(f"Worker {self.instance_id}: User {user_id} already claimed by another worker")
                    
                    except Exception as e:
                        self.logger.error(f"Worker {self.instance_id}: Error processing user data: {e}")
                        import traceback
                        self.logger.error(f"Traceback: {traceback.format_exc()}")
                        # email_alert("Error Processing User Data", f"Worker {self.instance_id}: Error processing user data: {e}")
                        continue
                
                # Small delay between batches
                time.sleep(5)
                    
            except Exception as e:
                self.logger.error(f"Worker {self.instance_id}: Error in main loop: {e}")
                email_alert("Worker Main Loop Error", f"Worker {self.instance_id}: Error in main loop: {e}")
                import traceback
                self.logger.error(f"Worker {self.instance_id}: Traceback: {traceback.format_exc()}")
                time.sleep(10)  # Wait 10 seconds on error before retrying


def main():
    """Main function"""
    # Get instance parameters from command line
    if len(sys.argv) != 3:
        print("Usage: python3 script_2.py <instance_id> <total_instances>")
        print("Example: python3 script_2.py 0 10")
        sys.exit(1)
    
    try:
        instance_id = int(sys.argv[1])
        total_instances = int(sys.argv[2])
    except ValueError:
        print("Error: instance_id and total_instances must be integers")
        sys.exit(1)
    
    # Validate parameters
    if instance_id < 0 or instance_id >= total_instances:
        print(f"Error: instance_id must be between 0 and {total_instances-1}")
        sys.exit(1)
    
    if total_instances <= 0:
        print("Error: total_instances must be greater than 0")
        sys.exit(1)
    
    # Initialize worker
    processor = VideoWorkerProcessor(instance_id, total_instances)
    
    # Check dependencies
    if not processor.check_dependencies():
        print("Dependency check failed!")
        # email_alert("Dependency Check Failed", f"Worker {instance_id}: Dependency check failed")
        sys.exit(1)
    
    # Connect to database
    if not processor.connect_database():
        print("Database connection failed!")
        sys.exit(1)
    
    try:
        # Start main worker loop with fresh connection approach
        processor.worker_main_loop_with_fresh_connection()
        
    except KeyboardInterrupt:
        processor.logger.info(f"Worker {instance_id}: Received shutdown signal")
        print(f"Worker {instance_id} shutting down...")
        
    except Exception as e:
        processor.logger.error(f"Worker {instance_id}: Unexpected error in main: {e}")
        # email_alert("Worker Fatal Error", f"Worker {instance_id}: Unexpected error in main: {e}")
        print(f"Worker {instance_id} failed with unexpected error!")
        sys.exit(1)
        
    finally:
        # Always close the database connection
        processor.disconnect_database()
        processor.logger.info(f"Worker {instance_id}: Shutdown complete")


if __name__ == "__main__":
    main()