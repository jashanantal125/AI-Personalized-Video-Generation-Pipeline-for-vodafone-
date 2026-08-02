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

# Import database connection
from db_script import db_connection

auth_key = "63904d234d1bdf1a" # w2

class WhatsAppMessagingProcessor:
    def __init__(self):
        """Initialize the WhatsApp messaging processor"""
        self.setup_logging()
        self.connection = None
        self.cursor = None
        
        # Whitelist numbers that can receive multiple messages per day
        self.whitelist_numbers = ['7496896006', '9872569478', '9814701008', '7696395611', '6283918159', '6283803127']
        
        # API configuration
        self.api_url = "https://whatsapp.adznetworkmedia.om/restapi/requestjson_v2.0.php"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_key}"
        }
        
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f'whatsapp_messaging_{datetime.datetime.now().strftime("%Y%m%d")}.log'),
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
                return False
        except Exception as e:
            self.logger.error(f"Database connection failed: {e}")
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
            query = "SELECT id, campaign_name, total_users FROM campaigns WHERE status = 'ongoing'"
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
                    else:
                        campaign_id = int(campaign[0])
                        campaign_name = str(campaign[1])
                        total_users = int(campaign[2]) if campaign[2] else 0
                    
                    valid_campaigns.append((campaign_id, campaign_name, total_users))
                    self.logger.info(f"Valid campaign found: ID={campaign_id}, Name='{campaign_name}', Total Users={total_users}")
                except (ValueError, TypeError, KeyError, IndexError) as e:
                    self.logger.warning(f"Skipping invalid campaign data: {campaign}, Error: {e}")
                    continue
            
            self.logger.info(f"Found {len(valid_campaigns)} ongoing campaigns")
            return valid_campaigns
        except Error as e:
            self.logger.error(f"Error fetching ongoing campaigns: {e}")
            return []
    
    def get_todays_processed_mobiles(self):
        """
        Get all mobile numbers that have already been processed today
        across ALL campaigns (excluding whitelisted numbers)
        """
        try:
            fresh_cursor = self.connection.cursor()
            today_date = datetime.date.today()
            
            # Get all mobiles that have logging entries today
            query = """
                SELECT DISTINCT u.mobile
                FROM logging_table l
                JOIN users u ON l.users_id = u.id
                JOIN campaigns c ON l.campaign_id = c.id
                WHERE DATE(c.created_at) = %s
                AND l.delivery_status IN ('sent', 'failed')
            """
            fresh_cursor.execute(query, (today_date,))
            results = fresh_cursor.fetchall()
            fresh_cursor.close()
            
            # Extract mobile numbers
            processed_mobiles = set()
            for row in results:
                mobile = str(row[0]) if isinstance(row, tuple) else str(row['mobile'])
                # Exclude whitelisted numbers
                if mobile not in self.whitelist_numbers:
                    processed_mobiles.add(mobile)
            
            self.logger.info(f"Found {len(processed_mobiles)} mobile numbers already processed today (excluding whitelist)")
            return processed_mobiles
            
        except Error as e:
            self.logger.error(f"Error fetching today's processed mobiles: {e}")
            return set()
    
    def get_users_ready_for_messaging(self, campaign_id, todays_processed_mobiles):
        """
        Get users who are ready for messaging but haven't been attempted yet
        EXCLUDES users whose mobile numbers have already been processed today (unless whitelisted)
        """
        try:
            fresh_cursor = self.connection.cursor()
            
            # Get users with completed videos who DON'T have any logging_table entries yet
            # AND whose mobile hasn't been processed today
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
                FOR UPDATE SKIP LOCKED
            """
            fresh_cursor.execute(query, (campaign_id,))
            users = fresh_cursor.fetchall()
            
            self.logger.info(f"Found {len(users)} users with videos and no logging entries in campaign {campaign_id}")
            
            # Handle both dictionary and tuple results and filter by today's processed mobiles
            valid_users = []
            already_processed_today = []
            
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
                    
                    # Check if mobile was already processed today (unless whitelisted)
                    if mobile not in self.whitelist_numbers and mobile in todays_processed_mobiles:
                        self.logger.info(f"Mobile {mobile} (user {user_id}) already processed today - marking as duplicate")
                        already_processed_today.append((user_id, mobile, video_id))
                        continue
                    
                    valid_users.append((user_id, mobile, video_url, video_id))
                    
                except (ValueError, TypeError, KeyError, IndexError) as e:
                    self.logger.warning(f"Skipping invalid user data: {user}, Error: {e}")
                    continue
            
            fresh_cursor.close()
            
            self.logger.info(f"Valid users ready for messaging: {len(valid_users)}")
            self.logger.info(f"Users skipped (already processed today): {len(already_processed_today)}")
            
            # Mark already processed today users as 'sent' without actually sending
            for user_id, mobile, video_id in already_processed_today:
                self.mark_as_already_sent_today(campaign_id, user_id, video_id, mobile)
            
            return valid_users
            
        except Error as e:
            self.logger.error(f"Error fetching users ready for messaging: {e}")
            return []
    
    def mark_as_already_sent_today(self, campaign_id, user_id, video_id, mobile):
        """
        Mark a user as 'sent' in logging_table because their mobile was already processed today
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
            
            self.logger.info(f"User {user_id} (mobile: {mobile}) marked as sent (duplicate mobile for today)")
            return True
            
        except Error as e:
            self.logger.error(f"Error marking user as already sent: {e}")
            self.connection.rollback()
            return False
    
    def send_whatsapp_batch(self, mobile_data_dict):
        """Send WhatsApp media messages via API for a batch"""
        self.logger.info(f"Sending WhatsApp batch to {len(mobile_data_dict)} users")
        
        # Prepare the data array for API
        data_array = []
        for mobile, header_data in mobile_data_dict.items():
            data_array.append({
                "headerValues": {
                    "headerData": header_data
                },
                "mobile": str(mobile)
            })
        
        # Prepare the request payload
        payload = {
            "version": "2.0",
            "country_code": "91",
            "wid": "13108",
            "type": "media",
            "data": data_array
        }
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # Make the API request
            self.logger.info(f"Making API request to {self.api_url}")
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
                "mobile_data": mobile_data_dict
            }
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"API request failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": timestamp,
                "mobile_data": mobile_data_dict
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
    
    def update_campaign_status(self, campaign_id, status):
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
            
            self.logger.info(f"Campaign {campaign_id} status updated from '{current_status}' to '{status}'")
            return True
        except Error as e:
            self.logger.error(f"Error updating campaign status: {e}")
            self.connection.rollback()
            return False
    
    def check_campaign_completion(self, campaign_id):
        """
        Check if ALL processable users have been handled for messaging.
        """
        try:
            fresh_cursor = self.connection.cursor()
            
            # Count users who should have messaging attempted (processed + have videos OR processed + failed videos)
            query1 = """
                SELECT COUNT(DISTINCT u.id) 
                FROM users u
                WHERE u.campaign_id = %s 
                AND u.status IN ('processed', 'failed')
            """
            fresh_cursor.execute(query1, (campaign_id,))
            result1 = fresh_cursor.fetchone()
            processable_users_count = result1[0] if isinstance(result1, tuple) else result1['COUNT(DISTINCT u.id)']
            
            # Count users who have been attempted for messaging (have logging entries)
            query2 = """
                SELECT COUNT(DISTINCT users_id) 
                FROM logging_table 
                WHERE campaign_id = %s
            """
            fresh_cursor.execute(query2, (campaign_id,))
            result2 = fresh_cursor.fetchone()
            logging_entries_count = result2[0] if isinstance(result2, tuple) else result2['COUNT(DISTINCT users_id)']
            
            # Get total users and current processing status for context
            query3 = """
                SELECT 
                    c.total_users,
                    COUNT(CASE WHEN u.status = 'pending' THEN 1 END) as pending_users,
                    COUNT(CASE WHEN u.status = 'processing' THEN 1 END) as processing_users,
                    COUNT(CASE WHEN u.status = 'processed' THEN 1 END) as processed_users,
                    COUNT(CASE WHEN u.status = 'failed' THEN 1 END) as failed_users
                FROM campaigns c
                LEFT JOIN users u ON c.id = u.campaign_id
                WHERE c.id = %s
                GROUP BY c.id, c.total_users
            """
            fresh_cursor.execute(query3, (campaign_id,))
            result3 = fresh_cursor.fetchone()
            
            if result3:
                if isinstance(result3, dict):
                    total_users = result3['total_users'] or 0
                    pending_users = result3['pending_users'] or 0
                    processing_users = result3['processing_users'] or 0
                    processed_users = result3['processed_users'] or 0
                    failed_users = result3['failed_users'] or 0
                else:
                    total_users = result3[0] or 0
                    pending_users = result3[1] or 0
                    processing_users = result3[2] or 0
                    processed_users = result3[3] or 0
                    failed_users = result3[4] or 0
            else:
                total_users = 0
                pending_users = processing_users = processed_users = failed_users = 0
            
            fresh_cursor.close()
            
            self.logger.info(f"Campaign {campaign_id} completion check:")
            self.logger.info(f"  - Total users in campaign: {total_users}")
            self.logger.info(f"  - Pending users: {pending_users}")
            self.logger.info(f"  - Processing users: {processing_users}")
            self.logger.info(f"  - Processed users: {processed_users}")
            self.logger.info(f"  - Failed users: {failed_users}")
            self.logger.info(f"  - Processable users (processed + failed): {processable_users_count}")
            self.logger.info(f"  - Users with logging entries: {logging_entries_count}")
            
            # Campaign is complete ONLY when:
            # 1. There are processable users (processed or failed)
            # 2. ALL processable users have logging entries
            # 3. No users are still pending/processing (Script 2 finished)
            is_complete = (
                processable_users_count > 0 and 
                logging_entries_count >= processable_users_count and
                pending_users == 0 and 
                processing_users == 0
            )
            
            if is_complete:
                self.logger.info(f"Campaign {campaign_id} is COMPLETE:")
                self.logger.info(f"  - All {processable_users_count} processable users have logging entries")
                self.logger.info(f"  - No users pending/processing (Script 2 finished)")
            else:
                if pending_users > 0 or processing_users > 0:
                    self.logger.info(f"Campaign {campaign_id} is NOT COMPLETE - Script 2 still processing users:")
                    self.logger.info(f"  - {pending_users} users pending")
                    self.logger.info(f"  - {processing_users} users processing")
                else:
                    remaining_messaging = processable_users_count - logging_entries_count
                    self.logger.info(f"Campaign {campaign_id} is NOT COMPLETE - {remaining_messaging} users need messaging attempts")
            
            return is_complete
            
        except Error as e:
            self.logger.error(f"Error checking campaign completion: {e}")
            return False
    
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
    
    def process_campaign_messaging(self, campaign_id, campaign_name, total_users_expected, todays_processed_mobiles):
        """Process messaging for a single campaign"""
        self.logger.info(f"Processing messaging for campaign: {campaign_name} (ID: {campaign_id}, Expected Users: {total_users_expected})")
        
        # First, handle users without videos (mark them as failed)
        users_without_videos_count = self.handle_users_without_videos(campaign_id)
        
        # Get users ready for messaging (with completed videos, not yet attempted, and not processed today)
        users_ready_for_messaging = self.get_users_ready_for_messaging(campaign_id, todays_processed_mobiles)
        
        if not users_ready_for_messaging:
            self.logger.info(f"No users ready for messaging in campaign {campaign_name}")
            # Check if campaign should be marked as completed
            if self.check_campaign_completion(campaign_id):
                self.update_campaign_status(campaign_id, 'completed')
            return True
        
        self.logger.info(f"Found {len(users_ready_for_messaging)} users ready for ACTUAL messaging (not already processed today)")
        
        # Process users in batches of 15
        batch_size = 80
        total_sent = 0
        total_failed = 0
        
        for i in range(0, len(users_ready_for_messaging), batch_size):
            batch = users_ready_for_messaging[i:i + batch_size]
            self.logger.info(f"Processing batch {i//batch_size + 1}: {len(batch)} users")
            
            # Create mobile_data_dict for this batch
            mobile_data_dict = {}
            batch_user_info = {}
            duplicate_mobiles = []
            
            for user_id, mobile, video_url, video_id in batch:
                # Check if mobile already exists in this batch
                if mobile in mobile_data_dict:
                    duplicate_mobiles.append(mobile)
                    self.logger.warning(f"DUPLICATE MOBILE in batch: {mobile} appears multiple times!")
                    self.logger.warning(f"  Previous: user_id={batch_user_info[mobile]['user_id']}, video={mobile_data_dict[mobile]}")
                    self.logger.warning(f"  Current: user_id={user_id}, video={video_url}")
                    
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
                
                mobile_data_dict[mobile] = video_url
                batch_user_info[mobile] = {
                    'user_id': user_id,
                    'video_id': video_id,
                    'video_url': video_url
                }
            
            if duplicate_mobiles:
                self.logger.error(f"Found {len(set(duplicate_mobiles))} duplicate mobile numbers in this batch")
            
            # Skip sending if batch is now empty after removing duplicates
            if not mobile_data_dict:
                self.logger.warning("Batch is empty after removing duplicates, skipping API call")
                continue
            
            # Send WhatsApp batch
            result = self.send_whatsapp_batch(mobile_data_dict)
            
            # Process results
            if result["success"]:
                self.logger.info(f"Batch API call successful")
                # Mark all users in batch as sent
                for mobile, video_url in mobile_data_dict.items():
                    user_info = batch_user_info[mobile]
                    
                    # VERIFICATION: Log what was actually sent
                    self.logger.info(f"Sent to mobile={mobile}, user_id={user_info['user_id']}, video_id={user_info['video_id']}, video_url={video_url}")
                    
                    # Verify the video URL matches
                    if user_info['video_url'] != video_url:
                        self.logger.error(f"VIDEO MISMATCH! Expected {user_info['video_url']}, sent {video_url}")
                    
                    success = self.log_delivery_status(
                        campaign_id, 
                        user_info['user_id'], 
                        user_info['video_id'], 
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
                for mobile in mobile_data_dict.keys():
                    user_info = batch_user_info[mobile]
                    self.log_delivery_status(
                        campaign_id, 
                        user_info['user_id'], 
                        user_info['video_id'], 
                        mobile, 
                        'failed', 
                        result.get('response')
                    )
                    total_failed += 1
            
            # Small delay between batches
            if i + batch_size < len(users_ready_for_messaging):
                self.logger.info("Waiting 3 seconds before next batch...")
                time.sleep(3)
        
        self.logger.info(f"Campaign {campaign_name} messaging completed: {total_sent} sent, {total_failed} failed")
        
        # Always check if campaign should be marked as completed after processing
        if self.check_campaign_completion(campaign_id):
            self.logger.info(f"Campaign {campaign_name} completed, marking as completed")
            self.update_campaign_status(campaign_id, 'completed')
        else:
            self.logger.info(f"Campaign {campaign_name} still has unprocessed users, keeping status as ongoing")
        
        return True
    
    def process_all_campaigns(self):
        """Main processing function for all ongoing campaigns"""
        self.logger.info("Starting WhatsApp messaging processing...")
        
        # Get today's processed mobiles once at the start (for efficiency)
        todays_processed_mobiles = self.get_todays_processed_mobiles()
        self.logger.info(f"Total mobiles already processed today: {len(todays_processed_mobiles)}")
        
        # Get ongoing campaigns
        ongoing_campaigns = self.get_ongoing_campaigns()
        if not ongoing_campaigns:
            self.logger.info("No ongoing campaigns found")
            return True
        
        total_campaigns_processed = 0
        total_campaigns_completed = 0
        
        for campaign_id, campaign_name, total_users in ongoing_campaigns:
            try:
                self.logger.info(f"Processing campaign: {campaign_name} (ID: {campaign_id})")
                success = self.process_campaign_messaging(campaign_id, campaign_name, total_users, todays_processed_mobiles)
                total_campaigns_processed += 1
                if success:
                    total_campaigns_completed += 1
                
                # Small delay between campaigns
                time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error processing campaign {campaign_name}: {e}")
                continue
        
        self.logger.info(f"Processing completed. Campaigns processed: {total_campaigns_processed}, Completed: {total_campaigns_completed}")
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
        print("WhatsApp messaging processing failed with unexpected error!")
        sys.exit(1)
    finally:
        # Always close the database connection
        processor.disconnect_database()


if __name__ == "__main__":
    main()