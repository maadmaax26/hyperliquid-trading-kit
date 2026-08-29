# Hyperliquid Trading Bot — Windows PC Complete Setup Guide

**From zero to running bots with Telegram monitoring in 12 steps.**

---

## What You're Building

| Component | What It Does |
|-----------|-------------|
| **Scalper Bot** | Trades BTC, ETH, SOL, XRP, ZEC on 5m candles using multi-confluence + momentum signals |
| **Market Maker Bot** | Two-sided quoting on kPEPE, kBONK, ARB — captures spread + maker rebates |
| **Hermes Agent** | AI assistant that monitors bots and sends Telegram alerts every 30 min |

Both bots run on the same Hyperliquid account with non-overlapping coins. They share one API key but never trade the same asset.

---

## Prerequisites Checklist

Before you start, you need:

- [ ] **Windows 10/11 PC** (64-bit) with at least 4 GB RAM
- [ ] **VPN** — installed and connected to **South Africa** or **Mexico** server (Hyperliquid blocks US IPs)
- [ ] **Hyperliquid account** — with USDC deposited at app.hyperliquid.xyz
- [ ] **API agent wallet** — generated in HL Settings → API (save the private key!)
- [ ] **Telegram account** — for receiving bot alerts on your phone
- [ ] **LLM API key** — for Hermes (OpenRouter recommended — has free models)

---

## Step 1: Install a VPN and Connect

Hyperliquid blocks US IP addresses. You **must** connect to a non-US server before doing anything else.

**Recommended VPN providers:**

| Provider | Cost | Kill Switch | South Africa | Mexico |
|----------|------|-------------|-------------|--------|
| **Mullvad** | $5/mo | ✅ Built-in | ✅ | ✅ |
| **ProtonVPN** | Free tier | ✅ Toggle | ✅ | ✅ |
| **ExpressVPN** | $8/mo | ✅ In app | ✅ | ✅ |
| **Tailscale** | Free | Via exit node | Set up VPS | Set up VPS |

1. Install your VPN of choice
2. Connect to a **South Africa** or **Mexico** server
3. Enable **kill switch** if available (prevents leaks if VPN drops)
4. Verify your IP is non-US:
   ```powershell
   # Open PowerShell and run:
   curl https://ifconfig.me
   # Should show a South Africa or Mexico IP, not a US IP
   ```

**⚠️ The VPN must stay connected whenever the bots are running. If it drops, the bots will get API errors and stop trading.**

---

## Step 2: Install Python

1. Go to https://www.python.org/downloads/
2. Download **Python 3.11+** (3.12 recommended)
3. Run the installer — **check these boxes during install:**
   - ✅ **Add Python to PATH** (critical — won't work without this)
   - ✅ **Install for all users**
4. Verify in PowerShell:
   ```powershell
   python --version
   # Should show: Python 3.11.x or 3.12.x
   ```

---

## Step 3: Install Git

1. Go to https://git-scm.com/downloads
2. Download and install with default settings
3. Verify:
   ```powershell
   git --version
   # Should show: git version 2.x.x
   ```

---

## Step 4: Clone the Trading Bot Repository

Open **PowerShell** and run:

```powershell
cd C:\Users\YOUR_USERNAME
git clone https://github.com/maadmaax26/hyperliquid-trading-kit.git
cd hyperliquid-trading-kit
```

This downloads the complete bot kit: scalper, market maker, backtest simulator, and monitoring tools.

---

## Step 5: Create Python Virtual Environments

The bots need isolated Python environments with their own dependencies. Create one for each bot:

```powershell
# === Scalper venv ===
cd scalper
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
deactivate
cd ..

# === Market Maker venv ===
cd market-maker
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
deactivate
cd ..
```

This installs:
- `hyperliquid-python-sdk==0.24.0` (exchange API)
- `python-dotenv` (config loading)
- `numpy` (indicators)
- `eth-account` (wallet signing)
- `requests` (API calls)

---

## Step 6: Get Your Hyperliquid API Keys

If you haven't already, create an API agent wallet on Hyperliquid:

1. Go to https://app.hyperliquid.xyz (with VPN connected)
2. Connect your wallet (MetaMask, etc.)
3. Go to **Settings → API**
4. Click **Generate API Key**
5. You'll see two values:
   - **API Agent Wallet Address** — starts with `0x...` (public, safe to share)
   - **API Agent Private Key** — starts with `0x...` (**SECRET — never share this!**)
6. Copy both values — you'll need them in Step 7

**Important:** The API agent wallet trades on behalf of your main wallet. It can only access funds you've approved for it. Your main wallet private key is never exposed.

---

## Step 7: Configure Your .env Files

Copy the example templates and fill in your wallet details:

```powershell
# Copy templates
copy scalper\.env.example scalper\.env
copy market-maker\.env.example market-maker\.env
```

Open each file in **VS Code** or **Notepad** (save as UTF-8 without BOM):

```powershell
# Edit scalper config
notepad scalper\.env
```

Fill in:
```
HL_PRIVATE_KEY=0xYOUR_API_AGENT_PRIVATE_KEY
PARENT_ADDRESS=0xYOUR_PARENT_WALLET_ADDRESS
USE_MAINNET=true
```

```powershell
# Edit market maker config
notepad market-maker\.env
```

Same values — both bots use the same API agent key on the same account.

**⚠️ Security:**
- Never commit `.env` files to Git (they're in `.gitignore`)
- Never share your private key with anyone
- If compromised, revoke the API key in Hyperliquid Settings

---

## Step 8: Test the Bots

Before running them as background services, test that they connect and work:

### Test the Scalper

```powershell
.\scalper\venv\Scripts\python.exe scalper\main.py
```

You should see:
```
🔗 Connecting to Hyperliquid...
📍 API Wallet:    0x...
📍 Trading on:    0x...
💰 Equity: $XX.XX
📋 Assets: ['BTC', 'ETH', 'SOL', 'XRP', 'ZEC', 'PAXG']
🚀 Scalper started — entering main loop
```

It will start scanning for trade signals. Press **Ctrl+C** to stop.

### Test the Market Maker

```powershell
.\market-maker\venv\Scripts\python.exe market-maker\mm_bot.py
```

You should see:
```
🔗 Connecting to Hyperliquid...
⚙️ kPEPE leverage set to 3x (cross)
⚙️ kBONK leverage set to 3x (cross)
⚙️ ARB leverage set to 3x (cross)
💰 Equity: $XX.XX
📋 Assets: ['kPEPE', 'kBONK', 'ARB']
🚀 Market maker started — entering main loop
📊 kPEPE: NEUTRAL | Bid=✅ Ask=✅ | Orders: 2
📊 kBONK: NEUTRAL | Bid=✅ Ask=✅ | Orders: 2
📊 ARB:   TRENDING | Bid=✅ Ask=✅ | Orders: 2
```

Press **Ctrl+C** to stop.

### If you get errors:
- **`WinError 10106`** → Run `setx SYSTEMROOT "C:\Windows"` and restart PowerShell
- **Connection refused** → VPN is not connected or using a US server
- **`insufficient margin`** → Not enough USDC in your account (need $50+)
- **`.env` not found** → Save as UTF-8 without BOM, check the file is named `.env` not `.env.txt`

---

## Step 9: Install Bots as Windows Services

Use **NSSM** (Non-Sucking Service Manager) to run the bots as Windows services that auto-start on boot and restart on crash.

### Install NSSM

```powershell
winget install nssm
```

Or download from https://nssm.cc/download

### Install Scalper as a Service

```powershell
nssm install HL-Scalper-Bot "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\venv\Scripts\python.exe" "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\main.py"

nssm set HL-Scalper-Bot AppDirectory "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper"
nssm set HL-Scalper-Bot AppEnvironmentExtra "PYTHONUNBUFFERED=1"
nssm set HL-Scalper-Bot DisplayName "Hyperliquid Scalper Bot"
nssm set HL-Scalper-Bot Start SERVICE_AUTO_START
nssm set HL-Scalper-Bot AppStdout "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\bot.log"
nssm set HL-Scalper-Bot AppStderr "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\bot.log"
nssm set HL-Scalper-Bot AppRotateFiles 1
nssm set HL-Scalper-Bot AppRotateBytes 10485760

nssm start HL-Scalper-Bot
```

### Install Market Maker as a Service

```powershell
nssm install HL-MM-Bot "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\venv\Scripts\python.exe" "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\mm_bot.py"

nssm set HL-MM-Bot AppDirectory "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker"
nssm set HL-MM-Bot AppEnvironmentExtra "PYTHONUNBUFFERED=1"
nssm set HL-MM-Bot DisplayName "Hyperliquid Market Maker Bot"
nssm set HL-MM-Bot Start SERVICE_AUTO_START
nssm set HL-MM-Bot AppStdout "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\mm_bot.log"
nssm set HL-MM-Bot AppStderr "C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\mm_bot.log"
nssm set HL-MM-Bot AppRotateFiles 1
nssm set HL-MM-Bot AppRotateBytes 10485760

nssm start HL-MM-Bot
```

### Verify Services Are Running

```powershell
nssm status HL-Scalper-Bot
nssm status HL-MM-Bot
# Both should show: SERVICE_RUNNING
```

### Managing the Services

```powershell
# Check status
nssm status HL-Scalper-Bot
nssm status HL-MM-Bot

# View logs
Get-Content C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\bot.log -Tail 20
Get-Content C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\mm_bot.log -Tail 20

# Restart
nssm restart HL-Scalper-Bot
nssm restart HL-MM-Bot

# Stop
nssm stop HL-Scalper-Bot
nssm stop HL-MM-Bot

# Remove (if you want to uninstall)
nssm remove HL-Scalper-Bot confirm
nssm remove HL-MM-Bot confirm
```

---

## Step 10: Install Hermes Desktop for Monitoring

Hermes Agent is an AI assistant that runs on your PC and monitors the bots. It sends alerts to Telegram every 30 minutes and lets you ask questions in plain English.

### Download Hermes Desktop

1. Go to **https://hermes-agent.nousresearch.com**
2. Click **Download** and select the **Windows** installer (.exe)
3. Run the installer — it handles everything: Python, dependencies, CLI, desktop app
4. Launch **Hermes Desktop** from your Start menu

### Alternative: CLI-only install

```powershell
# In PowerShell (Run as Administrator)
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

### Configure Hermes

On first launch, the app walks you through setup:

1. **Choose LLM provider** — recommended: **OpenRouter** (free models available, one API key for many models)
2. **Enter your API key** — get one at https://openrouter.ai/keys
3. **Verify it works** — type a test message in the chat window

You can also use the CLI:
```powershell
hermes setup     # Interactive wizard
hermes model     # Configure LLM provider
hermes doctor    # Health check
```

---

## Step 11: Connect Telegram for Alerts

This lets Hermes send you bot status reports on your phone.

### Create a Telegram Bot

1. Open Telegram and message **@BotFather** (https://t.me/BotFather)
2. Send `/newbot`
3. Follow the prompts — give your bot a name and username
4. Copy the **bot token** (format: `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`)

### Connect Hermes to Telegram

```powershell
hermes gateway setup
```

Select **Telegram** and follow the prompts:
1. Paste your bot token
2. Send a message to your new bot on Telegram
3. Hermes confirms the pairing

Verify the connection:
```powershell
hermes gateway status
# Should show: telegram: Connected ✓
```

Now you can chat with Hermes from your phone. Try sending:
```
What's my current account equity?
```

---

## Step 12: Set Up Automated Monitoring

Create a scheduled job that checks your bots every 30 minutes and sends a Telegram report.

### Via Hermes Desktop Chat (Easiest)

In the Hermes Desktop chat window, type:

```
Create a recurring job every 30 minutes that runs:
C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\venv\Scripts\python.exe C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\monitor\hl_monitor.py

Report the current equity, 24h change, per-bot P&L (scalper vs MM), and any alerts. Keep it concise. If there are critical alerts, include specific recommendations.
```

Hermes will create the cron job automatically and confirm.

### Via CLI

```powershell
hermes cron create --name "HL Performance Monitor" --schedule "30m" --deliver origin --prompt "Run C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\venv\Scripts\python.exe C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\monitor\hl_monitor.py and report the results. Report equity, 24h change, per-bot P&L, and any alerts. Keep responses concise."
```

### Test the Monitor Manually

```powershell
.\market-maker\venv\Scripts\python.exe monitor\hl_monitor.py
```

You should see:
```
📊 HYPERLIQUID PERFORMANCE MONITOR
  Current Equity:     $XX.XX
  Peak Equity:        $XX.XX
  Drawdown from Peak: X.X%
  24h Change:         📈 +$X.XX (+X.X%)
  Scalper:  X positions, uPnL $+X.XX
  MM Bot:   X positions, uPnL $+X.XX
  ✅ No alerts — all systems nominal
```

### What You'll Receive on Telegram

**Every 30 minutes (normal):**
> Equity $169.25 | 24h: +0.5% | Scalper +$1.20 (2 pos) | MM +$0.05 (3 pos) | Both bots active ✅

**When there's a problem:**
> ⚠️ WARNING: Daily Decline -3.2% (-$5.42)
> Equity dropped from $169.25 to $163.83 in 24h.
> Recommendations: 1. Check recent trades, 2. Review position sizes

**When a bot crashes:**
> 🚨 CRITICAL: Scalper Bot is FAILED
> Service is not running. Restart: nssm restart HL-Scalper-Bot

### Manage Cron Jobs

```powershell
hermes cron list              # List all jobs
hermes cron pause <job-id>    # Pause a job
hermes cron resume <job-id>   # Resume
hermes cron run <job-id>      # Run immediately
hermes cron remove <job-id>   # Delete
```

---

## Optional: Run Backtests

Test how the strategies would have performed on historical data:

```powershell
# Scalper backtest (uses 6 months of 5m candle data)
.\market-maker\venv\Scripts\python.exe simulator\backtest_scalper.py

# Market maker backtest
.\market-maker\venv\Scripts\python.exe simulator\backtest_mm.py

# Grid search optimizer — finds optimal TP/SL/trailing for each coin
.\market-maker\venv\Scripts\python.exe simulator\coin_optimizer.py
```

---

## Quick Reference: All Commands

### Start everything after a reboot
```powershell
# 1. Connect VPN first (South Africa or Mexico)

# 2. Start bot services (auto-start if configured with NSSM)
nssm start HL-Scalper-Bot
nssm start HL-MM-Bot

# 3. Hermes Desktop auto-starts with Windows, or launch manually
# Hermes cron jobs run automatically
```

### Check everything is running
```powershell
# VPN
curl https://ifconfig.me    # Non-US IP?

# Bots
nssm status HL-Scalper-Bot   # SERVICE_RUNNING?
nssm status HL-MM-Bot        # SERVICE_RUNNING?

# Hermes
hermes gateway status         # telegram: Connected ✓?

# Recent logs
Get-Content C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\scalper\bot.log -Tail 10
Get-Content C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\mm_bot.log -Tail 10
```

### Emergency stop everything
```powershell
nssm stop HL-Scalper-Bot
nssm stop HL-MM-Bot
```

### Ask Hermes from your phone (Telegram)
```
What's my equity right now?
Are both bots running?
Show me today's trades
Restart the scalper bot
What's the ZEC price?
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python` not found | Reinstall Python, check "Add to PATH" box |
| `WinError 10106` | Run `setx SYSTEMROOT "C:\Windows"`, restart PowerShell |
| Connection refused | VPN not connected or using US server |
| `insufficient margin` | Need more USDC in Hyperliquid account ($50+ minimum) |
| `.env` not loading | Save as UTF-8 without BOM (use VS Code, not Notepad) |
| NSSM service won't start | Check `Get-Content bot.log -Tail 20` for error |
| Hermes `command not found` | Restart terminal or run `source ~/.bashrc` equivalent |
| No Telegram response | Run `hermes gateway status` — may need to re-pair |
| Cron job not firing | `hermes cron list` — verify job is enabled |
| VPN drops and bots error | Reconnect VPN, then `nssm restart HL-Scalper-Bot` and `nssm restart HL-MM-Bot` |

---

## Safety Notes

- **Start with $50-100** to test before scaling up
- Both bots share one account — they **MUST** trade non-overlapping coins (scalper: BTC/ETH/SOL/XRP/ZEC/PAXG, MM: kPEPE/kBONK/ARB)
- Backtests are optimistic — real fills have slippage
- **Never trade money you can't afford to lose**
- Keep your private key secure — never paste it into chat, email, or anywhere online
- If you lose your API key, revoke it in Hyperliquid Settings → API and generate a new one

---

## File Structure

```
hyperliquid-trading-kit/
├── scalper/
│   ├── .env                ← Your wallet keys (DO NOT SHARE)
│   ├── .env.example        ← Template
│   ├── bot.py              ← Main scalper logic
│   ├── signals.py          ← Signal engine (confluence + momentum)
│   ├── config.py           ← Coin configs (TP/SL/trailing per coin)
│   ├── main.py             ← Entry point
│   ├── requirements.txt    ← Python dependencies
│   └── venv/               ← Python virtual environment
├── market-maker/
│   ├── .env                ← Your wallet keys (DO NOT SHARE)
│   ├── .env.example        ← Template
│   ├── mm_bot.py            ← Main MM logic
│   ├── mm_config.py        ← MM coin configs (spread/size/inventory)
│   ├── requirements.txt    ← Python dependencies
│   └── venv/               ← Python virtual environment
├── simulator/
│   ├── backtest_scalper.py ← Backtest scalper on historical data
│   ├── backtest_mm.py      ← Backtest MM on historical data
│   └── coin_optimizer.py   ← Grid search optimal params
├── monitor/
│   ├── hl_monitor.py       ← Performance monitor (run by Hermes cron)
│   └── hl_status.py        ← Status report (one-shot)
├── systemd/                ← Linux service templates (not needed on Windows)
├── docs/
│   ├── README.md           ← Full strategy docs + config reference
│   ├── WINDOWS-SETUP.md    ← This file
│   ├── HERMES-SETUP.md     ← Hermes setup details
│   └── PLATFORM-SETUP.md   ← Cross-platform reference
└── .gitignore              ← Protects .env files from Git
```

---

**GitHub:** https://github.com/maadmaax26/hyperliquid-trading-kit
**Issues:** https://github.com/maadmaax26/hyperliquid-trading-kit/issues
**Hermes Docs:** https://hermes-agent.nousresearch.com/docs