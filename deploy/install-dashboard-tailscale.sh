#!/bin/bash
# Dashboard accesible solo vía Tailscale (PC + móvil)
# Requiere DASHBOARD_PASSWORD en .env
set -e

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BOT_USER="${SUDO_USER:-$USER}"
SERVICE_FILE="/etc/systemd/system/nextwaves-dashboard.service"
ENV_FILE="${BOT_DIR}/.env"
PORT="8501"
ADDRESS="0.0.0.0"

if [ "$EUID" -ne 0 ]; then
    echo "Ejecuta con sudo: sudo bash deploy/install-dashboard-tailscale.sh"
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: No existe ${ENV_FILE}"
    exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE" 2>/dev/null || true
PORT="${DASHBOARD_PORT:-8501}"

if [ -z "${DASHBOARD_PASSWORD}" ]; then
    echo "ERROR: Debes definir DASHBOARD_PASSWORD en ${ENV_FILE}"
    echo "Ejemplo: DASHBOARD_PASSWORD=MiClaveSegura2026"
    exit 1
fi

echo "=== 1/4 Tailscale ==="
if ! command -v tailscale &>/dev/null; then
    echo "Instalando Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
else
    echo "Tailscale ya instalado."
fi

if ! tailscale status &>/dev/null; then
    echo ""
    echo "Conecta el VPS a tu red Tailscale:"
    echo "  sudo tailscale up"
    echo ""
    echo "Abre el enlace que aparece, inicia sesión y vuelve a ejecutar este script."
    exit 1
fi

TS_IP=$(tailscale ip -4 2>/dev/null || true)
if [ -z "$TS_IP" ]; then
    echo "ERROR: No se obtuvo IP Tailscale. Ejecuta: sudo tailscale up"
    exit 1
fi

echo "IP Tailscale del VPS: ${TS_IP}"

echo ""
echo "=== 2/4 Firewall (solo red Tailscale) ==="
if command -v ufw &>/dev/null; then
    ufw allow OpenSSH comment 'SSH' 2>/dev/null || true
    # Eliminar regla abierta previa si existía
    ufw delete allow "${PORT}/tcp" 2>/dev/null || true
    # Solo tráfico desde la red Tailscale (100.64.0.0/10)
    ufw allow from 100.64.0.0/10 to any port "${PORT}" proto tcp comment 'Nextwaves dashboard Tailscale'
    ufw --force enable 2>/dev/null || true
    echo "UFW: puerto ${PORT} permitido solo desde 100.64.0.0/10 (Tailscale)"
else
    echo "AVISO: ufw no instalado. Instala con: sudo apt install ufw"
fi

echo ""
echo "=== 3/4 Servicio dashboard ==="
sed -e "s|REPLACE_USER|${BOT_USER}|g" \
    -e "s|REPLACE_PATH|${BOT_DIR}|g" \
    -e "s|SERVER_ADDRESS|${ADDRESS}|g" \
    -e "s|SERVER_PORT|${PORT}|g" \
    "${BOT_DIR}/deploy/nextwaves-dashboard.service" > "${SERVICE_FILE}"

systemctl daemon-reload
systemctl enable nextwaves-dashboard
systemctl restart nextwaves-dashboard

echo ""
echo "=== 4/4 Comprobar ==="
sleep 2
if systemctl is-active --quiet nextwaves-dashboard; then
    echo "Dashboard: activo"
else
    echo "ERROR: el dashboard no arrancó. Revisa:"
    echo "  journalctl -u nextwaves-dashboard -n 30"
    exit 1
fi

echo ""
echo "============================================"
echo "  LISTO — Acceso PC y móvil vía Tailscale"
echo "============================================"
echo ""
echo "1. Instala Tailscale en tu PC y móvil (misma cuenta):"
echo "   https://tailscale.com/download"
echo ""
echo "2. Activa Tailscale en el dispositivo (toggle ON)"
echo ""
echo "3. Abre en el navegador (PC o móvil):"
echo ""
echo "   http://${TS_IP}:${PORT}"
echo ""
echo "4. Introduce la contraseña de DASHBOARD_PASSWORD del .env"
echo ""
echo "NOTA: No uses la IP pública del VPS — solo funciona con Tailscale conectado."
