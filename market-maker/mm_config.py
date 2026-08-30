"""
Configuration for Hyperliquid Market Maker Bot
Runs on a sub-account with independent margin/positions.

Strategy: Place simultaneous bid/ask limit orders around mid price.
Capture spread + maker rebate (0.003%) on both sides.
Use ADX to widen spreads in trends, tighten in ranges.
Manage inventory with skew and mean-reversion unwind.

V6.2: Switched from kPEPE to XMR + TAO based on L2 spread analysis.
  - XMR: 0.0443% spread, $53M vol, $17K depth — 277x better MM score than kPEPE
  - TAO: 0.0334% spread, $8.6M vol, $5.9K depth — 119x better MM score than kPEPE
  - kPEPE removed: $296K depth = too much competition, low fill share
  - Both XMR/TAO: max 5x leverage, 3 sz decimals
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
# Scalper uses: BTC, ETH, SOL, XRP, ZEC (PAXG disabled)
# MM bot uses: XMR, TAO (no overlap = no conflicts)
#
# V6.2 CHANGES:
#   - kPEPE REMOVED: $296K depth = too much competition, low fill share, MM score 0.0002
#   - XMR ADDED: 0.0443% spread, $53M vol, $17K depth — MM score 0.0650 (277x better)
#   - TAO ADDED: 0.0334% spread, $8.6M vol, $5.9K depth — MM score 0.0280 (119x better)
#   - Both max 5x leverage (HL limit), 3 sz decimals
#   - Order size 3% × 5x = $17.88 notional at $119 equity (above $10 min)
# ═══════════════════════════════════════════════════

XMR_MM = MMAssetConfig(
    coin="XMR",
    order_size_pct=0.02,           # V6.2: 2% × 5x = $12.40 notional (above $10 min), ~50% of cap per fill
    spread_pct=0.0015,             # 0.15% half-spread (raw spread 0.044%, net edge +0.030%/RT)
    min_spread_pct=0.0006,         # 0.06% floor — never quote tighter than this
    max_spread_pct=0.0050,         # 0.50% ceiling — in extreme trends, widen up to this
    max_inventory_pct=0.30,        # V6.2: 20%→30% — $37.20 cap, 3 fills before block
    inventory_skew_factor=0.6,     # Skew quotes 60% based on inventory direction
    leverage=5,                    # HL max for XMR = 5x
    min_order_notional=10.0,       # $10 HL minimum
)

TAO_MM = MMAssetConfig(
    coin="TAO",
    order_size_pct=0.02,           # V6.2: 2% × 5x = $12.40 notional (above $10 min)
    spread_pct=0.0012,             # 0.12% half-spread (raw spread 0.033%, net edge +0.019%/RT)
    min_spread_pct=0.0005,         # 0.05% floor
    max_spread_pct=0.0045,         # 0.45% ceiling
    max_inventory_pct=0.30,        # V6.2: 20%→30% — match XMR
    inventory_skew_factor=0.6,
    leverage=5,                    # HL max for TAO = 5x
    min_order_notional=10.0,
)

# Kept for reference but NOT active
KPEPE_MM = MMAssetConfig(
    coin="kPEPE",
    order_size_pct=0.03,
    spread_pct=0.0010,
    min_spread_pct=0.0004,
    max_spread_pct=0.0040,
    max_inventory_pct=0.20,
    inventory_skew_factor=0.6,
    leverage=6,
    min_order_notional=10.0,
)


@dataclass
class MMConfig:
    """Global market maker configuration."""

    # ── Authentication ──────────────────────────────────────────────
    private_key: str = os.getenv("HL_PRIVATE_KEY")
    parent_address: str = os.getenv(
        "HL_PARENT_ADDRESS",
        "0xYOUR_PARENT_WALLET_ADDRESS",
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
    # V6.2: XMR + TAO replace kPEPE
    # XMR: 0.0443% spread, $53M vol, $17K depth — 277x better MM score than kPEPE
    # TAO: 0.0334% spread, $8.6M vol, $5.9K depth — 119x better MM score than kPEPE
    # kPEPE removed: $296K depth = too much competition, low fill share
    assets: Dict[str, MMAssetConfig] = field(default_factory=lambda: {
        "XMR": XMR_MM,
        "TAO": TAO_MM,
    })

    # ── Logging ─────────────────────────────────────────────────────
    log_file: str = "mm_bot.log"
    state_file: str = "mm_state.json"
    verbose: bool = True