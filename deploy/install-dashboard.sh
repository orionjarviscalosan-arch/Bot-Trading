#!/bin/bash
# Instala el dashboard Streamlit (solo localhost — acceso vía túnel SSH)
set -e

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BOT_USER="${SUDO_USER:-$USER}"
SERVICE_FILE="/etc/systemd/system/nextwaves-dashboard.service"
ENV_FILE="${BOT_DIR}/.env"
PORT="8501"
ADDRESS="127.0.0.1"

if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE" 2>/dev/null || true
    PORT="${DASHBOARD_PORT:-8501}"
fi

if [ "$EUID" -ne 0 ]; then
    echo "Ejecuta con sudo: sudo bash deploy/install-dashboard.sh"
    exit 1
fi

sed -e "s|REPLACE_USER|${BOT_USER}|g" \
    -e "s|REPLACE_PATH|${BOT_DIR}|g" \
    -e "s|SERVER_ADDRESS|${ADDRESS}|g" \
    -e "s|SERVER_PORT|${PORT}|g" \
    "${BOT_DIR}/deploy/nextwaves-dashboard.service" > "${SERVICE_FILE}"

systemctl daemon-reload
systemctl enable nextwaves-dashboard
echo ""
echo "Dashboard instalado (localhost:${PORT})."
echo ""
echo "  sudo systemctl start nextwaves-dashboard"
echo ""
echo "Acceso PC — túnel SSH:"
echo "  ssh -L ${PORT}:127.0.0.1:${PORT} ${BOT_USER}@TU_IP_VPS"
echo "  http://localhost:${PORT}"
echo ""
echo "Para PC + móvil usa Tailscale:"
echo "  sudo bash deploy/install-dashboard-tailscale.sh"
