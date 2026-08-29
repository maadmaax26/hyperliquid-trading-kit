# macOS & Linux Setup Guide

This guide covers installing and running the Hyperliquid Trading Bot Kit on:
1. **macOS** (with VPN requirement for Hyperliquid access)
2. **Linux** (Ubuntu/Debian, also works for WSL)

For **Windows PC**, see `WINDOWS-SETUP.md` — a dedicated 12-step walkthrough.

---

## ⚠️ VPN Requirement (Read First)

**Hyperliquid restricts access for US residents.** Their Terms of Use (Section 1.5) block the trading interface from US IP addresses. Before running the bots, you MUST:

1. **Install and activate a VPN** connected to a non-US server
2. Recommended server locations: **South Africa** or **Mexico** (low latency, reliable)
3. The VPN must be running BEFORE the bot connects to Hyperliquid APIs
4. If the VPN drops, the bot will get API errors — use a kill switch if available
5. Verify your IP before starting: `curl -s ifconfig.me` should show a non-US IP

**Test the connection first:**
```bash
# With VPN active, verify HL API is reachable
curl -s https://api.hyperliquid.xyz/info -X POST -H "Content-Type: application/json" -d '{"type":"clearAllMids"}' | head -c 100
# Should return JSON with prices, not an error
```

---

## 1. macOS Setup

### Prerequisites

- **macOS 12+** (Monterey or newer)
- **Python 3.11+** — install via Homebrew
- **Hermes Agent** — CLI or desktop app
- **VPN** connected to South Africa or Mexico server (Hyperliquid blocks US IPs)
- **Hyperliquid account** with USDC deposited + API agent wallet

### Step 1: Install Homebrew + Python

```bash
# Install Homebrew if not present
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.12 and tools
brew install python@3.12 git curl

# Verify
python3 --version
# Should show: Python 3.12.x
```

### Step 2: Install Hermes Agent

```bash
# Install Hermes Agent
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# Run setup wizard
hermes setup
hermes model    # Configure LLM provider (OpenRouter recommended — free models available)

# Launch desktop app (optional)
hermes desktop
```

### Step 3: Clone the Trading Bot Kit

```bash
cd ~/
git clone https://github.com/maadmaax26/hyperliquid-trading-kit.git
cd hyperliquid-trading-kit
```

### Step 4: Create Virtual Environments

```bash
# === Scalper venv ===
cd scalper
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
cd ..

# === Market Maker venv ===
cd market-maker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
cd ..
```

### Step 5: Configure .env Files

```bash
cp scalper/.env.example scalper/.env
cp market-maker/.env.example market-maker/.env

# Edit with your wallet details
nano scalper/.env
nano market-maker/.env
```

Fill in:
```
HL_PRIVATE_KEY=0xYOUR_API_AGENT_PRIVATE_KEY
PARENT_ADDRESS=0xYOUR_PARENT_WALLET_ADDRESS
USE_MAINNET=true
```

### Step 6: Start VPN

```bash
# Start your VPN — connect to South Africa or Mexico
# Verify non-US IP:
curl -s ifconfig.me
# Should show a non-US IP address

# Test HL API connectivity:
curl -s https://api.hyperliquid.xyz/info -X POST -H "Content-Type: application/json" -d '{"type":"clearAllMids"}' | head -c 100
```

**VPN options for macOS:**

| Provider | CLI Connect (South Africa) | CLI Connect (Mexico) | Kill Switch |
|----------|---------------------------|----------------------|-------------|
| Mullvad | `mullvad relay set location za && mullvad connect` | `mullvad relay set location mx && mullvad connect` | ✅ Built-in |
| ExpressVPN | `expressvpn connect "South Africa"` | `expressvpn connect "Mexico"` | ✅ In app |
| ProtonVPN | `protonvpn-cli c --cc ZA` | `protonvpn-cli c --cc MX` | ✅ Kill switch toggle |
| Tailscale | Set up VPS in ZA, `tailscale up --exit-node=<vps-ip>` | Same with MX VPS | ✅ Via Tailscale |

### Step 7: Test the Bots

```bash
# Test scalper
~/hyperliquid-trading-kit/scalper/venv/bin/python ~/hyperliquid-trading-kit/scalper/main.py

# Test MM bot
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/market-maker/mm_bot.py

# Ctrl+C to stop
```

**Scalper should show:**
```
🔗 Connecting to Hyperliquid...
💰 Equity: $XX.XX
📋 Assets: ['BTC', 'ETH', 'SOL', 'XRP', 'ZEC', 'PAXG']
🚀 Scalper started — entering main loop
```

**MM bot should show:**
```
🔗 Connecting to Hyperliquid...
⚙️ kPEPE leverage set to 3x (cross)
⚙️ kBONK leverage set to 3x (cross)
⚙️ ARB leverage set to 3x (cross)
💰 Equity: $XX.XX
📋 Assets: ['kPEPE', 'kBONK', 'ARB']
🚀 Market maker started — entering main loop
📊 kPEPE: NEUTRAL | Bid=✅ Ask=✅ | Orders: 2
```

### Step 8: Run as Background Services (macOS launchd)

macOS uses **launchd** (equivalent to systemd):

**Create the scalper plist:**
```bash
cat > ~/Library/LaunchAgents/com.hl.scalper.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hl.scalper</string>
    <key>ProgramArguments</key>
    <array>
        <string>YOUR_HOME_DIR/hyperliquid-trading-kit/scalper/venv/bin/python</string>
        <string>YOUR_HOME_DIR/hyperliquid-trading-kit/scalper/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>YOUR_HOME_DIR/hyperliquid-trading-kit/scalper</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>YOUR_HOME_DIR/hyperliquid-scalper.log</string>
    <key>StandardErrorPath</key>
    <string>YOUR_HOME_DIR/hyperliquid-scalper.log</string>
</dict>
</plist>
EOF

# Replace YOUR_HOME_DIR with your actual home directory
sed -i '' "s|YOUR_HOME_DIR|$HOME|g" ~/Library/LaunchAgents/com.hl.scalper.plist
```

**Create the MM bot plist:**
```bash
cat > ~/Library/LaunchAgents/com.hl.mmbot.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hl.mmbot</string>
    <key>ProgramArguments</key>
    <array>
        <string>YOUR_HOME_DIR/hyperliquid-trading-kit/market-maker/venv/bin/python</string>
        <string>YOUR_HOME_DIR/hyperliquid-trading-kit/market-maker/mm_bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>YOUR_HOME_DIR/hyperliquid-trading-kit/market-maker</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>YOUR_HOME_DIR/hyperliquid-mm.log</string>
    <key>StandardErrorPath</key>
    <string>YOUR_HOME_DIR/hyperliquid-mm.log</string>
</dict>
</plist>
EOF

sed -i '' "s|YOUR_HOME_DIR|$HOME|g" ~/Library/LaunchAgents/com.hl.mmbot.plist
```

**Load and start:**
```bash
launchctl load ~/Library/LaunchAgents/com.hl.scalper.plist
launchctl load ~/Library/LaunchAgents/com.hl.mmbot.plist

# Check status
launchctl list | grep hl

# View logs
tail -f ~/hyperliquid-scalper.log
tail -f ~/hyperliquid-mm.log

# Stop
launchctl unload ~/Library/LaunchAgents/com.hl.scalper.plist
launchctl unload ~/Library/LaunchAgents/com.hl.mmbot.plist

# Restart
launchctl unload ~/Library/LaunchAgents/com.hl.scalper.plist
launchctl load ~/Library/LaunchAgents/com.hl.scalper.plist
```

### Step 9: Set Up Monitoring with Hermes

```bash
# Create a 30-minute cron job via Hermes
hermes cron create \
  --name "HL Performance Monitor" \
  --schedule "30m" \
  --deliver origin \
  --prompt "Run ~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py and report the results. Report equity, 24h change, per-bot P&L attribution, and any alerts. Keep responses concise. Include recommendations only when alerts are triggered."
```

Or in Hermes Desktop chat:
```
Create a recurring job every 30 minutes that runs:
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py
Report the equity, per-bot P&L, and any alerts to me.
```

**Test the monitor manually:**
```bash
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py
```

### Step 10: Run Backtests

```bash
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/simulator/backtest_scalper.py
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/simulator/backtest_mm.py
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/simulator/coin_optimizer.py
```

### macOS Notes

- macOS may block Python from network access on first run — check **System Settings → Privacy & Security → Network** and allow Python
- If `python3 -m venv` fails, run `brew install python@3.12` (venv is included)
- The `sed -i ''` syntax (with empty string) is macOS-specific — don't use Linux `sed -i` syntax
- **VPN must stay connected at all times** — if it drops, the bots will get connection errors. Use a VPN client with auto-reconnect and kill switch
- For always-on VPN, consider running the VPN on a router level or using a VPS as an exit node via Tailscale

---

## 2. Linux Setup (Ubuntu/Debian)

### Prerequisites

- **Ubuntu 22.04+** or **Debian 12+** (also works in WSL)
- **Python 3.11+**
- **Hermes Agent**
- **VPN** connected to South Africa or Mexico server (if in US)
- **Hyperliquid account** with USDC deposited + API agent wallet

### Step 1: Install Python + Tools

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl

# Verify
python3 --version
# Should show: Python 3.11+ 
```

### Step 2: Install Hermes Agent

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
source ~/.bashrc

# Run setup wizard
hermes setup
hermes model    # Configure LLM provider (OpenRouter recommended)
```

### Step 3: Clone the Trading Bot Kit

```bash
cd ~/
git clone https://github.com/maadmaax26/hyperliquid-trading-kit.git
cd hyperliquid-trading-kit
```

### Step 4: Create Virtual Environments

```bash
# === Scalper venv ===
cd scalper
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
cd ..

# === Market Maker venv ===
cd market-maker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
cd ..
```

### Step 5: Configure .env Files

```bash
cp scalper/.env.example scalper/.env
cp market-maker/.env.example market-maker/.env

nano scalper/.env
nano market-maker/.env
```

Fill in:
```
HL_PRIVATE_KEY=0xYOUR_API_AGENT_PRIVATE_KEY
PARENT_ADDRESS=0xYOUR_PARENT_WALLET_ADDRESS
USE_MAINNET=true
```

### Step 6: Start VPN (if in US)

```bash
# Connect to South Africa or Mexico server
# Verify non-US IP:
curl -s ifconfig.me

# Test HL API:
curl -s https://api.hyperliquid.xyz/info -X POST -H "Content-Type: application/json" -d '{"type":"clearAllMids"}' | head -c 100
```

**VPN options for Linux:**

| Provider | CLI Connect (South Africa) | Kill Switch |
|----------|---------------------------|-------------|
| Mullvad | `mullvad relay set location za && mullvad connect` | ✅ Built-in |
| ProtonVPN | `protonvpn-cli c --cc ZA` | ✅ Toggle |
| OpenVPN | `openvpn --config za.ovpn` | Manual |
| Tailscale | `tailscale up --exit-node=<vps-ip>` | ✅ Via Tailscale |

### Step 7: Test the Bots

```bash
# Test scalper
~/hyperliquid-trading-kit/scalper/venv/bin/python ~/hyperliquid-trading-kit/scalper/main.py

# Test MM bot
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/market-maker/mm_bot.py

# Ctrl+C to stop
```

### Step 8: Run as Background Services (Linux systemd)

Use the `setup.sh` script to install systemd service templates:

```bash
cd ~/hyperliquid-trading-kit
chmod +x setup.sh
./setup.sh
```

Or manually create the services:

**Scalper service (`~/.config/systemd/user/hl-scalper-bot.service`):**
```ini
[Unit]
Description=Hyperliquid Scalper Bot
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/hyperliquid-trading-kit/scalper
ExecStart=%h/hyperliquid-trading-kit/scalper/venv/bin/python %h/hyperliquid-trading-kit/scalper/main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

**MM bot service (`~/.config/systemd/user/hl-mm-bot.service`):**
```ini
[Unit]
Description=Hyperliquid Market Maker Bot
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/hyperliquid-trading-kit/market-maker
ExecStart=%h/hyperliquid-trading-kit/market-maker/venv/bin/python %h/hyperliquid-trading-kit/market-maker/mm_bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

**Enable and start:**
```bash
systemctl --user daemon-reload
systemctl --user enable hl-scalper-bot hl-mm-bot
systemctl --user start hl-scalper-bot hl-mm-bot

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

### Step 9: Set Up Monitoring with Hermes

```bash
# Create a 30-minute cron job
hermes cron create \
  --name "HL Performance Monitor" \
  --schedule "30m" \
  --deliver origin \
  --prompt "Run ~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py and report the results. Report equity, 24h change, per-bot P&L, and any alerts. Keep responses concise."
```

Or in Hermes chat:
```
Create a recurring job every 30 minutes that runs:
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py
Report equity, per-bot P&L, and alerts. Keep it concise.
```

**Test the monitor:**
```bash
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py
```

### Step 10: Run Backtests

```bash
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/simulator/backtest_scalper.py
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/simulator/backtest_mm.py
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/simulator/coin_optimizer.py
```

### Linux Notes

- For **WSSL**: the bots run inside WSL. Hermes Desktop can connect to a WSL backend via the remote backend feature
- If `systemctl --user` doesn't work, run `loginctl enable-linger $USER` to allow user services without a login session
- If Python venv fails, install `python3-venv`: `sudo apt install python3-venv`
- **VPN must stay connected** — if it drops, restart bots after reconnecting: `systemctl --user restart hl-scalper-bot hl-mm-bot`
- For headless servers (no desktop), use Hermes CLI only: `hermes setup` in terminal

---

## Strategy Overview (V6 — August 2026)

### Scalper Bot

The scalper trades 6 coins on 5-minute candles using a **dual signal engine**:

| Signal Type | When It Fires | Best Market |
|-------------|---------------|-------------|
| **Multi-Confluence** | RSI + EMA cross + MACD + Bollinger Bands align | Ranging / choppy markets |
| **Momentum Breakout** (V6) | ADX >25 + EMA9 > EMA21 + MACD histogram rising | Strong trends / breakouts |

**Per-coin optimized parameters:**

| Coin | Take Profit | Stop Loss | Trail Activate | Trail Stop | Win Rate | Profit Factor |
|------|------------|-----------|----------------|------------|----------|---------------|
| BTC | 0.21% | 0.25% | 0.15% | 0.04% | 81.3% | 3.44 |
| ETH | 0.25% | 0.30% | 0.17% | 0.04% | 76.3% | 2.85 |
| SOL | 0.30% | 0.40% | 0.23% | 0.06% | 73.5% | 2.44 |
| XRP | 0.23% | 0.25% | 0.17% | 0.04% | 78.8% | 4.73 |
| ZEC | 0.28% | 0.30% | 0.20% | 0.06% | 79.7% | 5.60 |

Additional filters:
- **Volatility regime gate** — skips dead markets (ATR < threshold)
- **1h trend filter** — blocks counter-trend entries (±0.3% from EMA50)
- **Daily loss limit** — stops trading at 4% daily drawdown
- **Max 3 concurrent positions**
- **Cooldown** — 300s between trades on same coin (ZEC)

### Market Maker Bot

Two-sided quoting on 3 coins, capturing spread + maker rebates:

| Coin | Half-Spread | Order Size | Max Inventory | Leverage |
|------|------------|------------|---------------|----------|
| kPEPE | 0.10% | 4% equity | 12% equity | 3x |
| kBONK | 0.12% | 4% equity | 12% equity | 3x |
| ARB | 0.12% | 4% equity | 12% equity | 3x |

Safety mechanisms:
- **Forced unwind** — market-closes positions exceeding 150% of inventory cap
- **Inventory cap at 80%** — stops adding to position at 80% (not 95%)
- **ADX >40 skip** — stops quoting in strong trends (adverse selection)
- **Volume filter** — skips coins with <0.5x average volume
- **Daily loss limit** — 4% drawdown stops trading for the day

### Hyperliquid Fee Structure

| Order Type | Fee | Rebate |
|------------|-----|--------|
| Taker (market) | 0.035% | — |
| Maker (limit) | 0.010% | -0.003% (rebate) |

The MM bot earns **0.003% net rebate** per filled maker order. The scalper pays 0.035% taker fee per entry/exit.

---

## VPN Quick Reference

| Provider | CLI Connect (South Africa) | CLI Connect (Mexico) | Kill Switch |
|----------|---------------------------|----------------------|-------------|
| Mullvad | `mullvad relay set location za && mullvad connect` | `mullvad relay set location mx && mullvad connect` | ✅ Built-in |
| ExpressVPN | `expressvpn connect "South Africa"` | `expressvpn connect "Mexico"` | ✅ In app |
| ProtonVPN | `protonvpn-cli c --cc ZA` | `protonvpn-cli c --cc MX` | ✅ Kill switch toggle |
| Tailscale exit node | Set up VPS in ZA, `tailscale up --exit-node=<vps-ip>` | Same with MX VPS | ✅ Via Tailscale |

Always verify before starting bots:
```bash
curl -s ifconfig.me  # Must show non-US IP
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python3: command not found` | macOS: `brew install python@3.12` / Linux: `sudo apt install python3` |
| `venv creation fails` | Install venv: `sudo apt install python3-venv` (Linux) or `brew install python@3.12` (macOS) |
| Connection refused / API errors | VPN not connected or using US server — reconnect to ZA/MX |
| `insufficient margin` | Need more USDC in Hyperliquid account ($50+ minimum) |
| `.env` not loading | Check file is named `.env` (no `.txt` extension), UTF-8 encoded |
| `hermes: command not found` | Run `source ~/.bashrc` or restart terminal |
| No Telegram response | Run `hermes gateway status` — may need to re-pair |
| Cron job not firing | `hermes cron list` — verify job is enabled |
| VPN drops and bots error | Reconnect VPN, then restart: `systemctl --user restart hl-scalper-bot hl-mm-bot` (Linux) or `launchctl unload/load` (macOS) |
| `systemctl --user` not working | Run `loginctl enable-linger $USER` (Linux only) |

---

## File Structure

```
hyperliquid-trading-kit/
├── scalper/
│   ├── .env                ← Your wallet keys (DO NOT SHARE)
│   ├── .env.example        ← Template
│   ├── bot.py              ← Main scalper logic (V6: cache key fix, price display)
│   ├── signals.py          ← Signal engine (confluence + momentum breakout)
│   ├── config.py           ← Per-coin optimized configs (TP/SL/trailing)
│   ├── main.py             ← Entry point
│   ├── requirements.txt    ← Python dependencies
│   └── venv/               ← Python virtual environment
├── market-maker/
│   ├── .env                ← Your wallet keys (DO NOT SHARE)
│   ├── .env.example        ← Template
│   ├── mm_bot.py            ← Main MM logic (V6: forced unwind, 80% cap)
│   ├── mm_config.py        ← MM configs (4% order size, spread, inventory)
│   ├── requirements.txt    ← Python dependencies
│   └── venv/               ← Python virtual environment
├── simulator/
│   ├── backtest_scalper.py ← Backtest scalper on 6 months of historical data
│   ├── backtest_mm.py      ← Backtest market maker
│   └── coin_optimizer.py   ← Grid search optimal TP/SL/trailing per coin
├── monitor/
│   ├── hl_monitor.py       ← Performance monitor (run by Hermes cron every 30 min)
│   └── hl_status.py        ← One-shot status report
├── systemd/                ← Linux systemd service templates
├── docs/
│   ├── README.md           ← Full strategy docs + configuration reference
│   ├── WINDOWS-SETUP.md    ← Complete Windows PC setup (12 steps)
│   ├── PLATFORM-SETUP.md    ← This file (macOS + Linux)
│   └── HERMES-SETUP.md     ← Hermes Agent setup + Telegram connection
└── .gitignore              ← Protects .env files from Git
```

---

**GitHub:** https://github.com/maadmaax26/hyperliquid-trading-kit
**Issues:** https://github.com/maadmaax26/hyperliquid-trading-kit/issues
**Hermes Docs:** https://hermes-agent.nousresearch.com/docs