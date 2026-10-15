#!/usr/bin/env bash
#
# One-command deploy for Drone Flight Report (Ubuntu / Debian).
#
# Usage (run from the project directory, as root):
#   DOMAIN=example.com EMAIL=me@example.com bash deploy/setup.sh
#
# What it does:
#   - installs python3 / nginx / certbot
#   - creates a venv and installs requirements
#   - installs a systemd service (waitress on :8080)
#   - configures nginx reverse proxy + HTTPS (certbot)
#
set -euo pipefail

# Non-interactive apt (avoid needrestart / debconf prompts during setup)
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a

DOMAIN="${DOMAIN:?set DOMAIN, e.g. DOMAIN=example.com}"
EMAIL="${EMAIL:?set EMAIL for the TLS certificate, e.g. EMAIL=me@example.com}"
APP_DIR="${APP_DIR:-/opt/drone-flight-report}"
SERVICE="drone-report"
PORT="${PORT:-8080}"

echo "==> Installing system packages"
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

echo "==> Setting up app in $APP_DIR"
mkdir -p "$APP_DIR"
# Copy sources only when we're not already inside APP_DIR (avoids "same file" error)
if [ "$(pwd -P)" != "$(cd "$APP_DIR" && pwd -P)" ]; then
    cp app.py wsgi.py requirements.txt "$APP_DIR"/
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

mkdir -p "$APP_DIR/generated" "$APP_DIR/data/logs"

echo "==> Installing systemd service"
cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=Drone Flight Report
After=network.target

[Service]
WorkingDirectory=${APP_DIR}
Environment=PORT=${PORT}
Environment=DEBUG=0
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/wsgi.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${SERVICE}"

echo "==> Configuring nginx"
cat > "/etc/nginx/sites-available/${SERVICE}" <<EOF
server {
    listen 80;
    server_name ${DOMAIN} www.${DOMAIN};

    client_max_body_size 110M;

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
EOF

ln -sf "/etc/nginx/sites-available/${SERVICE}" "/etc/nginx/sites-enabled/${SERVICE}"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "==> Requesting HTTPS certificate"
certbot --nginx -d "${DOMAIN}" -d "www.${DOMAIN}" \
    --non-interactive --agree-tos -m "${EMAIL}" --redirect || \
    echo "!! certbot failed — make sure DNS points here, then re-run: certbot --nginx -d ${DOMAIN}"

echo
echo "Done.  https://${DOMAIN}"
echo "Logs:  journalctl -u ${SERVICE} -f"
