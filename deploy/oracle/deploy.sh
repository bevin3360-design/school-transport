#!/usr/bin/env bash
# Deploy the latest main branch to this VM: pull, install deps, restart.
#   sudo bash /opt/school-transport/deploy/oracle/deploy.sh
set -euo pipefail

APP_DIR=/opt/school-transport

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

cd "$APP_DIR"
git fetch --depth 1 origin main
git reset --hard FETCH_HEAD
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/sts-platform/requirements.txt"
systemctl restart sts

if systemctl is-active --quiet sts; then
    echo "Running $(git rev-parse --short HEAD) on $(hostname)."
else
    echo "Service failed to start; last log lines:" >&2
    journalctl -u sts --no-pager -n 60 >&2
    exit 1
fi
