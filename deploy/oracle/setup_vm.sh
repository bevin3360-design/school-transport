#!/usr/bin/env bash
# One-time provisioning for a fresh Oracle Cloud Ubuntu 24.04 VM.
# Idempotent: safe to re-run after editing settings.
#
#   sudo bash /opt/school-transport/deploy/oracle/setup_vm.sh [domain]
#
# Without a domain it uses <public-ip-with-dashes>.sslip.io, which gets a real
# Let's Encrypt certificate via Caddy.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/bevin3360-design/school-transport.git}"
APP_DIR=/opt/school-transport
SERVICE_USER=sts
ENV_FILE=/etc/sts/sts.env

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

DOMAIN="${1:-${DOMAIN:-}}"
DOMAIN="${DOMAIN#https://}"
DOMAIN="${DOMAIN#http://}"
DOMAIN="${DOMAIN%%/*}"

if [ -z "$DOMAIN" ]; then
    PUBLIC_IP=$(curl -4 -fsS --max-time 10 https://api.ipify.org \
        || curl -4 -fsS --max-time 10 https://ifconfig.me \
        || true)
    if [ -z "$PUBLIC_IP" ]; then
        echo "Could not detect the public IP. Pass the host name: sudo bash $0 your.domain" >&2
        exit 1
    fi
    DOMAIN="${PUBLIC_IP//./-}.sslip.io"
fi

echo "==> Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    git python3 python3-venv curl gpg ca-certificates openssl \
    iptables iptables-persistent

if ! command -v caddy >/dev/null 2>&1; then
    echo "==> Installing Caddy"
    apt-get install -y --no-install-recommends debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
fi

echo "==> Creating service user"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "==> Fetching code"
if [ ! -d "$APP_DIR/.git" ]; then
    git clone --depth 1 "$REPO_URL" "$APP_DIR"
else
    git -C "$APP_DIR" fetch --depth 1 origin main
    git -C "$APP_DIR" reset --hard FETCH_HEAD
fi
chown -R root:root "$APP_DIR"
chmod -R o+rX "$APP_DIR"

echo "==> Building Python environment"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/sts-platform/requirements.txt"

install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$APP_DIR/sts-platform/instance"

echo "==> Writing $ENV_FILE"
install -d -m 750 /etc/sts
if [ ! -f "$ENV_FILE" ]; then
    (
        umask 077
        {
            echo "# Values for the app. Keep this file private; never commit it."
            echo "PORT=8000"
            echo "STS_COOKIE_SECURE=1"
            echo "SECRET_KEY=$(openssl rand -hex 32)"
            echo "DATABASE_URL="
        } > "$ENV_FILE"
    )
    chmod 600 "$ENV_FILE"
    echo "    Created with a generated SECRET_KEY. Add DATABASE_URL before starting."
else
    echo "    Already exists; leaving it untouched."
fi

echo "==> Installing systemd unit"
install -m 644 "$APP_DIR/deploy/oracle/sts.service" /etc/systemd/system/sts.service
systemctl daemon-reload
systemctl enable sts >/dev/null

echo "==> Opening ports 80 and 443 in the instance firewall"
iptables -C INPUT -p tcp --dport 8000 -j DROP 2>/dev/null \
    || iptables -I INPUT 1 -p tcp --dport 8000 -j DROP
for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
        || iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
    if command -v ip6tables >/dev/null 2>&1; then
        ip6tables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
            || ip6tables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
    fi
done
netfilter-persistent save >/dev/null
if [ ! -s /etc/iptables/rules.v4 ]; then
    echo "WARNING: firewall rules were not persisted; rerun netfilter-persistent save." >&2
fi

echo "==> Configuring Caddy for $DOMAIN"
sed "s/__DOMAIN__/$DOMAIN/" "$APP_DIR/deploy/oracle/Caddyfile" > /etc/caddy/Caddyfile
systemctl enable caddy >/dev/null
systemctl restart caddy

cat <<EOF

Done. HTTPS host: https://$DOMAIN

Remaining steps:
  1. sudo nano $ENV_FILE
       paste DATABASE_URL="..." on the last line, save
  2. sudo systemctl start sts
  3. sudo journalctl -u sts -f
       expect: scheme=postgresql ... and "Listening at: http://0.0.0.0:8000"
  4. curl -I https://$DOMAIN/

App logs:   sudo journalctl -u sts -n 200
Proxy logs: sudo journalctl -u caddy -n 100
EOF
