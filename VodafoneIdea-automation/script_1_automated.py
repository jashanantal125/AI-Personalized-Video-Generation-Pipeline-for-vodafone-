#!/usr/bin/env python3

import csv
import mysql.connector
from mysql.connector import Error
import logging
import sys
import os
from datetime import datetime, date
import re
import glob
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Import database connection
from db_script import db_connection

# CONFIGURATION - Easy to change
DECRYPTION_PASSWORD = "YOUR_DECRYPTION_PASSWORD"

# Numbers allowed to be added multiple times per day
ALLOWED_DUPLICATE_NUMBERS = ['9000000001', '9000000002']

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
    SENDER_PASSWORD = "YOUR_SMTP_APP_PASSWORD"
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


class ViServerDataProcessor:
    def __init__(self):
        """Initialize the Vi server data processor"""
        self.setup_logging()
        self.connection = None
        self.cursor = None
        self.decryption_password = DECRYPTION_PASSWORD
        self.allowed_duplicate_numbers = ALLOWED_DUPLICATE_NUMBERS
        # Daily tracking CSV file
        self.daily_csv_folder = "input_numbers"
        self.daily_csv_file = None
        self.daily_mobiles_data = {}  # {mobile: {'first_occurence_timestamp', 'occurrence_count', 'last_campaign_id'}}
        
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f'vi_server_data_{datetime.now().strftime("%Y%m%d")}.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def get_daily_csv_filename(self, campaign_date=None):
        """
        Get the CSV filename for today's date
        
        Args:
            campaign_date (str): Date in format YYYY-MM-DD, defaults to today
            
        Returns:
            str: Full path to daily CSV file
        """
        if campaign_date is None:
            campaign_date = date.today().strftime("%Y-%m-%d")
        
        # Ensure folder exists
        os.makedirs(self.daily_csv_folder, exist_ok=True)
        
        return os.path.join(self.daily_csv_folder, f"{campaign_date}.csv")
    
    def load_daily_csv(self, campaign_date=None):
        """
        Load or create the daily CSV file for tracking mobile numbers
        
        Args:
            campaign_date (str): Date in format YYYY-MM-DD
            
        Returns:
            bool: True if loaded successfully
        """
        try:
            self.daily_csv_file = self.get_daily_csv_filename(campaign_date)
            self.daily_mobiles_data = {}
            
            # If file exists, load it
            if os.path.exists(self.daily_csv_file):
                self.logger.info(f"Loading existing daily CSV: {self.daily_csv_file}")
                with open(self.daily_csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        mobile = row['mobile']
                        self.daily_mobiles_data[mobile] = {
                            'first_occurence_timestamp': row['first_occurence_timestamp'],
                            'occurrence_count': int(row['occurrence_count']),
                            'last_campaign_id': int(row['last_campaign_id'])
                        }
                self.logger.info(f"Loaded {len(self.daily_mobiles_data)} mobile numbers from daily CSV")
            else:
                self.logger.info(f"Creating new daily CSV: {self.daily_csv_file}")
                # Create new CSV with headers
                with open(self.daily_csv_file, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=['mobile', 'first_occurence_timestamp', 'occurrence_count', 'last_campaign_id'])
                    writer.writeheader()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error loading daily CSV: {e}")
            return False
    
    def save_daily_csv(self):
        """
        Save the daily mobile data back to CSV file
        
        Returns:
            bool: True if saved successfully
        """
        try:
            if not self.daily_csv_file:
                self.logger.error("No daily CSV file path set")
                return False
            
            # Write all data to CSV
            with open(self.daily_csv_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['mobile', 'first_occurence_timestamp', 'occurrence_count', 'last_campaign_id'])
                writer.writeheader()
                
                # Sort by mobile number for consistency
                for mobile in sorted(self.daily_mobiles_data.keys()):
                    data = self.daily_mobiles_data[mobile]
                    writer.writerow({
                        'mobile': mobile,
                        'first_occurence_timestamp': data['first_occurence_timestamp'],
                        'occurrence_count': data['occurrence_count'],
                        'last_campaign_id': data['last_campaign_id']
                    })
            
            self.logger.debug(f"Saved {len(self.daily_mobiles_data)} entries to daily CSV")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving daily CSV: {e}")
            return False
    
    def check_and_update_daily_mobile(self, decrypted_mobile, campaign_id):
        """
        Check if mobile exists in daily CSV and update occurrence
        
        Args:
            decrypted_mobile (str): Decrypted mobile number
            campaign_id (int): Current campaign ID
            
        Returns:
            bool: True if mobile can be added (first occurrence today), False if duplicate
        """
        # Check if whitelisted
        if decrypted_mobile in self.allowed_duplicate_numbers:
            return True
        
        # Check if mobile exists in today's data
        if decrypted_mobile in self.daily_mobiles_data:
            # Mobile already exists today - increment occurrence count
            self.daily_mobiles_data[decrypted_mobile]['occurrence_count'] += 1
            self.daily_mobiles_data[decrypted_mobile]['last_campaign_id'] = campaign_id
            self.logger.debug(f"Mobile {decrypted_mobile} duplicate detected (occurrence: {self.daily_mobiles_data[decrypted_mobile]['occurrence_count']})")
            return False
        else:
            # First occurrence today - add to tracking
            self.daily_mobiles_data[decrypted_mobile] = {
                'first_occurence_timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'occurrence_count': 1,
                'last_campaign_id': campaign_id
            }
            return True
    
    def connect_database(self):
        """Get database connection from external db_script"""
        try:
            self.connection = db_connection()
            
            if self.connection:
                # Create cursor that returns tuples (not dicts)
                self.cursor = self.connection.cursor()
                self.logger.info("Database connection established")
                return True
            else:
                self.logger.error("Failed to get database connection")
                email_alert("Database Connection Failed", "Script 1: Failed to establish database connection")
                return False
        except Exception as e:
            self.logger.error(f"Database connection failed: {e}")
            email_alert("Database Connection Error", f"Script 1: Database connection failed: {e}")
            return False
    
    def disconnect_database(self):
        """Close database connection"""
        try:
            if self.cursor:
                self.cursor.close()
            if self.connection:
                self.connection.close()
                self.logger.info("Database connection closed")
        except Exception as e:
            self.logger.error(f"Error closing database connection: {e}")
    
    def count_valid_data_rows(self, csv_file_path):
        """
        Count the number of valid data rows in CSV (excluding header and empty rows)
        
        Args:
            csv_file_path (str): Path to CSV file
            
        Returns:
            int: Number of valid data rows, or -1 if error
        """
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                # Detect delimiter
                sample = file.read(1024)
                file.seek(0)
                
                if ';' in sample:
                    delimiter = ';'
                else:
                    sniffer = csv.Sniffer()
                    try:
                        delimiter = sniffer.sniff(sample).delimiter
                    except:
                        delimiter = ','
                
                file.seek(0)
                reader = csv.DictReader(file, delimiter=delimiter, quotechar='"')
                
                # Count valid rows (non-empty mobile_no field)
                valid_count = 0
                for row in reader:
                    mobile = str(row.get('mobile_no', '')).strip().strip('"')
                    if mobile:  # Has a mobile number
                        valid_count += 1
                
                return valid_count
                
        except Exception as e:
            self.logger.error(f"Error counting valid rows in {csv_file_path}: {e}")
            return -1
    
    def safe_convert_to_int(self, value, field_name="value"):
        """
        Safely convert value to integer with validation rules:
        - Empty/None/NA → 0
        - Negative → 0
        - < 5 → 0
        - String → 0
        """
        if value is None or str(value).strip() == '' or str(value).strip().upper() in ['NONE', 'NULL', 'NA', 'N/A']:
            return 0
        
        try:
            cleaned_value = str(value).strip()
            
            # Handle spaced negative numbers: "- 5" → "-5"
            if cleaned_value.startswith('- '):
                cleaned_value = '-' + cleaned_value[2:].strip()
            
            # Remove any internal spaces
            cleaned_value = cleaned_value.replace(' ', '')
            
            # Convert to int (handle floats)
            if '.' in cleaned_value:
                result = int(float(cleaned_value))
            else:
                result = int(cleaned_value)
            
            # Convert negative or < 5 to 0
            if result < 5:
                self.logger.debug(f"Value {result} for {field_name} is < 5, converting to 0")
                return 0
            
            return result
                
        except (ValueError, TypeError):
            self.logger.warning(f"Could not convert '{value}' to integer for {field_name}, using 0")
            return 0
    
    def safe_convert_to_decimal(self, value, field_name="value"):
        """
        Safely convert value to decimal with validation rules:
        - Empty/None/NA → 0.00
        - Negative → 0.00
        - < 5 → 0.00
        - String → 0.00
        """
        if value is None or str(value).strip() == '' or str(value).strip().upper() in ['NONE', 'NULL', 'NA', 'N/A']:
            return 0.00
        
        try:
            cleaned_value = str(value).strip()
            
            # Handle spaced negative numbers: "- 5" → "-5"
            if cleaned_value.startswith('- '):
                cleaned_value = '-' + cleaned_value[2:].strip()
            
            # Remove any internal spaces
            cleaned_value = cleaned_value.replace(' ', '')
            
            # Convert to float
            result = float(cleaned_value)
            
            # Convert negative or < 5 to 0.00
            if result < 5.0:
                self.logger.debug(f"Value {result} for {field_name} is < 5, converting to 0.00")
                return 0.00
            
            return round(result, 2)
                
        except (ValueError, TypeError):
            self.logger.warning(f"Could not convert '{value}' to decimal for {field_name}, using 0.00")
            return 0.00

    def validate_circle_name(self, circle_name):
        """Validate circle name - must be a valid integer, remove leading zeros"""
        if circle_name is None or str(circle_name).strip() == '' or str(circle_name).strip().upper() in ['NONE', 'NULL', 'NA', 'N/A']:
            return None  # Invalid - skip this row
        
        try:
            # Try to convert to integer to validate and remove leading zeros
            circle_value = str(circle_name).strip()
            
            # Convert to integer (this validates it's a number and removes leading zeros)
            circle_int = int(circle_value)
            
            # Return as string without leading zeros
            return str(circle_int)
            
        except (ValueError, TypeError):
            # Not a valid integer - skip this row
            return None
    
    def extract_campaign_name_from_filename(self, csv_file_path):
        """Extract campaign name from CSV filename (e.g., BOAT_2025_10_03_18_00_45.csv)"""
        filename = os.path.basename(csv_file_path)
        campaign_name = os.path.splitext(filename)[0]
        return campaign_name
    
    def extract_date_from_campaign_name(self, campaign_name):
        """Extract date from campaign name (e.g., BOAT_2025_10_03_... -> 2025-10-03)"""
        try:
            # Pattern: BOAT_YYYY_MM_DD_...
            parts = campaign_name.split('_')
            if len(parts) >= 4:
                year = parts[1]
                month = parts[2]
                day = parts[3]
                return f"{year}-{month}-{day}"
        except Exception as e:
            self.logger.error(f"Error extracting date from campaign name: {e}")
        return None
    
    def campaign_exists(self, campaign_name):
        """Check if campaign already exists in campaigns table"""
        try:
            query = "SELECT id FROM campaigns WHERE campaign_name = %s"
            self.cursor.execute(query, (campaign_name,))
            result = self.cursor.fetchone()
            
            if result:
                # Handle both tuple (result[0]) and dict (result['id']) cursor types
                try:
                    return result[0] if not isinstance(result, dict) else result['id']
                except (KeyError, IndexError, TypeError):
                    # If neither works, try to get first value
                    return list(result.values())[0] if isinstance(result, dict) else result[0]
            return None
            
        except Exception as e:
            self.logger.error(f"Error checking campaign existence: {e}")
            self.logger.error(traceback.format_exc())
            return None

    def create_campaign(self, campaign_name):
        """Create new campaign in campaigns table"""
        try:
            insert_query = "INSERT INTO campaigns (campaign_name) VALUES (%s)"
            self.cursor.execute(insert_query, (campaign_name,))
            self.connection.commit()
            
            campaign_id = self.cursor.lastrowid
            self.logger.info(f"Created new campaign: '{campaign_name}' (ID: {campaign_id})")
            return campaign_id
                
        except Error as e:
            self.logger.error(f"Error creating campaign: {e}")
            self.connection.rollback()
            # email_alert("Campaign Creation Failed", f"Script 1: Failed to create campaign '{campaign_name}': {e}")
            return None
    
    def decrypt_mobile_number(self, encrypted_hex):
        """Decrypt mobile number using SQL DECODE function"""
        try:
            query = "SELECT CAST(DECODE(UNHEX(%s), %s) AS CHAR) as decrypted_mobile"
            self.cursor.execute(query, (encrypted_hex, self.decryption_password))
            result = self.cursor.fetchone()
            
            if result:
                # Handle both tuple and dict cursor types
                if isinstance(result, dict):
                    decrypted = result.get('decrypted_mobile')
                else:
                    decrypted = result[0]
                
                if decrypted:
                    return str(decrypted).strip()
            return None
        except Exception as e:
            self.logger.error(f"Error decrypting mobile number {encrypted_hex[:10]}...: {e}")
            return None

    def insert_user(self, campaign_id, encrypted_mobile, circle_name, validity_diff, current_balance):
        """
        Insert user data into users with DECRYPTED mobile and CSV-based duplicate check
        
        Duplicate Prevention Strategy:
        1. Decrypt mobile number
        2. Check against daily CSV file for duplicates
        3. If duplicate, increment occurrence count in CSV and skip
        4. If new, add to users table and update CSV
        
        Args:
            campaign_id: Campaign ID
            encrypted_mobile: Encrypted mobile number
            circle_name: Circle name
            validity_diff: Validity difference
            current_balance: Current balance
            
        Returns:
            int: user_id if success, -1 for duplicate, None for error
        """
        try:
            # First, decrypt the mobile number using SQL
            decrypted_mobile = self.decrypt_mobile_number(encrypted_mobile)
            
            if not decrypted_mobile:
                self.logger.warning(f"Could not decrypt mobile: {encrypted_mobile[:10]}...")
                return None
            
            # Check and update daily CSV
            can_add = self.check_and_update_daily_mobile(decrypted_mobile, campaign_id)
            
            if not can_add:
                # Duplicate found - save CSV immediately
                self.save_daily_csv()
                return -1  # Duplicate
            
            # Insert user
            user_query = """
                INSERT INTO users (campaign_id, mobile, circle_name, current_balance, validity_in_days, status) 
                VALUES (%s, %s, %s, %s, %s, 'pending')
            """
            user_values = (
                campaign_id,
                decrypted_mobile,  # Store DECRYPTED mobile
                circle_name,
                current_balance,
                validity_diff
            )
            
            self.cursor.execute(user_query, user_values)
            user_id = self.cursor.lastrowid
            
            # Update campaign counters
            update_query = """
                UPDATE campaigns 
                SET total_users = total_users + 1
                WHERE id = %s
            """
            self.cursor.execute(update_query, (campaign_id,))
            
            self.connection.commit()
            
            # Save CSV after successful insert
            self.save_daily_csv()
            
            return user_id
            
        except Error as e:
            if e.errno == 1062:  # Duplicate entry (should be rare with our checks)
                self.connection.rollback()
                self.logger.warning(f"Database duplicate constraint hit for mobile (should be rare)")
                return -1  # Duplicate
            else:
                self.logger.error(f"Database error inserting user: {e}")
                self.connection.rollback()
                return None
        except Exception as e:
            if "Duplicate entry" in str(e):
                self.connection.rollback()
                self.logger.warning(f"Database duplicate constraint hit for mobile (should be rare)")
                return -1
            else:
                self.logger.error(f"Unexpected error inserting user: {e}")
                self.connection.rollback()
                return None
    
    def process_vi_csv_file(self, csv_file_path):
        """Process Vi server CSV file with encrypted mobile numbers"""
        if not os.path.exists(csv_file_path):
            self.logger.error(f"CSV file not found: {csv_file_path}")
            # email_alert("CSV File Not Found", f"Script 1: CSV file not found: {csv_file_path}")
            return False
        
        if os.path.getsize(csv_file_path) == 0:
            self.logger.warning(f"CSV file is empty (0 bytes): {csv_file_path}")
            # Delete empty CSV file
            self.delete_csv_file(csv_file_path)
            return True  # Not an error, just skip it
        
        self.logger.info(f"Processing Vi CSV file: {csv_file_path}")
        
        # Extract campaign name and date
        campaign_name = self.extract_campaign_name_from_filename(csv_file_path)
        campaign_date = self.extract_date_from_campaign_name(campaign_name)
        self.logger.info(f"Campaign name: {campaign_name}")
        self.logger.info(f"Campaign date: {campaign_date}")
        
        # Check if campaign already exists
        existing_campaign_id = self.campaign_exists(campaign_name)
        if existing_campaign_id:
            self.logger.info(f"Campaign '{campaign_name}' already exists (ID: {existing_campaign_id}), skipping")
            # Delete the duplicate CSV file
            self.delete_csv_file(csv_file_path)
            return True  # Not an error, expected behavior
        
        # Count valid data rows BEFORE processing
        valid_row_count = self.count_valid_data_rows(csv_file_path)
        
        if valid_row_count == 0:
            self.logger.warning(f"CSV file has no valid data rows (only headers or empty): {csv_file_path}")
            # Delete empty CSV file
            self.delete_csv_file(csv_file_path)
            return True  # Not an error, just skip it
        
        if valid_row_count < 0:
            self.logger.error(f"Error counting rows in CSV file: {csv_file_path}")
            return False
        
        self.logger.info(f"CSV file has {valid_row_count} valid data rows")
        
        # Load daily CSV for this campaign's date
        if not self.load_daily_csv(campaign_date):
            self.logger.error("Failed to load daily CSV")
            return False
        
        stats = {
            'total_rows': 0,
            'successfully_inserted': 0,
            'duplicate_num_per_day': 0,
            'invalid_circle_name': 0,
            'invalid_mobile': 0,
            'decryption_failed': 0,
            'errors': 0
        }
        
        campaign_id = None
        
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                # Detect delimiter (likely semicolon based on your sample)
                sample = file.read(1024)
                file.seek(0)
                
                # Try to detect delimiter
                if ';' in sample:
                    delimiter = ';'
                    self.logger.info("Detected delimiter: ';'")
                else:
                    sniffer = csv.Sniffer()
                    try:
                        delimiter = sniffer.sniff(sample).delimiter
                        self.logger.info(f"Detected delimiter: '{delimiter}'")
                    except:
                        delimiter = ','
                        self.logger.info("Using default delimiter: ','")
                
                file.seek(0)
                reader = csv.DictReader(file, delimiter=delimiter, quotechar='"')
                
                # Normalize headers (strip quotes and whitespace)
                reader.fieldnames = [h.strip().strip('"').lower() for h in reader.fieldnames]
                self.logger.info(f"CSV headers: {reader.fieldnames}")
                
                # Verify required columns exist
                required_cols = ['mobile_no', 'circle_name', 'ul_validity_diff', 'current_balance']
                missing_cols = [col for col in required_cols if col not in reader.fieldnames]
                if missing_cols:
                    self.logger.error(f"Missing required columns: {missing_cols}")
                    # email_alert("Missing CSV Columns", f"Script 1: Missing columns in {csv_file_path}: {missing_cols}")
                    return False
                
                # Create campaign
                campaign_id = self.create_campaign(campaign_name)
                if not campaign_id:
                    self.logger.error(f"Failed to create campaign '{campaign_name}'")
                    # email_alert("Campaign Creation Failed", f"Script 1: Failed to create campaign '{campaign_name}'")
                    return False
                
                # Process rows
                for row_num, row in enumerate(reader, start=2):
                    try:
                        stats['total_rows'] += 1
                        
                        # Clean and extract required fields
                        encrypted_mobile = str(row.get('mobile_no', '')).strip().strip('"')
                        circle_name_raw = row.get('circle_name', '').strip().strip('"')
                        validity_diff = self.safe_convert_to_int(row.get('ul_validity_diff', '').strip().strip('"'), 'ul_validity_diff')
                        current_balance = self.safe_convert_to_decimal(row.get('current_balance', '').strip().strip('"'), 'current_balance')
                        
                        # Validate encrypted mobile
                        if not encrypted_mobile:
                            self.logger.debug(f"Row {row_num}: Empty mobile number, skipping")
                            stats['invalid_mobile'] += 1
                            continue
                        
                        # Validate circle_name - MUST be valid integer or skip the row
                        circle_name = self.validate_circle_name(circle_name_raw)
                        if circle_name is None:
                            self.logger.debug(f"Row {row_num}: Invalid circle_name '{circle_name_raw}' (must be integer), skipping row")
                            stats['invalid_circle_name'] += 1
                            continue
                        
                        # Insert user (with CSV-based duplicate check)
                        result = self.insert_user(campaign_id, encrypted_mobile, circle_name, validity_diff, current_balance)

                        if result and result > 0:
                            stats['successfully_inserted'] += 1
                        elif result == -1:
                            stats['duplicate_num_per_day'] += 1
                        elif result is None:
                            stats['decryption_failed'] += 1  # Track decryption failures
                        else:
                            stats['errors'] += 1
                        
                        # Progress logging
                        if stats['total_rows'] % 500 == 0:
                            self.logger.info(f"Processed {stats['total_rows']} rows... (Added: {stats['successfully_inserted']}, Skipped: {stats['duplicate_num_per_day'] + stats['invalid_circle_name'] + stats['invalid_mobile']})")
                            
                    except Exception as row_error:
                        self.logger.error(f"Row {row_num} error: {row_error}")
                        stats['errors'] += 1
                        continue
        
        except Exception as e:
            self.logger.error(f"Error processing CSV file: {e}")
            self.logger.error(traceback.format_exc())
            # email_alert("CSV Processing Error", f"Script 1: Error processing {csv_file_path}: {e}")
            return False
        
        # Final save of daily CSV
        self.save_daily_csv()
        
        # Update campaign duplicate counters in database (keep status as 'ongoing')
        if campaign_id:
            try:
                update_query = """
                    UPDATE campaigns 
                    SET duplicate_num_per_day = %s
                    WHERE id = %s
                """
                self.cursor.execute(update_query, (stats['duplicate_num_per_day'], campaign_id))
                self.connection.commit()
            except Exception as e:
                self.logger.error(f"Error updating campaign duplicate counters: {e}")
        
        # Summary
        self.logger.info("=" * 80)
        self.logger.info(f"PROCESSING SUMMARY for {os.path.basename(csv_file_path)}:")
        self.logger.info(f"Campaign: {campaign_name} (ID: {campaign_id})")
        self.logger.info(f"Campaign Date: {campaign_date}")
        self.logger.info(f"Total rows: {stats['total_rows']}")
        self.logger.info(f"Successfully inserted: {stats['successfully_inserted']}")
        self.logger.info(f"Duplicates (same day): {stats['duplicate_num_per_day']}")
        self.logger.info(f"Invalid circle_name (skipped): {stats['invalid_circle_name']}")
        self.logger.info(f"Invalid mobile (skipped): {stats['invalid_mobile']}")
        self.logger.info(f"Decryption failed: {stats['decryption_failed']}")
        self.logger.info(f"Errors: {stats['errors']}")
        self.logger.info("=" * 80)
        
        # Check if we should keep this campaign (must have at least 1 successfully inserted user)
        if stats['successfully_inserted'] == 0:
            self.logger.warning(f"Campaign {campaign_name} has 0 users inserted, deleting campaign from database")
            try:
                delete_query = "DELETE FROM campaigns WHERE id = %s"
                self.cursor.execute(delete_query, (campaign_id,))
                self.connection.commit()
                self.logger.info(f"Deleted empty campaign {campaign_name} (ID: {campaign_id})")
            except Exception as e:
                self.logger.error(f"Error deleting empty campaign: {e}")
        
        return True
    
    def delete_csv_file(self, csv_file_path):
        """Delete the CSV file after successful processing"""
        try:
            if os.path.exists(csv_file_path):
                os.remove(csv_file_path)
                self.logger.info(f"Deleted CSV file: {csv_file_path}")
                return True
            else:
                self.logger.warning(f"CSV file not found for deletion: {csv_file_path}")
                return False
        except Exception as e:
            self.logger.error(f"Error deleting CSV file {csv_file_path}: {e}")
            # email_alert("CSV Deletion Failed", f"Script 1: Failed to delete {csv_file_path}: {e}")
            return False
    
    def get_all_csv_files(self, folder_path):
        """Get all CSV files from the folder"""
        try:
            csv_pattern = os.path.join(folder_path, "BOAT_*.csv")
            csv_files = glob.glob(csv_pattern)
            
            if not csv_files:
                self.logger.info(f"No CSV files found in {folder_path}")
                return []
            
            # Sort by modification time (oldest first for FIFO processing)
            csv_files.sort(key=os.path.getmtime)
            
            self.logger.info(f"Found {len(csv_files)} CSV file(s): {[os.path.basename(f) for f in csv_files]}")
            return csv_files
            
        except Exception as e:
            self.logger.error(f"Error getting CSV files: {e}")
            # email_alert("Error Getting CSV Files", f"Script 1: Error getting CSV files from {folder_path}: {e}")
            return []
    
    def process_all_csv_files(self, folder_path="vi_server_files"):
        """Process all CSV files in the folder and delete them after successful processing"""
        self.logger.info(f"Checking for CSV files in: {folder_path}")
        
        if not os.path.exists(folder_path):
            self.logger.error(f"Folder not found: {folder_path}")
            # email_alert("Folder Not Found", f"Script 1: Folder not found: {folder_path}")
            return False
        
        # Get all CSV files
        csv_files = self.get_all_csv_files(folder_path)
        
        if not csv_files:
            self.logger.info("No CSV files to process")
            return True
        
        processed_count = 0
        failed_count = 0
        skipped_count = 0
        empty_count = 0
        
        # Process each file
        for csv_file in csv_files:
            campaign_name = self.extract_campaign_name_from_filename(csv_file)
            
            # Check file size first
            if os.path.getsize(csv_file) == 0:
                self.logger.warning(f"Skipping empty CSV file: {campaign_name}")
                empty_count += 1
                self.delete_csv_file(csv_file)
                continue
            
            # Check if already exists in database
            if self.campaign_exists(campaign_name):
                self.logger.info(f"Skipping existing campaign: {campaign_name}")
                skipped_count += 1
                # Delete the file since campaign already exists
                self.delete_csv_file(csv_file)
            else:
                self.logger.info(f"Processing new file: {os.path.basename(csv_file)}")
                success = self.process_vi_csv_file(csv_file)
                
                if success:
                    processed_count += 1
                    # Delete CSV file after successful processing
                    self.delete_csv_file(csv_file)
                else:
                    failed_count += 1
                    self.logger.error(f"Failed to process: {csv_file}")
                    # Do not delete failed files for manual review
        
        self.logger.info(f"Summary: Processed {processed_count}, Skipped {skipped_count}, Empty {empty_count}, Failed {failed_count}")
        
        # if failed_count > 0:
        #     email_alert("CSV Processing Completed with Errors", 
        #                f"Script 1: Processed: {processed_count}, Skipped: {skipped_count}, Failed: {failed_count}")
        
        return True


def main():
    """Main function - Process all CSV files in the folder"""
    csv_folder = "vi_server_files"
    
    if not os.path.exists(csv_folder):
        print(f"Folder not found: {csv_folder}")
        # email_alert("Folder Not Found", f"Script 1: Folder not found: {csv_folder}")
        sys.exit(1)
    
    processor = ViServerDataProcessor()
    
    if not processor.connect_database():
        sys.exit(1)
    
    try:
        success = processor.process_all_csv_files(csv_folder)
        
        if success:
            print("CSV file processing completed!")
        else:
            print("Processing failed!")
            sys.exit(1)
            
    except Exception as e:
        processor.logger.error(f"Unexpected error: {e}")
        processor.logger.error(traceback.format_exc())
        email_alert("Unexpected Error", f"Script 1: Unexpected error in main: {e}")
        sys.exit(1)
    finally:
        processor.disconnect_database()


if __name__ == "__main__":
    main()