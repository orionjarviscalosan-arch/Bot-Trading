#!/bin/bash
# Instala el servicio systemd para Ubuntu 24.04
set -e

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BOT_USER="${SUDO_USER:-$USER}"
SERVICE_FILE="/etc/systemd/system/nextwaves-bot.service"

if [ "$EUID" -ne 0 ]; then
    echo "Ejecuta con sudo: sudo bash deploy/install-service.sh"
    exit 1
fi

sed -e "s|REPLACE_USER|${BOT_USER}|g" \
    -e "s|REPLACE_PATH|${BOT_DIR}|g" \
    "${BOT_DIR}/deploy/nextwaves-bot.service" > "${SERVICE_FILE}"

systemctl daemon-reload
systemctl enable nextwaves-bot
echo ""
echo "Servicio instalado. Comandos útiles:"
echo "  sudo systemctl start nextwaves-bot"
echo "  sudo systemctl status nextwaves-bot"
echo "  journalctl -u nextwaves-bot -f"
