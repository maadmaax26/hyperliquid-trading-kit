# Hyperliquid Trading Bot — Quick Install Guide

**New here?** Use the full step-by-step guide for your platform:

| Platform | Full Guide |
|----------|-----------|
| 🪟 Windows PC | [WINDOWS-SETUP.md](WINDOWS-SETUP.md) — 12 steps, start to finish |
| 🍎 macOS | [PLATFORM-SETUP.md](PLATFORM-SETUP.md#1-macos-setup) — 10 steps |
| 🐧 Linux / WSL | [PLATFORM-SETUP.md](PLATFORM-SETUP.md#2-linux-setup-ubuntudebian) — 10 steps |
| 🤖 Hermes + Telegram | [HERMES-SETUP.md](HERMES-SETUP.md) — install, connect, monitoring |

Below is a condensed reference for all platforms.

---

## Prerequisites

1. **Git** — https://git-scm.com/downloads
2. **Python 3.11+** — https://python.org (Windows: check "Add Python to PATH")
3. **VPN** — connected to South Africa or Mexico (Hyperliquid blocks US IPs)
4. **Hyperliquid account** with USDC deposited + API agent wallet (app.hyperliquid.xyz → Settings → API)

## Installation

### Step 1: Clone the repo

```bash
git clone https://github.com/maadmaax26/hyperliquid-trading-kit.git
cd hyperliquid-trading-kit
```

### Step 2: Create virtual environments

**Linux / macOS:**
```bash
cd scalper
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
cd ..

cd market-maker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
cd ..
```

**Windows (PowerShell):**
```powershell
cd scalper
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
deactivate
cd ..

cd market-maker
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
deactivate
cd ..
```

### Step 3: Configure .env files

```bash
# Linux / macOS
cp scalper/.env.example scalper/.env
cp market-maker/.env.example market-maker/.env
nano scalper/.env
nano market-maker/.env
```

```powershell
# Windows
copy scalper\.env.example scalper\.env
copy market-maker\.env.example market-maker\.env
notepad scalper\.env
notepad market-maker\.env
```

Fill in:
```
HL_PRIVATE_KEY=0xYOUR_API_AGENT_PRIVATE_KEY
PARENT_ADDRESS=0xYOUR_PARENT_WALLET_ADDRESS
USE_MAINNET=true
```

### Step 4: Start VPN and verify

```bash
curl -s ifconfig.me    # Must show a non-US IP
curl -s https://api.hyperliquid.xyz/info -X POST -H "Content-Type: application/json" -d '{"type":"clearAllMids"}' | head -c 100
```

### Step 5: Test the bots

**Linux / macOS:**
```bash
scalper/venv/bin/python scalper/main.py        # Ctrl+C to stop
market-maker/venv/bin/python market-maker/mm_bot.py  # Ctrl+C to stop
```

**Windows:**
```powershell
.\scalper\venv\Scripts\python.exe scalper\main.py
.\market-maker\venv\Scripts\python.exe market-maker\mm_bot.py
```

### Step 6: Start as background services

**Linux (systemd):**
```bash
chmod +x setup.sh
./setup.sh
systemctl --user start hl-scalper-bot hl-mm-bot
```

**macOS (launchd):**
See [PLATFORM-SETUP.md](PLATFORM-SETUP.md#step-8-run-as-background-services-macos-launchd) for launchd plist templates.

**Windows (NSSM):**
See [WINDOWS-SETUP.md](WINDOWS-SETUP.md#step-9-install-bots-as-windows-services) for complete NSSM setup.

### Step 7: Install Hermes + set up monitoring

See [HERMES-SETUP.md](HERMES-SETUP.md) for full instructions. Summary:

1. Install Hermes from https://hermes-agent.nousresearch.com
2. Run `hermes setup` → configure LLM provider
3. Run `hermes gateway setup` → connect Telegram
4. Create monitoring cron job (runs every 30 min):

```bash
hermes cron create \
  --name "HL Performance Monitor" \
  --schedule "30m" \
  --deliver origin \
  --prompt "Run the hl_monitor.py script and report equity, per-bot P&L, and alerts"
```

### Step 8: Run backtests (optional)

```bash
market-maker/venv/bin/python simulator/backtest_scalper.py
market-maker/venv/bin/python simulator/backtest_mm.py
market-maker/venv/bin/python simulator/coin_optimizer.py
```

## Managing the Bots

**Linux:**
```bash
systemctl --user status hl-scalper-bot hl-mm-bot
journalctl --user -u hl-scalper-bot -f
systemctl --user restart hl-scalper-bot hl-mm-bot
systemctl --user stop hl-scalper-bot hl-mm-bot
```

**macOS:**
```bash
launchctl list | grep hl
tail -f ~/hyperliquid-scalper.log
launchctl unload ~/Library/LaunchAgents/com.hl.scalper.plist
launchctl load ~/Library/LaunchAgents/com.hl.scalper.plist
```

**Windows:**
```powershell
nssm status HL-Scalper-Bot
nssm status HL-MM-Bot
Get-Content C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\bot.log -Tail 20
nssm restart HL-Scalper-Bot
nssm restart HL-MM-Bot
nssm stop HL-Scalper-Bot
nssm stop HL-MM-Bot
```

## Documentation Index

| Document | Contents |
|----------|---------|
| [README.md](README.md) | Full strategy overview, architecture, configuration reference |
| [WINDOWS-SETUP.md](WINDOWS-SETUP.md) | Complete Windows PC setup — 12 steps from zero to running |
| [PLATFORM-SETUP.md](PLATFORM-SETUP.md) | macOS (10 steps) + Linux (10 steps) setup guides |
| [HERMES-SETUP.md](HERMES-SETUP.md) | Hermes Agent install, Telegram bot connection, 30-min monitoring cron job |
| [This file](INSTALL-GUIDE.md) | Quick reference for all platforms |

## Safety Notes

- Start with $50-100 to test before scaling up
- Both bots share one account — they MUST trade non-overlapping coins
- Backtests are optimistic — real fills are lower due to slippage
- Never trade money you can't afford to lose

## Support

- GitHub: https://github.com/maadmaax26/hyperliquid-trading-kit
- Issues: https://github.com/maadmaax26/hyperliquid-trading-kit/issues
- Hermes Docs: https://hermes-agent.nousresearch.com/docs