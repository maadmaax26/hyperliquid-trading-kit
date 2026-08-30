"""
Hyperliquid Market Maker Bot
Runs on a sub-account — independent from the scalper bot.

Strategy:
  1. Place bid/ask limit orders around mid price for each asset
  2. Capture bid-ask spread + maker rebate (0.003%) on both sides
  3. ADX-based dynamic spread: widen in trends, tighten in ranges
  4. Inventory skew: shift prices based on position to encourage mean reversion
  5. Risk: max inventory limits, daily loss cap, forced unwind

Architecture:
  - Uses the same API agent key as the scalper (approved on parent wallet)
  - Trades on sub-account via account_address parameter
  - WebSocket for price feeds (reduces REST polling)
  - Cancel/replace orders every N seconds to track mid price
"""
import time
import json
import logging
import signal as sig_module
import sys
import math
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account
from dotenv import load_dotenv

from mm_config import MMConfig, MMAssetConfig

load_dotenv()

# ── Logging setup ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("mm_bot.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("mm_bot")


# ════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS (lightweight — just what MM needs)
# ════════════════════════════════════════════════════════════════════

def calculate_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Calculate ADX (trend strength indicator)."""
    if len(highs) < period + 1:
        return 0.0

    dm_plus = np.maximum(highs[1:] - highs[:-1], 0)
    dm_minus = np.maximum(lows[:-1] - lows[1:], 0)

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )

    atr_smooth = np.zeros(len(tr))
    atr_smooth[period - 1] = np.mean(tr[:period])

    dm_plus_smooth = np.zeros(len(dm_plus))
    dm_plus_smooth[period - 1] = np.mean(dm_plus[:period])

    dm_minus_smooth = np.zeros(len(dm_minus))
    dm_minus_smooth[period - 1] = np.mean(dm_minus[:period])

    for i in range(period, len(tr)):
        atr_smooth[i] = (atr_smooth[i - 1] * (period - 1) + tr[i]) / period
        dm_plus_smooth[i] = (dm_plus_smooth[i - 1] * (period - 1) + dm_plus[i]) / period
        dm_minus_smooth[i] = (dm_minus_smooth[i - 1] * (period - 1) + dm_minus[i]) / period

    atr_safe = np.where(atr_smooth == 0, 1e-10, atr_smooth)
    di_plus = 100 * dm_plus_smooth / atr_safe
    di_minus = 100 * dm_minus_smooth / atr_safe
    dx = 100 * np.abs(di_plus - di_minus) / (di_plus + di_minus + 1e-10)

    if len(dx) >= period:
        return float(np.mean(dx[-period:]))
    return 0.0


def calculate_atr_pct(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """Calculate ATR as a percentage of price (volatility measure)."""
    if len(highs) < 2:
        return 0.0
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    if len(tr) >= period:
        atr = np.mean(tr[-period:])
        avg_price = np.mean(closes[-period:])
        return float(atr / avg_price) if avg_price > 0 else 0.0
    return 0.0


# ════════════════════════════════════════════════════════════════════
# ORDER TRACKING
# ════════════════════════════════════════════════════════════════════

@dataclass
class MMOrder:
    """Tracked market maker order."""
    coin: str
    side: str           # "B" (buy/bid) or "A" (sell/ask)
    size: float
    price: float
    oid: Optional[int] = None
    is_reduce_only: bool = False
    placed_at: float = 0.0


@dataclass
class MMInventory:
    """Current inventory state for an asset."""
    coin: str
    position_size: float = 0.0       # positive = long, negative = short
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    margin_used: float = 0.0
    orders: List[MMOrder] = field(default_factory=list)
    last_mid: float = 0.0
    adx: float = 0.0
    atr_pct: float = 0.0
    last_refresh: float = 0.0


# ════════════════════════════════════════════════════════════════════
# MARKET MAKER BOT
# ════════════════════════════════════════════════════════════════════

class HyperliquidMarketMaker:
    """Market maker bot that places bid/ask grids around mid price."""

    def __init__(self, config: MMConfig):
        self.config = config
        self.running = False

        # ── Connect to Hyperliquid ───────────────────────────────────
        # If sub_account_address is set, trade on sub-account
        # If empty, trade on parent (shared with scalper, but different coins)
        use_sub = bool(config.sub_account_address)
        trade_address = config.sub_account_address if use_sub else config.parent_address

        log.info("🔗 Connecting to Hyperliquid...")
        self.account = Account.from_key(config.private_key)
        self.api_address = self.account.address
        log.info(f"📍 API Wallet:    {self.api_address}")
        log.info(f"📍 Trading on:    {trade_address} {'(sub-account)' if use_sub else '(parent)'}")
        if use_sub:
            log.info(f"📍 Parent Wallet: {config.parent_address}")

        base_url = (
            constants.MAINNET_API_URL if config.use_mainnet
            else constants.TESTNET_API_URL
        )

        # Info queries the trading address
        self.info = Info(base_url, skip_ws=True)
        self.trade_address = trade_address

        # Exchange: use account_address for sub-account, or plain for parent
        if use_sub:
            self.exchange = Exchange(
                self.account,
                base_url,
                account_address=trade_address,
            )
        else:
            self.exchange = Exchange(self.account, base_url)

        # ── Load exchange metadata ──────────────────────────────────
        self.meta = self.info.meta()
        self.sz_decimals: Dict[str, int] = {}
        self.max_leverage: Dict[str, int] = {}

        for asset in self.meta["universe"]:
            name = asset["name"]
            self.sz_decimals[name] = asset["szDecimals"]
            self.max_leverage[name] = asset.get("maxLeverage", 50)

        # ── State ───────────────────────────────────────────────────
        self.inventories: Dict[str, MMInventory] = {
            coin: MMInventory(coin=coin) for coin in config.assets
        }
        self.daily_pnl: float = 0.0
        self.daily_pnl_date = datetime.now(timezone.utc).date()
        self.cycle_count: int = 0
        self.start_time: float = time.time()

        # ── Setup leverage for all assets ───────────────────────────
        self._setup_leverage()

        # ── Get initial equity ──────────────────────────────────────
        equity = self._get_equity()
        log.info(f"💰 Sub-account equity: ${equity:.2f}")

        if equity < 10:
            log.warning(f"⚠️  Low equity (${equity:.2f}) — need at least $10 per order")

        log.info(f"📋 Assets: {list(config.assets.keys())}")
        log.info(f"📋 Scan: every {config.scan_interval_seconds}s | "
                 f"Order refresh: every {config.order_refresh_seconds}s")

    # ════════════════════════════════════════════════════════════════
    # ACCOUNT QUERIES (sub-account scoped)
    # ════════════════════════════════════════════════════════════════

    def _get_equity(self) -> float:
        """Get sub-account equity (includes spot USDC for unified accounts)."""
        try:
            state = self.info.user_state(self.trade_address)
            margin = state.get("crossMarginSummary", state.get("marginSummary", {}))
            equity = float(margin.get("accountValue", 0))

            # For sub-accounts with unified accounts, spot USDC serves as margin
            # but is not reflected in crossMarginSummary. Add it manually.
            if equity == 0:
                try:
                    spot = self.info.spot_user_state(self.trade_address)
                    for b in spot.get("balances", []):
                        if b.get("coin") == "USDC":
                            equity += float(b.get("total", 0))
                except Exception:
                    pass

            if equity == 0:
                equity = float(state.get("withdrawable", 0))
            return equity
        except Exception as e:
            log.error(f"Failed to get equity: {e}")
            return 0.0

    def _get_free_margin(self) -> float:
        """Get available margin."""
        try:
            state = self.info.user_state(self.trade_address)
            margin = state.get("marginSummary", {})
            equity = float(margin.get("accountValue", 0))
            used = float(margin.get("totalMarginUsed", 0))
            return equity - used
        except Exception as e:
            log.error(f"Failed to get free margin: {e}")
            return 0.0

    def _sync_exchange_state(self):
        """Sync positions and orders from exchange.
        
        V6.2: Track realized PnL by comparing equity changes to unrealized PnL.
        When equity changes more than unrealized PnL explains, the difference is realized.
        """
        try:
            state = self.info.user_state(self.trade_address)
            
            # V6.2: Track realized PnL via equity delta method
            new_equity = float(state.get("marginSummary", {}).get("accountValue", 0))
            total_unrealized_new = 0.0
            
            exchange_positions = {}
            for p in state.get("assetPositions", []):
                pos = p.get("position", {})
                coin = pos.get("coin", "")
                size = float(pos.get("szi", 0))
                if abs(size) > 0:
                    exchange_positions[coin] = {
                        "size": size,
                        "entry_price": float(pos.get("entryPx", 0)),
                        "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                        "margin_used": float(pos.get("marginUsed", 0)),
                    }
                    total_unrealized_new += float(pos.get("unrealizedPnl", 0))

            # V6.2: Realized PnL = equity change - unrealized PnL change
            # This captures fills that closed positions for a profit/loss
            if hasattr(self, '_prev_equity') and hasattr(self, '_prev_unrealized'):
                equity_delta = new_equity - self._prev_equity
                unrealized_delta = total_unrealized_new - self._prev_unrealized
                realized_delta = equity_delta - unrealized_delta
                if abs(realized_delta) > 0.001:  # Only count non-trivial changes
                    self.daily_pnl += realized_delta
                    if abs(realized_delta) > 0.01:  # Log only meaningful amounts
                        log.info(f"💰 Realized PnL: ${realized_delta:+.2f} (equity Δ${equity_delta:+.2f}, uPnL Δ${unrealized_delta:+.2f}) → daily total: ${self.daily_pnl:+.2f}")
            self._prev_equity = new_equity
            self._prev_unrealized = total_unrealized_new

            # Update inventories
            for coin, inv in self.inventories.items():
                if coin in exchange_positions:
                    ep = exchange_positions[coin]
                    inv.position_size = ep["size"]
                    inv.entry_price = ep["entry_price"]
                    inv.unrealized_pnl = ep["unrealized_pnl"]
                    inv.margin_used = ep["margin_used"]
                else:
                    inv.position_size = 0.0
                    inv.entry_price = 0.0
                    inv.unrealized_pnl = 0.0
                    inv.margin_used = 0.0

        except Exception as e:
            log.error(f"Failed to sync exchange state: {e}")

    def _get_open_orders(self) -> List[Dict]:
        """Get open orders on sub-account."""
        try:
            try:
                return self.info.frontend_open_orders(self.trade_address)
            except Exception:
                return self.info.open_orders(self.trade_address)
        except Exception as e:
            log.error(f"Failed to get open orders: {e}")
            return []

    def _get_mid_prices(self) -> Dict[str, float]:
        """Fetch current mid prices."""
        try:
            all_mids = self.info.all_mids()
            prices = {}
            for coin in self.config.assets:
                if coin in all_mids:
                    prices[coin] = float(all_mids[coin])
            return prices
        except Exception as e:
            log.error(f"Failed to fetch prices: {e}")
            return {}

    def _get_l2(self, coin: str) -> Optional[Tuple[float, float]]:
        """Get best bid/ask from L2 snapshot."""
        try:
            book = self.info.l2_snapshot(coin)
            if book and "levels" in book:
                levels = book["levels"]
                if len(levels) >= 2 and len(levels[0]) > 0 and len(levels[1]) > 0:
                    best_bid = float(levels[0][0]["px"])
                    best_ask = float(levels[1][0]["px"])
                    return best_bid, best_ask
        except Exception as e:
            log.debug(f"Failed to get L2 for {coin}: {e}")
        return None

    def _fetch_candles(self, coin: str) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Fetch OHLCV candles for indicator calculation."""
        try:
            end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
            interval_ms = {"1m": 60_000, "3m": 180_000, "5m": 300_000}
            ms = interval_ms.get(self.config.candle_interval, 60_000)
            start_time = end_time - (self.config.candles_lookback * ms)

            candles = self.info.candles_snapshot(
                coin, self.config.candle_interval, start_time, end_time
            )
            if not candles or len(candles) < 30:
                return None

            highs = np.array([float(c["h"]) for c in candles])
            lows = np.array([float(c["l"]) for c in candles])
            closes = np.array([float(c["c"]) for c in candles])
            return highs, lows, closes
        except Exception as e:
            log.debug(f"Failed to fetch candles for {coin}: {e}")
            return None

    # ════════════════════════════════════════════════════════════════
    # LEVERAGE SETUP
    # ════════════════════════════════════════════════════════════════

    def _setup_leverage(self):
        """Set leverage for all traded assets on sub-account."""
        for coin, cfg in self.config.assets.items():
            try:
                max_lev = self.max_leverage.get(coin, 50)
                lev = min(cfg.leverage, max_lev)
                self.exchange.update_leverage(lev, coin, is_cross=True)
                log.info(f"⚙️ {coin} leverage set to {lev}x (cross)")
            except Exception as e:
                log.error(f"Failed to set {coin} leverage: {e}")

    # ════════════════════════════════════════════════════════════════
    # ORDER MANAGEMENT
    # ════════════════════════════════════════════════════════════════

    def _round_price(self, price: float, coin: str) -> float:
        """Round price to Hyperliquid precision."""
        if price == 0:
            return 0.0
        sig_figs = 5
        magnitude = math.floor(math.log10(abs(price))) + 1
        decimals = max(0, min(sig_figs - magnitude, 5))  # cap at 5 decimals (HL max for small prices)
        return round(price, decimals)

    def _round_size(self, size: float, coin: str) -> float:
        """Round size to exchange precision."""
        dec = self.sz_decimals.get(coin, 4)
        return round(size, dec)

    def _place_order(self, coin: str, is_buy: bool, size: float, price: float,
                     reduce_only: bool = False) -> Optional[int]:
        """Place a limit order (maker). Returns order OID or None."""
        try:
            size = self._round_size(size, coin)
            price = self._round_price(price, coin)

            if size <= 0:
                return None

            result = self.exchange.order(
                coin, is_buy, size, price,
                {"limit": {"tif": "Gtc"}},  # Gtc = resting maker order
                reduce_only=reduce_only,
            )

            if result and result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "resting" in statuses[0]:
                    oid = statuses[0]["resting"]["oid"]
                    side = "B" if is_buy else "A"
                    log.debug(f"📌 {coin} {side} order placed: {size} @ {price} (oid={oid})")
                    return int(oid)
                elif statuses and "filled" in statuses[0]:
                    # Immediate fill (shouldn't happen with maker orders, but handle it)
                    log.info(f"✅ {coin} order filled immediately: {size} @ {price}")
                    return None  # No OID to track — already filled
                elif statuses and "error" in statuses[0]:
                    log.warning(f"⚠️ {coin} order rejected: {statuses[0]['error']}")
                    return None

            log.warning(f"⚠️ Unexpected order response for {coin}: {result}")
            return None

        except Exception as e:
            log.error(f"❌ Error placing order for {coin}: {e}")
            return None

    def _cancel_order(self, coin: str, oid: int):
        """Cancel an order by OID."""
        try:
            self.exchange.cancel(coin, int(oid))
        except Exception as e:
            log.debug(f"Cancel error for {coin} oid={oid}: {e}")

    def _cancel_all_orders(self, coin: str):
        """Cancel all open orders for a coin."""
        open_orders = self._get_open_orders()
        for o in open_orders:
            if o.get("coin") == coin:
                oid = o.get("oid")
                if oid:
                    self._cancel_order(coin, int(oid))
        log.debug(f"🧹 Cancelled all orders for {coin}")

    def _cancel_all_orders_all_coins(self):
        """Cancel all orders across all coins."""
        open_orders = self._get_open_orders()
        for o in open_orders:
            coin = o.get("coin", "")
            oid = o.get("oid")
            if oid and coin:
                self._cancel_order(coin, int(oid))
        log.info(f"🧹 Cancelled all orders ({len(open_orders)} total)")

    # ════════════════════════════════════════════════════════════════
    # PRICING ENGINE — spread calculation + ADX adjustment + inventory skew
    # ════════════════════════════════════════════════════════════════

    def _calculate_spread(self, coin: str, adx: float, atr_pct: float) -> float:
        """Calculate dynamic half-spread based on ADX and volatility.

        ADX > 40 (strong trend): spread × 3.0 (avoid adverse selection)
        ADX > 25 (trending):     spread × 2.0
        ADX < 20 (ranging):      spread × 0.7 (tighten to capture more)
        ADX 20-25 (neutral):     base spread
        """
        cfg = self.config.assets[coin]
        base_spread = cfg.spread_pct

        # ADX-based adjustment
        if adx > self.config.adx_strong_trend:
            multiplier = self.config.strong_trend_multiplier
            regime = "STRONG TREND"
        elif adx > self.config.adx_trend_threshold:
            multiplier = self.config.trend_spread_multiplier
            regime = "TRENDING"
        elif adx < self.config.adx_range_threshold:
            multiplier = self.config.range_spread_multiplier
            regime = "RANGING"
        else:
            multiplier = 1.0
            regime = "NEUTRAL"

        # Also factor in ATR — higher volatility = wider spread
        # Use max of ADX-adjusted and ATR-based spread
        atr_spread = max(base_spread, atr_pct * 0.3)  # 30% of ATR as minimum

        spread = max(base_spread * multiplier, atr_spread)
        spread = min(spread, cfg.max_spread_pct)
        spread = max(spread, cfg.min_spread_pct)

        return spread, regime

    def _calculate_inventory_skew(self, coin: str, position_size: float, equity: float) -> float:
        """Calculate price skew based on inventory.

        When long: skew both orders down (lower bid and ask to encourage selling)
        When short: skew both orders up (encourage buying)

        Returns skew as a fraction of spread to shift prices.
        """
        cfg = self.config.assets[coin]
        max_inv = equity * cfg.max_inventory_pct * cfg.leverage

        if max_inv <= 0:
            return 0.0

        # Normalized inventory: -1 to +1
        inv_ratio = position_size / max_inv if max_inv > 0 else 0
        inv_ratio = max(-1.0, min(1.0, inv_ratio))

        # Apply skew
        skew = inv_ratio * cfg.inventory_skew_factor * cfg.spread_pct

        # If near max inventory, increase unwind pressure
        if abs(inv_ratio) > self.config.inventory_unwind_threshold:
            skew *= 2.0  # Double the skew to force unwind

        return skew

    def _should_quote_side(self, coin: str, position_size: float, equity: float, is_buy: bool) -> bool:
        """Check if we should quote on a given side based on inventory limits.
        
        V6.2 FIX: Inventory cap was multiplied by leverage, making it 5x too high.
        max_inventory_pct is a fraction of EQUITY (not equity × leverage).
        e.g. 20% of $110 = $22 max inventory, not $22 × 5 = $110.
        """
        cfg = self.config.assets[coin]
        # V6.2 FIX: Remove leverage from cap — max_inventory_pct is % of equity, not notional
        max_inv_usd = equity * cfg.max_inventory_pct

        current_inv_usd = abs(position_size) * self.inventories[coin].last_mid

        # If at 80% of max inventory, stop quoting on the side that would increase it
        if current_inv_usd >= max_inv_usd * 0.80:
            if position_size > 0 and not is_buy:
                # Long and at/near max — can still sell (reduce)
                return True
            elif position_size < 0 and is_buy:
                # Short and at/near max — can still buy (reduce)
                return True
            else:
                return False  # Would increase inventory beyond max

        return True

    # ════════════════════════════════════════════════════════════════
    # QUOTING ENGINE
    # ════════════════════════════════════════════════════════════════

    def _update_quotes(self, coin: str, mid_price: float, equity: float):
        """Update bid/ask quotes for a single asset."""
        cfg = self.config.assets[coin]
        inv = self.inventories[coin]

        # V5: Skip quoting in strong trends (ADX > 40) — adverse selection risk
        if self.config.skip_strong_trend and inv.adx > self.config.adx_strong_trend:
            log.info(f"📊 {coin}: ADX={inv.adx:.0f} > {self.config.adx_strong_trend} — strong trend, skipping new quotes")
            return

        # V5: Skip quoting in dead markets (low volume)
        if hasattr(inv, 'volume_ratio') and inv.volume_ratio < self.config.min_volume_ratio:
            log.debug(f"📊 {coin}: Volume {inv.volume_ratio:.2f}x < {self.config.min_volume_ratio}x — dead market, skipping")
            return

        # Calculate dynamic spread
        spread, regime = self._calculate_spread(coin, inv.adx, inv.atr_pct)

        # Calculate inventory skew
        skew = self._calculate_inventory_skew(coin, inv.position_size, equity)

        # Calculate bid/ask prices
        # Base: mid ± spread, then apply skew
        bid_price = mid_price * (1 - spread + skew)
        ask_price = mid_price * (1 + spread + skew)

        # V6.2 FIX: Calculate inv_ratio once (without leverage) — used for unwind threshold
        inv_ratio = (inv.position_size * mid_price) / (equity * cfg.max_inventory_pct) if equity > 0 else 0

        # In unwind mode (near max inventory), tighten the unwind side
        if abs(inv_ratio) > self.config.inventory_unwind_threshold:
            if inv_ratio > 0:
                # Long inventory — tighten ask (sell side) to unwind faster
                ask_price = mid_price * (1 + spread * self.config.unwind_spread_multiplier + skew)
            else:
                # Short inventory — tighten bid (buy side) to unwind faster
                bid_price = mid_price * (1 - spread * self.config.unwind_spread_multiplier + skew)

        # Check inventory limits
        can_quote_bid = self._should_quote_side(coin, inv.position_size, equity, is_buy=True)
        can_quote_ask = self._should_quote_side(coin, inv.position_size, equity, is_buy=False)

        # Calculate order size
        order_notional = equity * cfg.order_size_pct * cfg.leverage
        order_size = order_notional / mid_price if mid_price > 0 else 0
        order_size = self._round_size(order_size, coin)

        # Check minimum notional
        if order_size * mid_price < cfg.min_order_notional:
            log.debug(f"📊 {coin}: Order notional ${order_size * mid_price:.2f} below ${cfg.min_order_notional}")
            return

        # Cancel existing orders for this coin
        self._cancel_all_orders(coin)

        # Place new orders
        placed_orders = []

        if can_quote_bid and order_size > 0:
            bid_oid = self._place_order(coin, is_buy=True, size=order_size, price=bid_price)
            if bid_oid:
                placed_orders.append(MMOrder(
                    coin=coin, side="B", size=order_size, price=bid_price,
                    oid=bid_oid, placed_at=time.time(),
                ))

        if can_quote_ask and order_size > 0:
            ask_oid = self._place_order(coin, is_buy=False, size=order_size, price=ask_price)
            if ask_oid:
                placed_orders.append(MMOrder(
                    coin=coin, side="A", size=order_size, price=ask_price,
                    oid=ask_oid, placed_at=time.time(),
                ))

        inv.orders = placed_orders
        inv.last_refresh = time.time()

        log.info(
            f"📊 {coin}: {regime:>12} | ADX={inv.adx:.0f} | "
            f"Spread={spread*100:.3f}% | "
            f"Bid={bid_price:.2f}{'✅' if can_quote_bid else '❌'} "
            f"Ask={ask_price:.2f}{'✅' if can_quote_ask else '❌'} | "
            f"Inv={inv.position_size:+.4f} ({inv_ratio:+.1%}) | "
            f"Orders: {len(placed_orders)}"
        )

    # ════════════════════════════════════════════════════════════════
    # RISK MANAGEMENT
    # ════════════════════════════════════════════════════════════════

    def _check_risk_limits(self, equity: float) -> bool:
        """Check if any risk limits are breached. Returns True if safe to continue."""
        # Daily loss check
        if equity > 0:
            daily_loss_pct = abs(self.daily_pnl) / equity
            if self.daily_pnl < 0 and daily_loss_pct >= self.config.max_daily_loss_pct:
                log.error(f"🛑 DAILY LOSS LIMIT: ${self.daily_pnl:.2f} ({daily_loss_pct:.1%})")
                return False

        # Total inventory check — V6.2 FIX: use equity only, not equity × leverage
        total_inv_usd = sum(
            abs(inv.position_size) * inv.last_mid
            for inv in self.inventories.values()
        )
        total_inv_pct = total_inv_usd / equity if equity > 0 else 0

        if total_inv_pct > self.config.emergency_close_threshold:
            log.error(f"🛑 EMERGENCY: Total inventory {total_inv_pct:.1%} > {self.config.emergency_close_threshold:.0%}")
            return False

        return True

    def _check_unwind_needed(self, equity: float):
        """Check if any positions need forced unwind (too old or too large).
        
        V6: Force-close positions that exceed 150% of max inventory cap.
        The quoting engine handles gradual unwind via skewed prices, but when
        inventory gets way over cap (150%+), a market close is safer than waiting.
        """
        for coin, inv in self.inventories.items():
            if abs(inv.position_size) == 0:
                continue

            cfg = self.config.assets[coin]
            # V6.2 FIX: Remove leverage from cap — max_inventory_pct is % of equity
            max_inv_usd = equity * cfg.max_inventory_pct
            current_inv_usd = abs(inv.position_size) * inv.last_mid

            if max_inv_usd <= 0:
                continue

            inv_ratio = current_inv_usd / max_inv_usd

            # Force close at 150% of cap — emergency unwind
            if inv_ratio > 1.5:
                log.warning(
                    f"🚨 {coin}: Inventory {inv_ratio:.1%} of cap — FORCED UNWIND"
                )
                is_buy = inv.position_size < 0  # short → buy to close
                close_sz = abs(inv.position_size)
                try:
                    result = self.exchange.market_open(coin, is_buy, close_sz, None, 0.01)
                    status = result.get("status", "unknown")
                    if status == "ok":
                        log.info(f"✅ {coin}: Force-closed {close_sz:.4f}")
                        inv.position_size = 0.0
                    else:
                        log.error(f"❌ {coin}: Force close failed: {result}")
                except Exception as e:
                    log.error(f"❌ {coin}: Force close error: {e}")

    # ════════════════════════════════════════════════════════════════
    # INDICATOR UPDATE
    # ════════════════════════════════════════════════════════════════

    def _update_indicators(self):
        """Update ADX and ATR for all assets."""
        for coin, inv in self.inventories.items():
            candle_data = self._fetch_candles(coin)
            if candle_data is None:
                continue

            highs, lows, closes = candle_data
            inv.adx = calculate_adx(highs, lows, closes)
            inv.atr_pct = calculate_atr_pct(highs, lows, closes)

    # ════════════════════════════════════════════════════════════════
    # DASHBOARD
    # ════════════════════════════════════════════════════════════════

    def _print_dashboard(self, equity: float, prices: Dict[str, float]):
        """Print status dashboard."""
        uptime = time.time() - self.start_time
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)

        total_inv_usd = sum(
            abs(inv.position_size) * inv.last_mid
            for inv in self.inventories.values()
        )
        total_unrealized = sum(inv.unrealized_pnl for inv in self.inventories.values())
        free_margin = self._get_free_margin()
        total_orders = sum(len(inv.orders) for inv in self.inventories.values())

        print(f"\n{'─' * 70}")
        print(f"🤖 MARKET MAKER BOT | Cycle #{self.cycle_count} | "
              f"Uptime: {hours}h {minutes}m")
        print(f"{'─' * 70}")
        print(f"Equity: ${equity:.2f} | Free: ${free_margin:.2f} | "
              f"uPnL: ${total_unrealized:+.2f}")
        print(f"Inventory: ${total_inv_usd:.2f} | Orders: {total_orders} | "
              f"Daily PnL: ${self.daily_pnl:+.2f}")
        print(f"{'─' * 70}")

        for coin, inv in self.inventories.items():
            cfg = self.config.assets[coin]
            price = prices.get(coin, 0)
            spread, regime = self._calculate_spread(coin, inv.adx, inv.atr_pct)

            if abs(inv.position_size) > 0:
                inv_pct = abs(inv.position_size) * price / (equity * cfg.leverage) if equity > 0 else 0
                pos_str = f"{'LONG' if inv.position_size > 0 else 'SHORT'} {abs(inv.position_size):.4f} ({inv_pct:.0%} cap)"
            else:
                pos_str = "FLAT"

            orders_str = f"{len(inv.orders)} orders" if inv.orders else "no orders"
            print(f"  {coin:5s} ${price:>10.2f} | ADX={inv.adx:>5.1f} | "
                  f"Spread={spread*100:.3f}% | {regime:>12} | "
                  f"{pos_str:>25s} | {orders_str}")

        print(f"{'─' * 70}\n")

    # ════════════════════════════════════════════════════════════════
    # MAIN LOOP
    # ════════════════════════════════════════════════════════════════

    def run(self):
        """Main market making loop."""
        self.running = True

        def _shutdown(sig, frame):
            log.info("\n🛑 Shutting down market maker...")
            self.running = False

        sig_module.signal(sig_module.SIGINT, _shutdown)
        sig_module.signal(sig_module.SIGTERM, _shutdown)

        log.info("🚀 Market maker started — entering main loop")

        last_indicator_update = 0
        last_order_refresh = {coin: 0 for coin in self.config.assets}
        last_daily_reset = datetime.now(timezone.utc).date()

        while self.running:
            try:
                self.cycle_count += 1

                # ── Daily reset ──────────────────────────────────────
                today = datetime.now(timezone.utc).date()
                if today != last_daily_reset:
                    self.daily_pnl = 0.0
                    self.daily_pnl_date = today
                    last_daily_reset = today
                    log.info(f"📅 Daily PnL reset")

                # ── Sync exchange state ──────────────────────────────
                self._sync_exchange_state()

                # ── Get equity and prices ────────────────────────────
                equity = self._get_equity()
                if equity <= 0:
                    log.warning("Zero equity — cannot market make")
                    time.sleep(10)
                    continue

                prices = self._get_mid_prices()
                if not prices:
                    log.warning("No prices available — retrying...")
                    time.sleep(5)
                    continue

                # Update last_mid for all inventories
                for coin, inv in self.inventories.items():
                    if coin in prices:
                        inv.last_mid = prices[coin]

                # ── Update indicators (every 30s) ────────────────────
                now = time.time()
                if now - last_indicator_update > 30:
                    self._update_indicators()
                    last_indicator_update = now

                # ── Risk check ───────────────────────────────────────
                if not self._check_risk_limits(equity):
                    log.error("🛑 RISK LIMIT BREACHED — stopping bot")
                    break

                # ── V6: Check if any positions need forced unwind ──
                self._check_unwind_needed(equity)

                # ── Update quotes for each asset ─────────────────────
                for coin, cfg in self.config.assets.items():
                    if not self.running:
                        break

                    mid_price = prices.get(coin)
                    if mid_price is None or mid_price <= 0:
                        continue

                    # Refresh orders at configured interval
                    last_refresh = last_order_refresh.get(coin, 0)
                    if now - last_refresh >= self.config.order_refresh_seconds:
                        self._update_quotes(coin, mid_price, equity)
                        last_order_refresh[coin] = now

                # ── Dashboard (every 10 cycles) ──────────────────────
                if self.config.verbose and self.cycle_count % 10 == 0:
                    self._print_dashboard(equity, prices)

                # ── Save state ───────────────────────────────────────
                if self.cycle_count % 20 == 0:
                    self._save_state()

                time.sleep(self.config.scan_interval_seconds)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"❗ Main loop error: {e}", exc_info=True)
                time.sleep(10)

        self._shutdown_gracefully()

    def _save_state(self):
        """Save bot state to JSON file."""
        state = {
            "cycle_count": self.cycle_count,
            "daily_pnl": self.daily_pnl,
            "start_time": self.start_time,
            "inventories": {
                coin: {
                    "position_size": inv.position_size,
                    "entry_price": inv.entry_price,
                    "unrealized_pnl": inv.unrealized_pnl,
                    "adx": inv.adx,
                    "atr_pct": inv.atr_pct,
                    "last_mid": inv.last_mid,
                    "orders": [
                        {"side": o.side, "size": o.size, "price": o.price, "oid": o.oid}
                        for o in inv.orders
                    ],
                }
                for coin, inv in self.inventories.items()
            },
        }
        try:
            with open(self.config.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save state: {e}")

    def _shutdown_gracefully(self):
        """Cancel all orders and optionally close positions."""
        log.info("🛑 Cancelling all orders...")
        self._cancel_all_orders_all_coins()

        # Save final state
        self._save_state()

        # Print summary
        equity = self._get_equity()
        total_unrealized = sum(inv.unrealized_pnl for inv in self.inventories.values())
        total_orders = sum(len(inv.orders) for inv in self.inventories.values())

        log.info(f"\n{'=' * 60}")
        log.info(f"📊 MARKET MAKER SESSION SUMMARY")
        log.info(f"   Equity:      ${equity:.2f}")
        log.info(f"   Unrealized:  ${total_unrealized:+.2f}")
        log.info(f"   Daily PnL:   ${self.daily_pnl:+.2f}")
        log.info(f"   Cycles:      {self.cycle_count}")
        log.info(f"   Open orders: {total_orders}")

        for coin, inv in self.inventories.items():
            if abs(inv.position_size) > 0:
                log.info(f"   {coin}: {'LONG' if inv.position_size > 0 else 'SHORT'} "
                         f"{abs(inv.position_size):.4f} @ ${inv.entry_price:.2f} "
                         f"(uPnL: ${inv.unrealized_pnl:+.2f})")

        log.info(f"{'=' * 60}")
        log.info("NOTE: Positions left open — they will be managed by the quoting")
        log.info("      engine on next start, or can be closed manually.")


# ════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    config = MMConfig()

    if config.private_key is None:
        print("❌ HL_PRIVATE_KEY not set in .env")
        sys.exit(1)

    bot = HyperliquidMarketMaker(config)
    bot.run()