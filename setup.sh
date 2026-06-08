#!/bin/bash
# setup.sh — Instalación en VPS Ubuntu 24.04
# Ejecutar como: bash setup.sh

set -e
echo "=== Nextwaves Bot — Setup VPS (Ubuntu 24.04) ==="

sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git sqlite3

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data

if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANTE: Edita el archivo .env con tus credenciales:"
    echo "   nano .env"
fi

echo ""
echo "=== Setup completo ==="
echo ""
echo "Pasos siguientes:"
echo "1. Edita .env — BOT_MODE=shadow para empezar sin dinero real"
echo "2. Prueba manual: source venv/bin/activate && python main.py"
echo "3. Instala servicio systemd (recomendado para 24/7):"
echo "   sudo bash deploy/install-service.sh"
echo "4. Ver logs: tail -f data/bot.log"
echo "   o: journalctl -u nextwaves-bot -f"
echo ""
echo "NUNCA pongas BOT_MODE=live sin al menos 4 semanas de shadow trading"
