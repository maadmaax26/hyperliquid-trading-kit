"""
Configuration for Hyperliquid Market Maker Bot
Runs on a sub-account with independent margin/positions.

Strategy: Place simultaneous bid/ask limit orders around mid price.
Capture spread + maker rebate (0.003%) on both sides.
Use ADX to widen spreads in trends, tighten in ranges.
Manage inventory with skew and mean-reversion unwind.
"""
import os
from dataclasses import dataclass, field
from typing import Dict
from dotenv import load_dotenv

load_dotenv()


@dataclass
class MMAssetConfig:
    """Per-asset market making parameters."""
    coin: str
    order_size_pct: float          # % of equity per order (notional/leverage)
    spread_pct: float              # Base half-spread (bid/ask distance from mid)
    min_spread_pct: float          # Minimum half-spread (floor)
    max_spread_pct: float          # Maximum half-spread (ceiling)
    max_inventory_pct: float       # Max position size as % of equity (stop quoting on that side)
    inventory_skew_factor: float   # How much to skew prices based on inventory (0-1)
    leverage: int                  # Leverage for this asset
    min_order_notional: float      # Minimum order size in USD ($10 HL limit)


# ═══════════════════════════════════════════════════
# ASSET CONFIGS — coins NOT traded by scalper bot
# Scalper uses: BTC, ETH, SOL, XRP, ZEC, PAXG
# MM bot uses: kPEPE, ARB (no overlap = no conflicts)
# kBONK removed V6: consistently losing (30% WR, adverse selection)
# ═══════════════════════════════════════════════════

KPEPE_MM = MMAssetConfig(
    coin="kPEPE",
    order_size_pct=0.02,           # V6.1: 4%→2% — was causing rapid inventory buildup and forced unwind
    spread_pct=0.0010,             # 0.10% half-spread (raw spread 0.027%, net +0.027%)
    min_spread_pct=0.0004,
    max_spread_pct=0.0040,
    max_inventory_pct=0.20,        # V6.1: 12%→20% — give more room before forced unwind
    inventory_skew_factor=0.6,
    leverage=3,
    min_order_notional=10.0,
)

KBONK_MM = MMAssetConfig(
    coin="kBONK",
    order_size_pct=0.04,           # 4% equity — ensures >$10 min notional at 3x lev even at $80 equity
    spread_pct=0.0012,             # 0.12% half-spread (raw spread 0.033%, net +0.036%)
    min_spread_pct=0.0005,
    max_spread_pct=0.0045,
    max_inventory_pct=0.12,        # 12% per asset (36% total across 3 assets)
    inventory_skew_factor=0.6,
    leverage=3,
    min_order_notional=10.0,
)

ARB_MM = MMAssetConfig(
    coin="ARB",
    order_size_pct=0.04,           # 4% equity — ensures >$10 min notional at 3x lev even at $80 equity
    spread_pct=0.0012,             # 0.12% half-spread (raw spread 0.023%, net +0.020%)
    min_spread_pct=0.0005,
    max_spread_pct=0.0040,
    max_inventory_pct=0.12,        # 12% per asset (36% total across 3 assets)
    inventory_skew_factor=0.6,
    leverage=3,
    min_order_notional=10.0,
)


@dataclass
class MMConfig:
    """Global market maker configuration."""

    # ── Authentication ──────────────────────────────────────────────
    private_key: str = os.getenv("HL_PRIVATE_KEY")
    parent_address: str = os.getenv(
        "HL_PARENT_ADDRESS",
        "0x95d5C0D037fFd7868c5E36518bE474d8BBC457fe",
    )
    sub_account_address: str = os.getenv("HL_SUB_ACCOUNT", "")  # Empty = run on parent
    use_mainnet: bool = os.getenv("USE_MAINNET", "false").lower() in ("true", "1", "yes")

    # ── Timing ──────────────────────────────────────────────────────
    scan_interval_seconds: int = 3          # Fast scan — MM needs to be responsive
    order_refresh_seconds: int = 10         # How often to cancel/replace orders
    candle_interval: str = "1m"             # 1m candles for ADX/volatility
    candles_lookback: int = 100             # 100 candles for indicator calc

    # ── Risk Management ─────────────────────────────────────────────
    max_daily_loss_pct: float = 0.04         # V5: Tightened 10%→4% (backtested improvement)
    max_total_inventory_pct: float = 0.80    # Max total inventory across all assets
    inventory_unwind_threshold: float = 0.70  # Start aggressive unwind at 70% of max
    emergency_close_threshold: float = 0.90  # Close everything at 90%

    # ── ADX-Based Spread Adjustment ─────────────────────────────────
    adx_trend_threshold: float = 25.0       # ADX above this = trending (widen spreads)
    adx_strong_trend: float = 40.0          # ADX above this = strong trend (widen more)
    adx_range_threshold: float = 20.0       # ADX below this = ranging (tighten spreads)
    trend_spread_multiplier: float = 2.0    # Multiply spread by 2x in trends
    strong_trend_multiplier: float = 3.0    # Multiply spread by 3x in strong trends
    range_spread_multiplier: float = 0.7    # Multiply spread by 0.7x in ranges

    # ── V5: Strong trend skip — don't quote in ADX > 40 (adverse selection) ──
    skip_strong_trend: bool = True          # Only unwind existing positions, no new quotes
    min_volume_ratio: float = 0.5            # V5: Skip quoting when volume < 0.5x avg (dead market)

    # ── Inventory Management ────────────────────────────────────────
    skew_power: float = 1.0                 # Linear skew (1.0) vs exponential (>1)
    unwind_spread_multiplier: float = 0.5   # Tighten spread on unwind side to fill faster
    max_hold_minutes: int = 120             # Force unwind positions older than this

    # ── Assets (no overlap with scalper bot) ────────────────────────
    # kPEPE: best volume ($270K/5m) + depth ($848K), net +0.027%/round trip, 78% WR
    # kBONK: REMOVED V6 — 30% WR, adverse selection, consistent losses
    # ARB: REMOVED V6.1 — 33% WR, -$0.50/24h, adverse selection
    assets: Dict[str, MMAssetConfig] = field(default_factory=lambda: {
        "kPEPE": KPEPE_MM,
    })

    # ── Logging ─────────────────────────────────────────────────────
    log_file: str = "mm_bot.log"
    state_file: str = "mm_state.json"
    verbose: bool = True