# Telegram Advanced Group Manager Bot

Standalone Pyrogram + MySQL moderation and engagement bot for Ubuntu VPS.

## Installation
1. Install Python 3.12 and MySQL 8 on Ubuntu 24.04.
2. Clone this repository, then run `sudo bash install.sh`.
3. Create the `group_manager` MySQL database and a dedicated MySQL user.
4. Configure `/opt/group-manager/.env` using `.env.example`.
5. Run `sudo systemctl enable --now group-manager`.
6. Inspect logs with `sudo journalctl -u group-manager -f`.

Grant the bot delete, ban/restrict, and invite privileges. Disable BotFather privacy mode for moderation.

## Security
Never commit `.env`, tokens, passwords, or session files.

## Limitations
Initial implementation, not production-hardened. CAPTCHA is basic, scheduler recovery is limited, flood counters reset after restart, and activity stats begin when the bot is installed. OTT updates are admin-authored.
