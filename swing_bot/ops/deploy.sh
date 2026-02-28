#!/bin/bash
# Deploy swing bot on Linux VPS (Ubuntu/Debian)
set -e

BOT_DIR="/home/ubuntu/swing_bot"
SERVICE_NAME="swing_bot"

echo "=== Swing Bot Deployment ==="

# 1. Install system dependencies
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip

# 2. Create bot directory
mkdir -p $BOT_DIR

# 3. Copy files (run from project root)
rsync -av --exclude='.env' --exclude='*.db' --exclude='__pycache__' \
    ./ $BOT_DIR/

# 4. Create virtualenv and install dependencies
cd $BOT_DIR
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5. Copy .env if it doesn't exist
if [ ! -f $BOT_DIR/.env ]; then
    cp $BOT_DIR/.env.example $BOT_DIR/.env
    echo ">>> IMPORTANT: Edit $BOT_DIR/.env with your API keys before starting."
fi

# 6. Install systemd service
sudo cp $BOT_DIR/ops/swing_bot.service /etc/systemd/system/$SERVICE_NAME.service
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME

echo ""
echo "=== Deployment complete ==="
echo "Next steps:"
echo "  1. Edit $BOT_DIR/.env with your API keys"
echo "  2. sudo systemctl start $SERVICE_NAME"
echo "  3. sudo systemctl status $SERVICE_NAME"
echo "  4. sudo journalctl -u $SERVICE_NAME -f   (to tail logs)"
