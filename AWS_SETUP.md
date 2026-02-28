# AWS Server Setup — Swing Trade Bot

## 1. Launch EC2 Instance

- **AMI:** Ubuntu 22.04 LTS
- **Instance type:** t3.micro (free tier eligible, sufficient for this bot)
- **Storage:** 20 GB gp3
- **Security group:** Allow SSH (port 22) from your IP only

## 2. Connect to Server

```bash
ssh -i your-key.pem ubuntu@<your-ec2-public-ip>
```

## 3. System Update & Python Setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3.11 python3.11-venv python3-pip git -y
```

## 4. Upload Project to Server

**Option A — From local machine (scp):**
```bash
scp -i your-key.pem -r d:/swing_trade/swing_bot ubuntu@<your-ec2-public-ip>:~/swing_bot
```

**Option B — Git clone (if you push to a private repo):**
```bash
cd ~
git clone https://github.com/<your-username>/swing_trade.git
cd swing_trade/swing_bot
```

## 5. Create Virtual Environment & Install Dependencies

```bash
cd ~/swing_bot
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Upload .env File

From your local machine:
```bash
scp -i your-key.pem d:/swing_trade/swing_bot/.env ubuntu@<your-ec2-public-ip>:~/swing_bot/.env
```

Verify on server:
```bash
cat ~/swing_bot/.env
```

## 7. Test Run (foreground)

```bash
cd ~/swing_bot
source venv/bin/activate
python main.py
```

Check that the Telegram bot sends the startup message. Press `Ctrl+C` to stop.

## 8. Run as Background Service (systemd)

Create the service file:
```bash
sudo nano /etc/systemd/system/swingbot.service
```

Paste this:
```ini
[Unit]
Description=Swing Trade Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/swing_bot
ExecStart=/home/ubuntu/swing_bot/venv/bin/python main.py
Restart=on-failure
RestartSec=10
EnvironmentFile=/home/ubuntu/swing_bot/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable swingbot
sudo systemctl start swingbot
```

## 9. Useful Commands

```bash
# Check status
sudo systemctl status swingbot

# View live logs
sudo journalctl -u swingbot -f

# Restart after code changes
sudo systemctl restart swingbot

# Stop
sudo systemctl stop swingbot

# View bot log file
tail -f ~/swing_bot/swing_bot.log
```

## 10. Update Code on Server

```bash
# Upload new files from local
scp -i your-key.pem -r d:/swing_trade/swing_bot ubuntu@<your-ec2-public-ip>:~/swing_bot

# Then restart
ssh -i your-key.pem ubuntu@<your-ec2-public-ip> "sudo systemctl restart swingbot"
```

## Notes

- Never commit `.env` to git — it has your API keys
- t3.micro gives 1 vCPU + 1GB RAM, more than enough for this bot
- The bot auto-restarts on crash via `Restart=on-failure`
- Use `journalctl` for systemd logs and `swing_bot.log` for app logs
