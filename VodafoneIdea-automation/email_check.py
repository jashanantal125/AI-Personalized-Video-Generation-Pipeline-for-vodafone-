import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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


email_alert('tsubject', "test body")