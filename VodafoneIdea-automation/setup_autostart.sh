#!/bin/bash
# setup_autostart.sh - Setup workers to auto-start on system boot and cron monitoring

WORK_DIR="/home/ecore/vicode/VodafoneIdea"
START_SCRIPT="$WORK_DIR/start_workers.sh"
MONITOR_SCRIPT="$WORK_DIR/monitor_and_restart_workers.sh"
USER="ecore"

echo "=========================================="
echo "Setting up Video Workers Auto-Start"
echo "=========================================="
echo ""

# Make scripts executable
echo "Making scripts executable..."
chmod +x "$START_SCRIPT"
chmod +x "$MONITOR_SCRIPT"
chmod +x "$WORK_DIR/status_workers.sh"
chmod +x "$WORK_DIR/stop_workers.sh"
echo "Done."
echo ""

# Setup systemd service for auto-start on boot
echo "Setting up systemd service..."

sudo tee /etc/systemd/system/video-workers.service > /dev/null <<EOF
[Unit]
Description=Video Workers Service
After=network.target mysql.service

[Service]
Type=forking
User=$USER
WorkingDirectory=$WORK_DIR
ExecStart=$START_SCRIPT
ExecStop=$WORK_DIR/stop_workers.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "Systemd service created: /etc/systemd/system/video-workers.service"
echo ""

# Reload systemd and enable service
echo "Enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable video-workers.service
echo "Done."
echo ""

# Setup cron job for monitoring (every 5 minutes)
echo "Setting up cron job for monitoring..."

# Remove existing cron job if any
(crontab -l 2>/dev/null | grep -v "monitor_and_restart_workers.sh") | crontab -

# Add new cron job
(crontab -l 2>/dev/null; echo "*/5 * * * * $MONITOR_SCRIPT >> $WORK_DIR/logs/cron_monitor.log 2>&1") | crontab -

echo "Cron job added: runs every 5 minutes"
echo ""

# Display current crontab
echo "Current crontab entries:"
crontab -l | grep "monitor_and_restart_workers"
echo ""

echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Available commands:"
echo "  Start workers:   ./start_workers.sh"
echo "  Stop workers:    ./stop_workers.sh"
echo "  Check status:    ./status_workers.sh"
echo "  Monitor workers: ./monitor_and_restart_workers.sh"
echo ""
echo "Systemd service commands:"
echo "  sudo systemctl start video-workers    # Start workers"
echo "  sudo systemctl stop video-workers     # Stop workers"
echo "  sudo systemctl status video-workers   # Check status"
echo "  sudo systemctl restart video-workers  # Restart workers"
echo ""
echo "Monitoring:"
echo "  - Cron runs every 5 minutes to check and restart failed workers"
echo "  - Workers auto-start on system boot via systemd"
echo "  - Email alerts will be sent if restart fails"
echo ""
echo "Logs location:"
echo "  Worker logs:   $WORK_DIR/logs/worker-*.log"
echo "  Monitor log:   $WORK_DIR/logs/monitor.log"
echo "  Cron log:      $WORK_DIR/logs/cron_monitor.log"
echo ""
