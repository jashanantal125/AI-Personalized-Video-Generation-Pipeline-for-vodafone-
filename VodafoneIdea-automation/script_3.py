#!/usr/bin/env python3

import requests
import json
import datetime
import os
import mysql.connector
from mysql.connector import Error
import logging
import sys
import time
import csv
from pathlib import Path
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Import database connection
from db_script import db_connection

# ============================================================================
# CONFIGURATION VARIABLES - Easy to change
# ============================================================================
AUTH_KEY = "63904d234d1bdf1a"  # w2
API_URL = "https://whatsapp.adznetworkmedia.om/restapi/bulkwp_json.php"
WID = "13108"
BATCH_SIZE = 10  # Number of users per batch
BATCH_DELAY = 2  # Seconds to wait between batches
MEDIA_CHECK_TIMEOUT = 1  # Seconds to wait for media URL check
MEDIA_RETRY_DELAY = 4  # Seconds to wait before retrying failed media check

# CSV tracking directory
CSV_TRACKING_DIR = "/home/ecore/vicode/VodafoneIdea/executed_num_sheets"
# ============================================================================


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
    RECIPIENT_EMAILS = ["mahesh@ldttechnology.com"]
    
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


class CSVDuplicateTracker:
    """Manages CSV-based duplicate tracking for mobile numbers"""
    
    def __init__(self, base_dir, logger):
        self.base_dir = base_dir
        self.logger = logger
        self.cache = {}  # In-memory cache: {date: {mobile: {timestamp, occurrence, campaign_id}}}
        
        # Create directory if it doesn't exist
        Path(self.base_dir).mkdir(parents=True, exist_ok=True)
        self.logger.info(f"CSV tracking directory: {self.base_dir}")
    
    def get_csv_path(self, date):
        """Get CSV file path for a specific date"""
        date_str = date.strftime("%Y-%m-%d")
        return os.path.join(self.base_dir, f"{date_str}.csv")
    
    def load_csv(self, date):
        """Load CSV file for a specific date into cache"""
        date_str = date.strftime("%Y-%m-%d")
        
        if date_str in self.cache:
            return self.cache[date_str]
        
        csv_path = self.get_csv_path(date)
        mobile_data = {}
        
        if os.path.exists(csv_path):
            try:
                with open(csv_path, 'r', newline='') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        mobile_data[row['mobile']] = {
                            'first_sent_timestamp': row['first_sent_timestamp'],
                            'occurrence_count': int(row['occurrence_count']),
                            'last_campaign_id': row['last_campaign_id']
                        }
                self.logger.info(f"Loaded {len(mobile_data)} mobiles from {csv_path}")
            except Exception as e:
                self.logger.error(f"Error loading CSV {csv_path}: {e}")
                mobile_data = {}
        else:
            self.logger.info(f"CSV file {csv_path} does not exist, will create new one")
        
        self.cache[date_str] = mobile_data
        return mobile_data
    
    def save_csv(self, date):
        """Save cache data to CSV file for a specific date"""
        date_str = date.strftime("%Y-%m-%d")
        
        if date_str not in self.cache:
            self.logger.warning(f"No cache data to save for {date_str}")
            return False
        
        csv_path = self.get_csv_path(date)
        mobile_data = self.cache[date_str]
        
        try:
            with open(csv_path, 'w', newline='') as csvfile:
                fieldnames = ['mobile', 'first_sent_timestamp', 'occurrence_count', 'last_campaign_id']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for mobile, data in mobile_data.items():
                    writer.writerow({
                        'mobile': mobile,
                        'first_sent_timestamp': data['first_sent_timestamp'],
                        'occurrence_count': data['occurrence_count'],
                        'last_campaign_id': data['last_campaign_id']
                    })
            
            self.logger.info(f"Saved {len(mobile_data)} mobiles to {csv_path}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving CSV {csv_path}: {e}")
            return False
    
    def check_and_add_mobile(self, mobile, campaign_created_date, campaign_id):
        """
        Check if mobile exists in CSV for campaign creation date.
        If exists: increment occurrence and return True (is duplicate)
        If not exists: add to CSV and return False (not duplicate)
        
        Returns:
            tuple: (is_duplicate: bool, occurrence_count: int)
        """
        date_str = campaign_created_date.strftime("%Y-%m-%d")
        
        # Load cache for this date
        mobile_data = self.load_csv(campaign_created_date)
        
        if mobile in mobile_data:
            # Mobile exists - increment occurrence
            mobile_data[mobile]['occurrence_count'] += 1
            mobile_data[mobile]['last_campaign_id'] = str(campaign_id)
            occurrence = mobile_data[mobile]['occurrence_count']
            
            self.logger.info(f"DUPLICATE: Mobile {mobile} found in {date_str} CSV (occurrence: {occurrence})")
            
            # Save updated data
            self.save_csv(campaign_created_date)
            
            return True, occurrence
        else:
            # Mobile doesn't exist - add it
            current_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mobile_data[mobile] = {
                'first_sent_timestamp': current_timestamp,
                'occurrence_count': 1,
                'last_campaign_id': str(campaign_id)
            }
            
            self.logger.info(f"NEW: Mobile {mobile} added to {date_str} CSV")
            
            # Save updated data
            self.save_csv(campaign_created_date)
            
            return False, 1


class WhatsAppMessagingProcessor:
    def __init__(self):
        """Initialize the WhatsApp messaging processor"""
        self.setup_logging()
        self.connection = None
        self.cursor = None
        
        # API configuration
        self.api_url = API_URL
        self.headers = {
            "Content-Type": "application/json"
        }
        self.auth_key = AUTH_KEY
        self.wid = WID
        self.batch_size = BATCH_SIZE
        self.batch_delay = BATCH_DELAY
        
        # Initialize CSV duplicate tracker
        self.duplicate_tracker = CSVDuplicateTracker(CSV_TRACKING_DIR, self.logger)
        
    def setup_logging(self):
        """Setup logging configuration"""
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f'{log_dir}/whatsapp_messaging_{datetime.datetime.now().strftime("%Y%m%d")}.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def connect_database(self):
        """Get database connection from external db_script"""
        try:
            self.connection = db_connection()
            if self.connection:
                self.cursor = self.connection.cursor()
                
                # Test cursor
                self.cursor.execute("SELECT 1")
                test_result = self.cursor.fetchone()
                self.logger.info(f"Database cursor test result: {test_result}")
                
                self.logger.info("Database connection established")
                return True
            else:
                self.logger.error("Failed to get database connection")
                email_alert("Database Connection Failed", "Script 3: Failed to get database connection")
                return False
        except Exception as e:
            self.logger.error(f"Database connection failed: {e}")
            email_alert("Database Connection Error", f"Script 3: Database connection failed: {e}")
            return False
    
    def disconnect_database(self):
        """Close database connection"""
        try:
            if self.cursor:
                self.cursor.close()
                self.logger.info("Database cursor closed")
            if self.connection:
                self.connection.close()
                self.logger.info("Database connection closed")
        except Exception as e:
            self.logger.error(f"Error closing database connection: {e}")
    
    def get_ongoing_campaigns(self):
        """Get all campaigns with 'ongoing' status"""
        try:
            fresh_cursor = self.connection.cursor()
            query = "SELECT id, campaign_name, total_users, created_at FROM campaigns WHERE status = 'ongoing'"
            fresh_cursor.execute(query)
            campaigns = fresh_cursor.fetchall()
            fresh_cursor.close()
            
            self.logger.info(f"Raw campaigns data: {campaigns}")
            
            # Handle both dictionary and tuple results
            valid_campaigns = []
            for campaign in campaigns:
                try:
                    if isinstance(campaign, dict):
                        campaign_id = int(campaign['id'])
                        campaign_name = str(campaign['campaign_name'])
                        total_users = int(campaign['total_users']) if campaign['total_users'] else 0
                        created_at = campaign['created_at']
                    else:
                        campaign_id = int(campaign[0])
                        campaign_name = str(campaign[1])
                        total_users = int(campaign[2]) if campaign[2] else 0
                        created_at = campaign[3]
                    
                    valid_campaigns.append((campaign_id, campaign_name, total_users, created_at))
                    self.logger.info(f"Valid campaign found: ID={campaign_id}, Name='{campaign_name}', Total Users={total_users}, Created={created_at}")
                except (ValueError, TypeError, KeyError, IndexError) as e:
                    self.logger.warning(f"Skipping invalid campaign data: {campaign}, Error: {e}")
                    continue
            
            self.logger.info(f"Found {len(valid_campaigns)} ongoing campaigns")
            return valid_campaigns
        except Error as e:
            self.logger.error(f"Error fetching ongoing campaigns: {e}")
            email_alert("Error Fetching Campaigns", f"Script 3: Error fetching ongoing campaigns: {e}")
            return []
    
    def check_media_availability(self, video_url, user_id):
        """
        Check if media URL is accessible with retry logic
        Returns: True if accessible (200), False otherwise
        """
        try:
            # First attempt
            self.logger.info(f"Checking media availability for user {user_id}: {video_url}")
            response = requests.head(video_url, timeout=MEDIA_CHECK_TIMEOUT, allow_redirects=True)
            
            if response.status_code == 200:
                self.logger.info(f"Media available (200) for user {user_id}")
                return True
            
            # If not 200, wait and retry once
            self.logger.warning(f"Media check failed (status {response.status_code}) for user {user_id}, retrying in {MEDIA_RETRY_DELAY}s...")
            time.sleep(MEDIA_RETRY_DELAY)
            
            # Second attempt
            response = requests.head(video_url, timeout=MEDIA_CHECK_TIMEOUT, allow_redirects=True)
            
            if response.status_code == 200:
                self.logger.info(f"Media available (200) on retry for user {user_id}")
                return True
            else:
                self.logger.error(f"Media unavailable (status {response.status_code}) for user {user_id} after retry")
                return False
                
        except requests.exceptions.Timeout:
            self.logger.error(f"Media check timeout for user {user_id}: {video_url}")
            return False
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Media check error for user {user_id}: {e}")
            return False
    
    def get_users_ready_for_messaging(self, campaign_id, campaign_created_date):
        """
        Get users who are ready for messaging but haven't been attempted yet
        NO filtering by today's date - CSV tracker handles all duplicate prevention
        """
        try:
            fresh_cursor = self.connection.cursor()
            
            # Get users with completed videos who DON'T have any logging_table entries yet
            query = """
                SELECT u.id, u.mobile, v.video_public_url, v.id as video_id
                FROM users u
                JOIN videos_table v ON u.id = v.users_id
                LEFT JOIN logging_table l ON u.id = l.users_id AND u.campaign_id = l.campaign_id AND v.id = l.video_id
                WHERE u.campaign_id = %s 
                AND u.status = 'processed' 
                AND v.generation_status = 'completed'
                AND v.video_public_url != ''
                AND v.video_public_url IS NOT NULL
                AND l.users_id IS NULL
                ORDER BY u.id
            """
            fresh_cursor.execute(query, (campaign_id,))
            users = fresh_cursor.fetchall()
            fresh_cursor.close()
            
            self.logger.info(f"Found {len(users)} users with videos and no logging entries in campaign {campaign_id}")
            
            # Handle both dictionary and tuple results
            valid_users = []
            csv_duplicates = []
            
            for user in users:
                try:
                    if isinstance(user, dict):
                        user_id = int(user['id'])
                        mobile = str(user['mobile']).strip()
                        video_url = str(user['video_public_url']).strip()
                        video_id = int(user['video_id'])
                    else:
                        user_id = int(user[0])
                        mobile = str(user[1]).strip()
                        video_url = str(user[2]).strip()
                        video_id = int(user[3])
                    
                    # Validate mobile number format (basic validation)
                    if len(mobile) < 10 or not mobile.isdigit():
                        self.logger.warning(f"Invalid mobile number for user {user_id}: {mobile}")
                        continue
                    
                    # Validate video URL
                    if not video_url.startswith(('http://', 'https://')):
                        self.logger.warning(f"Invalid video URL for user {user_id}: {video_url}")
                        continue
                    
                    # Check CSV duplicate tracker (based on campaign creation date)
                    is_duplicate, occurrence = self.duplicate_tracker.check_and_add_mobile(
                        mobile, 
                        campaign_created_date.date() if isinstance(campaign_created_date, datetime.datetime) else campaign_created_date,
                        campaign_id
                    )
                    
                    if is_duplicate:
                        self.logger.info(f"Mobile {mobile} (user {user_id}) is DUPLICATE (occurrence: {occurrence}) - marking as sent without API call")
                        csv_duplicates.append((user_id, mobile, video_id, occurrence))
                        continue
                    
                    valid_users.append((user_id, mobile, video_url, video_id))
                    
                except (ValueError, TypeError, KeyError, IndexError) as e:
                    self.logger.warning(f"Skipping invalid user data: {user}, Error: {e}")
                    continue
            
            self.logger.info(f"Valid users ready for messaging: {len(valid_users)}")
            self.logger.info(f"Users skipped (CSV duplicates): {len(csv_duplicates)}")
            
            # Mark CSV duplicate users as 'sent' without actually sending
            for user_id, mobile, video_id, occurrence in csv_duplicates:
                self.mark_as_duplicate_sent(campaign_id, user_id, video_id, mobile, occurrence)
            
            return valid_users
            
        except Error as e:
            self.logger.error(f"Error fetching users ready for messaging: {e}")
            email_alert("Error Fetching Users", f"Script 3: Error fetching users for campaign {campaign_id}: {e}")
            return []
    
    def mark_as_duplicate_sent(self, campaign_id, user_id, video_id, mobile, occurrence):
        """
        Mark a user as 'sent' in logging_table because their mobile is a duplicate (found in CSV)
        This prevents duplicate sends while maintaining accurate campaign completion tracking
        """
        try:
            fresh_cursor = self.connection.cursor()
            
            # Check if entry already exists
            check_query = """
                SELECT id FROM logging_table 
                WHERE campaign_id = %s AND users_id = %s AND video_id = %s
            """
            fresh_cursor.execute(check_query, (campaign_id, user_id, video_id))
            existing_entry = fresh_cursor.fetchone()
            
            if existing_entry:
                self.logger.debug(f"Entry already exists for user {user_id}, skipping")
                fresh_cursor.close()
                return True
            
            # Insert as 'sent' with current timestamp
            sent_at = datetime.datetime.now()
            
            query = """
                INSERT INTO logging_table (campaign_id, users_id, video_id, delivery_status, sent_at)
                VALUES (%s, %s, %s, 'sent', %s)
            """
            fresh_cursor.execute(query, (campaign_id, user_id, video_id, sent_at))
            self.connection.commit()
            fresh_cursor.close()
            
            self.logger.info(f"User {user_id} (mobile: {mobile}) marked as sent (duplicate #{occurrence} from CSV)")
            return True
            
        except Error as e:
            self.logger.error(f"Error marking user as duplicate sent: {e}")
            self.connection.rollback()
            return False
    
    def send_whatsapp_batch(self, batch_user_info):
        """Send WhatsApp media messages via bulk API for a batch
        
        Args:
            batch_user_info: Dictionary with mobile as key and dict with user_id, video_id, video_url
        """
        self.logger.info(f"Sending WhatsApp batch to {len(batch_user_info)} users using bulk API")
        
        # Prepare the messages array for bulk API format
        messages = []
        for mobile, user_data in batch_user_info.items():
            message_obj = {
                "dest": [str(mobile)],
                "param": {
                    "1": ""  # Dynamic content parameter if needed
                },
                "headerValues": {
                    "headerFileName": "video",
                    "headerData": user_data['video_url']
                }
            }
            messages.append(message_obj)
        
        # Prepare the request payload in bulk API format
        payload = {
            "version": "1.0",
            "authkey": self.auth_key,
            "encrpt": "0",
            "wid": self.wid,
            "country_code": "91",
            "type": "media",
            "dynamic_content": "1",
            "messages": messages
        }
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # Make the API request
            self.logger.info(f"Making API request to {self.api_url}")
            self.logger.info(f"Payload preview (first message): {json.dumps({'messages': messages[:1]}, indent=2)}")
            
            response = requests.post(self.api_url, json=payload, headers=self.headers, timeout=60)
            
            # Parse response
            try:
                response_json = response.json()
            except json.JSONDecodeError:
                response_json = {"error": "Invalid JSON response", "raw_response": response.text}
            
            self.logger.info(f"API Response - Status Code: {response.status_code}")
            self.logger.info(f"API Response - Body: {json.dumps(response_json, indent=2)}")
            
            return {
                "success": response.status_code == 200,
                "status_code": response.status_code,
                "response": response_json,
                "timestamp": timestamp,
                "batch_user_info": batch_user_info
            }
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API request failed: {str(e)}")
            email_alert("WhatsApp API Error", f"Script 3: API request failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": timestamp,
                "batch_user_info": batch_user_info
            }
    
    def log_delivery_status(self, campaign_id, user_id, video_id, mobile, delivery_status, api_response=None):
        """Log delivery status to logging_table with duplicate prevention"""
        try:
            fresh_cursor = self.connection.cursor()
            
            # First check if entry already exists to prevent duplicates
            check_query = """
                SELECT id FROM logging_table 
                WHERE campaign_id = %s AND users_id = %s AND video_id = %s
            """
            fresh_cursor.execute(check_query, (campaign_id, user_id, video_id))
            existing_entry = fresh_cursor.fetchone()
            
            if existing_entry:
                self.logger.warning(f"Entry already exists for user {user_id} in campaign {campaign_id}, skipping duplicate")
                fresh_cursor.close()
                return True
            
            sent_at = datetime.datetime.now() if delivery_status == 'sent' else None
            
            query = """
                INSERT INTO logging_table (campaign_id, users_id, video_id, delivery_status, sent_at)
                VALUES (%s, %s, %s, %s, %s)
            """
            fresh_cursor.execute(query, (campaign_id, user_id, video_id, delivery_status, sent_at))
            self.connection.commit()
            fresh_cursor.close()
            
            self.logger.info(f"Logged delivery status for user {user_id} (mobile: {mobile}): {delivery_status}")
            return True
            
        except Error as e:
            self.logger.error(f"Error logging delivery status: {e}")
            self.connection.rollback()
            return False
    
    def update_campaign_status(self, campaign_id, status, reason=""):
        """Update campaign status with validation"""
        try:
            fresh_cursor = self.connection.cursor()
            
            # First check current status to avoid unnecessary updates
            check_query = "SELECT status FROM campaigns WHERE id = %s"
            fresh_cursor.execute(check_query, (campaign_id,))
            result = fresh_cursor.fetchone()
            
            if not result:
                self.logger.error(f"Campaign {campaign_id} not found")
                fresh_cursor.close()
                return False
            
            current_status = result[0] if isinstance(result, tuple) else result['status']
            
            if current_status == status:
                self.logger.info(f"Campaign {campaign_id} already has status '{status}', no update needed")
                fresh_cursor.close()
                return True
            
            # Update status
            update_query = "UPDATE campaigns SET status = %s WHERE id = %s"
            fresh_cursor.execute(update_query, (status, campaign_id))
            self.connection.commit()
            fresh_cursor.close()
            
            log_message = f"Campaign {campaign_id} status updated from '{current_status}' to '{status}'"
            if reason:
                log_message += f" - Reason: {reason}"
            
            self.logger.info(log_message)
            # email_alert("Campaign Status Updated", log_message)
            return True
        except Error as e:
            self.logger.error(f"Error updating campaign status: {e}")
            self.connection.rollback()
            return False
    
    def check_campaign_completion(self, campaign_id, campaign_name, total_users_expected):
        """
        COMPREHENSIVE campaign completion check.
        
        A campaign is complete when:
        1. Campaign has total_users > 0 (not an empty campaign)
        2. ALL users are accounted for in users table (actual_users == total_users)
        3. NO users are pending/processing (Script 2 finished)
        4. ALL processable users (processed + failed) have logging entries
        5. Logging entries count matches processable users count EXACTLY
        
        Special case: If total_users == 0, mark as completed (empty campaign)
        """
        try:
            fresh_cursor = self.connection.cursor()
            
            # Special case: Empty campaigns (total_users = 0)
            if total_users_expected == 0:
                self.logger.info(f"Campaign {campaign_id} ({campaign_name}) has total_users=0, marking as completed")
                fresh_cursor.close()
                return True, "Empty campaign (total_users=0)"
            
            # Get comprehensive user status counts
            query = """
                SELECT 
                    COUNT(u.id) as actual_users,
                    COUNT(CASE WHEN u.status = 'pending' THEN 1 END) as pending_users,
                    COUNT(CASE WHEN u.status = 'processing' THEN 1 END) as processing_users,
                    COUNT(CASE WHEN u.status = 'processed' THEN 1 END) as processed_users,
                    COUNT(CASE WHEN u.status = 'failed' THEN 1 END) as failed_users
                FROM users u
                WHERE u.campaign_id = %s
            """
            fresh_cursor.execute(query, (campaign_id,))
            result = fresh_cursor.fetchone()
            
            if isinstance(result, dict):
                actual_users = result['actual_users'] or 0
                pending_users = result['pending_users'] or 0
                processing_users = result['processing_users'] or 0
                processed_users = result['processed_users'] or 0
                failed_users = result['failed_users'] or 0
            else:
                actual_users = result[0] or 0
                pending_users = result[1] or 0
                processing_users = result[2] or 0
                processed_users = result[3] or 0
                failed_users = result[4] or 0
            
            # Count processable users (processed + failed)
            processable_users_count = processed_users + failed_users
            
            # Count users with logging entries
            query2 = """
                SELECT COUNT(DISTINCT users_id) 
                FROM logging_table 
                WHERE campaign_id = %s
            """
            fresh_cursor.execute(query2, (campaign_id,))
            result2 = fresh_cursor.fetchone()
            logging_entries_count = result2[0] if isinstance(result2, tuple) else result2['COUNT(DISTINCT users_id)']
            
            fresh_cursor.close()
            
            # Detailed logging
            self.logger.info(f"=" * 80)
            self.logger.info(f"Campaign Completion Check: {campaign_name} (ID: {campaign_id})")
            self.logger.info(f"=" * 80)
            self.logger.info(f"  Expected total_users: {total_users_expected}")
            self.logger.info(f"  Actual users in DB: {actual_users}")
            self.logger.info(f"  Pending users: {pending_users}")
            self.logger.info(f"  Processing users: {processing_users}")
            self.logger.info(f"  Processed users: {processed_users}")
            self.logger.info(f"  Failed users: {failed_users}")
            self.logger.info(f"  Processable users (processed + failed): {processable_users_count}")
            self.logger.info(f"  Users with logging entries: {logging_entries_count}")
            self.logger.info(f"-" * 80)
            
            # Validation checks
            checks = []
            reasons = []
            
            # Check 1: All users inserted
            if actual_users != total_users_expected:
                checks.append(False)
                reasons.append(f"User count mismatch: expected {total_users_expected}, got {actual_users}")
            else:
                checks.append(True)
                self.logger.info(f"  ✓ Check 1 PASSED: All users inserted ({actual_users}/{total_users_expected})")
            
            # Check 2: No pending/processing users (Script 2 finished)
            if pending_users > 0 or processing_users > 0:
                checks.append(False)
                reasons.append(f"Script 2 still running: {pending_users} pending, {processing_users} processing")
            else:
                checks.append(True)
                self.logger.info(f"  ✓ Check 2 PASSED: No pending/processing users (Script 2 finished)")
            
            # Check 3: Processable users exist
            if processable_users_count == 0:
                checks.append(False)
                reasons.append("No processable users (all still pending/processing)")
            else:
                checks.append(True)
                self.logger.info(f"  ✓ Check 3 PASSED: {processable_users_count} processable users exist")
            
            # Check 4: ALL processable users have logging entries (EXACT match)
            if logging_entries_count != processable_users_count:
                checks.append(False)
                missing = processable_users_count - logging_entries_count
                reasons.append(f"Logging incomplete: {logging_entries_count}/{processable_users_count} ({missing} missing)")
            else:
                checks.append(True)
                self.logger.info(f"  ✓ Check 4 PASSED: All {processable_users_count} processable users have logging entries")
            
            # Campaign is complete ONLY if ALL checks pass
            is_complete = all(checks)
            
            if is_complete:
                self.logger.info(f"  ✅ Campaign {campaign_id} ({campaign_name}) is COMPLETE")
                self.logger.info(f"=" * 80)
                return True, "All checks passed"
            else:
                self.logger.info(f"  ❌ Campaign {campaign_id} ({campaign_name}) is NOT COMPLETE")
                for reason in reasons:
                    self.logger.info(f"     - {reason}")
                self.logger.info(f"=" * 80)
                return False, "; ".join(reasons)
            
        except Error as e:
            self.logger.error(f"Error checking campaign completion: {e}")
            return False, f"Database error: {e}"
    
    def handle_users_without_videos(self, campaign_id):
        """Handle users who are processed but don't have completed videos"""
        try:
            fresh_cursor = self.connection.cursor()
            
            # Find processed users without completed videos who don't have logging entries
            query = """
                SELECT u.id, u.mobile
                FROM users u
                LEFT JOIN videos_table v ON u.id = v.users_id AND v.generation_status = 'completed'
                LEFT JOIN logging_table l ON u.id = l.users_id AND u.campaign_id = l.campaign_id
                WHERE u.campaign_id = %s 
                AND u.status = 'processed'
                AND (v.id IS NULL OR v.video_public_url IS NULL OR v.video_public_url = '')
                AND l.users_id IS NULL
            """
            fresh_cursor.execute(query, (campaign_id,))
            users_without_videos = fresh_cursor.fetchall()
            fresh_cursor.close()
            
            if users_without_videos:
                self.logger.info(f"Found {len(users_without_videos)} processed users without completed videos")
                
                # Log these users as 'failed' since they can't receive messages without videos
                for user_data in users_without_videos:
                    try:
                        if isinstance(user_data, dict):
                            user_id = int(user_data['id'])
                            mobile = str(user_data['mobile'])
                        else:
                            user_id = int(user_data[0])
                            mobile = str(user_data[1])
                        
                        # Log as failed with video_id = 0 (no video available)
                        self.log_delivery_status(campaign_id, user_id, 0, mobile, 'failed')
                        self.logger.info(f"Marked user {user_id} as failed (no completed video)")
                        
                    except (ValueError, TypeError, KeyError, IndexError) as e:
                        self.logger.warning(f"Error processing user without video: {user_data}, Error: {e}")
                        continue
            
            return len(users_without_videos)
            
        except Error as e:
            self.logger.error(f"Error handling users without videos: {e}")
            return 0
    
    def handle_failed_users(self, campaign_id):
        """Mark failed users in logging table so campaign can complete"""
        try:
            fresh_cursor = self.connection.cursor()
            
            # Find failed users without logging entries and get their video_id
            query = """
                SELECT u.id, u.mobile, v.id as video_id
                FROM users u
                LEFT JOIN videos_table v ON u.id = v.users_id
                LEFT JOIN logging_table l ON u.id = l.users_id AND u.campaign_id = l.campaign_id
                WHERE u.campaign_id = %s 
                AND u.status = 'failed'
                AND l.users_id IS NULL
            """
            fresh_cursor.execute(query, (campaign_id,))
            failed_users = fresh_cursor.fetchall()
            fresh_cursor.close()
            
            if failed_users:
                self.logger.info(f"Found {len(failed_users)} failed users without logging entries")
                
                for user_data in failed_users:
                    try:
                        if isinstance(user_data, dict):
                            user_id = int(user_data['id'])
                            mobile = str(user_data['mobile'])
                            video_id = user_data.get('video_id')
                        else:
                            user_id = int(user_data[0])
                            mobile = str(user_data[1])
                            video_id = user_data[2] if len(user_data) > 2 else None
                        
                        # Only log if we have a valid video_id
                        if video_id:
                            self.log_delivery_status(campaign_id, user_id, video_id, mobile, 'failed')
                            self.logger.info(f"Marked failed user {user_id} in logging table with video_id {video_id}")
                        else:
                            self.logger.warning(f"Skipping failed user {user_id} - no video_id found in videos_table")
                        
                    except (ValueError, TypeError, KeyError, IndexError) as e:
                        self.logger.warning(f"Error processing failed user: {user_data}, Error: {e}")
                        continue
            
            return len(failed_users)
            
        except Error as e:
            self.logger.error(f"Error handling failed users: {e}")
            return 0

    # def process_campaign_messaging(self, campaign_id, campaign_name, total_users_expected, campaign_created_date):
    #     """Process messaging for a single campaign"""
    #     self.logger.info(f"\n{'=' * 100}")
    #     self.logger.info(f"Processing messaging for campaign: {campaign_name} (ID: {campaign_id})")
    #     self.logger.info(f"Expected Users: {total_users_expected}, Created: {campaign_created_date}")
    #     self.logger.info(f"{'=' * 100}\n")
        
    #     # First, handle users without videos (mark them as failed)
    #     users_without_videos_count = self.handle_users_without_videos(campaign_id)
        
    #     # Get users ready for messaging (with completed videos, not yet attempted)
    #     # CSV tracker will handle duplicate prevention based on campaign creation date
    #     users_ready_for_messaging = self.get_users_ready_for_messaging(campaign_id, campaign_created_date)
        
    #     if not users_ready_for_messaging:
    #         self.logger.info(f"No users ready for messaging in campaign {campaign_name}")
    #         # Check if campaign should be marked as completed
    #         is_complete, reason = self.check_campaign_completion(campaign_id, campaign_name, total_users_expected)
    #         if is_complete:
    #             self.update_campaign_status(campaign_id, 'completed', reason)
    #         return True
        
    #     self.logger.info(f"Found {len(users_ready_for_messaging)} users ready for messaging")
        
    #     # Process users in batches
    #     total_sent = 0
    #     total_failed = 0
    #     media_failed = 0
        
    #     for i in range(0, len(users_ready_for_messaging), self.batch_size):
    #         batch = users_ready_for_messaging[i:i + self.batch_size]
    #         self.logger.info(f"Processing batch {i//self.batch_size + 1}: {len(batch)} users")
            
    #         # Create batch_user_info for this batch with media verification
    #         batch_user_info = {}
    #         duplicate_mobiles = []
            
    #         for user_id, mobile, video_url, video_id in batch:
    #             # Check if mobile already exists in this batch
    #             if mobile in batch_user_info:
    #                 duplicate_mobiles.append(mobile)
    #                 self.logger.warning(f"DUPLICATE MOBILE in batch: {mobile} appears multiple times!")
                    
    #                 # Log the duplicate case as failed immediately
    #                 self.log_delivery_status(
    #                     campaign_id, 
    #                     user_id, 
    #                     video_id, 
    #                     mobile, 
    #                     'failed',
    #                     {'error': 'Duplicate mobile in batch'}
    #                 )
    #                 total_failed += 1
    #                 continue  # Skip this duplicate entry
                
    #             # Check media availability for dynamic videos (not static circle videos)
    #             # Static videos have format like: https://.../14.mp4 (just circle number)
    #             # Dynamic videos have format like: https://.../9876543210_123.mp4 (mobile_campaignid)
    #             is_dynamic_video = '_' in video_url.split('/')[-1]
                
    #             if is_dynamic_video:
    #                 media_available = self.check_media_availability(video_url, user_id)
                    
    #                 if not media_available:
    #                     self.logger.error(f"Media unavailable for user {user_id}, marking as failed")
    #                     self.log_delivery_status(
    #                         campaign_id,
    #                         user_id,
    #                         video_id,
    #                         mobile,
    #                         'failed',
    #                         {'error': 'Media URL not accessible'}
    #                     )
    #                     total_failed += 1
    #                     media_failed += 1
    #                     continue
                
    #             batch_user_info[mobile] = {
    #                 'user_id': user_id,
    #                 'video_id': video_id,
    #                 'video_url': video_url
    #             }
            
    #         if duplicate_mobiles:
    #             self.logger.error(f"Found {len(set(duplicate_mobiles))} duplicate mobile numbers in this batch")
            
    #         if media_failed > 0:
    #             self.logger.warning(f"Media check failed for {media_failed} users in this batch")
            
    #         # Skip sending if batch is now empty after filtering
    #         if not batch_user_info:
    #             self.logger.warning("Batch is empty after filtering, skipping API call")
    #             continue
            
    #         # Send WhatsApp batch using bulk API
    #         result = self.send_whatsapp_batch(batch_user_info)
            
    #         # Process results
    #         if result["success"]:
    #             self.logger.info(f"Batch API call successful")
    #             # Mark all users in batch as sent
    #             for mobile, user_data in batch_user_info.items():
    #                 self.logger.info(f"Sent to mobile={mobile}, user_id={user_data['user_id']}, video_id={user_data['video_id']}")
                    
    #                 success = self.log_delivery_status(
    #                     campaign_id, 
    #                     user_data['user_id'], 
    #                     user_data['video_id'], 
    #                     mobile, 
    #                     'sent', 
    #                     result.get('response')
    #                 )
    #                 if success:
    #                     total_sent += 1
    #                 else:
    #                     total_failed += 1
                
    #         else:
    #             self.logger.error(f"Batch API call failed")
    #             # Mark all users in batch as failed
    #             for mobile, user_data in batch_user_info.items():
    #                 self.log_delivery_status(
    #                     campaign_id, 
    #                     user_data['user_id'], 
    #                     user_data['video_id'], 
    #                     mobile, 
    #                     'failed', 
    #                     result.get('response')
    #                 )
    #                 total_failed += 1
            
    #         # Delay between batches
    #         if i + self.batch_size < len(users_ready_for_messaging):
    #             self.logger.info(f"Waiting {self.batch_delay} seconds before next batch...")
    #             time.sleep(self.batch_delay)
        
    #     self.logger.info(f"\nCampaign {campaign_name} messaging completed:")
    #     self.logger.info(f"  - Sent: {total_sent}")
    #     self.logger.info(f"  - Failed: {total_failed} (including {media_failed} media unavailable)")
        
    #     # Always check if campaign should be marked as completed after processing
    #     is_complete, reason = self.check_campaign_completion(campaign_id, campaign_name, total_users_expected)
    #     if is_complete:
    #         self.logger.info(f"Campaign {campaign_name} completed, marking as completed")
    #         self.update_campaign_status(campaign_id, 'completed', reason)
    #     else:
    #         self.logger.info(f"Campaign {campaign_name} still incomplete: {reason}")
        
    #     return True
    
    def process_campaign_messaging(self, campaign_id, campaign_name, total_users_expected, campaign_created_date):
        """Process messaging for a single campaign"""
        self.logger.info(f"\n{'=' * 100}")
        self.logger.info(f"Processing messaging for campaign: {campaign_name} (ID: {campaign_id})")
        self.logger.info(f"Expected Users: {total_users_expected}, Created: {campaign_created_date}")
        self.logger.info(f"{'=' * 100}\n")
        
        # First, handle users without videos (mark them as failed)
        users_without_videos_count = self.handle_users_without_videos(campaign_id)
        
        # Handle failed users (mark them in logging table)
        failed_users_count = self.handle_failed_users(campaign_id)
        if failed_users_count > 0:
            self.logger.info(f"Marked {failed_users_count} failed users in logging table")
        
        # Get users ready for messaging (with completed videos, not yet attempted)
        # CSV tracker will handle duplicate prevention based on campaign creation date
        users_ready_for_messaging = self.get_users_ready_for_messaging(campaign_id, campaign_created_date)
        
        if not users_ready_for_messaging:
            self.logger.info(f"No users ready for messaging in campaign {campaign_name}")
            # Check if campaign should be marked as completed
            is_complete, reason = self.check_campaign_completion(campaign_id, campaign_name, total_users_expected)
            if is_complete:
                self.update_campaign_status(campaign_id, 'completed', reason)
            return True
        
        self.logger.info(f"Found {len(users_ready_for_messaging)} users ready for messaging")
        
        # Process users in batches
        total_sent = 0
        total_failed = 0
        media_failed = 0
        
        for i in range(0, len(users_ready_for_messaging), self.batch_size):
            batch = users_ready_for_messaging[i:i + self.batch_size]
            self.logger.info(f"Processing batch {i//self.batch_size + 1}: {len(batch)} users")
            
            # Create batch_user_info for this batch with media verification
            batch_user_info = {}
            duplicate_mobiles = []
            
            for user_id, mobile, video_url, video_id in batch:
                # Check if mobile already exists in this batch
                if mobile in batch_user_info:
                    duplicate_mobiles.append(mobile)
                    self.logger.warning(f"DUPLICATE MOBILE in batch: {mobile} appears multiple times!")
                    
                    # Log the duplicate case as failed immediately
                    self.log_delivery_status(
                        campaign_id, 
                        user_id, 
                        video_id, 
                        mobile, 
                        'failed',
                        {'error': 'Duplicate mobile in batch'}
                    )
                    total_failed += 1
                    continue  # Skip this duplicate entry
                
                # Check media availability for dynamic videos (not static circle videos)
                # Static videos have format like: https://.../14.mp4 (just circle number)
                # Dynamic videos have format like: https://.../9876543210_123.mp4 (mobile_campaignid)
                is_dynamic_video = '_' in video_url.split('/')[-1]
                
                if is_dynamic_video:
                    media_available = self.check_media_availability(video_url, user_id)
                    
                    if not media_available:
                        self.logger.error(f"Media unavailable for user {user_id}, marking as failed")
                        self.log_delivery_status(
                            campaign_id,
                            user_id,
                            video_id,
                            mobile,
                            'failed',
                            {'error': 'Media URL not accessible'}
                        )
                        total_failed += 1
                        media_failed += 1
                        continue
                
                batch_user_info[mobile] = {
                    'user_id': user_id,
                    'video_id': video_id,
                    'video_url': video_url
                }
            
            if duplicate_mobiles:
                self.logger.error(f"Found {len(set(duplicate_mobiles))} duplicate mobile numbers in this batch")
            
            if media_failed > 0:
                self.logger.warning(f"Media check failed for {media_failed} users in this batch")
            
            # Skip sending if batch is now empty after filtering
            if not batch_user_info:
                self.logger.warning("Batch is empty after filtering, skipping API call")
                continue
            
            # Send WhatsApp batch using bulk API
            result = self.send_whatsapp_batch(batch_user_info)
            
            # Process results
            if result["success"]:
                self.logger.info(f"Batch API call successful")
                # Mark all users in batch as sent
                for mobile, user_data in batch_user_info.items():
                    self.logger.info(f"Sent to mobile={mobile}, user_id={user_data['user_id']}, video_id={user_data['video_id']}")
                    
                    success = self.log_delivery_status(
                        campaign_id, 
                        user_data['user_id'], 
                        user_data['video_id'], 
                        mobile, 
                        'sent', 
                        result.get('response')
                    )
                    if success:
                        total_sent += 1
                    else:
                        total_failed += 1
                
            else:
                self.logger.error(f"Batch API call failed")
                # Mark all users in batch as failed
                for mobile, user_data in batch_user_info.items():
                    self.log_delivery_status(
                        campaign_id, 
                        user_data['user_id'], 
                        user_data['video_id'], 
                        mobile, 
                        'failed', 
                        result.get('response')
                    )
                    total_failed += 1
            
            # Delay between batches
            if i + self.batch_size < len(users_ready_for_messaging):
                self.logger.info(f"Waiting {self.batch_delay} seconds before next batch...")
                time.sleep(self.batch_delay)
        
        self.logger.info(f"\nCampaign {campaign_name} messaging completed:")
        self.logger.info(f"  - Sent: {total_sent}")
        self.logger.info(f"  - Failed: {total_failed} (including {media_failed} media unavailable)")
        
        # Always check if campaign should be marked as completed after processing
        is_complete, reason = self.check_campaign_completion(campaign_id, campaign_name, total_users_expected)
        if is_complete:
            self.logger.info(f"Campaign {campaign_name} completed, marking as completed")
            self.update_campaign_status(campaign_id, 'completed', reason)
        else:
            self.logger.info(f"Campaign {campaign_name} still incomplete: {reason}")
        
        return True

    def process_all_campaigns(self):
        """Main processing function for all ongoing campaigns"""
        self.logger.info("\n" + "=" * 100)
        self.logger.info("Starting WhatsApp messaging processing...")
        self.logger.info("=" * 100 + "\n")
        
        # Get ongoing campaigns
        ongoing_campaigns = self.get_ongoing_campaigns()
        if not ongoing_campaigns:
            self.logger.info("No ongoing campaigns found")
            return True
        
        total_campaigns_processed = 0
        total_campaigns_completed = 0
        
        for campaign_id, campaign_name, total_users, created_at in ongoing_campaigns:
            try:
                self.logger.info(f"Processing campaign: {campaign_name} (ID: {campaign_id})")
                success = self.process_campaign_messaging(campaign_id, campaign_name, total_users, created_at)
                total_campaigns_processed += 1
                if success:
                    total_campaigns_completed += 1
                
                # Small delay between campaigns
                time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error processing campaign {campaign_name}: {e}")
                email_alert("Campaign Processing Error", f"Script 3: Error processing campaign {campaign_name}: {e}")
                continue
        
        self.logger.info(f"\n{'=' * 100}")
        self.logger.info(f"Processing completed.")
        self.logger.info(f"Campaigns processed: {total_campaigns_processed}, Completed: {total_campaigns_completed}")
        self.logger.info(f"{'=' * 100}\n")
        return True


def main():
    """Main function"""
    processor = WhatsAppMessagingProcessor()
    
    # Connect to database
    if not processor.connect_database():
        sys.exit(1)
    
    try:
        # Process all campaigns
        success = processor.process_all_campaigns()
        
        if success:
            print("WhatsApp messaging processing completed successfully!")
        else:
            print("WhatsApp messaging processing failed!")
            sys.exit(1)
            
    except Exception as e:
        processor.logger.error(f"Unexpected error in main: {e}")
        email_alert("Script 3 Fatal Error", f"Script 3: Unexpected error in main: {e}")
        print("WhatsApp messaging processing failed with unexpected error!")
        sys.exit(1)
    finally:
        # Always close the database connection
        processor.disconnect_database()


if __name__ == "__main__":
    main()