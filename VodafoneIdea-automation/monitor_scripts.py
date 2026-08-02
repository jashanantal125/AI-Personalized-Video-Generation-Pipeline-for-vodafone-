#!/usr/bin/env python3
"""
Campaign Monitoring Script
Sends email alerts with daily statistics at scheduled intervals
"""

import mysql.connector
from datetime import datetime, date
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import csv
import json

# Database Configuration
DB_CONFIG = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': 'YOUR_DB_PASSWORD',
    'database': 'vi_auto'
}

# Email Configuration
EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender_email': 'developer@ldttechnology.com',
    'sender_password': 'YOUR_SMTP_APP_PASSWORD',
    'recipient_emails': ['mahesh@ldttechnology.com', 'snigdha.sharma@ldttechnology.com']
}

# Paths
EXECUTED_SHEETS_DIR = '/home/ecore/vicode/VodafoneIdea/executed_num_sheets/'
INPUT_NUMBERS_DIR = '/home/ecore/vicode/VodafoneIdea/input_numbers/'
VIDEO_CONFIG_PATH = '/home/ecore/vicode/VodafoneIdea/video_config.json'


def get_db_connection():
    """Establish database connection"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None


def get_today_stats():
    """Get all statistics for today's campaigns"""
    conn = get_db_connection()
    if not conn:
        return None
    
    cursor = conn.cursor(dictionary=True)
    today = date.today()
    
    stats = {}
    
    # First, get excluded circles from config
    excluded_circles = get_excluded_circles()
    
    try:
        # 1. Total campaigns executed today
        cursor.execute("""
            SELECT COUNT(*) as total_campaigns
            FROM campaigns
            WHERE DATE(created_at) = %s
        """, (today,))
        stats['total_campaigns'] = cursor.fetchone()['total_campaigns']
        
        # 2. Total users in today's campaigns
        cursor.execute("""
            SELECT COUNT(u.id) as total_users
            FROM users u
            INNER JOIN campaigns c ON u.campaign_id = c.id
            WHERE DATE(c.created_at) = %s
        """, (today,))
        stats['total_users'] = cursor.fetchone()['total_users']
        
        # 3. Ongoing campaigns count
        cursor.execute("""
            SELECT COUNT(*) as ongoing_campaigns
            FROM campaigns
            WHERE DATE(created_at) = %s AND status = 'ongoing'
        """, (today,))
        stats['ongoing_campaigns'] = cursor.fetchone()['ongoing_campaigns']
        
        # 4. Completed campaigns count
        cursor.execute("""
            SELECT COUNT(*) as completed_campaigns
            FROM campaigns
            WHERE DATE(created_at) = %s AND status = 'completed'
        """, (today,))
        stats['completed_campaigns'] = cursor.fetchone()['completed_campaigns']
        
        # 5. Failed status count from users.status
        cursor.execute("""
            SELECT COUNT(u.id) as failed_users
            FROM users u
            INNER JOIN campaigns c ON u.campaign_id = c.id
            WHERE DATE(c.created_at) = %s AND u.status = 'failed'
        """, (today,))
        stats['failed_users'] = cursor.fetchone()['failed_users']
        
        # 6. Pending users count
        cursor.execute("""
            SELECT COUNT(u.id) as pending_users
            FROM users u
            INNER JOIN campaigns c ON u.campaign_id = c.id
            WHERE DATE(c.created_at) = %s AND u.status = 'pending'
        """, (today,))
        stats['pending_users'] = cursor.fetchone()['pending_users']
        
        # 7. Processing users count
        cursor.execute("""
            SELECT COUNT(u.id) as processing_users
            FROM users u
            INNER JOIN campaigns c ON u.campaign_id = c.id
            WHERE DATE(c.created_at) = %s AND u.status = 'processing'
        """, (today,))
        stats['processing_users'] = cursor.fetchone()['processing_users']
        
        # 8. Processed users count
        cursor.execute("""
            SELECT COUNT(u.id) as processed_users
            FROM users u
            INNER JOIN campaigns c ON u.campaign_id = c.id
            WHERE DATE(c.created_at) = %s AND u.status = 'processed'
        """, (today,))
        stats['processed_users'] = cursor.fetchone()['processed_users']
        
        # 9. Failed delivery count from logging_table
        cursor.execute("""
            SELECT COUNT(l.id) as failed_deliveries
            FROM logging_table l
            INNER JOIN campaigns c ON l.campaign_id = c.id
            WHERE DATE(c.created_at) = %s AND l.delivery_status = 'failed'
        """, (today,))
        stats['failed_deliveries'] = cursor.fetchone()['failed_deliveries']
        
        # 10. Successful deliveries
        cursor.execute("""
            SELECT COUNT(l.id) as successful_deliveries
            FROM logging_table l
            INNER JOIN campaigns c ON l.campaign_id = c.id
            WHERE DATE(c.created_at) = %s AND l.delivery_status = 'sent'
        """, (today,))
        stats['successful_deliveries'] = cursor.fetchone()['successful_deliveries']
        
        # 11. Pending deliveries
        cursor.execute("""
            SELECT COUNT(l.id) as pending_deliveries
            FROM logging_table l
            INNER JOIN campaigns c ON l.campaign_id = c.id
            WHERE DATE(c.created_at) = %s AND l.delivery_status = 'pending'
        """, (today,))
        stats['pending_deliveries'] = cursor.fetchone()['pending_deliveries']
        
        # 12. Failed video generation count
        cursor.execute("""
            SELECT COUNT(v.id) as failed_videos
            FROM videos_table v
            INNER JOIN users u ON v.users_id = u.id
            INNER JOIN campaigns c ON u.campaign_id = c.id
            WHERE DATE(c.created_at) = %s AND v.generation_status = 'failed'
        """, (today,))
        stats['failed_videos'] = cursor.fetchone()['failed_videos']
        
        # 13. Completed videos count
        cursor.execute("""
            SELECT COUNT(v.id) as completed_videos
            FROM videos_table v
            INNER JOIN users u ON v.users_id = u.id
            INNER JOIN campaigns c ON u.campaign_id = c.id
            WHERE DATE(c.created_at) = %s AND v.generation_status = 'completed'
        """, (today,))
        stats['completed_videos'] = cursor.fetchone()['completed_videos']
        
        # 14. Count users from restricted circles (circles that are excluded from video generation)
        if excluded_circles:
            # Build SQL IN clause with placeholders
            placeholders = ','.join(['%s'] * len(excluded_circles))
            query = f"""
                SELECT COUNT(u.id) as restricted_circle_users
                FROM users u
                INNER JOIN campaigns c ON u.campaign_id = c.id
                WHERE DATE(c.created_at) = %s AND u.circle_name IN ({placeholders})
            """
            cursor.execute(query, (today, *excluded_circles))
            stats['restricted_circle_users'] = cursor.fetchone()['restricted_circle_users']
        else:
            stats['restricted_circle_users'] = 0
        
        # 15. Get TOP 10 latest campaign details for today
        cursor.execute("""
            SELECT 
                campaign_name,
                total_users,
                processed_records,
                duplicate_num_per_batch,
                duplicate_num_per_day,
                status,
                created_at
            FROM campaigns
            WHERE DATE(created_at) = %s
            ORDER BY created_at DESC
            LIMIT 10
        """, (today,))
        stats['campaign_details'] = cursor.fetchall()
        
    except mysql.connector.Error as err:
        print(f"Database query error: {err}")
        return None
    finally:
        cursor.close()
        conn.close()
    
    return stats


def count_duplicates_removed_by_script1():
    """
    Count duplicate numbers removed by Script 1 from today's input_numbers CSV
    This counts occurrence_count > 1 entries (duplicates blocked by script 1)
    """
    today = date.today().strftime('%Y-%m-%d')
    csv_file = os.path.join(INPUT_NUMBERS_DIR, f'{today}.csv')
    
    if not os.path.exists(csv_file):
        return 0
    
    try:
        duplicate_count = 0
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                occurrence_count = int(row.get('occurrence_count', 1))
                # Count all occurrences beyond the first one as duplicates blocked
                if occurrence_count > 1:
                    duplicate_count += (occurrence_count - 1)
        return duplicate_count
    except Exception as e:
        print(f"Error reading input_numbers CSV file: {e}")
        return 0


def count_duplicates_removed_by_script3():
    """Count duplicate numbers removed by Script 3 from today's executed_num_sheets CSV"""
    today = date.today().strftime('%Y-%m-%d')
    csv_file = os.path.join(EXECUTED_SHEETS_DIR, f'{today}.csv')
    
    if not os.path.exists(csv_file):
        return 0
    
    try:
        with open(csv_file, 'r') as f:
            reader = csv.reader(f)
            # Skip header if exists
            try:
                next(reader)
            except StopIteration:
                return 0
            # Count rows
            count = sum(1 for row in reader if row)
        return count
    except Exception as e:
        print(f"Error reading executed_num_sheets CSV file: {e}")
        return 0


def get_excluded_circles():
    """
    Get excluded circles from video_config.json
    Returns list of circle strings or empty list
    """
    try:
        if not os.path.exists(VIDEO_CONFIG_PATH):
            print(f"Warning: video_config.json not found at {VIDEO_CONFIG_PATH}")
            return []
        
        with open(VIDEO_CONFIG_PATH, 'r') as f:
            config = json.load(f)
            filter_circles = config.get('default_config', {}).get('filter_circles', [])
            return filter_circles
    except Exception as e:
        print(f"Error reading video_config.json: {e}")
        return []


def format_email_body(stats, duplicates_script1, duplicates_script3, excluded_circles):
    """Format statistics into HTML email body"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    today = date.today().strftime('%Y-%m-%d')
    
    # Calculate delivery success rate
    total_deliveries = stats['successful_deliveries'] + stats['failed_deliveries'] + stats['pending_deliveries']
    success_rate = (stats['successful_deliveries'] / total_deliveries * 100) if total_deliveries > 0 else 0
    
    # Calculate video generation success rate
    total_videos = stats['completed_videos'] + stats['failed_videos']
    video_success_rate = (stats['completed_videos'] / total_videos * 100) if total_videos > 0 else 0
    
    # Format excluded circles display
    if excluded_circles:
        excluded_circles_display = ', '.join(excluded_circles)
    else:
        excluded_circles_display = '[]'
    
    # Get restricted circle users count
    restricted_circle_users = stats.get('restricted_circle_users', 0)
    
    html = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #e0e0e0;
                background-color: #1a1a1a;
                margin: 0;
                padding: 0;
            }}
            .header {{
                background: linear-gradient(135deg, #2e7d32 0%, #4CAF50 100%);
                color: white;
                padding: 20px;
                text-align: center;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
            }}
            .content {{
                padding: 20px;
                background-color: #1a1a1a;
            }}
            h2 {{
                color: #4CAF50;
                border-bottom: 2px solid #2e7d32;
                padding-bottom: 10px;
                margin-top: 30px;
            }}
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 15px;
                margin: 20px 0;
            }}
            .stat-box {{
                border: 1px solid #333;
                padding: 15px;
                border-radius: 8px;
                background: linear-gradient(135deg, #2a2a2a 0%, #1f1f1f 100%);
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.5);
                transition: transform 0.2s;
            }}
            .stat-box:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(76, 175, 80, 0.3);
            }}
            .stat-label {{
                font-weight: bold;
                color: #b0b0b0;
                font-size: 14px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .stat-value {{
                font-size: 24px;
                color: #4CAF50;
                margin-top: 5px;
                font-weight: bold;
            }}
            .alert {{
                background: linear-gradient(135deg, #f57c00 0%, #ff9800 100%);
                color: white;
                padding: 12px;
                border-radius: 8px;
                margin: 10px 0;
                border-left: 4px solid #ef6c00;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
            }}
            .error {{
                background: linear-gradient(135deg, #c62828 0%, #f44336 100%);
                color: white;
                padding: 12px;
                border-radius: 8px;
                margin: 10px 0;
                border-left: 4px solid #b71c1c;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
            }}
            .success {{
                background: linear-gradient(135deg, #2e7d32 0%, #4CAF50 100%);
                color: white;
                padding: 12px;
                border-radius: 8px;
                margin: 10px 0;
                border-left: 4px solid #1b5e20;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
                background-color: #2a2a2a;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.5);
            }}
            th, td {{
                border: 1px solid #333;
                padding: 12px;
                text-align: left;
            }}
            th {{
                background: linear-gradient(135deg, #2e7d32 0%, #4CAF50 100%);
                color: white;
                font-weight: bold;
                text-transform: uppercase;
                font-size: 12px;
                letter-spacing: 0.5px;
            }}
            td {{
                color: #e0e0e0;
            }}
            tr:nth-child(even) {{
                background-color: #252525;
            }}
            tr:hover {{
                background-color: #2d2d2d;
            }}
            .footer {{
                margin-top: 30px;
                padding: 20px;
                background-color: #0f0f0f;
                text-align: center;
                font-size: 12px;
                color: #888;
                border-top: 2px solid #2e7d32;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📊 VodafoneIdea Campaign Monitoring Report</h1>
            <p>Report Date: {today} | Generated at: {now}</p>
        </div>
        
        <div class="content">
            <h2>📈 Campaign Overview</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-label">Total Campaigns Executed</div>
                    <div class="stat-value">{stats['total_campaigns']}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Total Users in Campaigns</div>
                    <div class="stat-value">{stats['total_users']:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Ongoing Campaigns</div>
                    <div class="stat-value">{stats['ongoing_campaigns']}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Completed Campaigns</div>
                    <div class="stat-value">{stats['completed_campaigns']}</div>
                </div>
            </div>
            
            <h2>👥 User Processing Status</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-label">Pending Users</div>
                    <div class="stat-value">{stats['pending_users']:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Processing Users</div>
                    <div class="stat-value">{stats['processing_users']:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Processed Users</div>
                    <div class="stat-value">{stats['processed_users']:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">❌ Failed Users</div>
                    <div class="stat-value" style="color: #f44336;">{stats['failed_users']:,}</div>
                </div>
            </div>
            
            <h2>🔄 Duplicate Management</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-label">✅ Duplicates Blocked by Script 1</div>
                    <div class="stat-value" style="color: #2196F3;">{duplicates_script1:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">✅ Duplicates Blocked by Script 3</div>
                    <div class="stat-value" style="color: #4CAF50;">{duplicates_script3:,}</div>
                </div>
            </div>
            
            <h2>📹 Video Generation Status</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-label">Videos Generated</div>
                    <div class="stat-value">{stats['completed_videos']:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">❌ Failed Video Generation</div>
                    <div class="stat-value" style="color: #f44336;">{stats['failed_videos']:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Video Success Rate</div>
                    <div class="stat-value">{video_success_rate:.1f}%</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">🚫 Users from Restricted Circles</div>
                    <div class="stat-value" style="color: #9c27b0;">{restricted_circle_users:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">🚫 Excluded Circles</div>
                    <div class="stat-value" style="font-size: 18px; color: #ff9800;">{excluded_circles_display}</div>
                </div>
            </div>
            
            <h2>📤 Delivery Status</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-label">✅ Successful Deliveries</div>
                    <div class="stat-value" style="color: #4CAF50;">{stats['successful_deliveries']:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">❌ Failed Deliveries</div>
                    <div class="stat-value" style="color: #f44336;">{stats['failed_deliveries']:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">⏳ Pending Deliveries</div>
                    <div class="stat-value" style="color: #ff9800;">{stats['pending_deliveries']:,}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Delivery Success Rate</div>
                    <div class="stat-value">{success_rate:.1f}%</div>
                </div>
            </div>
    """
    
    # Add alerts for critical issues
    alerts = []
    if stats['failed_users'] > 0:
        alerts.append(f"⚠️ {stats['failed_users']} users failed processing")
    if stats['failed_deliveries'] > 0:
        alerts.append(f"⚠️ {stats['failed_deliveries']} messages failed delivery")
    if stats['failed_videos'] > 0:
        alerts.append(f"⚠️ {stats['failed_videos']} videos failed generation")
    if stats['ongoing_campaigns'] > 0:
        alerts.append(f"ℹ️ {stats['ongoing_campaigns']} campaigns still ongoing")
    
    if alerts:
        html += """
            <h2>⚠️ Alerts & Notifications</h2>
        """
        for alert in alerts:
            html += f'<div class="alert">{alert}</div>'
    
    # Add campaign details table if there are campaigns (TOP 10 ONLY)
    if stats['campaign_details']:
        html += """
            <h2>📋 Latest Campaign Details (Top 10)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Campaign Name</th>
                        <th>Total Users</th>
                        <th>Processed</th>
                        <th>Status</th>
                        <th>Created At</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for campaign in stats['campaign_details']:
            status_color = {
                'ongoing': '#ff9800',
                'completed': '#4CAF50',
                'paused': '#9e9e9e'
            }.get(campaign['status'], '#333')
            
            html += f"""
                    <tr>
                        <td>{campaign['campaign_name']}</td>
                        <td>{campaign['total_users']:,}</td>
                        <td>{campaign['processed_records']:,}</td>
                        <td style="color: {status_color}; font-weight: bold;">{campaign['status'].upper()}</td>
                        <td>{campaign['created_at'].strftime('%H:%M:%S')}</td>
                    </tr>
            """
        
        html += """
                </tbody>
            </table>
        """
    else:
        html += '<div class="alert">ℹ️ No campaigns executed today yet.</div>'
    
    html += """
            <div class="footer">
                <p>This is an automated report from VodafoneIdea Campaign Monitoring System</p>
                <p>Generated by monitor_scripts.py</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html


def send_email(subject, html_body):
    """Send email with statistics"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = ', '.join(EMAIL_CONFIG['recipient_emails'])
        
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
            server.send_message(msg)
        
        print(f"✅ Email sent successfully at {datetime.now()}")
        return True
        
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False


def main():
    """Main execution function"""
    print(f"\n{'='*60}")
    print(f"📊 Campaign Monitoring Report - {datetime.now()}")
    print(f"{'='*60}\n")
    
    # Get statistics
    print("📈 Fetching statistics from database...")
    stats = get_today_stats()
    
    if not stats:
        print("❌ Failed to retrieve statistics")
        return
    
    print("✅ Statistics retrieved successfully")
    
    # Get duplicates blocked by Script 1
    print("🔍 Counting duplicates blocked by Script 1...")
    duplicates_script1 = count_duplicates_removed_by_script1()
    print(f"✅ Duplicates blocked by Script 1: {duplicates_script1}")
    
    # Get duplicates removed by Script 3
    print("🔍 Counting duplicates removed by Script 3...")
    duplicates_script3 = count_duplicates_removed_by_script3()
    print(f"✅ Duplicates removed by Script 3: {duplicates_script3}")
    
    # Get excluded circles from video config
    print("🎥 Reading excluded circles from video_config.json...")
    excluded_circles = get_excluded_circles()
    print(f"✅ Excluded circles: {excluded_circles if excluded_circles else '[]'}")
    
    # Format email
    print("📧 Formatting email...")
    now = datetime.now().strftime('%H:%M')
    today = date.today().strftime('%Y-%m-%d')
    subject = f"VodafoneIdea Campaign Report - {today} at {now}"
    html_body = format_email_body(stats, duplicates_script1, duplicates_script3, excluded_circles)
    
    # Send email
    print("📤 Sending email...")
    if send_email(subject, html_body):
        print("✅ Monitoring report sent successfully!")
    else:
        print("❌ Failed to send monitoring report")
    
    # Print summary
    print(f"\n{'='*60}")
    print("📊 SUMMARY")
    print(f"{'='*60}")
    print(f"Total Campaigns: {stats['total_campaigns']}")
    print(f"Total Users: {stats['total_users']:,}")
    print(f"Ongoing Campaigns: {stats['ongoing_campaigns']}")
    print(f"Failed Users: {stats['failed_users']:,}")
    print(f"Failed Deliveries: {stats['failed_deliveries']:,}")
    print(f"Duplicates Blocked (Script 1): {duplicates_script1:,}")
    print(f"Duplicates Removed (Script 3): {duplicates_script3:,}")
    print(f"Restricted Circle Users: {stats.get('restricted_circle_users', 0):,}")
    print(f"Excluded Circles: {excluded_circles if excluded_circles else '[]'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()