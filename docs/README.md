# Hyperliquid Trading Bot Kit

A complete algorithmic trading system for Hyperliquid perpetual futures.

## What's Included

| Component | Description |
|-----------|-------------|
| **Scalper Bot** | 5m directional trading — multi-confluence + momentum breakout signals (V6) |
| **Market Maker Bot** | Two-sided quoting with spread capture + maker rebates |
| **Simulator** | Backtest both strategies on 6 months of historical data |
| **Monitor** | Equity tracking, drawdown alerts, per-bot P&L attribution |
| **Hermes Agent** | AI assistant for automated Telegram monitoring |

## Quick Start — Pick Your Platform

| Platform | Setup Guide | Steps |
|----------|------------|-------|
| 🪟 **Windows PC** | [WINDOWS-SETUP.md](docs/WINDOWS-SETUP.md) | 12 steps — VPN → Python → bots → Hermes → Telegram |
| 🍎 **macOS** | [docs/PLATFORM-SETUP.md](docs/PLATFORM-SETUP.md#1-macos-setup) | 10 steps — Homebrew → bots → launchd → Hermes |
| 🐧 **Linux / WSL** | [docs/PLATFORM-SETUP.md](docs/PLATFORM-SETUP.md#2-linux-setup-ubuntudebian) | 10 steps — apt → bots → systemd → Hermes |

**All platforms need a VPN connected to South Africa or Mexico** (Hyperliquid blocks US IPs).

## Setup Overview (All Platforms)

1. **VPN** — Connect to non-US server (South Africa or Mexico)
2. **Python 3.11+** — Install with pip/venv
3. **Clone** — `git clone https://github.com/maadmaax26/hyperliquid-trading-kit.git`
4. **Install** — Create venvs, install dependencies (`requirements.txt`)
5. **API Keys** — Generate at app.hyperliquid.xyz → Settings → API
6. **Configure** — Copy `.env.example` → `.env`, fill in wallet details
7. **Test** — Run bots manually, verify they connect to Hyperliquid
8. **Start Services** — systemd (Linux), launchd (macOS), or NSSM (Windows)
9. **Install Hermes** — Download from hermes-agent.nousresearch.com
10. **Connect Telegram** — `hermes gateway setup` → BotFather → pair
11. **Set Up Monitoring** — 30-min cron job sends alerts to Telegram
12. **Done** — Bots run 24/7, Hermes reports every 30 min

For detailed step-by-step instructions, see your platform guide above.

## Prerequisites

- **VPN** — connected to South Africa or Mexico (Hyperliquid blocks US IPs)
- **Python 3.11+** with `venv` module
- **Hyperliquid account** with USDC deposited
- **API agent wallet** — generated at app.hyperliquid.xyz → Settings → API
- **LLM API key** — for Hermes (OpenRouter recommended — free models at openrouter.ai)

## Getting Your Hyperliquid API Keys

1. Go to [app.hyperliquid.xyz](https://app.hyperliquid.xyz) (with VPN connected)
2. Connect your wallet (MetaMask, Rabby, etc.)
3. Navigate to **Settings → API → Generate API Wallet**
4. Copy:
   - **API Agent Private Key** → goes in `.env` as `HL_PRIVATE_KEY`
   - **Parent Wallet Address** → goes in `.env` as `PARENT_ADDRESS`
5. Fund your account with USDC (Arbitrum network)

## Architecture

```
hyperliquid-trading-kit/
├── scalper/              # Scalper bot (5m directional trading)
│   ├── bot.py            # Main bot engine — V6: cache key fix, price display, trend filter
│   ├── config.py         # Per-coin optimized configs (TP/SL/trailing)
│   ├── signals.py        # Signal engine — multi-confluence + momentum breakout (V6)
│   ├── indicators.py     # Technical indicator calculations
│   ├── risk_manager_v5.py # Position management, trailing stops, daily loss limits
│   ├── main.py           # Entry point
│   ├── trade_logger.py   # Trade history persistence
│   ├── .env.example      # Configuration template
│   └── requirements.txt  # Python dependencies
│
├── market-maker/         # Market maker bot (spread capture)
│   ├── mm_bot.py          # MM engine — V6: forced unwind, 80% inventory cap
│   ├── mm_config.py       # MM configs — 4% order size, spreads, leverage
│   ├── .env.example       # Configuration template
│   └── requirements.txt   # Python dependencies
│
├── simulator/             # Backtesting engine
│   ├── backtest_scalper.py  # Scalper strategy backtester
│   ├── backtest_mm.py       # MM strategy backtester
│   ├── coin_optimizer.py    # Grid search for optimal TP/SL/trailing per coin
│   └── zec_backtest.py      # Single-coin deep analysis
│
├── monitor/              # Performance monitoring
│   ├── hl_monitor.py     # Equity tracking, drawdown detection, alerts
│   ├── hl_status.py      # Real-time position & P&L report
│   └── hl_equity_snapshot.py  # Lightweight one-line equity snapshot
│
├── systemd/              # Linux systemd service templates
│   ├── hl-scalper-bot.service
│   ├── hl-mm-bot.service
│   ├── hl-status.service
│   └── hl-status.timer
│
├── price-history/        # Historical candle data (JSON, 9 coins × 2 timeframes)
│
├── docs/
│   ├── README.md         # This file — start here
│   ├── WINDOWS-SETUP.md  # Complete Windows PC setup (12 steps)
│   ├── PLATFORM-SETUP.md # macOS + Linux setup (10 steps each)
│   ├── HERMES-SETUP.md   # Hermes Agent + Telegram monitoring setup
│   └── INSTALL-GUIDE.md  # Quick reference install guide
│
└── setup.sh              # One-command installer (Linux/macOS)
```

## Strategy Overview

### Scalper Bot (V6)

**Coins:** BTC, ETH, SOL, XRP, ZEC, PAXG (non-overlapping with MM bot)

**Dual signal engine:**

| Signal Type | When It Fires | Best Market |
|-------------|---------------|-------------|
| **Multi-Confluence** | RSI + EMA cross + MACD + Bollinger Bands align (score ≥ 10) | Ranging / choppy |
| **Momentum Breakout** (V6) | ADX >25 + EMA9 > EMA21 + MACD histogram rising | Strong trends |

**Per-coin optimized parameters:**

| Coin | Take Profit | Stop Loss | Trail Activate | Trail Stop | Win Rate | Profit Factor | Max DD |
|------|------------|-----------|----------------|------------|----------|---------------|--------|
| BTC | 0.21% | 0.25% | 0.15% | 0.04% | 81.3% | 3.44 | 1.7% |
| ETH | 0.25% | 0.30% | 0.17% | 0.04% | 76.3% | 2.85 | 3.1% |
| SOL | 0.30% | 0.40% | 0.23% | 0.06% | 73.5% | 2.44 | 4.1% |
| XRP | 0.23% | 0.25% | 0.17% | 0.04% | 78.8% | 4.73 | 2.1% |
| ZEC | 0.28% | 0.30% | 0.20% | 0.06% | 79.7% | 5.60 | 6.2% |

**Safety filters:**
- Volatility regime gate (ATR < 0.10% → skip)
- 1h EMA50 trend filter (±0.3% threshold — blocks counter-trend entries)
- Daily loss limit: 4% of equity
- Max 3 concurrent positions
- Cooldown: 120-300s between trades on same coin

**Trailing stops are the profit engine** — 100% win rate in all backtests when trailing activates.

### Market Maker Bot (V6)

**Coins:** kPEPE, kBONK, ARB (non-overlapping with scalper)

| Coin | Half-Spread | Order Size | Max Inventory | Leverage |
|------|------------|------------|---------------|----------|
| kPEPE | 0.10% | 4% equity | 12% equity | 3x |
| kBONK | 0.12% | 4% equity | 12% equity | 3x |
| ARB | 0.12% | 4% equity | 12% equity | 3x |

**Safety mechanisms (V6):**
- Forced unwind at 150% of inventory cap (market-close)
- Stop adding at 80% of cap (was 95%)
- ADX >40 skip (adverse selection protection)
- Volume <0.5x average skip (dead market filter)
- Daily loss limit: 4%

## Configuration

### Scalper (per coin, in `scalper/config.py`):
```python
BTC_CONFIG = AssetConfig(
    take_profit_pct=0.0021,        # 0.21% TP
    stop_loss_pct=0.0025,          # 0.25% SL
    trailing_activate_pct=0.0015,  # Trailing activates at +0.15%
    trailing_stop_pct=0.0004,      # Trail distance: 0.04%
    position_size_pct=0.35,        # 35% of equity per position
    min_signal_score=10,          # Minimum confluence score
    cooldown_seconds=120,          # Cooldown between trades
)
```

### MM bot (per coin, in `market-maker/mm_config.py`):
```python
KPEPE_MM = MMAssetConfig(
    coin="kPEPE",
    order_size_pct=0.04,     # 4% of equity per order
    spread_pct=0.0010,       # 0.10% half-spread
    leverage=3,               # 3x leverage
    max_inventory_pct=0.12,   # Max 12% of equity in inventory
)
```

Use `simulator/coin_optimizer.py` to find optimal parameters for new coins.

## Running Backtests

```bash
# From the market-maker venv (has numpy)
market-maker/venv/bin/python simulator/backtest_scalper.py
market-maker/venv/bin/python simulator/backtest_mm.py
market-maker/venv/bin/python simulator/coin_optimizer.py
```

## Monitoring

```bash
# Real-time status (one-shot)
market-maker/venv/bin/python monitor/hl_status.py

# Watch mode (refreshes every 30s)
market-maker/venv/bin/python monitor/hl_status.py --watch

# Performance monitor with drawdown alerts
market-maker/venv/bin/python monitor/hl_monitor.py
```

For automated Telegram alerts every 30 minutes, set up Hermes Agent — see [docs/HERMES-SETUP.md](docs/HERMES-SETUP.md).

## Fee Structure (Hyperliquid)

| Order Type | Fee | Rebate |
|------------|-----|--------|
| Taker (market) | 0.035% | — |
| Maker (limit) | 0.010% | -0.003% (rebate) |
| **Net maker round-trip** | **0.014%** | MM bot pays this |
| **Net taker round-trip** | **0.045%** | Scalper pays this |

## Safety Notes

- **Start small:** Test with $50-100 before scaling up
- **Both bots share one account:** They MUST trade non-overlapping coins
- **Backtests are optimistic:** Real fills have slippage and queue position
- **Never trade money you can't afford to lose**
- **Keep private keys secure:** Never commit `.env` files or share keys

## Documentation

| Document | What's In It |
|----------|-------------|
| [WINDOWS-SETUP.md](docs/WINDOWS-SETUP.md) | Complete Windows PC setup — 12 steps from zero to running |
| [PLATFORM-SETUP.md](docs/PLATFORM-SETUP.md) | macOS (10 steps) + Linux (10 steps) setup guides |
| [HERMES-SETUP.md](docs/HERMES-SETUP.md) | Hermes Agent install, Telegram connection, monitoring cron jobs |
| [INSTALL-GUIDE.md](docs/INSTALL-GUIDE.md) | Quick reference install guide (all platforms) |
| **This README.md** | Strategy overview, configuration, architecture |

## Support

- **GitHub Issues:** https://github.com/maadmaax26/hyperliquid-trading-kit/issues
- **Hermes Docs:** https://hermes-agent.nousresearch.com/docs

## License

Provided for educational purposes. Trade at your own risk.