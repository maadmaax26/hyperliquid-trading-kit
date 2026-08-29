# Hyperliquid Trading Bot Kit

A complete algorithmic trading system for Hyperliquid perpetual futures, featuring:
- **Scalper Bot** — 5m timeframe directional trading with multi-indicator confluence signals
- **Market Maker Bot** — Spread capture with ADX-based dynamic spreads and inventory skew
- **Simulator** — Backtest both strategies on 6 months of historical price data
- **Monitor** — Real-time equity tracking, drawdown alerts, and per-bot P&L attribution

## Quick Start

**Choose your platform:**
- 🐧 **Linux/WSL** — use `./setup.sh` below (uses systemd)
- 🪟 **Windows with Hermes Desktop** — see [docs/PLATFORM-SETUP.md](PLATFORM-SETUP.md#1-windows-pc-setup-with-hermes-desktop)
- 🍎 **macOS** — see [docs/PLATFORM-SETUP.md](PLATFORM-SETUP.md#2-macos-setup-with-vpn)

### Linux / WSL Quick Start

```bash
# 1. Clone or copy this directory to your machine
git clone <repo-url> hyperliquid-trading-kit
cd hyperliquid-trading-kit

# 2. Run the installer
./setup.sh

# 3. Edit .env files with your wallet details
nano scalper/.env
nano market-maker/.env

# 4. Test the bots (connects to HL, doesn't trade until configured)
scalper/venv/bin/python scalper/bot.py

# 5. Start as services
systemctl --user start hl-scalper-bot.service
systemctl --user start hl-mm-bot.service
systemctl --user start hl-status.timer
```

## Prerequisites

- **VPN required** — Hyperliquid blocks US IP addresses (Terms of Use §1.5). Connect to a non-US server (South Africa, Mexico, etc.) before starting the bots. See [docs/PLATFORM-SETUP.md](PLATFORM-SETUP.md#vpn-quick-reference) for VPN setup.
- **Python 3.11+** with `venv` module
- **Hyperliquid account** with USDC deposited
- **API agent wallet** (generated at app.hyperliquid.xyz → Settings → API)

## Getting Your Hyperliquid API Keys

1. Go to [app.hyperliquid.xyz](https://app.hyperliquid.xyz)
2. Connect your wallet (MetaMask, Rabby, etc.)
3. Navigate to **Settings → API → Generate API Wallet**
4. Copy:
   - **API Agent Private Key** → goes in `.env` as `HL_PRIVATE_KEY`
   - **Parent Wallet Address** → goes in `.env` as `PARENT_ADDRESS`/`HL_PARENT_ADDRESS`
5. Fund your account with USDC (Arbitrum network)

## Architecture

```
hyperliquid-trading-kit/
├── scalper/              # Scalper bot (5m directional trading)
│   ├── bot.py            # Main bot engine (~1940 lines)
│   ├── config.py         # All trading parameters (TP/SL/trailing per coin)
│   ├── signals.py        # Multi-indicator signal engine (RSI, EMA, MACD, BB, ADX, VWAP)
│   ├── indicators.py     # Technical indicator calculations
│   ├── risk_manager_v5.py # Position management, trailing stops, daily loss limits
│   ├── main.py           # Entry point
│   ├── trade_logger.py   # Trade history persistence
│   ├── .env.example      # Configuration template
│   └── requirements.txt  # Python dependencies
│
├── market-maker/         # Market maker bot (spread capture)
│   ├── mm_bot.py          # MM engine with ADX spreads, inventory skew, risk controls
│   ├── mm_config.py       # MM parameters (per-asset spreads, sizes, leverage)
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
├── systemd/              # Systemd service templates
│   ├── hl-scalper-bot.service
│   ├── hl-mm-bot.service
│   ├── hl-status.service
│   └── hl-status.timer
│
├── price-history/        # Historical candle data (JSON)
│   ├── BTC_5m.json, BTC_1h.json
│   ├── ETH_5m.json, ETH_1h.json
│   └── ... (9 coins × 2 timeframes)
│
├── docs/
│   ├── README.md         # This file
│   ├── STRATEGY.md       # Detailed strategy documentation
│   └── CONFIGURATION.md  # How to tune parameters
│
└── setup.sh              # One-command installer
```

## Strategy Overview

### Scalper Bot

**Coins:** BTC, ETH, SOL, XRP, ZEC (PAXG disabled — low volatility)

**Entry signals** (5m candles, 2+ factor confluence, min score = 10):
- RSI oversold/overbought (+3)
- EMA 9/21 cross with ADX trend filter (+3 trending, +1 ranging)
- MACD cross + momentum (+3 trending, +2 ranging)
- Bollinger Bands extreme (+3 ranging, +1 trending)
- Volume spike confirmation (+1)
- VWAP mean reversion (separate engine)

**Exit:**
- Take profit (tight: 0.21-0.30% per coin)
- Stop loss (0.25-0.40% per coin)
- Trailing stop (activates at 0.15-0.23%, trails at 0.04-0.06% — this is the profit engine)
- Time limit: 100 min max hold
- Daily loss limit: 4% of equity

**V5 enhancements (backtested):**
- 1h EMA50 trend filter (skips strongly counter-trend entries)
- ATR volatility gate (skips when 5m ATR < 0.10%)
- Swing trading disabled (was losing money at 29% WR)
- SOL re-enabled at min_score=9
- Max 3 concurrent positions

**Backtested performance ($1000, 17 days):**
| Coin | Win Rate | Profit Factor | Max Drawdown |
|------|----------|---------------|--------------|
| BTC  | 81%      | 3.44          | 1.7%         |
| ETH  | 76%      | 2.85          | 3.1%         |
| SOL  | 74%      | 2.44          | 4.1%         |
| XRP  | 79%      | 4.73          | 2.1%         |
| ZEC  | 80%      | 5.60          | 6.2%         |

### Market Maker Bot

**Coins:** kPEPE, kBONK, ARB (non-overlapping with scalper)

**Strategy:**
- Places bid/ask limit orders around mid price
- Spread dynamically adjusted by ADX (wider in trends, tighter in ranges)
- Inventory skew shifts quotes to reduce position when inventory builds
- Maker/maker fills + rebate = positive EV when spread > 0.014%

**Risk controls:**
- Max inventory per asset (12% of equity)
- Emergency close at 90% inventory
- ADX > 40: skip quoting (adverse selection protection)
- Volume < 0.5x average: skip quoting (dead market)
- Daily loss limit: 4%

**Backtested performance ($1000, 17 days):**
| Metric | Value |
|--------|-------|
| Final equity | $1,631 (+63%) |
| Total fills | 19,866 |
| Round trips | 7,209 |
| Fees paid | $83.68 |
| Rebates earned | $25.10 |
| Max drawdown | 0.16% |

⚠️ MM backtest assumes all orders fill when candle crosses the price. Real-world fills are lower due to queue position and partial fills.

## Configuration

### Changing Trading Parameters

All parameters are in `scalper/config.py` and `market-maker/mm_config.py`. Key settings:

**Scalper (per coin):**
```python
BTC_CONFIG = AssetConfig(
    take_profit_pct=0.0021,        # 0.21% TP
    stop_loss_pct=0.0025,          # 0.25% SL
    trailing_activate_pct=0.0015, # Trailing activates at +0.15%
    trailing_stop_pct=0.0004,     # Trail distance: 0.04%
    position_size_pct=0.35,       # 35% of equity per position
    min_signal_score=10,          # Minimum confluence score
    cooldown_seconds=120,         # Cooldown between trades
)
```

**MM bot (per coin):**
```python
KPEPE_MM = MMAssetConfig(
    coin="kPEPE",
    order_size_pct=0.035,     # 3.5% of equity per order
    spread_pct=0.0010,        # 0.10% half-spread
    leverage=3,               # 3x leverage
    max_inventory_pct=0.12,   # Max 12% of equity in inventory
)
```

### Changing Coins

**Scalper:** Edit `config.py` → `BotConfig.assets` dict. Each coin needs an `AssetConfig` with appropriate TP/SL for its volatility.

**MM bot:** Edit `mm_config.py` → `assets` dict. Choose coins with:
1. Wide bid-ask spread (> 0.014% after fees — this is the profit source)
2. No overlap with scalper coins (positions would net)
3. Sufficient liquidity ($100K+ daily volume)
4. 10x leverage available

Use `simulator/coin_optimizer.py` to find optimal parameters for new coins.

## Running Backtests

```bash
# Run from the market-maker venv (has numpy)

# Backtest the scalper strategy
market-maker/venv/bin/python simulator/backtest_scalper.py

# Backtest the MM strategy
market-maker/venv/bin/python simulator/backtest_mm.py

# Optimize TP/SL/trailing for all coins (grid search)
market-maker/venv/bin/python simulator/coin_optimizer.py

# Deep analysis of a single coin
market-maker/venv/bin/python simulator/zec_backtest.py
```

The simulator uses historical price data in `price-history/`. To download fresh data, use the Hyperliquid SDK:

```python
from hyperliquid.info import Info
from hyperliquid.utils import constants
import json, time

info = Info(constants.MAINNET_API_URL, skip_ws=True)
end_time = int(time.time() * 1000)
candles = info.candles_snapshot("BTC", "5m", 5000, end_time)
with open("price-history/BTC_5m.json", "w") as f:
    json.dump(candles, f)
```

## Monitoring

```bash
# Real-time status (one-shot)
market-maker/venv/bin/python monitor/hl_status.py

# Watch mode (refreshes every 30s)
market-maker/venv/bin/python monitor/hl_status.py --watch

# Performance monitor with drawdown alerts
market-maker/venv/bin/python monitor/hl_monitor.py

# JSON output (for logging/automation)
market-maker/venv/bin/python monitor/hl_monitor.py --json
```

### Setting Up with Hermes Agent (Optional)

If you use [Hermes Agent](https://hermes-agent.nousresearch.com), you can set up automated monitoring via a cron job:

```
hermes cron create --name "HL Monitor" --schedule "30m" --deliver origin
```

With the prompt:
```
Run /home/<user>/hyperliquid-trading-kit/market-maker/venv/bin/python
     /home/<user>/hyperliquid-trading-kit/monitor/hl_monitor.py
Report equity, P&L per bot, and any alerts.
```

## Safety Notes

- **Start small:** Test with $50-100 before scaling up
- **Both bots share one account:** They MUST trade non-overlapping coins
- **Monitor regularly:** Check `hl_monitor.py` output daily
- **Backtests are optimistic:** Real fills are lower, slippage exists, signals lag
- **Crypto is risky:** Never trade money you can't afford to lose

## Fee Structure (Hyperliquid)

| Order Type | Fee | Notes |
|-----------|-----|-------|
| Taker (market) | 0.035% | Scalper uses this for entries + exchange TP/SL |
| Maker (limit) | 0.010% | MM bot uses this for both sides |
| Maker rebate | -0.003% | Returned on maker fills |
| Net maker/maker | 0.014% | MM bot round-trip cost (2 × 0.010% - 2 × 0.003%) |
| Net taker/taker | 0.045% | Scalper round-trip cost (2 × 0.035% + 0.003% infra) |

## License

This is provided for educational purposes. Trade at your own risk.