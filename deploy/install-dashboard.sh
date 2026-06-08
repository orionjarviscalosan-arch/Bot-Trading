#!/bin/bash
# Instala el servicio systemd del dashboard Streamlit
set -e

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BOT_USER="${SUDO_USER:-$USER}"
SERVICE_FILE="/etc/systemd/system/nextwaves-dashboard.service"
PORT="${DASHBOARD_PORT:-8501}"

if [ "$EUID" -ne 0 ]; then
    echo "Ejecuta con sudo: sudo bash deploy/install-dashboard.sh"
    exit 1
fi

sed -e "s|REPLACE_USER|${BOT_USER}|g" \
    -e "s|REPLACE_PATH|${BOT_DIR}|g" \
    -e "s|--server.port 8501|--server.port ${PORT}|g" \
    "${BOT_DIR}/deploy/nextwaves-dashboard.service" > "${SERVICE_FILE}"

systemctl daemon-reload
systemctl enable nextwaves-dashboard
echo ""
echo "Dashboard instalado (solo localhost:${PORT})."
echo ""
echo "  sudo systemctl start nextwaves-dashboard"
echo "  journalctl -u nextwaves-dashboard -f"
echo ""
echo "Acceso desde tu PC (túnel SSH — recomendado):"
echo "  ssh -L ${PORT}:127.0.0.1:${PORT} ${BOT_USER}@TU_IP_VPS"
echo "  Luego abre: http://localhost:${PORT}"
