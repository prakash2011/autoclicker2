#!/bin/bash
set -e

SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/antigravity-autoclicker.service"
SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/auto_submit.py"

mkdir -p "$SERVICE_DIR"

cat << EOF > "$SERVICE_FILE"
[Unit]
Description=Antigravity Auto-Submit Daemon
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $SCRIPT_PATH run
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=PATH=/home/gset-vapt/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload

echo "✅ Systemd user service installed to: $SERVICE_FILE"
echo ""
echo "To start the service:"
echo "  systemctl --user start antigravity-autoclicker"
echo ""
echo "To enable auto-start on login:"
echo "  systemctl --user enable antigravity-autoclicker"
echo ""
echo "To check status:"
echo "  systemctl --user status antigravity-autoclicker"
echo ""
echo "To stop the service:"
echo "  systemctl --user stop antigravity-autoclicker"
