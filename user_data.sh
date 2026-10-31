#!/bin/bash
# EC2 user data for the Launch Template (Amazon Linux 2023).
# Replace the four values below before use.
REPO_URL="https://github.com/YOUR_USER/flask-3tier.git"
DB_HOST="YOUR-RDS-ENDPOINT.rds.amazonaws.com"
DB_PASSWORD="YOUR_DB_PASSWORD"
REDIS_HOST="YOUR-ELASTICACHE-ENDPOINT.cache.amazonaws.com"

dnf install -y git python3-pip
git clone "$REPO_URL" /opt/app
cd /opt/app
pip3 install -r requirements.txt

cat > /etc/systemd/system/flaskapp.service <<EOF
[Unit]
Description=Flask 3-tier app
After=network.target

[Service]
WorkingDirectory=/opt/app
Environment=DB_HOST=$DB_HOST
Environment=DB_NAME=notesdb
Environment=DB_USER=postgres
Environment=DB_PASSWORD=$DB_PASSWORD
Environment=REDIS_HOST=$REDIS_HOST
Environment=SECRET_KEY=$(openssl rand -hex 16)
ExecStart=/usr/local/bin/gunicorn -w 2 -b 0.0.0.0:8080 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now flaskapp
