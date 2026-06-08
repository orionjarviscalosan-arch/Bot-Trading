# Nextwaves Bot — Guía completa

Bot autónomo de trading para BTC/USDT Spot en Binance.
Basado en la suite completa de 8 indicadores Nextwaves v7.

---

## Arquitectura

```
main.py                  Orquestador + scheduler
├── signal_engine.py     5 pilares de confluencia (réplica Pine Script)
├── order_manager.py     Órdenes Binance Spot (BUY/SELL)
├── risk_manager.py      Kill switch, posición máxima, pérdidas consecutivas
├── shadow_trader.py     Paper trading paralelo (siempre activo)
├── optimizer.py         Auto-optimización cada 30 días
├── telegram_notifier.py Notificaciones en tiempo real
└── database.py          SQLite — registro de todo
```

---

## Instalación en VPS

```bash
# 1. Clonar / subir el proyecto
git clone <tu-repo> nextwaves-bot
cd nextwaves-bot

# 2. Ejecutar setup
bash setup.sh

# 3. Configurar credenciales
nano .env
```

### Variables en .env

```env
BINANCE_API_KEY=...      # Solo permisos de TRADING, nunca retiro
BINANCE_API_SECRET=...
TELEGRAM_TOKEN=...       # @BotFather para crear el bot
TELEGRAM_CHAT_ID=...     # Tu user ID (@userinfobot)
BOT_MODE=shadow          # SIEMPRE shadow primero
SYMBOL=BTC/USDT
TIMEFRAME=4h
MAX_CAPITAL_USDT=1000.0
```

### Crear API Key en Binance

1. Binance → Perfil → Gestión de API
2. Crear nueva API key (tipo: Sistema)
3. Permisos: SOLO activar "Trading Spot y Margen"
4. **NUNCA activar "Retiro"**
5. Restringir IP a la IP de tu VPS

---

## Fases de despliegue

### Fase 1 — Shadow (semanas 1-4)
```env
BOT_MODE=shadow
```
El bot calcula todo y registra operaciones virtuales sin tocar tu dinero.
Verifica que las señales coinciden con el backtest.

**Criterios para pasar a live:**
- ≥ 20 trades en shadow
- Win Rate ≥ 45%
- Profit Factor ≥ 1.4
- Sin inconsistencias vs backtest

### Fase 2 — Live con capital mínimo (semanas 5-12)
```env
BOT_MODE=live
MAX_CAPITAL_USDT=200.0   # Empieza con poco
```

### Fase 3 — Capital completo
Solo cuando la Fase 2 confirma los resultados del shadow.

---

## Arranque y gestión

### Opción recomendada — systemd (24/7, reinicio automático)

```bash
source venv/bin/activate
# Probar primero en foreground
python main.py

# Instalar servicio (Ubuntu 24.04)
sudo bash deploy/install-service.sh
sudo systemctl start nextwaves-bot
sudo systemctl status nextwaves-bot

# Logs en vivo
journalctl -u nextwaves-bot -f
tail -f data/bot.log
```

### Opción alternativa — screen

```bash
source venv/bin/activate
screen -S nextwaves python main.py
# Ctrl+A, D para desconectar
screen -r nextwaves
tail -f data/bot.log
```

---

## Auto-optimización

Cada 30 días (job programado a las 03:00 UTC) el bot:
1. Descarga datos históricos
2. Hace grid search sobre los parámetros clave
3. Guarda el mejor candidato si supera al set activo en backtest
4. Tras 14 días de evaluación, promueve si mejora Calmar y PF
5. Te notifica por Telegram

La optimización **no se ejecuta en el primer arranque** — espera 30 días.

---

## Kill Switch

El bot para automáticamente si:
- Drawdown total ≥ 15%
- Pérdida en un día ≥ 5%
- 5 pérdidas consecutivas (pausa 24h)

Recibirás notificación en Telegram y deberás revisar manualmente.

---

## Monitoreo de base de datos

```bash
# Ver últimos trades
sqlite3 data/nextwaves_bot.db \
  "SELECT mode, entry_price, exit_price, pnl_usdt, exit_reason FROM trades ORDER BY id DESC LIMIT 10;"

# Métricas shadow
sqlite3 data/nextwaves_bot.db \
  "SELECT COUNT(*), AVG(pnl_usdt), MIN(pnl_usdt), MAX(pnl_usdt) FROM trades WHERE mode='shadow';"

# Parámetros activos
sqlite3 data/nextwaves_bot.db \
  "SELECT params FROM param_sets WHERE active=1;"
```

---

## ⚠️ Advertencias importantes

1. **Empieza siempre en shadow** — mínimo 4 semanas
2. **Nunca arriesgues dinero que no puedas perder**
3. **El backtest no garantiza resultados futuros**
4. Las API keys con solo permiso de trading no pueden retirar fondos
5. Mantén el VPS actualizado y monitorizado
6. El bot opera en 4H — no es necesario revisar cada minuto
