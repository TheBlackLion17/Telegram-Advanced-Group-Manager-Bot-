#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run as root';exit 1;fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-dev build-essential mysql-server libssl-dev
id groupbot &>/dev/null || useradd --system --home-dir /opt/group-manager --shell /usr/sbin/nologin groupbot
mkdir -p /opt/group-manager
cp -a bot.py config.py utils.py requirements.txt plugins database .env.example /opt/group-manager/
cd /opt/group-manager
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
if [[ ! -f .env ]]; then cp .env.example .env;fi
chown -R groupbot:groupbot /opt/group-manager
chmod 600 /opt/group-manager/.env
cp "$OLDPWD/group-manager.service" /etc/systemd/system/group-manager.service
systemctl daemon-reload
echo 'NEXT: create MySQL database/user; edit /opt/group-manager/.env; then systemctl enable --now group-manager'
