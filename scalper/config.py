"""
Configuration for Hyperliquid Scalping Bot
All tunable parameters in one place.

═══════════════════════════════════════════════════════════════════
OPTIMIZATION LOG
═══════════════════════════════════════════════════════════════════
v2: Added 30m swing trade strategy alongside 5m scalping.
    Swing targets are 3-4x wider than scalp targets.
    Both strategies run concurrently on different timeframes.

v3: Performance tuning based on 50-trade analysis (38% WR, -$2.65):
    - Widened SL: BTC +40%, ETH +40%, SOL +33% (room to breathe)
    - SOL disabled: min_signal_score=10 (20% WR, worst performer)
    - Signal quality raised: BTC/ETH/XRP 3→5 (fewer, better trades)
    - Leverage reduced: 10x → 7x (less volatile PnL swings)
    - Cooldowns extended: all assets → 120s (avoid chasing losses)
    - SOL swing disabled
    Kept: BB Squeeze (60% WR), trailing stops (100% WR), TP exits (100% WR)
    Expected: 45-50% WR, break-even to +$1-2 per 50 trades

v4: AI ENHANCED - Ollama LLM-powered optimization (46% → 55% WR target):
    - Max positions: 3 → 2 (better focus, less overtrading)
    - Trades/hour: 5 → 3 (quality over quantity, AI recommended)
    - Global cooldown: 60s → 120s (stricter timing)
    - Max session trades: 25 → 20 (harder limit)
    - Multi-signal confluence: Require 2+ indicators (RSI+MACD+EMA+BB)
    - MACD added to scalp signals (was only swing)
    - Volatility-based trailing stops (ATR-adjusted)
    - Position size scaling: -50% in extreme vol, +10% in low vol
    - Dynamic score thresholds: 8-15 based on volatility regime
    - Ollama Model: qwen2.5:7b-instruct
    Expected: 50-55% WR, improved profit factor 1.02 → 1.3+
═══════════════════════════════════════════════════════════════════
"""
import os
from dataclasses import dataclass, field, replace
from typing import Dict
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AssetConfig:
    """Per-asset trading parameters for 5m scalping."""
    coin: str
    take_profit_pct: float          # Price move % for TP
    stop_loss_pct: float            # Price move % for SL
    trailing_activate_pct: float    # Activate trailing stop after this gain
    trailing_stop_pct: float        # Trailing stop distance
    position_size_pct: float        # % of free margin to allocate
    min_signal_score: int           # Minimum score to enter
    cooldown_seconds: int           # Cooldown between trades on same asset
    max_spread_pct: float           # Max bid-ask spread to enter


@dataclass
class SwingConfig:
    """Per-asset trading parameters for 30m swing trades.

    Swing trades hold longer and target larger moves.
    TP/SL are 3-4x wider than scalp equivalents.
    """
    coin: str
    enabled: bool                   # Enable/disable swing for this asset
    take_profit_pct: float          # Wider TP for 30m moves
    stop_loss_pct: float            # Wider SL (more room to breathe)
    trailing_activate_pct: float    # Activate trailing after this gain
    trailing_stop_pct: float        # Trailing stop distance
    position_size_pct: float        # % of free margin (usually smaller than scalp)
    min_signal_score: int           # Higher bar for swing entries
    cooldown_seconds: int           # Longer cooldown between swing trades
    max_spread_pct: float           # Max spread to enter
    max_hold_minutes: int           # Max hold time before force-close


# ═══════════════════════════════════════════════════════════════
# 5m SCALP CONFIGS (unchanged from optimized values)
# ═══════════════════════════════════════════════════════════════

BTC_CONFIG = AssetConfig(
    coin="BTC",
    take_profit_pct=0.0032,         # V6: 0.21%→0.32% (1.5x) — fees were 33% of TP, now 22%. BE WR 70%→57%
    stop_loss_pct=0.0025,           # Keep 0.25% SL
    trailing_activate_pct=0.0023,   # V6: 0.15%→0.23% — activate later (matches wider TP)
    trailing_stop_pct=0.0006,       # V6: 0.04%→0.06% — slightly wider trail for bigger moves
    position_size_pct=0.25,         # V6: 35%→25% equal sizing, max 5 positions
    min_signal_score=10,
    cooldown_seconds=300,           # V6.1: 120→300 — reduce churning/fees
    max_spread_pct=0.001,
)

ETH_CONFIG = AssetConfig(
    coin="ETH",
    take_profit_pct=0.0030,         # V6.1: 0.38%→0.30% — was too wide, only 14 fills/24h, 29% WR
    stop_loss_pct=0.0030,           # Keep 0.30% SL
    trailing_activate_pct=0.0025,   # V6: 0.17%→0.25% — activate later
    trailing_stop_pct=0.0006,       # V6: 0.04%→0.06% — slightly wider trail
    position_size_pct=0.25,         # V6: 30%→25% equal sizing
    min_signal_score=10,
    cooldown_seconds=300,           # V6.1: 120→300 — reduce churning/fees
    max_spread_pct=0.001,
)

SOL_CONFIG = AssetConfig(
    coin="SOL",
    take_profit_pct=0.0045,         # V6: 0.30%→0.45% (1.5x) — fees 23%→16% of TP. BE WR 67%→55%
    stop_loss_pct=0.0040,           # Keep 0.40% SL
    trailing_activate_pct=0.0035,   # V6: 0.23%→0.35% — activate later
    trailing_stop_pct=0.0009,       # V6: 0.06%→0.09% — wider trail for SOL volatility
    position_size_pct=0.25,         # V6: 20%→25% equal sizing
    min_signal_score=9,             # V5: Re-enabled at 9 (was disabled at 20)
    cooldown_seconds=300,           # V6.1: 120→300 — reduce churning/fees
    max_spread_pct=0.0015,
)

XRP_CONFIG = AssetConfig(
    coin="XRP",
    take_profit_pct=0.0034,         # V6: 0.23%→0.34% (1.5x) — fees 30%→20% of TP. BE WR 67%→54%
    stop_loss_pct=0.0035,           # V6.1: 0.25%→0.35% — was too tight, 43% WR, stopped on noise
    trailing_activate_pct=0.0025,   # V6: 0.17%→0.25% — activate later
    trailing_stop_pct=0.0006,       # V6: 0.04%→0.06% — slightly wider trail
    position_size_pct=0.25,         # V6: 20%→25% equal sizing
    min_signal_score=10,
    cooldown_seconds=300,           # V6.1: 120→300 — reduce churning/fees
    max_spread_pct=0.001,
)

PAXG_CONFIG = AssetConfig(
    coin="PAXG",
    take_profit_pct=0.0030,
    stop_loss_pct=0.0018,
    trailing_activate_pct=0.0020,
    trailing_stop_pct=0.0010,
    position_size_pct=0.15,         # V6: keep small — PAXG barely moves
    min_signal_score=5,
    cooldown_seconds=300,           # V6.1: 120→300 — reduce churning/fees
    max_spread_pct=0.002,
)

ZEC_CONFIG = AssetConfig(
    coin="ZEC",
    take_profit_pct=0.0060,         # V6.1: 0.42%→0.60% (2x ATR) — better R:R, wider for trend captures
    stop_loss_pct=0.0045,           # V6.1: 0.30%→0.45% (1.5x ATR) — was 1.0 ATR, too tight, noise stopped out
    trailing_activate_pct=0.0030,   # V6: 0.20%→0.30% — activate later
    trailing_stop_pct=0.0015,       # V6.1: 0.09%→0.15% (0.5 ATR) — wider trail for trend moves
    position_size_pct=0.25,         # V6: 20%→25% equal sizing
    min_signal_score=10,            # V6.1: RE-ENABLED (was 99/disabled) — trend filter now works
    cooldown_seconds=300,           # V6.1: 180→300 — reduce churning/fees
    max_spread_pct=0.002,           # ZEC spreads tend to be wider than BTC/ETH
)


# ═══════════════════════════════════════════════════════════════
# 30m SWING CONFIGS
#
# Swing trades target 3-4x larger moves than scalps.
# Typical 30m price ranges:
#   BTC: 0.15-0.60%    → TP 0.80%, SL 0.45%
#   ETH: 0.20-0.80%    → TP 1.00%, SL 0.50%
#   SOL: 0.30-1.20%    → TP 1.30%, SL 0.65%
#   XRP: 0.20-0.80%    → TP 1.00%, SL 0.50%
#   PAXG: 0.05-0.25%   → TP 0.50%, SL 0.30%
# ═══════════════════════════════════════════════════════════════

BTC_SWING = SwingConfig(
    coin="BTC",
    enabled=True,
    take_profit_pct=0.010,          # 1.0% price → 10% at 10x leverage (increased)
    stop_loss_pct=0.0040,           # tightened SL to improve RR
    trailing_activate_pct=0.007,    # Activate trail slightly earlier
    trailing_stop_pct=0.0025,       # tighter trailing stop
    position_size_pct=0.25,         # increased allocation for strong performer
    min_signal_score=5,             # Higher bar for swing entry
    cooldown_seconds=300,           # 5 min cooldown between swings
    max_spread_pct=0.001,
    max_hold_minutes=180,           # Reduced max hold to limit tail risk
)

ETH_SWING = SwingConfig(
    coin="ETH",
    enabled=True,
    take_profit_pct=0.011,          # small TP bump
    stop_loss_pct=0.005,            # keep SL
    trailing_activate_pct=0.007,
    trailing_stop_pct=0.003,        # slightly tighter trailing
    position_size_pct=0.18,         # keep allocation
    min_signal_score=5,
    cooldown_seconds=300,
    max_spread_pct=0.001,
    max_hold_minutes=180,           # reduced hold
)

SOL_SWING = SwingConfig(
    coin="SOL",
    enabled=True,                   # Enabled based on backtest strengths
    take_profit_pct=0.015,          # increased TP
    stop_loss_pct=0.0055,           # tightened SL
    trailing_activate_pct=0.010,
    trailing_stop_pct=0.003,        # tighter trailing
    position_size_pct=0.22,         # increased allocation for SOL
    min_signal_score=5,
    cooldown_seconds=300,
    max_spread_pct=0.0015,
    max_hold_minutes=180,           # reduced hold
)

XRP_SWING = SwingConfig(
    coin="XRP",
    enabled=True,
    take_profit_pct=0.010,
    stop_loss_pct=0.005,
    trailing_activate_pct=0.007,
    trailing_stop_pct=0.0035,
    position_size_pct=0.15,
    min_signal_score=5,
    cooldown_seconds=300,
    max_spread_pct=0.001,
    max_hold_minutes=240,
)

PAXG_SWING = SwingConfig(
    coin="PAXG",
    enabled=False,                  # Disabled — too low volatility for swing
    take_profit_pct=0.005,
    stop_loss_pct=0.003,
    trailing_activate_pct=0.003,
    trailing_stop_pct=0.0015,
    position_size_pct=0.10,
    min_signal_score=6,
    cooldown_seconds=600,
    max_spread_pct=0.002,
    max_hold_minutes=180,
)

ZEC_SWING = SwingConfig(
    coin="ZEC",
    enabled=True,                   # ZEC is volatile enough for swing
    take_profit_pct=0.018,          # Wide TP — ZEC 30m moves can be 2-3%+
    stop_loss_pct=0.006,            # R:R 3.0 — ZEC's 41% WR needs generous R:R
    trailing_activate_pct=0.012,
    trailing_stop_pct=0.004,
    position_size_pct=0.18,         # Moderate — ZEC is high-vol
    min_signal_score=7,             # Higher bar than scalp (swing needs conviction)
    cooldown_seconds=600,           # 10 min cooldown — don't overtrade ZEC
    max_spread_pct=0.002,
    max_hold_minutes=240,           # 4h max hold
)


@dataclass
class BotConfig:
    """Global bot configuration."""

    # ── Authentication ──────────────────────────────────────────────
    private_key: str = os.getenv("HL_PRIVATE_KEY")  # MUST be set in .env (no hardcoded default)
    if private_key is None:
        raise RuntimeError("HL_PRIVATE_KEY not set in environment/.env — set it before starting the bot.")
    parent_address: str = os.getenv(
        "HL_PARENT_ADDRESS",
        "0xYOUR_PARENT_WALLET_ADDRESS",
    )
    use_mainnet: bool = os.getenv("USE_MAINNET", "false").lower() in ("true", "1", "yes")

    # ── Leverage ────────────────────────────────────────────────────
    leverage: int = 10                        # V6: 7x→10x — targets 3-5% per win on margin
    cross_margin: bool = False

    # ── Risk Management ─────────────────────────────────────────────
    # V5 ENHANCED: Backtested improvements (49% WR→54%, DD 12.7%→6.95%, Sharpe 2.84→3.46)
    max_concurrent_positions: int = 5     # V6: 3→5 — all coins can trade simultaneously, equal 25% sizing
    max_concurrent_swing: int = 0         # V5: Swing disabled (29.1% WR, -$109 drag in backtest)
    max_daily_loss_pct: float = 0.04      # V5: Tightened 5%→4% (DD 12.7%→6.95%)
    max_consecutive_losses: int = 3
    loss_cooldown_seconds: int = 600
    max_position_pct: float = 0.175       # 17.5% equity per position (shared with MM bot)
    swing_margin_reserve: float = 0.0     # V5: No swing margin reserved (swing disabled)

    # ── Timing ──────────────────────────────────────────────────────
    scan_interval_seconds: int = 5
    candle_interval: str = "5m"            # Scalp timeframe (matches TP/SL design + signal labels)
    candle_interval_fast: str = "5m"       # Fast check timeframe
    candle_interval_swing: str = "1h"      # Swing timeframe (Changed from 4h - API limit workaround)
    candles_lookback: int = 300            # Increased lookback for higher timeframes
    swing_candles_lookback: int = 100      # Reduced: 100 x 1h = ~4 days (API friendly)

    # ── Trade Frequency Controls (V3 CRITICAL FIXES) ─────────────────
    # Prevent overtrading that caused massive losses in v2
    # AI ENHANCED (v4): Reduced for ranging market optimization
    coin_cooldown_seconds: int = 600       # 10 min between same asset trades
    global_cooldown_seconds: int = 120      # AI: Increased 60s→120s (stricter)
    max_trades_per_hour: int = 3            # AI: Reduced 5→3 (avoid overtrading)
    max_trades_per_session: int = 20       # AI: Reduced 25→20 (quality focus)

    # ── Strategy Toggle ─────────────────────────────────────────────
    enable_scalp: bool = True
    enable_swing: bool = False  # V5: Disabled — swing had 29.1% WR, -$109 drag in backtest

    # ── Assets ──────────────────────────────────────────────────────
    assets: Dict[str, AssetConfig] = field(default_factory=lambda: {
        "BTC": BTC_CONFIG,                                  # ACTIVE SCALP
        "ETH": ETH_CONFIG,                                  # ACTIVE SCALP
        "SOL": replace(SOL_CONFIG, min_signal_score=9),     # V5: Re-enabled at 9 (was disabled at 20, backtest shows +$49 at 53% WR)
        "XRP": XRP_CONFIG,                                  # ACTIVE SCALP (Best performer)
        "ZEC": ZEC_CONFIG,                                   # ACTIVE SCALP (tuned for ZEC volatility)
        "PAXG": replace(PAXG_CONFIG, min_signal_score=99),  # V6.1: DISABLED — low volatility, not profitable
    })

    swing_assets: Dict[str, SwingConfig] = field(default_factory=lambda: {
        "BTC": replace(BTC_SWING, enabled=False),       # V5: Swing disabled
        "ETH": replace(ETH_SWING, enabled=False),
        "SOL": replace(SOL_SWING, enabled=False),
        "XRP": replace(XRP_SWING, enabled=False),
        "ZEC": replace(ZEC_SWING, enabled=False),
        "PAXG": replace(PAXG_SWING, enabled=False),
    })

    # ── Logging ─────────────────────────────────────────────────────
    log_file: str = "scalper.log"
    trade_log_file: str = "trades.json"
    state_file: str = "bot_state.json"
    verbose: bool = True