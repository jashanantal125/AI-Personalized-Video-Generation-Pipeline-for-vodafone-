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

# Import database connection
from db_script import db_connection

# Set up Google Cloud credentials
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "svc.json"

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
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Failed to load video configuration: {e}")
            sys.exit(1)
    
    def get_circle_config(self, circle_name):
        """Get configuration for specific circle"""
        # Normalize circle name (remove leading zeros, etc.)
        if circle_name and str(circle_name).isdigit():
            normalized_circle = str(int(circle_name))
        else:
            normalized_circle = str(circle_name) if circle_name else "6"
        
        if normalized_circle in self.config['video_configs']:
            self.logger.info(f"Using configuration for circle: {normalized_circle}")
            return self.config['video_configs'][normalized_circle]
        else:
            # Use default configuration
            default_circle = self.config['default_config']['circle']
            self.logger.warning(f"Circle {normalized_circle} not found, using default: {default_circle}")
            return self.config['video_configs'][default_circle]
    
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
                return False
        except Exception as e:
            self.logger.error(f"Database connection failed: {e}")
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
    
    def get_pending_users_for_instance_fresh(self):
        """Get pending users with a completely fresh database connection"""
        fresh_connection = None
        fresh_cursor = None
        
        try:
            # Create a completely fresh connection for this query
            fresh_connection = db_connection()
            if not fresh_connection:
                self.logger.error("Failed to create fresh database connection")
                return []
            
            # Use default cursor (returns tuples) for consistency
            fresh_cursor = fresh_connection.cursor()
            
            # Ensure we're reading the latest committed data
            fresh_cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            fresh_cursor.execute("SET autocommit = 1")
            
            query = """
            SELECT u.id, u.mobile, u.current_balance, u.validity_in_days, 
                   COALESCE(u.circle_name, '6') as circle_name, c.campaign_name, c.id as campaign_id
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
                
                # Show sample of recent users regardless of status
                debug_query5 = "SELECT id, mobile, status, campaign_id, created_at FROM users ORDER BY created_at DESC LIMIT 5"
                fresh_cursor.execute(debug_query5)
                recent_users = fresh_cursor.fetchall()
                self.logger.info(f"Worker {self.instance_id} Debug - Recent users: {recent_users}")
            
            return users
            
        except Exception as e:
            self.logger.error(f"Error fetching pending users with fresh connection: {e}")
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
        """Update user status"""
        try:
            query = "UPDATE users SET status = %s WHERE id = %s"
            self.cursor.execute(query, (status, user_id))
            
            # Update campaign processed_records if status is 'processed'
            if status == 'processed':
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
            # Use empty video if ANY value is zero
            return balance_zero or validity_zero
        except (ValueError, TypeError):
            # If we can't parse the values, use empty video as safe fallback
            return True
    
    # def get_static_video_url(self, circle_name):
    #     """Get the pre-existing static video URL for a circle without copying any files"""
    #     try:
    #         # Normalize circle name
    #         if circle_name and str(circle_name).isdigit():
    #             normalized_circle = str(int(circle_name))
    #         else:
    #             normalized_circle = str(circle_name) if circle_name else "6"
            
    #         # Construct the static video URL
    #         public_url_base = self.config['default_config']['public_url_base']
    #         static_video_url = f"{public_url_base}/{normalized_circle}.mp4"
            
    #         self.logger.info(f"Using pre-existing static video URL: {static_video_url}")
            
    #         return static_video_url
            
    #     except Exception as e:
    #         self.logger.error(f"Error getting static video URL: {e}")
    #         return None

    def get_static_video_url(self, circle_name):
        """Get the pre-existing static video URL for a circle without copying any files"""
        try:
            # Normalize circle name
            if circle_name and str(circle_name).isdigit():
                # Convert to int, then pad with leading zero if needed
                normalized_circle = f"{int(circle_name):02d}"
            else:
                # Use default if circle_name is missing or invalid
                normalized_circle = "06"

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
        """Generate TTS audio with appropriate speaking rate based on digit count and circle-specific voice"""
        digit_count = len(str(text))
        
        # Get speaking rates from circle config instead of default config
        speaking_rates = circle_config.get('speaking_rates', {
            "1": 0.7,
            "2": 0.7,
            "3": 1.0,
            "4": 1.4
        })
        speaking_rate = speaking_rates.get(str(digit_count), 1.0)
        
        # Get language and voice from circle config
        language_code = circle_config.get('language_code', 'hi-IN')
        tts_voice_name = circle_config.get('tts_voice_name', 'hi-IN-Neural2-A')
        
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
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            self.logger.error(f"Error embedding audio: {result.stderr}")
            return False
        
        self.logger.info(f"Successfully embedded audio: {output_video}")
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
        """Add text overlays with WhatsApp-compatible encoding"""
        self.logger.info("Adding text overlays to video...")
        
        validity_digits = len(str(validity_text))
        amount_digits = len(str(amount_text))
        
        # Get font sizing based on circle configuration
        is_dynamic_font = circle_config.get('is_dynamic_font_circle', False)
        
        if is_dynamic_font:
            # Dynamic font sizing based on digit count
            validity_font_size = 11 if validity_digits == 4 else 15
            amount_font_size = 11 if amount_digits == 4 else 15
            self.logger.info(f"Using dynamic font sizing: validity={validity_font_size}, amount={amount_font_size}")
        else:
            # Fixed font size
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
        
        # Escape text properly for FFmpeg
        validity_escaped = str(validity_text).replace("'", "\\'").replace(":", "\\:")
        amount_escaped = str(amount_text).replace("'", "\\'").replace(":", "\\:")
        
        font_path = self.get_available_font()
        
        if font_path:
            drawtext_filter = (
                f"drawtext=fontfile='{font_path}':text='{validity_escaped}':fontsize={validity_font_size}:fontcolor=white:"
                f"x={text_x1}:y={text_y1}:enable='between(t,{circle_config['val_text_start_time']},{circle_config['val_text_end_time']})',"
                f"drawtext=fontfile='{font_path}':text='{amount_escaped}':fontsize={amount_font_size}:fontcolor=white:"
                f"x={text_x2}:y={text_y2}:enable='between(t,{circle_config['amnt_text_start_time']},{circle_config['amnt_text_end_time']})'"
            )
        else:
            drawtext_filter = (
                f"drawtext=fontfamily=sans:text='{validity_escaped}':fontsize={validity_font_size}:fontcolor=white:"
                f"x={text_x1}:y={text_y1}:enable='between(t,{circle_config['val_text_start_time']},{circle_config['val_text_end_time']})',"
                f"drawtext=fontfamily=sans:text='{amount_escaped}':fontsize={amount_font_size}:fontcolor=white:"
                f"x={text_x2}:y={text_y2}:enable='between(t,{circle_config['amnt_text_start_time']},{circle_config['amnt_text_end_time']})'"
            )
        
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
            output_file
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.logger.info("Text overlay added successfully")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error adding text overlay: {e}")
            return False
    
    def generate_video_for_user(self, user_id, mobile, balance, validity_days, circle_name, campaign_id):
        """Generate video for a specific user using circle-specific configuration"""
        self.logger.info(f"Worker {self.instance_id}: Generating video for user {user_id} (mobile: {mobile}, circle: {circle_name})")
        
        # Get circle-specific configuration
        circle_config = self.get_circle_config(circle_name)
        
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
                
                # Update user status to 'processed'
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
            
            # Update user status to 'processed'
            if not self.update_user_status(user_id, 'processed'):
                raise Exception("Failed to update user status")
            
            self.logger.info(f"Worker {self.instance_id}: Video generation completed for user {user_id}")
            self.logger.info(f"Video saved at: {final_video_path}")
            self.logger.info(f"Public URL: {public_url}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Video generation failed for user {user_id}: {e}")
            
            # Insert failed video record
            self.insert_video_record(user_id, "", 'failed')
            
            # Update user status to 'failed'
            self.update_user_status(user_id, 'failed')
            
            return False
            
        finally:
            # Clean up temporary files (only if they exist and we're not using static video)
            if not self.should_use_empty_video(balance, validity_days):
                temp_files = [
                    f"temp_worker_{self.instance_id}/validity_{mobile}_{campaign_id}.mp3",
                    f"temp_worker_{self.instance_id}/amount_{mobile}_{campaign_id}.mp3",
                    f"temp_worker_{self.instance_id}/video_{mobile}_{campaign_id}.mp4"
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
            return False
        
        # Check Google Cloud credentials
        if not os.path.exists("svc.json"):
            self.logger.error("Google Cloud service account file 'svc.json' not found!")
            self.logger.error("Make sure svc.json is in vi_video/python/ directory")
            return False
        else:
            self.logger.info("Google Cloud credentials file found")
        
        # Check video configuration
        if not os.path.exists("video_config.json"):
            self.logger.error("Video configuration file 'video_config.json' not found!")
            self.logger.error("Make sure video_config.json is in vi_video/python/ directory")
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
        
        # Note: We no longer check for empty_value_video_path since we're using pre-existing static URLs
        self.logger.info("Static video URLs will be used for low balance/validity (no file copying)")
        
        return True
    
    def worker_main_loop_with_fresh_connection(self):
        """Main worker loop using fresh database connections for queries"""
        self.logger.info(f"Worker {self.instance_id}: Starting main processing loop (fresh connection mode)")
        
        processed_count = 0
        loop_iterations = 0
        
        while True:
            try:
                loop_iterations += 1
                
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
                            user_id = user_data['id']
                            mobile = user_data['mobile']
                            current_balance = user_data['current_balance']
                            validity_in_days = user_data['validity_in_days']
                            circle_name = user_data['circle_name'] if user_data['circle_name'] else "6"
                            campaign_name = user_data['campaign_name']
                            campaign_id = user_data['campaign_id']
                        else:
                            # Handle tuple format (from fetchall)
                            user_id = user_data[0]
                            mobile = user_data[1]
                            current_balance = user_data[2]
                            validity_in_days = user_data[3]
                            circle_name = user_data[4] if user_data[4] else "6"
                            campaign_name = user_data[5]
                            campaign_id = user_data[6]
                        
                        self.logger.info(f"Worker {self.instance_id}: Attempting to process user {user_id} (mobile: {mobile})")
                        
                        # Try to claim this user atomically using persistent connection
                        if self.claim_user_for_processing(user_id):
                            self.logger.info(f"Worker {self.instance_id}: Successfully claimed user {user_id}")
                            
                            try:
                                # Generate video for this user
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
                                # Update user status to failed
                                self.update_user_status(user_id, 'failed')
                        
                        else:
                            self.logger.info(f"Worker {self.instance_id}: User {user_id} already claimed by another worker")
                    
                    except Exception as e:
                        self.logger.error(f"Worker {self.instance_id}: Error processing user data {user_data}: {e}")
                        continue
                
                # Small delay between batches
                time.sleep(5)
                
                # Restart worker after processing 1000 videos to prevent memory leaks
                # if processed_count >= 1000:
                #     self.logger.info(f"Worker {self.instance_id}: Processed 1000 videos, restarting for memory management...")
                #     break
                    
            except Exception as e:
                self.logger.error(f"Worker {self.instance_id}: Error in main loop: {e}")
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
        print(f"Worker {instance_id} failed with unexpected error!")
        sys.exit(1)
        
    finally:
        # Always close the database connection
        processor.disconnect_database()
        processor.logger.info(f"Worker {instance_id}: Shutdown complete")


if __name__ == "__main__":
    main()