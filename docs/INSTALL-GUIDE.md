# Hyperliquid Trading Bot — Setup Guide

## Prerequisites

1. **Git** — https://git-scm.com/downloads (Mac: `brew install git`, Linux: `sudo apt install git`)
2. **Python 3.11+** — https://python.org (Windows: check "Add Python to PATH" during install)
3. **VPN** — connected to South Africa or Mexico (Hyperliquid blocks US IPs)
4. **Hyperliquid account** with USDC deposited + API agent wallet (generate at app.hyperliquid.xyz → Settings → API)

## Installation

### Step 1: Clone the repo

```bash
git clone https://github.com/maadmaax26/hyperliquid-trading-kit.git
cd hyperliquid-trading-kit
```

### Step 2: Run the installer

**Linux / macOS:**
```bash
chmod +x setup.sh
./setup.sh
```

**Windows:** Open `docs/PLATFORM-SETUP.md` and follow the Windows section — it has step-by-step instructions for venv creation and NSSM service setup.

### Step 3: Add your wallet details

```bash
nano scalper/.env
nano market-maker/.env
```

Fill in:
```
HL_PRIVATE_KEY=0xYOUR_API_AGENT_PRIVATE_KEY
PARENT_ADDRESS=0xYOUR_PARENT_WALLET_ADDRESS
USE_MAINNET=true
```

### Step 4: Start your VPN

Hyperliquid blocks US IP addresses. Connect to a non-US server (South Africa or Mexico work well).

Verify your connection:
```bash
curl -s ifconfig.me    # Must show a non-US IP
```

### Step 5: Test the bots

```bash
# Linux / macOS
scalper/venv/bin/python scalper/main.py
market-maker/venv/bin/python market-maker/mm_bot.py

# Windows
scalper\venv\Scripts\python.exe scalper\main.py
market-maker\venv\Scripts\python.exe market-maker\mm_bot.py
```

Press Ctrl+C to stop.

### Step 6: Start as background services

**Linux (systemd):**
```bash
systemctl --user start hl-scalper-bot hl-mm-bot hl-status.timer
```

**macOS (launchd):**
See `docs/PLATFORM-SETUP.md` — launchd plist templates included.

**Windows (NSSM):**
See `docs/PLATFORM-SETUP.md` — NSSM service setup instructions included.

### Step 7: Run backtests (optional)

See how the strategies perform on 6 months of historical data:

```bash
market-maker/venv/bin/python simulator/backtest_scalper.py
market-maker/venv/bin/python simulator/backtest_mm.py
market-maker/venv/bin/python simulator/coin_optimizer.py
```

### Step 8: Monitor

```bash
# One-shot status report
market-maker/venv/bin/python monitor/hl_status.py

# Performance monitor with drawdown alerts
market-maker/venv/bin/python monitor/hl_monitor.py

# Watch mode (refreshes every 30s)
market-maker/venv/bin/python monitor/hl_status.py --watch
```

## Documentation

- **Full README:** `docs/README.md` — strategy details, configuration, fee structure
- **Platform setup:** `docs/PLATFORM-SETUP.md` — Windows, macOS, VPN instructions
- **Config tuning:** `docs/README.md` → Configuration section — how to change coins, TP/SL, sizes

## Managing the Bots

**Linux:**
```bash
# Check status
systemctl --user status hl-scalper-bot hl-mm-bot

# View logs
journalctl --user -u hl-scalper-bot -f
journalctl --user -u hl-mm-bot -f

# Restart
systemctl --user restart hl-scalper-bot hl-mm-bot

# Stop
systemctl --user stop hl-scalper-bot hl-mm-bot
```

**macOS:**
```bash
# Check status
launchctl list | grep hl

# View logs
tail -f ~/hyperliquid-scalper.log
tail -f ~/hyperliquid-mm.log

# Restart
launchctl unload ~/Library/LaunchAgents/com.hl.scalper.plist
launchctl load ~/Library/LaunchAgents/com.hl.scalper.plist
```

**Windows (NSSM):**
```powershell
nssm status HL-Scalper-Bot
nssm restart HL-Scalper-Bot
nssm stop HL-Scalper-Bot
```

## Support

- GitHub repo: https://github.com/maadmaax26/hyperliquid-trading-kit
- Report issues: https://github.com/maadmaax26/hyperliquid-trading-kit/issues

## Safety Notes

- Start with $50-100 to test before scaling up
- Both bots share one account — they MUST trade non-overlapping coins
- Backtests are optimistic — real fills are lower due to slippage and queue position
- Never trade money you can't afford to lose