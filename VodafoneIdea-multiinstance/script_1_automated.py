#!/usr/bin/env python3

import csv
import mysql.connector
from mysql.connector import Error
import logging
import sys
import os
from datetime import datetime
import re
import glob
import traceback

# Import database connection
from db_script import db_connection

# CONFIGURATION - Easy to change
DECRYPTION_PASSWORD = "YOUR_DECRYPTION_PASSWORD"

class ViServerDataProcessor:
    def __init__(self):
        """Initialize the Vi server data processor"""
        self.setup_logging()
        self.connection = None
        self.cursor = None
        self.decryption_password = DECRYPTION_PASSWORD
        
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
                self.logger.info("Database connection closed")
        except Exception as e:
            self.logger.error(f"Error closing database connection: {e}")
    
    def safe_convert_to_int(self, value, field_name="value"):
        """Safely convert value to integer, handling empty/None/negative/string values"""
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
            
            # Convert negative to 0
            if result < 0:
                self.logger.debug(f"Negative value {result} for {field_name}, converting to 0")
                return 0
            
            return result
                
        except (ValueError, TypeError):
            self.logger.warning(f"Could not convert '{value}' to integer for {field_name}, using 0")
            return 0
    
    # def validate_circle_name(self, circle_name):
    #     """Validate circle name - must be a valid integer, otherwise return None to skip the row"""
    #     if circle_name is None or str(circle_name).strip() == '' or str(circle_name).strip().upper() in ['NONE', 'NULL', 'NA', 'N/A']:
    #         return None  # Invalid - skip this row
        
    #     try:
    #         # Try to convert to integer
    #         circle_value = str(circle_name).strip()
            
    #         # Check if it's a valid integer
    #         int(circle_value)
            
    #         # Return the string representation of the integer
    #         return circle_value
    #     except (ValueError, TypeError):
    #         # Not a valid integer - skip this row
    #         return None

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
    
    # def campaign_exists_in_test(self, campaign_name):
    #     """Check if campaign already exists in test_campaigns table"""
    #     try:
    #         query = "SELECT id FROM test_campaigns WHERE campaign_name = %s"
    #         self.cursor.execute(query, (campaign_name,))
    #         result = self.cursor.fetchone()
    #         if result:
    #             return result[0]
    #         return None
    #     except Error as e:
    #         self.logger.error(f"Error checking campaign existence: {e}")
    #         return None
        
    def campaign_exists_in_test(self, campaign_name):
        """Check if campaign already exists in test_campaigns table"""
        try:
            query = "SELECT id FROM test_campaigns WHERE campaign_name = %s"
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

    def create_test_campaign(self, campaign_name):
        """Create new campaign in test_campaigns table"""
        try:
            insert_query = "INSERT INTO test_campaigns (campaign_name) VALUES (%s)"
            self.cursor.execute(insert_query, (campaign_name,))
            self.connection.commit()
            
            campaign_id = self.cursor.lastrowid
            self.logger.info(f"Created new test campaign: '{campaign_name}' (ID: {campaign_id})")
            return campaign_id
                
        except Error as e:
            self.logger.error(f"Error creating test campaign: {e}")
            self.connection.rollback()
            return None
    
    # def insert_test_user(self, campaign_id, encrypted_mobile, circle_name, validity_diff, current_balance):
    #     """Insert user data into test_users with encrypted mobile"""
    #     try:
    #         user_query = """
    #             INSERT INTO test_users (campaign_id, mobile, circle_name, current_balance, validity_dt, validity_in_days, status) 
    #             VALUES (%s, %s, %s, %s, '1970-01-01', %s, 'pending')
    #         """
    #         user_values = (
    #             campaign_id,
    #             encrypted_mobile,  # Store encrypted mobile
    #             circle_name,
    #             current_balance,
    #             validity_diff
    #         )
            
    #         self.cursor.execute(user_query, user_values)
    #         user_id = self.cursor.lastrowid
            
    #         # Update campaign total_users count
    #         update_query = "UPDATE test_campaigns SET total_users = total_users + 1 WHERE id = %s"
    #         self.cursor.execute(update_query, (campaign_id,))
            
    #         self.connection.commit()
            
    #         return user_id
            
    #     except Error as e:
    #         if e.errno == 1062:  # Duplicate entry
    #             self.connection.rollback()
    #             return -1  # Duplicate
    #         else:
    #             self.logger.error(f"Database error inserting user: {e}")
    #             self.connection.rollback()
    #             return None
    #     except Exception as e:
    #         if "Duplicate entry" in str(e):
    #             self.connection.rollback()
    #             return -1
    #         else:
    #             self.logger.error(f"Unexpected error inserting user: {e}")
    #             self.connection.rollback()
    #             return None

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

    def insert_test_user(self, campaign_id, encrypted_mobile, circle_name, validity_diff, current_balance):
        """Insert user data into test_users with DECRYPTED mobile"""
        try:
            # First, decrypt the mobile number using SQL
            decrypted_mobile = self.decrypt_mobile_number(encrypted_mobile)
            
            if not decrypted_mobile:
                self.logger.warning(f"Could not decrypt mobile: {encrypted_mobile[:10]}...")
                return None
            
            user_query = """
                INSERT INTO test_users (campaign_id, mobile, circle_name, current_balance, validity_dt, validity_in_days, status) 
                VALUES (%s, %s, %s, %s, '1970-01-01', %s, 'pending')
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
            
            # Update campaign total_users count
            update_query = "UPDATE test_campaigns SET total_users = total_users + 1 WHERE id = %s"
            self.cursor.execute(update_query, (campaign_id,))
            
            self.connection.commit()
            
            return user_id
            
        except Error as e:
            if e.errno == 1062:  # Duplicate entry
                self.connection.rollback()
                return -1  # Duplicate
            else:
                self.logger.error(f"Database error inserting user: {e}")
                self.connection.rollback()
                return None
        except Exception as e:
            if "Duplicate entry" in str(e):
                self.connection.rollback()
                return -1
            else:
                self.logger.error(f"Unexpected error inserting user: {e}")
                self.connection.rollback()
                return None
    
    def process_vi_csv_file(self, csv_file_path):
        """Process Vi server CSV file with encrypted mobile numbers"""
        if not os.path.exists(csv_file_path):
            self.logger.error(f"CSV file not found: {csv_file_path}")
            return False
        
        if os.path.getsize(csv_file_path) == 0:
            self.logger.error(f"CSV file is empty: {csv_file_path}")
            return False
        
        self.logger.info(f"Processing Vi CSV file: {csv_file_path}")
        
        # Extract campaign name and date
        campaign_name = self.extract_campaign_name_from_filename(csv_file_path)
        campaign_date = self.extract_date_from_campaign_name(campaign_name)
        self.logger.info(f"Campaign date: {campaign_date}")
        
        # Check if campaign already exists
        existing_campaign_id = self.campaign_exists_in_test(campaign_name)
        if existing_campaign_id:
            self.logger.info(f"Campaign '{campaign_name}' already exists (ID: {existing_campaign_id}), skipping")
            return True  # Not an error, expected behavior
        
        stats = {
            'total_rows': 0,
            'successfully_inserted': 0,
            'duplicates_in_test_users': 0,
            'invalid_circle_name': 0,
            'invalid_mobile': 0,
            'decryption_failed': 0,
            'errors': 0
        }
        
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
                    return False
                
                # Create campaign
                campaign_id = self.create_test_campaign(campaign_name)
                if not campaign_id:
                    self.logger.error(f"Failed to create campaign '{campaign_name}'")
                    return False
                
                # Process rows
                for row_num, row in enumerate(reader, start=2):
                    try:
                        stats['total_rows'] += 1
                        
                        # Clean and extract required fields
                        encrypted_mobile = str(row.get('mobile_no', '')).strip().strip('"')
                        circle_name_raw = row.get('circle_name', '').strip().strip('"')
                        validity_diff = self.safe_convert_to_int(row.get('ul_validity_diff', '').strip().strip('"'), 'ul_validity_diff')
                        current_balance = self.safe_convert_to_int(row.get('current_balance', '').strip().strip('"'), 'current_balance')
                        
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
                        
                        # Insert user (storing encrypted mobile)
                        result = self.insert_test_user(campaign_id, encrypted_mobile, circle_name, validity_diff, current_balance)

                        if result and result > 0:
                            stats['successfully_inserted'] += 1
                        elif result == -1:
                            stats['duplicates_in_test_users'] += 1
                        elif result is None:
                            stats['decryption_failed'] += 1  # Track decryption failures
                        else:
                            stats['errors'] += 1
                        
                        # Progress logging
                        if stats['total_rows'] % 500 == 0:
                            self.logger.info(f"Processed {stats['total_rows']} rows... (Added: {stats['successfully_inserted']}, Skipped: {stats['duplicates_in_test_users'] + stats['invalid_circle_name'] + stats['invalid_mobile']})")
                            
                    except Exception as row_error:
                        self.logger.error(f"Row {row_num} error: {row_error}")
                        stats['errors'] += 1
                        continue
        
        except Exception as e:
            self.logger.error(f"Error processing CSV file: {e}")
            self.logger.error(traceback.format_exc())
            return False
        
        # Summary
        self.logger.info("=" * 80)
        self.logger.info(f"PROCESSING SUMMARY for {os.path.basename(csv_file_path)}:")
        self.logger.info(f"Campaign: {campaign_name} (ID: {campaign_id})")
        self.logger.info(f"Total rows: {stats['total_rows']}")
        self.logger.info(f"Successfully inserted: {stats['successfully_inserted']}")
        self.logger.info(f"Duplicates in test_users: {stats['duplicates_in_test_users']}")
        self.logger.info(f"Invalid circle_name (skipped): {stats['invalid_circle_name']}")
        self.logger.info(f"Invalid mobile (skipped): {stats['invalid_mobile']}")
        self.logger.info(f"Errors: {stats['errors']}")
        self.logger.info("=" * 80)
        
        return True
    
    def get_latest_two_files(self, folder_path):
        """Get the two most recent CSV files from the folder"""
        try:
            csv_pattern = os.path.join(folder_path, "BOAT_*.csv")
            csv_files = glob.glob(csv_pattern)
            
            if not csv_files:
                self.logger.info(f"No CSV files found in {folder_path}")
                return []
            
            # Sort by modification time (newest first)
            csv_files.sort(key=os.path.getmtime, reverse=True)
            
            # Return latest 2 files
            latest_files = csv_files[:2]
            self.logger.info(f"Latest 2 files: {[os.path.basename(f) for f in latest_files]}")
            return latest_files
            
        except Exception as e:
            self.logger.error(f"Error getting latest files: {e}")
            return []
    
    def process_latest_files(self, folder_path="vicode/vi_server_files"):
        """Process only the latest 2 files that don't exist in database"""
        self.logger.info(f"Checking latest files in: {folder_path}")
        
        if not os.path.exists(folder_path):
            self.logger.error(f"Folder not found: {folder_path}")
            return False
        
        # Get latest 2 files
        latest_files = self.get_latest_two_files(folder_path)
        
        if not latest_files:
            self.logger.info("No files to process")
            return True
        
        processed_count = 0
        skipped_count = 0
        
        # Check and process each file
        for csv_file in latest_files:
            campaign_name = self.extract_campaign_name_from_filename(csv_file)
            
            # Check if already exists in database
            if self.campaign_exists_in_test(campaign_name):
                self.logger.info(f"Skipping existing campaign: {campaign_name}")
                skipped_count += 1
            else:
                self.logger.info(f"Processing new file: {os.path.basename(csv_file)}")
                success = self.process_vi_csv_file(csv_file)
                if success:
                    processed_count += 1
                else:
                    self.logger.error(f"Failed to process: {csv_file}")
        
        self.logger.info(f"Summary: Processed {processed_count}, Skipped {skipped_count}")
        return True


def main():
    """Main function - Process only latest 2 files"""
    csv_folder = "vi_server_files"
    
    if not os.path.exists(csv_folder):
        print(f"Folder not found: {csv_folder}")
        sys.exit(1)
    
    processor = ViServerDataProcessor()
    
    if not processor.connect_database():
        sys.exit(1)
    
    try:
        success = processor.process_latest_files(csv_folder)
        
        if success:
            print("Latest files processing completed!")
        else:
            print("Processing failed!")
            sys.exit(1)
            
    except Exception as e:
        processor.logger.error(f"Unexpected error: {e}")
        processor.logger.error(traceback.format_exc())
        sys.exit(1)
    finally:
        processor.disconnect_database()


if __name__ == "__main__":
    main()