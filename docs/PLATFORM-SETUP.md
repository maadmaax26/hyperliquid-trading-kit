# Platform Setup Guide

This guide covers installing and running the Hyperliquid Trading Bot Kit on:
1. **Windows PC with Hermes Desktop** (native Windows, no WSL required)
2. **macOS** (with VPN requirement for Hyperliquid access)

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

## 1. Windows PC Setup (with Hermes Desktop)

### Prerequisites

- **Windows 10/11** (64-bit)
- **Python 3.11+** — download from https://python.org (check "Add to PATH" during install)
- **Hermes Desktop** — download from https://hermes-agent.nousresearch.com or run:
  ```powershell
  # Install Hermes via installer
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh -o install.sh
  # Or download the desktop app directly from the docs site
  ```
- **VPN** connected to South Africa or Mexico server
- **Hyperliquid account** with USDC deposited + API agent wallet generated

### Step 1: Install Python

Download Python 3.11+ from https://www.python.org/downloads/

During installation:
- ✅ Check **"Add Python to PATH"**
- Select **"Install for all users"**

Verify in PowerShell:
```powershell
python --version
# Should show: Python 3.11.x or higher
```

### Step 2: Install Hermes Desktop

Option A — Download the desktop app:
```powershell
# Go to https://hermes-agent.nousresearch.com/docs
# Download the Windows desktop installer
# Run the .exe and follow the wizard
```

Option B — Install via CLI (if you want terminal access too):
```powershell
# In PowerShell (Run as Administrator)
irm https://hermes-agent.nousresearch.com/install.sh | bash
# Or use winget:
winget install NousResearch.HermesAgent
```

After install, launch Hermes:
```powershell
hermes setup    # Interactive setup wizard — pick your model + provider
hermes model    # Configure your LLM provider (OpenRouter, OpenAI, etc.)
hermes desktop  # Launch the desktop app
```

### Step 3: Extract the Trading Bot Kit

```powershell
# Extract the tarball (use 7-Zip or tar — Windows 10+ has tar built in)
cd C:\Users\YOUR_USERNAME
tar xzf hyperliquid-trading-kit.tar.gz
cd hyperliquid-trading-kit
```

### Step 4: Create Virtual Environments

Windows uses `Scripts\` instead of `bin/` for venv:

```powershell
# Create scalper venv
cd scalper
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
deactivate
cd ..

# Create market-maker venv
cd market-maker
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
deactivate
cd ..
```

### Step 5: Configure .env Files

```powershell
# Copy templates and edit
copy scalper\.env.example scalper\.env
copy market-maker\.env.example market-maker\.env

# Edit with Notepad or your editor
notepad scalper\.env
notepad market-maker\.env
```

Fill in:
```
HL_PRIVATE_KEY=0xYOUR_API_AGENT_PRIVATE_KEY
PARENT_ADDRESS=0xYOUR_PARENT_WALLET_ADDRESS
USE_MAINNET=true
```

### Step 6: Test the Bots

```powershell
# Test scalper (will connect to HL, scan for signals)
.\scalper\venv\Scripts\python.exe scalper\main.py

# Test MM bot
.\market-maker\venv\Scripts\python.exe market-maker\mm_bot.py

# Press Ctrl+C to stop
```

### Step 7: Run as Background Services (Windows)

Windows doesn't use systemd. Use **NSSM** (Non-Sucking Service Manager) or **Task Scheduler**:

#### Option A: NSSM (recommended — auto-restart on crash)

```powershell
# Install NSSM
winget install nssm

# Install scalper as a Windows service
nssm install HL-Scalper-Bot "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\venv\Scripts\python.exe" "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\main.py"
nssm set HL-Scalper-Bot AppDirectory "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper"
nssm set HL-Scalper-Bot AppEnvironmentExtra "PYTHONUNBUFFERED=1"
nssm start HL-Scalper-Bot

# Install MM bot as a Windows service
nssm install HL-MM-Bot "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\venv\Scripts\python.exe" "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\mm_bot.py"
nssm set HL-MM-Bot AppDirectory "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker"
nssm set HL-MM-Bot AppEnvironmentExtra "PYTHONUNBUFFERED=1"
nssm start HL-MM-Bot
```

Manage services:
```powershell
# Check status
nssm status HL-Scalper-Bot
nssm status HL-MM-Bot

# Restart
nssm restart HL-Scalper-Bot
nssm restart HL-MM-Bot

# Stop
nssm stop HL-Scalper-Bot
nssm stop HL-MM-Bot

# Remove
nssm remove HL-Scalper-Bot confirm
nssm remove HL-MM-Bot confirm
```

#### Option B: Task Scheduler (simpler, no auto-restart)

```powershell
# Create a scheduled task that runs at logon
schtasks /create /tn "HL-Scalper-Bot" /tr "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\venv\Scripts\python.exe C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\main.py" /sc onlogon /rl highest
schtasks /run /tn "HL-Scalper-Bot"

schtasks /create /tn "HL-MM-Bot" /tr "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\venv\Scripts\python.exe C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\mm_bot.py" /sc onlogon /rl highest
schtasks /run /tn "HL-MM-Bot"
```

### Step 8: Set Up Monitoring with Hermes

In Hermes Desktop, create a cron job for automated monitoring:

```powershell
# In Hermes Desktop chat, say:
"Create a cron job that runs every 30 minutes:
C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\venv\Scripts\python.exe
C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\monitor\hl_monitor.py
Report equity and any alerts."
```

Or via CLI:
```powershell
hermes cron create --name "HL Monitor" --schedule "30m" --deliver origin --prompt "Run C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\venv\Scripts\python.exe C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\monitor\hl_monitor.py and report results"
```

### Step 9: Run Backtests

```powershell
.\market-maker\venv\Scripts\python.exe simulator\backtest_scalper.py
.\market-maker\venv\Scripts\python.exe simulator\backtest_mm.py
.\market-maker\venv\Scripts\python.exe simulator\coin_optimizer.py
```

### Windows Notes

- Use **forward slashes** in Python paths (`C:/Users/...`) — works everywhere
- If Python scripts fail with `WinError 10106`, set environment variable:
  ```powershell
  setx SYSTEMROOT "C:\Windows"
  ```
- If `.env` files don't load, ensure they're saved as **UTF-8 without BOM** (use VS Code, not Notepad)
- The VPN must stay connected — if it drops, the bots will error. Use a VPN with auto-reconnect + kill switch

---

## 2. macOS Setup (with VPN)

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

# Install Python 3.11+ and tools
brew install python@3.12 git curl

# Verify
python3 --version
# Should show: Python 3.12.x
```

### Step 2: Install Hermes

```bash
# Install Hermes Agent
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# Run setup wizard
hermes setup
hermes model    # Configure LLM provider

# Launch desktop app (optional)
hermes desktop
```

### Step 3: Extract the Trading Bot Kit

```bash
cd ~/
tar xzf hyperliquid-trading-kit.tar.gz
cd hyperliquid-trading-kit
```

### Step 4: Install Dependencies

```bash
# Create scalper venv
cd scalper
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
cd ..

# Create market-maker venv
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
- **Mullvad** — CLI tool `mullvad connect` (select ZA or MX server)
- **ExpressVPN** — app or CLI `expressvpn connect "South Africa"`
- **ProtonVPN** — CLI `protonvpn-cli connect --cc ZA`
- **Tailscale + exit node** — set up a VPS in ZA/MX as exit node

### Step 7: Test the Bots

```bash
# Test scalper
scalper/venv/bin/python scalper/main.py

# Test MM bot
market-maker/venv/bin/python market-maker/mm_bot.py

# Ctrl+C to stop
```

### Step 8: Run as Background Services (macOS)

macOS uses **launchd** (equivalent to systemd):

Create the scalper plist:
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

Create the MM bot plist:
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

Load and start services:
```bash
# Load (starts immediately due to RunAtLoad)
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
  --name "HL Monitor" \
  --schedule "30m" \
  --deliver origin \
  --prompt "Run ~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py and report equity, per-bot PnL, and any alerts"
```

Or in Hermes Desktop chat:
```
Create a recurring job every 30 minutes that runs:
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py
Report the equity, per-bot P&L, and any alerts to me.
```

### Step 10: Run Backtests

```bash
market-maker/venv/bin/python simulator/backtest_scalper.py
market-maker/venv/bin/python simulator/backtest_mm.py
market-maker/venv/bin/python simulator/coin_optimizer.py
```

### macOS Notes

- macOS may block Python from network access on first run — check **System Settings → Privacy & Security → Network** and allow Python
- If `python3 -m venv` fails, run `brew install python@3.12` (venv is included)
- The `sed -i ''` syntax (with empty string) is macOS-specific — don't use Linux `sed -i` syntax
- **VPN must stay connected at all times** — if it drops, the bots will get connection errors. Use a VPN client with auto-reconnect and kill switch (Mullvad and ProtonVPN both support this)
- For always-on VPN, consider running the VPN on a router level or using a VPS as an exit node via Tailscale

---

## VPN Quick Reference

| Provider | CLI Connect (ZA) | CLI Connect (MX) | Kill Switch |
|----------|-------------------|-------------------|-------------|
| Mullvad | `mullvad relay set location za && mullvad connect` | `mullvad relay set location mx && mullvad connect` | ✅ Built-in |
| ExpressVPN | `expressvpn connect "South Africa"` | `expressvpn connect "Mexico"` | ✅ In app |
| ProtonVPN | `protonvpn-cli c --cc ZA` | `protonvpn-cli c --cc MX` | ✅ Kill switch toggle |
| Tailscale exit node | Set up VPS in ZA, `tailscale up --exit-node=<vps-ip>` | Same with MX VPS | ✅ Via Tailscale |

Always verify before starting bots:
```bash
curl -s ifconfig.me  # Must show non-US IP
```