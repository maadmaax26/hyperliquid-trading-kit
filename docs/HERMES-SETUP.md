# Setting Up Hermes Agent to Monitor Your Trading Bots

Hermes Agent is an AI assistant that can run on your machine alongside the trading bots. It connects to Telegram (or other messaging apps) so you can chat with it, get status reports, receive alerts, and even control the bots from your phone. It also runs scheduled monitoring jobs automatically.

---

## Step 1: Install Hermes Agent

### Linux / macOS / WSL

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
source ~/.bashrc   # or source ~/.zshrc
```

### Windows (native, PowerShell)

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

### Or download the desktop app (recommended for Windows/Mac)

Go to https://hermes-agent.nousresearch.com and download the Desktop installer. It includes the CLI and a native app with a chat interface.

---

## Step 2: Configure Hermes

After install, run the setup wizard:

```bash
hermes setup      # Interactive setup — configures paths, tools
hermes model      # Choose your LLM provider (OpenRouter, OpenAI, Anthropic, etc.)
hermes doctor     # Health check — verifies everything is working
```

### Choose a Provider

`hermes model` will walk you through selecting an LLM provider. Options include:
- **OpenRouter** — access many models with one API key (recommended)
- **OpenAI** — GPT-4o, o1, etc.
- **Anthropic** — Claude models
- **Google** — Gemini
- **xAI** — Grok
- **Local models** — Ollama, llama.cpp (free, runs on your hardware)
- **Nous Portal** — Nous Research's own provider

You need at least one provider configured for Hermes to work. OpenRouter has free models available.

---

## Step 3: Connect Telegram (so you can chat from your phone)

This lets you send messages to Hermes from your phone and receive bot status reports.

```bash
hermes gateway setup
```

Select **Telegram** and follow the prompts:
1. Create a Telegram bot by messaging [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow instructions to get a bot token
3. Paste the token when Hermes asks for it
4. Send a message to your new bot on Telegram to pair your account

Verify the connection:
```bash
hermes gateway status
```

---

## Step 4: Create the Monitoring Cron Job

This creates a scheduled job that runs every 30 minutes, checks your bot performance, and sends a report to your Telegram chat.

### Via Telegram chat (easiest)

Once Hermes is connected to Telegram, just send this message to your bot:

```
Create a recurring job every 30 minutes that runs:
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py

Report the current equity, 24h change, per-bot P&L (scalper vs MM), and any alerts. Keep it concise. If there are critical alerts, include specific recommendations.
```

Hermes will create the cron job automatically and confirm.

### Via CLI

```bash
hermes cron create \
  --name "HL Performance Monitor" \
  --schedule "30m" \
  --deliver origin \
  --prompt "Run ~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py and report the results. Report equity, 24h change, per-bot P&L attribution, and any alerts. Keep responses concise. Include recommendations only when alerts are triggered."
```

### Windows equivalent

```
hermes cron create --name "HL Monitor" --schedule "30m" --deliver origin --prompt "Run C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\venv\Scripts\python.exe C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\monitor\hl_monitor.py and report equity, P&L, and alerts"
```

---

## Step 5: Verify the Monitor Works

Run the monitor manually to test:

```bash
# Linux / macOS
~/hyperliquid-trading-kit/market-maker/venv/bin/python ~/hyperliquid-trading-kit/monitor/hl_monitor.py

# Windows
C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\market-maker\venv\Scripts\python.exe C:\Users\YOUR_USERNAME\hyperliquid-trading-kit\monitor\hl_monitor.py
```

You should see a report like:
```
📊 HYPERLIQUID PERFORMANCE MONITOR
  Current Equity:     $169.25
  Peak Equity:        $169.25
  Drawdown from Peak: 0.0%
  24h Change:         📈 +$0.00 (+0.0%)
  Scalper:  0 positions, uPnL $+0.00
  MM Bot:   2 positions, uPnL $+0.05
  ✅ No alerts — all systems nominal
```

---

## Step 6: Managing Cron Jobs

List your scheduled jobs:
```bash
hermes cron list
```

Pause a job:
```bash
hermes cron pause <job-id>
```

Resume:
```bash
hermes cron resume <job-id>
```

Remove:
```bash
hermes cron remove <job-id>
```

Run a job immediately (without waiting for schedule):
```bash
hermes cron run <job-id>
```

---

## What You'll Get on Telegram

Every 30 minutes, Hermes sends a message to your Telegram chat:

**When everything is fine:**
> Equity $169.25 | 24h: +0.0% | Scalper $0.00 (0 pos) | MM +$0.05 (2 pos) | Both bots active ✅

**When there's a problem:**
> ⚠️ WARNING: Daily Decline -3.2% (-$5.42)
> Equity dropped from $169.25 to $163.83 in 24h.
> Scalper is dragging (-$4.20, ZEC short losing).
> Recommendations: 1. Check ZEC TP/SL, 2. Review recent trades, 3. Consider reducing position size

**When a bot crashes:**
> 🚨 CRITICAL: Scalper Bot is FAILED
> Service is not running. Last log: [error message]
> Recommendations: 1. Restart: systemctl --user start hl-scalper-bot.service, 2. Check logs: journalctl --user -u hl-scalper-bot -n 50

---

## Advanced: Chatting with Hermes About Your Bots

Once Telegram is connected, you can ask Hermes questions anytime:

```
What's my current account equity?
```
```
How are the bots performing today?
```
```
Check if both bot services are running
```
```
Restart the scalper bot
```
```
What's the ZEC price right now?
```
```
Run the coin optimizer and show me the results
```

Hermes has terminal access, so it can run any of the bot scripts, check logs, restart services, and analyze performance — all from a Telegram chat on your phone.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `hermes: command not found` | Run `source ~/.bashrc` or restart terminal |
| No response on Telegram | Check `hermes gateway status` — bot may not be connected |
| Cron job not firing | Check `hermes cron list` — verify job is enabled |
| Monitor script errors | Ensure `.env` files are configured with wallet addresses |
| `gho_... token` errors | Re-run `hermes model` to reconfigure LLM provider |
| VPN drops and bots error | Hermes will report the bot crash — restart after VPN reconnects |

Full Hermes docs: https://hermes-agent.nousresearch.com/docs