def process_csv_files_folder(self, folder_path="csv_files"):
        """Process all CSV files in the specified folder"""
        self.logger.info(f"Starting to process CSV files from folder: {folder_path}")
        
        # Check if folder exists
        if not os.path.exists(folder_path):
            self.logger.error(f"CSV files folder not found: {folder_path}")
            return False
        
        # Get all CSV files in the folder
        csv_pattern = os.path.join(folder_path, "*.csv")
        csv_files = glob.glob(csv_pattern)
        
        if not csv_files:
            self.logger.info(f"No CSV files found in folder: {folder_path}")
            return True  # Not an error, just no files to process
        
        self.logger.info(f"Found {len(csv_files)} CSV files to process")
        
        # Track overall statistics
        overall_stats = {
            'total_files': len(csv_files),
            'processed_files': 0,
            'skipped_files': 0,
            'failed_files': 0
        }
        
        # Process each CSV file
        for csv_file in csv_files:
            self.logger.info(f"=" * 80)
            self.logger.info(f"🔄 Processing file: {csv_file}")
            
            try:
                # Extract campaign name to check if it already exists
                campaign_name = self.extract_campaign_name_from_filename(csv_file)
                self.logger.info(f"Extracted campaign name from filename: '{campaign_name}'")
                
                existing_campaign_id = self.campaign_exists(campaign_name)
                
                if existing_campaign_id:
                    self.logger.info(f"CSV already exists. Campaign '{campaign_name}' (ID: {existing_campaign_id})")
                    overall_stats['skipped_files'] += 1
                else:
                    # Process the file
                    success = self.process_csv_file(csv_file)
                    if success:
                        overall_stats['processed_files'] += 1
                        self.logger.info(f"✅ Successfully processed: {os.path.basename(csv_file)}")
                    else:
                        overall_stats['failed_files'] += 1
                        self.logger.error(f"❌ Failed to process: {os.path.basename(csv_file)}")
                        
            except Exception as e:
                self.logger.error(f"Unexpected error processing {csv_file}: {e}")
                overall_stats['failed_files'] += 1
        
        # Print overall summary
        self.logger.info(f"=" * 80)
        self.logger.info("🎯 OVERALL PROCESSING SUMMARY:")
        self.logger.info(f"📁 Total files found: {overall_stats['total_files']}")
        self.logger.info(f"✅ New files processed: {overall_stats['processed_files']}")
        self.logger.info(f"⏭️  Files skipped (campaigns exist): {overall_stats['skipped_files']}")
        self#!/usr/bin/env python3

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

# Import database connection
from db_script import db_connection

class IncomingDataProcessor:
    def __init__(self):
        """Initialize the incoming data processor - uses external DB connection"""
        self.setup_logging()
        self.connection = None
        self.cursor = None
        
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f'incoming_data_{datetime.now().strftime("%Y%m%d")}.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def connect_database(self):
        """Get database connection from external db_script and create cursor locally"""
        try:
            # Get only the connection from db_script (updated to return only connection)
            self.connection = db_connection()
            
            if self.connection:
                # Create cursor locally in this script
                self.cursor = self.connection.cursor()
                self.logger.info("Database connection established, cursor created locally")
                return True
            else:
                self.logger.error("Failed to get database connection from db_script")
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
    
    def count_csv_rows(self, csv_file_path):
        """Count total data rows in CSV file (excluding header)"""
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                # Detect delimiter
                sample = file.read(1024)
                file.seek(0)
                sniffer = csv.Sniffer()
                try:
                    delimiter = sniffer.sniff(sample).delimiter
                except:
                    delimiter = ','
                
                file.seek(0)
                reader = csv.reader(file, delimiter=delimiter)
                
                # Skip header
                next(reader, None)
                
                # Count data rows
                row_count = sum(1 for row in reader if any(cell.strip() for cell in row))  # Count non-empty rows
                
                return row_count
        except Exception as e:
            self.logger.error(f"Error counting CSV rows: {e}")
            return 0
    
    def get_campaign_user_count_before_after(self, campaign_id, before_processing=True):
        """Get user count for a campaign with explicit timing"""
        try:
            if before_processing:
                # For new campaigns, this should be 0
                query = "SELECT COUNT(*) FROM users WHERE campaign_id = %s"
            else:
                # Get fresh count after processing
                query = "SELECT COUNT(*) FROM users WHERE campaign_id = %s"
            
            self.cursor.execute(query, (campaign_id,))
            result = self.cursor.fetchone()
            if result and len(result) > 0:
                return result[0]
            return 0
        except Error as e:
            self.logger.error(f"Error getting campaign user count: {e}")
            return 0
        except Exception as e:
            self.logger.error(f"Unexpected error getting campaign user count: {e}")
            return 0

    def check_duplicate_in_campaign_detailed(self, campaign_id, mobile):
        """Detailed duplicate check with logging"""
        try:
            query = "SELECT id, mobile FROM users WHERE campaign_id = %s AND mobile = %s"
            self.cursor.execute(query, (campaign_id, mobile))
            result = self.cursor.fetchone()
            if result and len(result) > 0:
                self.logger.debug(f"Found existing user: Mobile {mobile} already exists with ID {result[0]}")
                return result[0]
            return None
        except Exception as e:
            self.logger.error(f"Error checking duplicate for {mobile}: {e}")
            return None
    
    def extract_campaign_name_from_filename(self, csv_file_path):
        """Extract campaign name from CSV filename"""
        filename = os.path.basename(csv_file_path)
        campaign_name = os.path.splitext(filename)[0]
        
        # Clean campaign name (replace underscores with spaces, etc.)
        campaign_name = campaign_name.replace('_', ' ')
        
        self.logger.info(f"Extracted campaign name from filename: '{campaign_name}'")
        return campaign_name
    
    def validate_mobile_number(self, mobile):
        """Validate and format mobile number"""
        # Remove any non-digit characters
        mobile = re.sub(r'\D', '', str(mobile))
        
        # Check if it's a valid Indian mobile number
        if len(mobile) == 10 and mobile.startswith(('6', '7', '8', '9')):
            return mobile
        elif len(mobile) == 12 and mobile.startswith('91'):
            return mobile[2:]  # Remove country code
        elif len(mobile) == 13 and mobile.startswith('+91'):
            return mobile[3:]  # Remove country code with +
        else:
            return None
        
    def safe_convert_to_int(self, value, field_name="value"):
        """Safely convert value to integer, treating empty/None as 0"""
        if value is None or str(value).strip() == '':
            return 0
        
        try:
            # Clean the value - remove all spaces and handle minus signs properly
            cleaned_value = str(value).strip()
            
            # Handle spaced negative numbers: "- 5" → "-5"
            if cleaned_value.startswith('- '):
                cleaned_value = '-' + cleaned_value[2:].strip()
            
            # Remove any remaining internal spaces (for cases like "- 5 . 0")
            cleaned_value = cleaned_value.replace(' ', '')
            
            # Handle float values by converting to int (truncate decimal)
            if '.' in cleaned_value:
                return int(float(cleaned_value))
            else:
                return int(cleaned_value)
                
        except (ValueError, TypeError):
            self.logger.warning(f"Could not convert '{value}' to integer for {field_name}, using 0")
            return 0

    # def safe_convert_to_int(self, value, field_name="value"):
    #     """Safely convert value to integer, treating empty/None as 0"""
    #     if value is None or str(value).strip() == '':
    #         return 0
        
    #     try:
    #         # Handle float values by converting to int (truncate decimal)
    #         if '.' in str(value):
    #             return int(float(str(value).strip()))
    #         else:
    #             return int(str(value).strip())
    #     except (ValueError, TypeError):
    #         self.logger.warning(f"Could not convert '{value}' to integer for {field_name}, using 0")
    #         return 0

    # def validate_csv_row(self, row):
    #     """Validate individual CSV row data - Updated to handle empty values as 0"""
    #     errors = []
        
    #     # Check required fields - mobile_no is the only truly required field
    #     if 'mobile_no' not in row or not row['mobile_no'] or str(row['mobile_no']).strip() == '':
    #         errors.append("Missing or empty mobile_no")
    #         return False, errors
        
    #     # Validate mobile number
    #     validated_mobile = self.validate_mobile_number(row['mobile_no'])
    #     if not validated_mobile:
    #         errors.append("Invalid mobile number format")
    #     else:
    #         row['mobile_no'] = validated_mobile
        
    #     # Handle circle_name - default to '6' if empty
    #     circle_name = str(row.get('circle_name', '')).strip()
    #     if not circle_name:
    #         circle_name = '6'  # Default circle
    #         self.logger.info(f"Empty circle_name for mobile {row['mobile_no']}, using default: '6'")
    #     row['circle_name'] = circle_name
        
    #     # Handle current_balance - convert empty to 0
    #     balance_value = self.safe_convert_to_int(row.get('current_balance', ''), 'current_balance')
    #     if balance_value < 0:
    #         errors.append("Current balance should be non-negative")
    #     row['current_balance'] = balance_value
        
    #     # Handle service_validity - convert empty to 0
    #     validity_value = self.safe_convert_to_int(row.get('service_validity', ''), 'service_validity')
    #     if validity_value < 0:
    #         errors.append("Service validity days should be non-negative")
        
    #     row['validity_days'] = validity_value
    #     row['validity_date'] = None  # Set to None since we're not using dates anymore
        
    #     return len(errors) == 0, errors

    def validate_csv_row(self, row):
        """Validate individual CSV row data - Updated to handle negative values by converting to 0"""
        errors = []
        
        # Check required fields - mobile_no is the only truly required field
        if 'mobile_no' not in row or not row['mobile_no'] or str(row['mobile_no']).strip() == '':
            errors.append("Missing or empty mobile_no")
            return False, errors
        
        # Validate mobile number
        validated_mobile = self.validate_mobile_number(row['mobile_no'])
        if not validated_mobile:
            errors.append("Invalid mobile number format")
        else:
            row['mobile_no'] = validated_mobile
        
        # Handle circle_name - default to '6' if empty
        circle_name = str(row.get('circle_name', '')).strip()
        if not circle_name:
            circle_name = '6'  # Default circle
            self.logger.info(f"Empty circle_name for mobile {row['mobile_no']}, using default: '6'")
        row['circle_name'] = circle_name
        
        # Handle current_balance - convert empty/negative to 0
        balance_value = self.safe_convert_to_int(row.get('current_balance', ''), 'current_balance')
        if balance_value < 0:
            self.logger.info(f"Negative balance {balance_value} for mobile {row['mobile_no']}, converting to 0")
            balance_value = 0
        row['current_balance'] = balance_value
        
        # Handle service_validity - convert empty/negative to 0
        validity_value = self.safe_convert_to_int(row.get('service_validity', ''), 'service_validity')
        if validity_value < 0:
            self.logger.info(f"Negative validity {validity_value} for mobile {row['mobile_no']}, converting to 0")
            validity_value = 0
        
        row['validity_days'] = validity_value
        row['validity_date'] = None  # Set to None since we're not using dates anymore
        
        return len(errors) == 0, errors

    def campaign_exists(self, campaign_name):
        """Check if campaign already exists by name"""
        try:
            query = "SELECT id FROM campaigns WHERE campaign_name = %s"
            self.cursor.execute(query, (campaign_name,))
            result = self.cursor.fetchone()
            if result and len(result) > 0:
                return result[0]
            return None
        except Error as e:
            self.logger.error(f"Error checking campaign existence: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error checking campaign existence: {e}")
            return None
    
    def get_or_create_campaign(self, campaign_name):
        """Get existing campaign ID or create new campaign"""
        try:
            # Check if campaign exists
            query = "SELECT id FROM campaigns WHERE campaign_name = %s"
            self.cursor.execute(query, (campaign_name,))
            result = self.cursor.fetchone()
            
            if result and len(result) > 0:
                campaign_id = result[0]
                self.logger.info(f"Using existing campaign: '{campaign_name}' (ID: {campaign_id})")
                return campaign_id
            else:
                # Create new campaign - NO circle_name needed here
                insert_query = "INSERT INTO campaigns (campaign_name) VALUES (%s)"
                self.cursor.execute(insert_query, (campaign_name,))
                self.connection.commit()
                
                campaign_id = self.cursor.lastrowid
                self.logger.info(f"Created new campaign: '{campaign_name}' (ID: {campaign_id})")
                return campaign_id
                
        except Error as e:
            self.logger.error(f"Error getting/creating campaign: {e}")
            self.connection.rollback()
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error getting/creating campaign: {e}")
            self.connection.rollback()
            return None
    
    def user_exists_in_campaign(self, campaign_id, mobile):
        """Check if user already exists in the campaign"""
        try:
            query = "SELECT id FROM users WHERE campaign_id = %s AND mobile = %s"
            self.cursor.execute(query, (campaign_id, mobile))
            result = self.cursor.fetchone()
            if result and len(result) > 0:
                return result[0]
            return None
        except Error as e:
            self.logger.error(f"Error checking user existence: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error checking user existence: {e}")
            return None

    def insert_user_and_update_campaign(self, campaign_id, row_data):
        """Insert new user data - Updated to include circle_name and update total_users"""
        try:
            # Insert user with circle_name from CSV
            user_query = """
                INSERT INTO users (campaign_id, mobile, circle_name, current_balance, validity_dt, validity_in_days, status) 
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            """
            user_values = (
                campaign_id,
                row_data['mobile_no'],
                row_data['circle_name'],  # Now from CSV
                row_data['current_balance'],
                '1970-01-01',  # Use a default date
                row_data['validity_days']
            )
            
            self.cursor.execute(user_query, user_values)
            user_id = self.cursor.lastrowid
            
            # Update campaign total_users count (NOT processed_records - that's handled by Script 2)
            update_query = "UPDATE campaigns SET total_users = total_users + 1 WHERE id = %s"
            self.cursor.execute(update_query, (campaign_id,))
            
            # Commit the operation
            self.connection.commit()
            
            self.logger.debug(f"New user inserted: {row_data['mobile_no']} (ID: {user_id}, Circle: {row_data['circle_name']})")
            self.logger.debug(f"Balance: {row_data['current_balance']}, Validity Days: {row_data['validity_days']}")
            
            return user_id
            
        except Error as e:
            # Check if it's a duplicate entry error
            if e.errno == 1062:  # MySQL duplicate entry error
                self.logger.debug(f"Duplicate mobile number {row_data['mobile_no']} in campaign, skipping")
                self.connection.rollback()
                return -1  # Return -1 to indicate duplicate (not None for error)
            else:
                self.logger.error(f"Database error inserting user {row_data['mobile_no']}: {e}")
                self.connection.rollback()
                return None
        except Exception as e:
            # Handle PyMySQL IntegrityError specifically for duplicates
            if "Duplicate entry" in str(e) and "unique_campaign_mobile" in str(e):
                self.logger.debug(f"Duplicate mobile number {row_data['mobile_no']} in campaign, skipping")
                self.connection.rollback()
                return -1  # Return -1 to indicate duplicate
            else:
                self.logger.error(f"Unexpected error inserting user {row_data['mobile_no']}: {e}")
                self.connection.rollback()
                return None
    
    def process_csv_file(self, csv_file_path):
        """Process CSV file and insert data - Updated to handle empty values and provide detailed counting"""
        if not os.path.exists(csv_file_path):
            self.logger.error(f"CSV file not found: {csv_file_path}")
            return False
        
        # Check if file is empty
        if os.path.getsize(csv_file_path) == 0:
            self.logger.error(f"CSV file is empty: {csv_file_path}")
            return False
        
        self.logger.info(f"Starting CSV processing: {csv_file_path}")
        
        # Extract campaign name from filename
        campaign_name = self.extract_campaign_name_from_filename(csv_file_path)
        
        # Check if campaign already exists - if yes, skip entire file
        existing_campaign_id = self.campaign_exists(campaign_name)
        if existing_campaign_id:
            self.logger.info(f"Campaign '{campaign_name}' already exists (ID: {existing_campaign_id}), skipping file: {csv_file_path}")
            return True  # Return True since this is expected behavior, not an error
        
        # Count total rows in CSV before processing
        total_csv_rows = self.count_csv_rows(csv_file_path)
        self.logger.info(f"🔢 TOTAL ROWS IN CSV (excluding header): {total_csv_rows}")
        
        # Get initial user count for this campaign (should be 0 for new campaign)
        initial_user_count = 0  # Since it's a new campaign
        
        stats = {
            'total_rows_processed': 0,
            'successfully_inserted': 0,
            'duplicates_skipped': 0,
            'validation_errors': 0,
            'database_errors': 0,
            'other_errors': 0
        }
        
        try:
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                # Detect delimiter
                sample = file.read(1024)
                file.seek(0)
                sniffer = csv.Sniffer()
                try:
                    delimiter = sniffer.sniff(sample).delimiter
                    self.logger.info(f"Detected delimiter: '{delimiter}'")
                except:
                    delimiter = ','
                    self.logger.info(f"Using default delimiter: ','")
                
                reader = csv.DictReader(file, delimiter=delimiter)
                
                # Validate headers - handle case variations and optional fields
                original_headers = [h.strip() for h in reader.fieldnames if h]
                csv_headers = set([h.lower() for h in original_headers])
                required_headers = {'mobile_no'}  # Only mobile_no is truly required
                
                self.logger.info(f"CSV headers: {original_headers}")
                
                # Check that at least mobile_no is present (handle variations)
                mobile_header_found = False
                for header in csv_headers:
                    if 'mobile' in header.lower():
                        mobile_header_found = True
                        break
                
                if not mobile_header_found:
                    self.logger.error(f"No mobile number column found in headers: {list(csv_headers)}")
                    return False
                
                # Create campaign for this CSV file
                campaign_id = self.get_or_create_campaign(campaign_name)
                if not campaign_id:
                    self.logger.error(f"Failed to create campaign '{campaign_name}'")
                    return False
                
                # Process each row
                self.logger.info(f"Starting to process rows...")
                
                for row_num, row in enumerate(reader, start=2):  # Start from 2 (header is row 1)
                    try:
                        stats['total_rows_processed'] += 1
                        
                        # Clean row data (strip whitespace and convert keys to lowercase)
                        clean_row = {}
                        for k, v in row.items():
                            if k:  # Only process non-None keys
                                clean_key = k.strip().lower()
                                clean_value = str(v).strip() if v is not None else ''
                                clean_row[clean_key] = clean_value
                        
                        # Handle header case variations for mobile_no
                        if 'mobile_no' not in clean_row:
                            for key in clean_row.keys():
                                if 'mobile' in key.lower():
                                    clean_row['mobile_no'] = clean_row[key]
                                    break
                        
                        # Ensure all expected fields exist with defaults
                        if 'circle_name' not in clean_row:
                            clean_row['circle_name'] = ''
                        if 'current_balance' not in clean_row:
                            clean_row['current_balance'] = ''
                        if 'service_validity' not in clean_row:
                            clean_row['service_validity'] = ''
                        
                        # Validate row data
                        is_valid, validation_errors = self.validate_csv_row(clean_row)
                        
                        if not is_valid:
                            self.logger.warning(f"Row {row_num} validation failed: {validation_errors}")
                            stats['validation_errors'] += 1
                            continue
                        
                        # Check if user exists in this campaign using detailed check
                        existing_user_id = self.check_duplicate_in_campaign_detailed(campaign_id, clean_row['mobile_no'])
                        
                        if existing_user_id:
                            self.logger.debug(f"User {clean_row['mobile_no']} already exists in campaign, skipping")
                            stats['duplicates_skipped'] += 1
                        else:
                            # Insert new user
                            result = self.insert_user_and_update_campaign(campaign_id, clean_row)
                            if result and result > 0:  # Successfully inserted
                                stats['successfully_inserted'] += 1
                                self.logger.debug(f"Successfully inserted: {clean_row['mobile_no']} (ID: {result})")
                            elif result == -1:  # Duplicate caught at database level
                                stats['duplicates_skipped'] += 1
                                self.logger.debug(f"Database duplicate caught for: {clean_row['mobile_no']}")
                            else:  # Actual error
                                stats['database_errors'] += 1
                                self.logger.warning(f"Database error for: {clean_row['mobile_no']}")
                        
                        # Progress logging for large files
                        if stats['total_rows_processed'] % 500 == 0:
                            self.logger.info(f"Processed {stats['total_rows_processed']} rows... (Added: {stats['successfully_inserted']}, Duplicates: {stats['duplicates_skipped']}, Errors: {stats['validation_errors'] + stats['database_errors'] + stats['other_errors']})")
                            
                    except Exception as row_error:
                        self.logger.error(f"Row {row_num} error: {row_error}")
                        stats['other_errors'] += 1
                        continue
                
                # Check if no data rows were found
                if stats['total_rows_processed'] == 0:
                    self.logger.error(f"CSV file contains no data rows: {csv_file_path}")
                    return False
        
        except Exception as e:
            self.logger.error(f"Error processing CSV file: {e}")
            return False
        
        # Get final user count for this campaign with fresh query
        final_user_count = self.get_campaign_user_count_before_after(campaign_id, before_processing=False)
        users_added_to_db = final_user_count - initial_user_count
        
        # Calculate total errors and issues
        total_duplicates = stats['duplicates_skipped']
        total_errors = stats['validation_errors'] + stats['database_errors'] + stats['other_errors']
        expected_additions = total_csv_rows - total_duplicates - total_errors
        
        # Print detailed analysis
        self.logger.info("=" * 80)
        self.logger.info("📊 FINAL PROCESSING ANALYSIS:")
        self.logger.info(f"📄 CSV File: {os.path.basename(csv_file_path)}")
        self.logger.info(f"🏷️  Campaign: {campaign_name} (ID: {campaign_id})")
        self.logger.info(f"🔢 Total CSV rows (excluding header): {total_csv_rows}")
        self.logger.info(f"🔄 Rows processed by script: {stats['total_rows_processed']}")
        self.logger.info(f"👥 Users actually added to database: {users_added_to_db}")
        self.logger.info(f"✅ Successfully inserted: {stats['successfully_inserted']}")
        self.logger.info(f"🔄 Duplicates skipped: {stats['duplicates_skipped']}")
        self.logger.info(f"⚠️  Validation errors: {stats['validation_errors']}")
        self.logger.info(f"❌ Database errors: {stats['database_errors']}")
        self.logger.info(f"💥 Other errors: {stats['other_errors']}")
        
        # Calculate discrepancies
        if total_csv_rows != stats['total_rows_processed']:
            missing_rows = total_csv_rows - stats['total_rows_processed']
            self.logger.warning(f"⚠️  MISSING ROWS: {missing_rows} rows from CSV were not processed by script")
        
        # Check for discrepancy between what script thinks it inserted vs what's actually in DB
        if users_added_to_db != stats['successfully_inserted']:
            db_discrepancy = abs(users_added_to_db - stats['successfully_inserted'])
            self.logger.warning(f"⚠️  DATABASE DISCREPANCY: {db_discrepancy} difference between script count and actual DB count")
            self.logger.warning(f"   Script thinks it inserted: {stats['successfully_inserted']}")
            self.logger.warning(f"   Actually found in database: {users_added_to_db}")
        
        processing_rate = (users_added_to_db / total_csv_rows * 100) if total_csv_rows > 0 else 0
        self.logger.info(f"📈 Success Rate: {users_added_to_db}/{total_csv_rows} ({processing_rate:.1f}%)")
        
        if users_added_to_db == total_csv_rows:
            self.logger.info(f"✨ PERFECT MATCH: All CSV rows successfully added to database!")
        elif users_added_to_db == expected_additions:
            self.logger.info(f"✅ EXPECTED RESULT: All valid rows added (after excluding duplicates/errors)")
        
        self.logger.info("=" * 80)
        
        return True
    
    def process_csv_files_folder(self, folder_path="csv_files"):
        """Process all CSV files in the specified folder"""
        self.logger.info(f"Starting to process CSV files from folder: {folder_path}")
        
        # Check if folder exists
        if not os.path.exists(folder_path):
            self.logger.error(f"CSV files folder not found: {folder_path}")
            return False
        
        # Get all CSV files in the folder
        csv_pattern = os.path.join(folder_path, "*.csv")
        csv_files = glob.glob(csv_pattern)
        
        if not csv_files:
            self.logger.info(f"No CSV files found in folder: {folder_path}")
            return True  # Not an error, just no files to process
        
        self.logger.info(f"Found {len(csv_files)} CSV files to process")
        
        # Track overall statistics
        overall_stats = {
            'total_files': len(csv_files),
            'processed_files': 0,
            'skipped_files': 0,
            'failed_files': 0
        }
        
        # Process each CSV file
        for csv_file in csv_files:
            self.logger.info(f"=" * 80)
            self.logger.info(f"🔄 Processing file: {csv_file}")
            
            try:
                # Extract campaign name to check if it already exists
                campaign_name = self.extract_campaign_name_from_filename(csv_file)
                self.logger.info(f"Extracted campaign name from filename: '{campaign_name}'")
                
                existing_campaign_id = self.campaign_exists(campaign_name)
                
                if existing_campaign_id:
                    self.logger.info(f"CSV already exists. Campaign '{campaign_name}' (ID: {existing_campaign_id})")
                    overall_stats['skipped_files'] += 1
                else:
                    # Process the file
                    success = self.process_csv_file(csv_file)
                    if success:
                        overall_stats['processed_files'] += 1
                        self.logger.info(f"✅ Successfully processed: {os.path.basename(csv_file)}")
                    else:
                        overall_stats['failed_files'] += 1
                        self.logger.error(f"❌ Failed to process: {os.path.basename(csv_file)}")
                        
            except Exception as e:
                self.logger.error(f"Unexpected error processing {csv_file}: {e}")
                overall_stats['failed_files'] += 1
        
        # Print overall summary
        self.logger.info(f"=" * 80)
        self.logger.info("🎯 OVERALL PROCESSING SUMMARY:")
        self.logger.info(f"📁 Total files found: {overall_stats['total_files']}")
        self.logger.info(f"✅ New files processed: {overall_stats['processed_files']}")
        self.logger.info(f"⏭️  Files skipped (campaigns exist): {overall_stats['skipped_files']}")
        self.logger.info(f"❌ Files failed: {overall_stats['failed_files']}")
        
        # Return True if at least some files were processed successfully or skipped
        return overall_stats['failed_files'] < overall_stats['total_files']
    
    def get_processing_stats(self):
        """Get current processing statistics from database"""
        try:
            self.logger.info("=" * 80)
            self.logger.info("📊 OVERALL DATABASE STATISTICS:")
            
            # Total users
            self.cursor.execute("SELECT COUNT(*) FROM users")
            result = self.cursor.fetchone()
            total_users = result[0] if result and len(result) > 0 else 0
            self.logger.info(f"👥 Total Users: {total_users}")
            
            # Pending users
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'pending'")
            result = self.cursor.fetchone()
            pending = result[0] if result and len(result) > 0 else 0
            self.logger.info(f"⏳ Pending: {pending}")
            
            # Processed users (processed by Script 2)
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'processed'")
            result = self.cursor.fetchone()
            processed_users = result[0] if result and len(result) > 0 else 0
            self.logger.info(f"✅ Processed: {processed_users}")
            
            # Failed users
            self.cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'failed'")
            result = self.cursor.fetchone()
            failed = result[0] if result and len(result) > 0 else 0
            self.logger.info(f"❌ Failed: {failed}")
            
            # Campaign-wise stats
            self.logger.info("📋 RECENT CAMPAIGNS:")
            campaign_query = """
                SELECT 
                    c.campaign_name,
                    c.created_at,
                    c.total_users,
                    c.processed_records,
                    COUNT(DISTINCT u.circle_name) as unique_circles
                FROM campaigns c
                LEFT JOIN users u ON c.id = u.campaign_id
                GROUP BY c.id, c.campaign_name, c.created_at, c.total_users, c.processed_records
                ORDER BY c.created_at DESC
                LIMIT 10
            """
            self.cursor.execute(campaign_query)
            campaigns = self.cursor.fetchall()
            
            for campaign_data in campaigns:
                if campaign_data and len(campaign_data) >= 5:
                    name, created, total_users, processed_records, unique_circles = campaign_data
                    
                    # Calculate completion percentage
                    completion = (processed_records / total_users * 100) if total_users > 0 else 0
                    
                    self.logger.info(f"   📊 {name}: {processed_records}/{total_users} processed ({completion:.1f}%), {unique_circles} circles - Created: {created}")
            
            self.logger.info("=" * 80)
                
        except Error as e:
            self.logger.error(f"Error getting statistics: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error getting statistics: {e}")


def main():
    """Main function - Updated to process entire CSV folder"""
    # Folder containing CSV files
    csv_folder = "csv_files"
    
    # Check if folder exists
    if not os.path.exists(csv_folder):
        print(f"CSV files folder not found: {csv_folder}")
        print(f"Please create the '{csv_folder}' directory and place your CSV files there")
        sys.exit(1)
    
    processor = IncomingDataProcessor()
    
    # Connect to database using external db_script
    if not processor.connect_database():
        sys.exit(1)
    
    try:
        # Process all CSV files in the folder
        success = processor.process_csv_files_folder(csv_folder)
        
        if success:
            # Show statistics
            processor.get_processing_stats()
            print("CSV files processing completed successfully!")
        else:
            print("CSV files processing failed!")
            sys.exit(1)
            
    except Exception as e:
        processor.logger.error(f"Unexpected error in main: {e}")
        processor.logger.error(f"Full traceback: {traceback.format_exc()}")
        print("CSV processing failed with unexpected error!")
        sys.exit(1)
    finally:
        # Always close the database connection
        processor.disconnect_database()


if __name__ == "__main__":
    main()