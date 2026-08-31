"""
Hyperliquid Autonomous Scalping Bot — Core Engine
v2.2: Limit order entries (maker fees) + trade frequency controls
"""
import time
import logging
import signal
import sys
import json
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account

from config import BotConfig, AssetConfig, SwingConfig
from indicators import TechnicalIndicators as IndicatorSet
from signals import SignalEngine, Direction, Signal
from risk_manager_v5 import RiskManager, ActivePosition

log = logging.getLogger("scalper")


class HyperliquidScalper:
    """
    Autonomous perpetual futures trading bot.
    Dual-strategy: 5m scalping + 30m swing trading.
    Uses aggressive limit orders for entries (maker fee) and
    market orders only for exits (reliable fills).
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self.running = False

        # ── Connect to Hyperliquid ──────────────────────────────────
        log.info("🔗 Connecting to Hyperliquid...")
        self.account = Account.from_key(config.private_key)
        self.api_address = self.account.address

        if config.parent_address:
            self.address = config.parent_address
            log.info(f"📍 API Wallet:    {self.api_address}")
            log.info(f"📍 Parent Wallet: {self.address} (used for queries)")
        else:
            self.address = self.api_address
            log.info(f"📍 Wallet: {self.address}")

        base_url = (
            constants.MAINNET_API_URL if config.use_mainnet
            else constants.TESTNET_API_URL
        )
        self.info = Info(base_url, skip_ws=True)
        self.exchange = Exchange(self.account, base_url)

        # ── Load exchange metadata ──────────────────────────────────
        self.meta = self.info.meta()
        self.sz_decimals: Dict[str, int] = {}
        self.max_leverage: Dict[str, int] = {}
        self.coin_index: Dict[str, int] = {}
        self.hip3_coins: set = set()

        for i, asset in enumerate(self.meta["universe"]):
            name = asset["name"]
            self.sz_decimals[name] = asset["szDecimals"]
            self.max_leverage[name] = asset.get("maxLeverage", 50)
            self.coin_index[name] = i

        self._load_hip3_metadata()

        # ── Initialize components ───────────────────────────────────
        self.signal_engine = SignalEngine()
        self.risk_mgr = RiskManager(config)

        # ── Scalp state ─────────────────────────────────────────────
        self.prices: Dict[str, float] = {}
        self.last_candle_fetch: Dict[str, float] = {}
        self.cached_indicators: Dict[str, IndicatorSet] = {}
        self.partial_tp: Dict[str, Dict] = {}
        self.cycle_count = 0
        self.start_time = time.time()

        # ── Swing state ─────────────────────────────────────────────
        self.last_swing_eval: Dict[str, float] = {}
        self.swing_eval_interval = 60
        self.cached_swing_indicators: Dict[str, IndicatorSet] = {}
        self.last_swing_candle_fetch: Dict[str, float] = {}

        # ── Trade frequency controls ────────────────────────────────
        self.coin_cooldowns: Dict[str, float] = {}    # coin -> earliest next trade time
        self.last_entry_time: float = 0                # timestamp of last entry
        self.trade_timestamps: List[float] = []        # rolling window for hourly cap
        self.session_trade_count: int = 0              # V3: hard session limit
        self.max_trades_per_session: int = getattr(config, 'max_trades_per_session', 25)

        # Tunable parameters (V3: tightened to prevent overtrading)
        # Read from config if available, else use strict defaults
        self.coin_cooldown_seconds = getattr(config, 'coin_cooldown_seconds', 600)      # 10 min (was 120)
        self.global_cooldown_seconds = getattr(config, 'global_cooldown_seconds', 60) # 1 min (was 20)
        self.max_trades_per_hour = getattr(config, 'max_trades_per_hour', 5)           # 5/hr max (was 10)
        self.limit_order_timeout = 30        # V6.1: 10→30s — was timing out too fast, 0/508 maker fills
        self.min_partial_fill_pct = 0.50     # Close partial fills below 50%

        # ── Exchange sync state ─────────────────────────────────────
        self._absent_counts: Dict[str, int] = {}
        self._ABSENT_THRESHOLD = 2

        # ── Setup leverage ──────────────────────────────────────────
        self._setup_leverage()

        # ── Recover open positions from exchange ──────────────────
        self._recover_positions()

        # ── Get initial balance ───────────────────────────────────
        balance = self._get_equity()
        self.risk_mgr.reset_daily(balance)
        log.info(f"💰 Starting equity: ${float(balance):.2f}")
        log.info(
            f"📋 Strategies: "
            f"{'SCALP ✅' if config.enable_scalp else 'SCALP ❌'} | "
            f"{'SWING ✅' if config.enable_swing else 'SWING ❌'}"
        )
        log.info(
            f"📋 V3 Frequency Controls: {self.max_trades_per_hour}/hr max | "
            f"{self.global_cooldown_seconds}s global CD | "
            f"{self.coin_cooldown_seconds}s coin CD | "
            f"Session max: {self.max_trades_per_session} | "
            f"{self.limit_order_timeout}s limit timeout"
        )
        log.info(
            f"📋 Entries: Limit orders (maker fee) | "
            f"Exits: Market orders (reliable fills)"
        )

    # ════════════════════════════════════════════════════════════════
    # EXCHANGE INTERACTION
    # ════════════════════════════════════════════════════════════════

    def _load_hip3_metadata(self):
        """Load metadata for HIP-3 builder-deployed perps."""
        dex_names = set()
        for coin in self.config.assets:
            if ":" in coin:
                dex_names.add(coin.split(":")[0])
        if not dex_names:
            return

        import requests as req_lib
        base_url = (
            constants.MAINNET_API_URL if self.config.use_mainnet
            else constants.TESTNET_API_URL
        )
        api_url = base_url.rstrip("/")
        if not api_url.endswith("/info"):
            api_url = api_url + "/info"

        for dex in dex_names:
            try:
                resp = req_lib.post(
                    api_url,
                    json={"type": "metaAndAssetCtxs", "dex": dex},
                    headers={"Content-Type": "application/json"},
                    timeout=10,
                )
                data = resp.json()
                if isinstance(data, list) and len(data) >= 1:
                    universe = data[0].get("universe", [])
                    for i, asset in enumerate(universe):
                        name = asset["name"]
                        sz_dec = asset.get("szDecimals", 2)
                        max_lev = asset.get("maxLeverage", 20)
                        self.sz_decimals[name] = sz_dec
                        self.max_leverage[name] = max_lev
                        self.hip3_coins.add(name)
                        if hasattr(self.info, 'coin_to_asset'):
                            self.info.coin_to_asset[name] = i
                        if hasattr(self.info, 'name_to_coin'):
                            self.info.name_to_coin[name] = name
                        if hasattr(self.info, 'asset_to_sz_decimals'):
                            self.info.asset_to_sz_decimals[name] = sz_dec
                        log.info(
                            f"📦 HIP-3 loaded: {name} "
                            f"(szDec={sz_dec}, maxLev={max_lev}, idx={i})"
                        )
            except Exception as e:
                log.error(f"Failed to load HIP-3 metadata for dex '{dex}': {e}")

    def _setup_leverage(self):
        """Set leverage for all traded assets."""
        all_coins = set(self.config.assets.keys())
        all_coins.update(
            c for c, sc in self.config.swing_assets.items() if sc.enabled
        )
        for coin in all_coins:
            try:
                max_lev = self.max_leverage.get(coin, 50)
                lev = min(self.config.leverage, max_lev)
                is_cross = self.config.cross_margin and coin not in self.hip3_coins
                self.exchange.update_leverage(lev, coin, is_cross=is_cross)
                margin_mode = "cross" if is_cross else "isolated"
                log.info(f"⚙️ {coin} leverage set to {lev}x ({margin_mode})")
            except Exception as e:
                log.error(f"Failed to set {coin} leverage: {e}")

    def _recover_positions(self):
        """Recover open positions from exchange after restart."""
        try:
            state = self.info.user_state(self.address)
            try:
                open_orders = self.info.frontend_open_orders(self.address)
            except Exception:
                open_orders = self.info.open_orders(self.address)

            coin_orders = {}
            for o in open_orders:
                coin = o.get("coin", "")
                if coin not in coin_orders:
                    coin_orders[coin] = []
                coin_orders[coin].append(o)

            recovered = 0
            for p in state.get("assetPositions", []):
                position = p.get("position", {})
                coin = position.get("coin", "")
                size = float(position.get("szi", 0))
                entry_price = float(position.get("entryPx", 0))

                if abs(size) == 0 or coin not in self.config.assets:
                    continue
                if self._has_any_position(coin):
                    continue

                is_long = size > 0
                direction = "LONG" if is_long else "SHORT"
                abs_size = abs(size)

                tp_order_id = None
                sl_order_id = None
                tp_price = (
                    entry_price * (1 + 0.03)
                    if is_long else entry_price * (1 - 0.03)
                )
                sl_price = (
                    entry_price * (1 - 0.005)
                    if is_long else entry_price * (1 + 0.005)
                )

                orders = coin_orders.get(coin, [])
                for o in orders:
                    oid = str(o.get("oid", ""))
                    trigger_px = (
                        float(o.get("triggerPx", 0))
                        if o.get("triggerPx") else 0
                    )
                    order_side = o.get("side", "")
                    reduce_only = o.get("reduceOnly", False)
                    if not reduce_only or trigger_px == 0:
                        continue

                    if is_long and order_side == "A":
                        if trigger_px > entry_price:
                            tp_order_id = oid
                            tp_price = trigger_px
                        else:
                            sl_order_id = oid
                            sl_price = trigger_px
                    elif not is_long and order_side == "B":
                        if trigger_px < entry_price:
                            tp_order_id = oid
                            tp_price = trigger_px
                        else:
                            sl_order_id = oid
                            sl_price = trigger_px

                pos = ActivePosition(
                    coin=coin,
                    direction=direction,
                    entry_price=entry_price,
                    size=abs_size,
                    entry_time=time.time(),
                    tp_price=tp_price,
                    sl_price=sl_price,
                    highest_price=entry_price,
                    lowest_price=entry_price,
                    tp_order_id=tp_order_id,
                    sl_order_id=sl_order_id,
                    timeframe="5m",
                    strategy="recovered",
                )
                self.risk_mgr.register_position(pos)
                recovered += 1

                tp_str = (
                    f"TP oid={tp_order_id} @{tp_price:.2f}"
                    if tp_order_id else "TP: none found"
                )
                sl_str = (
                    f"SL oid={sl_order_id} @{sl_price:.2f}"
                    if sl_order_id else "SL: none found"
                )
                log.info(
                    f"♻️ Recovered {direction} {coin}: "
                    f"size={abs_size} entry={entry_price:.2f} | "
                    f"{tp_str} | {sl_str}"
                )

                # V6.3 FIX: If SL/TP orders were NOT found on exchange, PLACE THEM NOW
                if not sl_order_id:
                    new_sl_oid = self._place_trigger_order(
                        coin, not is_long, float(abs_size),
                        float(sl_price), "sl"
                    )
                    if new_sl_oid:
                        pos.sl_order_id = new_sl_oid
                        log.info(f"📌 {coin}: SL placed for recovered position @ ${sl_price:.2f} (oid={new_sl_oid})")
                    else:
                        log.error(f"❌ {coin}: FAILED to place SL for recovered position!")
                if not tp_order_id:
                    new_tp_oid = self._place_trigger_order(
                        coin, not is_long, float(abs_size),
                        float(tp_price), "tp"
                    )
                    if new_tp_oid:
                        pos.tp_order_id = new_tp_oid
                        log.info(f"📌 {coin}: TP placed for recovered position @ ${tp_price:.2f} (oid={new_tp_oid})")
                    else:
                        log.error(f"❌ {coin}: FAILED to place TP for recovered position!")

            if recovered:
                log.info(f"♻️ Recovered {recovered} position(s) from exchange")
            else:
                log.info("♻️ No existing positions to recover")

        except Exception as e:
            log.error(f"Failed to recover positions: {e}")
            import traceback
            log.error(traceback.format_exc())

    # ── Account queries ─────────────────────────────────────────────

    def _get_equity(self) -> float:
        """Get account equity."""
        try:
            state = self.info.user_state(self.address)
            # V6.2 FIX: Use marginSummary (total) not crossMarginSummary (cross only)
            # marginSummary includes both cross and isolated margin positions
            margin = state.get("marginSummary", {})
            equity = float(margin.get("accountValue", 0))
            if equity == 0:
                equity = float(state.get("withdrawable", 0))
            if equity == 0:
                try:
                    spot = self.info.spot_user_state(self.address)
                    for b in spot.get("balances", []):
                        if b.get("coin") == "USDC":
                            equity = float(b.get("total", 0))
                            break
                except Exception:
                    pass
            return equity
        except Exception as e:
            log.error(f"Failed to get equity: {e}")
            return 0.0

    def _get_free_margin(self) -> float:
        """Get available margin for new positions."""
        try:
            state = self.info.user_state(self.address)
            margin_summary = state.get("marginSummary", {})
            equity = float(margin_summary.get("accountValue", 0))
            used = float(margin_summary.get("totalMarginUsed", 0))
            return equity - used
        except Exception as e:
            log.error(f"Failed to get free margin: {e}")
            return 0.0

    def _get_portfolio_pnl(self) -> tuple[float, float, float]:
        """Get total portfolio PnL: (unrealized, realized, total).
        
        Returns:
            (unrealized_pnl, realized_pnl, total_portfolio_pnl)
        """
        try:
            state = self.info.user_state(self.address)
            unrealized = 0.0
            
            # Unrealized from open positions
            for pos in state.get("assetPositions", []):
                position = pos.get("position", {})
                coin = position.get("coin", "")
                entry_px = float(position.get("entryPx", 0))
                current_px = float(position.get("markPx", 0))
                size = float(position.get("szi", 0))
                
                if abs(size) > 0 and entry_px > 0:
                    if size > 0:  # Long
                        pnl = (current_px - entry_px) * abs(size)
                    else:  # Short
                        pnl = (entry_px - current_px) * abs(size)
                    unrealized += pnl
            
            # Realized from trade history
            stats = self.risk_mgr.get_stats()
            realized = stats.get('total_pnl', 0)
            
            return unrealized, realized, unrealized + realized
        except Exception as e:
            log.error(f"Failed to get portfolio PnL: {e}")
            return 0.0, 0.0, 0.0

    # ── Market data ─────────────────────────────────────────────────

    def _get_mid_prices(self) -> Dict[str, float]:
        """Fetch current mid prices for all assets."""
        try:
            all_mids = self.info.all_mids()
            prices = {}
            for coin in self.config.assets:
                if coin in all_mids:
                    prices[coin] = float(all_mids[coin])
            self.prices = prices
            return prices
        except Exception as e:
            log.error(f"Failed to fetch prices: {e}")
            return self.prices

    def _get_l2_spread(self, coin: str) -> float:
        """Get current bid-ask spread as a percentage."""
        try:
            book = self.info.l2_snapshot(coin)
            if book and "levels" in book:
                levels = book["levels"]
                if (
                    len(levels) >= 2
                    and len(levels[0]) > 0
                    and len(levels[1]) > 0
                ):
                    best_bid = float(levels[0][0]["px"])
                    best_ask = float(levels[1][0]["px"])
                    mid = (best_bid + best_ask) / 2
                    spread = (best_ask - best_bid) / mid
                    return spread
        except Exception as e:
            log.debug(f"Failed to get L2 for {coin}: {e}")
        return 0.01

    def _fetch_candles(
        self, coin: str, interval: str, count: int = 200
    ) -> Optional[IndicatorSet]:
        """Fetch OHLCV candles and compute indicators."""
        try:
            end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
            interval_ms = {
                "1m": 60_000, "3m": 180_000, "5m": 300_000,
                "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000,
            }
            ms_per_candle = interval_ms.get(interval, 300_000)
            start_time = end_time - (count * ms_per_candle)

            candles = self.info.candles_snapshot(
                coin, interval, start_time, end_time
            )
            if not candles or len(candles) < 50:
                log.warning(
                    f"Insufficient candles for {coin}/{interval}: "
                    f"got {len(candles) if candles else 0}"
                )
                return None

            opens = np.array([float(c["o"]) for c in candles])
            highs = np.array([float(c["h"]) for c in candles])
            lows = np.array([float(c["l"]) for c in candles])
            closes = np.array([float(c["c"]) for c in candles])
            vols = np.array([float(c["v"]) for c in candles])

            return IndicatorSet(opens, highs, lows, closes, vols)

        except Exception as e:
            log.error(f"Failed to fetch candles for {coin}/{interval}: {e}")
            return None

    # ════════════════════════════════════════════════════════════════
    # EXCHANGE POSITION QUERIES (parent wallet aware)
    # ════════════════════════════════════════════════════════════════

    def _get_exchange_position(self, coin: str) -> Optional[Dict]:
        """Query the ACTUAL exchange position for a coin on parent wallet."""
        try:
            state = self.info.user_state(self.address)
            for p in state.get("assetPositions", []):
                position = p.get("position", {})
                if position.get("coin") == coin:
                    size = float(position.get("szi", 0))
                    if abs(size) > 0:
                        return {
                            "size": abs(size),
                            "szi": size,
                            "direction": "LONG" if size > 0 else "SHORT",
                            "entry_price": float(
                                position.get("entryPx", 0)
                            ),
                            "unrealized_pnl": float(
                                position.get("unrealizedPnl", 0)
                            ),
                        }
            return None
        except Exception as e:
            log.error(f"Failed to query exchange position for {coin}: {e}")
            return None

    def _get_all_exchange_positions(self) -> Dict[str, Dict]:
        """Query ALL exchange positions on parent wallet."""
        result = {}
        try:
            state = self.info.user_state(self.address)
            for p in state.get("assetPositions", []):
                position = p.get("position", {})
                coin = position.get("coin", "")
                size = float(position.get("szi", 0))
                if abs(size) > 0:
                    result[coin] = {
                        "size": abs(size),
                        "szi": size,
                        "direction": "LONG" if size > 0 else "SHORT",
                        "entry_price": float(
                            position.get("entryPx", 0)
                        ),
                        "unrealized_pnl": float(
                            position.get("unrealizedPnl", 0)
                        ),
                        "return_on_equity": float(
                            position.get("returnOnEquity", 0)
                        ),
                    }
        except Exception as e:
            log.error(f"Failed to query exchange positions: {e}")
        return result

    # ════════════════════════════════════════════════════════════════
    # ORDER EXECUTION
    # ════════════════════════════════════════════════════════════════

    def _round_price(self, price: float, coin: str) -> float:
        """Round price to Hyperliquid precision rules."""
        import math
        if price == 0:
            return 0.0
        sig_figs = 5
        magnitude = math.floor(math.log10(abs(price))) + 1
        decimal_places_for_sig = max(0, sig_figs - magnitude)
        max_decimals = 6
        sz_dec = self.sz_decimals.get(coin, 0)
        max_decimal_places = max(0, max_decimals - sz_dec)
        decimals = min(decimal_places_for_sig, max_decimal_places)
        return round(price, decimals)

    def _round_size(self, size: float, coin: str) -> float:
        """Round size to exchange precision."""
        dec = self.sz_decimals.get(coin, 4)
        return round(size, dec)

    # ── Limit order entry (maker fee) ───────────────────────────────

    def _limit_open(
        self, coin: str, is_buy: bool, size: float,
    ) -> Optional[Dict]:
        """Open a position via aggressive limit order at best bid/ask.

        Places a limit order at the best bid (buys) or best ask (sells)
        to capture maker fee (0.01%) instead of taker fee (0.035%).

        Returns: {"status": "ok", "fill_price": float, "fill_size": float}
                 or None if the order didn't fill within timeout.
        """
        try:
            size = self._round_size(size, coin)
            if size <= 0:
                return None

            # ── Get order book for pricing ──
            book = self.info.l2_snapshot(coin)
            if (
                not book
                or "levels" not in book
                or len(book["levels"]) < 2
                or not book["levels"][0]
                or not book["levels"][1]
            ):
                log.warning(
                    f"⚠️ No order book for {coin} — skipping entry"
                )
                return None

            best_bid = float(book["levels"][0][0]["px"])
            best_ask = float(book["levels"][1][0]["px"])

            # Place at best bid (buy) or best ask (sell) → maker fee
            if is_buy:
                limit_price = best_bid
            else:
                limit_price = best_ask

            limit_price = self._round_price(limit_price, coin)

            log.info(
                f"📝 Limit {'LONG' if is_buy else 'SHORT'} {coin} | "
                f"Size: {size} @ {limit_price} "
                f"(bid={best_bid} ask={best_ask} spread="
                f"{(best_ask - best_bid) / best_bid:.4%})"
            )

            # ── Place limit order (Gtc — sits on book as maker) ──
            result = self.exchange.order(
                coin, is_buy, size, limit_price,
                {"limit": {"tif": "Gtc"}},
            )

            if result is None:
                log.error(f"❌ Limit order returned None for {coin}")
                return None

            if result.get("status") != "ok":
                log.error(f"❌ Limit order failed for {coin}: {result}")
                return None

            statuses = (
                result.get("response", {})
                .get("data", {})
                .get("statuses", [])
            )

            if not statuses:
                log.warning(f"⚠️ No status in limit order response for {coin}")
                return None

            status = statuses[0]

            # ── Filled immediately (crossed spread — rare, still ok) ──
            if "filled" in status:
                log.info(f"✅ Limit order filled immediately for {coin}")
                time.sleep(0.3)
                exch_pos = self._get_exchange_position(coin)
                if exch_pos:
                    return {
                        "status": "ok",
                        "fill_price": exch_pos["entry_price"],
                        "fill_size": exch_pos["size"],
                    }
                return {
                    "status": "ok",
                    "fill_price": limit_price,
                    "fill_size": size,
                }

            # ── Resting on book — wait for fill ──
            if "resting" in status:
                oid = status["resting"]["oid"]
                log.info(f"⏳ Limit order resting for {coin} (oid={oid})")
                return self._wait_for_limit_fill(coin, int(oid), size)

            # ── Error (e.g., insufficient margin, bad price) ──
            if "error" in status:
                log.warning(
                    f"⚠️ Limit order rejected for {coin}: "
                    f"{status['error']}"
                )
                return None

            log.warning(
                f"⚠️ Unexpected limit order status for {coin}: {status}"
            )
            return None

        except Exception as e:
            log.error(f"❌ Exception in limit open for {coin}: {e}")
            return None

    def _wait_for_limit_fill(
        self, coin: str, oid: int, requested_size: float,
    ) -> Optional[Dict]:
        """Wait for a resting limit order to fill.

        Polls open_orders every 1.5s. If the order disappears from
        open orders AND a position exists, it was filled. On timeout,
        cancels the order and checks for partial fills.

        Returns: fill result dict or None.
        """
        timeout = self.limit_order_timeout
        start = time.time()
        poll_interval = 1.5

        while time.time() - start < timeout:
            time.sleep(poll_interval)

            # ── Check if shutdown requested during wait ──
            if not self.running:
                log.info(f"🛑 Shutdown during limit wait — cancelling {coin}")
                try:
                    self.exchange.cancel(coin, oid)
                except Exception:
                    pass
                return None

            # ── Check if order still resting ──
            try:
                open_orders = self.info.open_orders(self.address)
                order_exists = any(
                    o.get("oid") == oid
                    for o in open_orders
                    if o.get("coin") == coin
                )

                if not order_exists:
                    # Order gone from book — check if position appeared
                    exch_pos = self._get_exchange_position(coin)
                    if exch_pos is not None and exch_pos["size"] > 0:
                        log.info(
                            f"✅ Limit filled for {coin}: "
                            f"size={exch_pos['size']} "
                            f"@ {exch_pos['entry_price']}"
                        )
                        return {
                            "status": "ok",
                            "fill_price": exch_pos["entry_price"],
                            "fill_size": exch_pos["size"],
                        }
                    else:
                        # Order cancelled externally or expired
                        log.info(
                            f"⏭️ Limit order for {coin} disappeared "
                            f"without fill"
                        )
                        return None
            except Exception as e:
                log.debug(f"Error polling order status for {coin}: {e}")

        # ── Timeout — cancel the order ──
        log.info(
            f"⏰ Limit order timeout ({timeout}s) for {coin} — "
            f"cancelling oid={oid}"
        )
        try:
            self.exchange.cancel(coin, oid)
        except Exception as e:
            log.debug(f"Cancel error for {coin} oid={oid}: {e}")

        # Brief wait for cancel to propagate, then check for partial fill
        time.sleep(0.5)
        exch_pos = self._get_exchange_position(coin)

        if exch_pos is not None and exch_pos["size"] > 0:
            fill_pct = exch_pos["size"] / requested_size

            if fill_pct >= self.min_partial_fill_pct:
                log.info(
                    f"✅ Partial fill for {coin}: "
                    f"{exch_pos['size']}/{requested_size} "
                    f"({fill_pct:.0%}) — keeping position"
                )
                return {
                    "status": "ok",
                    "fill_price": exch_pos["entry_price"],
                    "fill_size": exch_pos["size"],
                    "partial": True,
                }
            else:
                # Partial fill too small — close it to avoid orphan
                log.info(
                    f"⏭️ Tiny partial fill for {coin}: "
                    f"{exch_pos['size']}/{requested_size} "
                    f"({fill_pct:.0%}) — closing"
                )
                self._close_position_on_exchange(coin)
                return None

        log.info(f"⏭️ No fill for {coin} — skipping this opportunity")
        return None

    # ── Market order (for exits only) ───────────────────────────────

    def _market_open(
        self, coin: str, is_buy: bool, size: float,
    ) -> Optional[Dict]:
        """Send a market order. Used for exits and emergency closes only."""
        try:
            size = self._round_size(size, coin)
            if size <= 0:
                return None
            result = self.exchange.market_open(
                coin, is_buy, size, slippage=0.01
            )
            if result is None:
                log.error(f"❌ market_open returned None for {coin}")
                return None
            if result.get("status") == "ok":
                return result
            else:
                log.error(f"❌ Market order failed for {coin}: {result}")
                return None
        except Exception as e:
            log.error(f"❌ Exception in market order for {coin}: {e}")
            return None

    def _close_position_on_exchange(
        self, coin: str, tracked_pos: Optional[ActivePosition] = None,
        use_limit: bool = False,
    ) -> Optional[Dict]:
        """Close a position by querying exchange for actual size and
        sending an order in the opposite direction.

        V6: use_limit=True places a limit order at best bid/ask (maker fee)
        instead of market order (taker fee). Used for trailing stop exits.
        Emergency closes always use market for guaranteed fill.
        """
        exchange_pos = self._get_exchange_position(coin)

        if exchange_pos is not None:
            actual_size = exchange_pos["size"]
            is_long = exchange_pos["direction"] == "LONG"
            close_size = float(self._round_size(actual_size, coin))
            log.info(
                f"🔄 Closing {coin} | Exchange: "
                f"{'LONG' if is_long else 'SHORT'} size={close_size}"
            )
        elif tracked_pos is not None:
            log.warning(
                f"⚠️ No exchange position found for {coin} — "
                f"using tracked size={tracked_pos.size}"
            )
            actual_size = tracked_pos.size
            is_long = tracked_pos.direction == "LONG"
            close_size = float(self._round_size(actual_size, coin))
        else:
            log.warning(
                f"⚠️ No exchange or tracked position for {coin} — "
                f"nothing to close"
            )
            return {"status": "ok", "note": "no_position"}

        if close_size <= 0:
            return {"status": "ok", "note": "zero_size"}

        try:
            if use_limit:
                # V6: Place limit order at best bid/ask for maker fee
                book = self.info.l2_snapshot(coin)
                if (book and "levels" in book and len(book["levels"]) >= 2
                        and book["levels"][0] and book["levels"][1]):
                    best_bid = float(book["levels"][0][0]["px"])
                    best_ask = float(book["levels"][1][0]["px"])
                    # Close LONG → sell at best bid (maker)
                    # Close SHORT → buy at best ask (maker)
                    limit_price = best_bid if is_long else best_ask
                    limit_price = float(self._round_price(limit_price, coin))
                    log.info(f"📝 Limit close {coin} @ {limit_price} (maker)")
                    result = self.exchange.order(
                        coin, not is_long, close_size, limit_price,
                        {"limit": {"tif": "Ioc"}},  # Immediate-or-Cancel
                        reduce_only=True,
                    )
                    if result and result.get("status") == "ok":
                        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                        if statuses and "filled" in statuses[0]:
                            log.info(f"✅ Limit close filled for {coin} (maker)")
                            return result
                        # If not filled, fall through to market
                        log.info(f"⏭️ Limit close not filled for {coin} — using market")
                    # Fall through to market order
                # No order book — use market

            result = self.exchange.market_open(
                coin, not is_long, close_size, slippage=0.01,
            )
            if result is None:
                log.error(f"❌ Close order returned None for {coin}")
                return None
            if result.get("status") == "ok":
                log.info(f"✅ {coin} position closed (size={close_size})")
                return result
            else:
                log.error(f"❌ Close failed for {coin}: {result}")
                return None
        except Exception as e:
            log.error(f"❌ Exception closing {coin}: {e}")
            return None

    # ── Trigger orders (TP/SL) ──────────────────────────────────────

    def _place_trigger_order(
        self, coin: str, is_buy: bool, size: float,
        trigger_price: float, tpsl: str,
    ) -> Optional[str]:
        """Place a TP or SL trigger order with limit execution.

        Uses limit orders instead of market orders when triggered:
        - TP: limit at trigger price (exact fill)
        - SL: limit slightly past trigger to ensure fill
              (0.1% slippage allowance)
        Returns order ID.
        """
        try:
            size = float(self._round_size(size, coin))
            trigger_price = float(self._round_price(trigger_price, coin))

            # Set limit price:
            # TP orders: fill at trigger price exactly
            # SL orders: allow 0.25% slippage to ensure fill (was 0.1% — too tight, caused rejected SLs)
            if tpsl == "tp":
                limit_price = trigger_price
            else:
                # SL: set limit worse than trigger to ensure fill
                # is_buy=True means we're buying to close a SHORT (price going up)
                # is_buy=False means we're selling to close a LONG (price going down)
                slippage = 0.0025  # 0.25% (widened from 0.1% to prevent SL rejection)
                if is_buy:
                    limit_price = trigger_price * (1 + slippage)
                else:
                    limit_price = trigger_price * (1 - slippage)

            limit_price = float(self._round_price(limit_price, coin))

            log.debug(
                f"TP/SL: coin={coin} is_buy={is_buy} size={size} "
                f"trigger={trigger_price} limit={limit_price} tpsl={tpsl}"
            )

            result = self.exchange.order(
                coin, is_buy, size, limit_price,
                {"trigger": {
                    "triggerPx": float(trigger_price),
                    "isMarket": False,
                    "tpsl": tpsl,
                }},
                reduce_only=True,
            )

            if result.get("status") == "ok":
                statuses = (
                    result.get("response", {})
                    .get("data", {})
                    .get("statuses", [])
                )
                if statuses and "resting" in statuses[0]:
                    oid = statuses[0]["resting"]["oid"]
                    log.info(
                        f"📌 {tpsl.upper()} limit order for {coin} "
                        f"trigger={trigger_price} limit={limit_price} "
                        f"(oid={oid})"
                    )
                    return str(oid)
            log.warning(f"⚠️ Trigger order response for {coin}: {result}")
            return None
        except Exception as e:
            import traceback
            log.error(
                f"Failed to place {tpsl} order for {coin}: {e}\n"
                f"{traceback.format_exc()}"
            )
            return None

    def _verify_all_sl_orders(self):
        """Verify all SL orders are still active on exchange.
        
        V6.3: If SL order is missing, RE-PLACE it immediately.
        Previously only warned — now actively re-places missing SLs.
        """
        if not self.risk_mgr.active_positions:
            return

        try:
            open_orders = self.info.frontend_open_orders(self.address)
        except Exception:
            try:
                open_orders = self.info.open_orders(self.address)
            except Exception as e:
                log.debug(f"Could not fetch orders for SL verification: {e}")
                return

        for pos_key, pos in list(self.risk_mgr.active_positions.items()):
            verified = self.risk_mgr.verify_sl_orders(pos.coin, open_orders, timeframe=pos.timeframe)
            if not verified:
                # V6.3: SL order is missing — re-place it NOW
                log.warning(f"🚨 {pos.coin}: SL order missing! Re-placing SL @ ${pos.sl_price:.2f}")
                is_long = pos.direction == "LONG"
                new_sl_oid = self._place_trigger_order(
                    pos.coin, not is_long, float(pos.size),
                    float(pos.sl_price), "sl"
                )
                if new_sl_oid:
                    pos.sl_order_id = new_sl_oid
                    log.info(f"✅ {pos.coin}: SL re-placed @ ${pos.sl_price:.2f} (oid={new_sl_oid})")
                else:
                    log.error(f"❌ {pos.coin}: FAILED to re-place SL! Position unprotected!")

    def _cancel_orders(self, coin: str, order_ids: list):
        """Cancel specific orders."""
        for oid in order_ids:
            if oid is None:
                continue
            try:
                self.exchange.cancel(coin, int(oid))
            except Exception as e:
                log.debug(f"Cancel order {oid} for {coin}: {e}")

    def _cancel_all_coin_orders(self, coin: str):
        """Cancel ALL open orders on a coin."""
        try:
            try:
                open_orders = self.info.frontend_open_orders(self.address)
            except Exception:
                open_orders = self.info.open_orders(self.address)

            coin_orders = [
                o for o in open_orders if o.get("coin") == coin
            ]
            if coin_orders:
                for order in coin_orders:
                    oid = order.get("oid")
                    if oid:
                        try:
                            self.exchange.cancel(coin, int(oid))
                            log.info(
                                f"🧹 Cancelled order {oid} for {coin}"
                            )
                        except Exception as e:
                            log.debug(
                                f"Failed to cancel order {oid} "
                                f"for {coin}: {e}"
                            )
                log.info(
                    f"🧹 Cleaned up {len(coin_orders)} open order(s) "
                    f"for {coin}"
                )
        except Exception as e:
            log.error(
                f"Failed to query/cancel open orders for {coin}: {e}"
            )

    # ════════════════════════════════════════════════════════════════
    # TRADE FREQUENCY CONTROLS
    # ════════════════════════════════════════════════════════════════

    def _can_trade_frequency(self, coin: str) -> Tuple[bool, str]:
        """Check if a new trade is allowed by frequency limits.

        Enforces:
          1. Global cooldown between any entries
          2. Per-coin cooldown after exit
          3. Rolling hourly trade cap
        """
        now = time.time()

        # ── Global cooldown ──
        since_last = now - self.last_entry_time
        if since_last < self.global_cooldown_seconds:
            remaining = self.global_cooldown_seconds - since_last
            return False, f"Global cooldown: {remaining:.0f}s"

        # ── Per-coin cooldown ──
        coin_earliest = self.coin_cooldowns.get(coin, 0)
        if now < coin_earliest:
            remaining = coin_earliest - now
            return False, f"Coin cooldown: {remaining:.0f}s"

        # ── Hourly trade cap ──
        self.trade_timestamps = [
            t for t in self.trade_timestamps if now - t < 3600
        ]
        if len(self.trade_timestamps) >= self.max_trades_per_hour:
            oldest = min(self.trade_timestamps)
            next_slot = oldest + 3600 - now
            return False, (
                f"Hourly cap: {len(self.trade_timestamps)}/"
                f"{self.max_trades_per_hour} (next slot in "
                f"{next_slot:.0f}s)"
            )

        # ── Session trade hard limit ──
        if self.session_trade_count >= self.max_trades_per_session:
            return False, (
                f"SESSION LIMIT REACHED: {self.session_trade_count}/"
                f"{self.max_trades_per_session} trades. Bot will not trade further."
            )

        return True, ""

    def _record_trade_entry(self, coin: str):
        """Record that a new entry was made (for frequency tracking)."""
        now = time.time()
        self.last_entry_time = now
        self.trade_timestamps.append(now)
        self.session_trade_count += 1  # V3: track session total

    def _record_trade_exit(self, coin: str):
        """Record that a position was exited (set per-coin cooldown)."""
        self.coin_cooldowns[coin] = (
            time.time() + self.coin_cooldown_seconds
        )

    # ════════════════════════════════════════════════════════════════
    # POSITION HELPERS
    # ════════════════════════════════════════════════════════════════

    def _has_any_position(self, coin: str) -> bool:
        """Check if ANY position (scalp or swing) exists for this coin."""
        scalp_key = RiskManager.position_key(coin, "5m")
        swing_key = RiskManager.position_key(coin, "30m")
        return (
            scalp_key in self.risk_mgr.positions
            or swing_key in self.risk_mgr.positions
        )

    def _find_position_for_coin(
        self, coin: str,
    ) -> Optional[ActivePosition]:
        """Find any tracked position for a coin (scalp or swing)."""
        scalp_key = RiskManager.position_key(coin, "5m")
        swing_key = RiskManager.position_key(coin, "30m")
        return (
            self.risk_mgr.positions.get(scalp_key)
            or self.risk_mgr.positions.get(swing_key)
        )

    def _get_config_for_position(self, pos: ActivePosition):
        """Return the correct config for a position."""
        if pos.timeframe == "30m":
            return self.config.swing_assets.get(pos.coin)
        return self.config.assets.get(pos.coin)

    # ════════════════════════════════════════════════════════════════
    # EXCHANGE SYNC
    # ════════════════════════════════════════════════════════════════

    def _sync_exchange_positions(self):
        """Sync bot state with actual exchange positions.

        Detects:
          - Positions closed by exchange TP/SL (absent from exchange)
          - Partial TP fills (size changed)
        Requires 2 consecutive absent checks before treating as closed.
        """
        try:
            exchange_positions = self._get_all_exchange_positions()

            closed_keys = []
            for pos_key in list(self.risk_mgr.positions.keys()):
                pos = self.risk_mgr.positions[pos_key]
                coin = pos.coin

                if coin in exchange_positions:
                    # ── Position exists — reset absent counter ──
                    self._absent_counts.pop(pos_key, None)

                    # ── Check for size change (partial TP fill) ──
                    exch = exchange_positions[coin]
                    tracked_size = abs(pos.size)
                    exchange_size = exch["size"]

                    size_diff_pct = (
                        abs(exchange_size - tracked_size)
                        / max(tracked_size, 0.0001)
                    )
                    if exchange_size > 0 and size_diff_pct > 0.01:
                        ptp = self.partial_tp.get(coin, {})
                        if ptp and not ptp.get("filled"):
                            ptp["filled"] = True
                            label = (
                                "[SWING]" if pos.timeframe == "30m"
                                else "[SCALP]"
                            )
                            log.info(
                                f"✅ {label} Partial TP detected for "
                                f"{coin}: {tracked_size} → "
                                f"{exchange_size}"
                            )

                            # Move SL to breakeven
                            if pos.sl_order_id:
                                self._cancel_orders(
                                    coin, [pos.sl_order_id]
                                )
                            is_long = pos.direction == "LONG"
                            be_price = self._round_price(
                                pos.entry_price, coin
                            )
                            new_sl_oid = self._place_trigger_order(
                                coin, not is_long,
                                float(exchange_size),
                                float(be_price), "sl",
                            )
                            pos.sl_order_id = new_sl_oid
                            pos.sl_price = be_price
                            log.info(
                                f"📌 SL → breakeven ${be_price:.2f} "
                                f"for {coin}"
                            )

                        pos.size = exchange_size
                else:
                    # ── Position NOT on exchange ──
                    count = self._absent_counts.get(pos_key, 0) + 1
                    self._absent_counts[pos_key] = count

                    if count >= self._ABSENT_THRESHOLD:
                        self._cancel_all_coin_orders(coin)
                        current_price = self.prices.get(coin, 0)
                        self.risk_mgr.close_position(
                            coin, current_price, "EXCHANGE_TP_SL",
                            timeframe=pos.timeframe,
                        )
                        self._record_trade_exit(coin)
                        closed_keys.append(pos_key)
                        self._absent_counts.pop(pos_key, None)
                    else:
                        log.debug(
                            f"⏳ {coin} absent from exchange "
                            f"({count}/{self._ABSENT_THRESHOLD})"
                        )

            if closed_keys:
                for key in closed_keys:
                    for coin in list(self.partial_tp.keys()):
                        if not self._has_any_position(coin):
                            self.partial_tp.pop(coin, None)
                log.info(f"🔄 Synced: {closed_keys} closed on exchange")

        except Exception as e:
            log.error(f"Failed to sync positions: {e}")

    def _detect_orphaned_positions(self):
        """V6.3 SAFETY NET: Detect exchange positions the bot isn't tracking.
        
        These are 'orphaned' positions — opened by a previous bot run, or lost
        during a restart. They have NO SL/TP orders protecting them.
        
        For each orphan:
        1. If it's a coin we trade, register it + place SL/TP immediately
        2. If it's a coin we don't trade (MM bot's coin), skip it
        3. Log a WARNING so we know about it
        """
        try:
            exchange_positions = self._get_all_exchange_positions()
            if not exchange_positions:
                return

            # Get all coins the bot is currently tracking
            tracked_coins = set()
            for pos_key, pos in self.risk_mgr.positions.items():
                tracked_coins.add(pos.coin)

            # Find orphans: on exchange but not tracked
            for coin, exch_pos in exchange_positions.items():
                if coin in tracked_coins:
                    continue  # Bot is managing this one
                if coin not in self.config.assets:
                    continue  # MM bot's coin (XMR, TAO) — not our problem

                # ORPHANED POSITION DETECTED
                size = exch_pos["size"]
                szi = exch_pos["szi"]
                entry = exch_pos["entry_price"]
                direction = exch_pos["direction"]
                is_long = direction == "LONG"
                uPnL = exch_pos.get("unrealized_pnl", 0)

                log.warning(
                    f"🚨 ORPHANED POSITION: {coin} {direction} "
                    f"size={size} @ ${entry:.2f} uPnL=${uPnL:.2f} — "
                    f"NOT tracked by bot, NO SL/TP! Recovering..."
                )

                # Place SL/TP orders based on config for this coin
                asset_cfg = self.config.assets[coin]
                sl_pct = asset_cfg.stop_loss_pct
                tp_pct = asset_cfg.take_profit_pct

                # Use ATR-based SL/TP if available, otherwise config %
                indicators = self.cached_indicators.get(
                    f"{coin}_{self.config.candle_interval}"
                )
                atr_val = indicators.get('atr', 0) if indicators else 0
                if atr_val and atr_val > 0:
                    atr_pct = atr_val / entry
                    sl_pct = min(atr_pct * 1.5, sl_pct * 2)
                    tp_pct = min(atr_pct * 2.0, tp_pct * 2)

                if is_long:
                    sl_price = entry * (1 - sl_pct)
                    tp_price = entry * (1 + tp_pct)
                else:
                    sl_price = entry * (1 + sl_pct)
                    tp_price = entry * (1 - tp_pct)

                sl_price = self._round_price(sl_price, coin)
                tp_price = self._round_price(tp_price, coin)

                # Place SL order
                sl_oid = self._place_trigger_order(
                    coin, not is_long, float(size), float(sl_price), "sl"
                )
                # Place TP order
                tp_oid = self._place_trigger_order(
                    coin, not is_long, float(size), float(tp_price), "tp"
                )

                if sl_oid or tp_oid:
                    # Register with risk manager
                    from risk_manager_v5 import Position
                    pos = Position(
                        coin=coin,
                        direction=direction,
                        size=size,
                        entry_price=entry,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        sl_order_id=sl_oid,
                        tp_order_id=tp_oid,
                        strategy="SCALP",
                        timeframe="5m",
                        entry_time=time.time(),
                    )
                    self.risk_mgr.register_position(pos)

                    log.info(
                        f"✅ RECOVERED orphaned {coin} {direction}: "
                        f"SL=${sl_price:.2f} TP=${tp_price:.2f}"
                    )
                else:
                    log.error(
                        f"❌ FAILED to place SL/TP for orphaned {coin} — "
                        f"position remains UNPROTECTED!"
                    )

        except Exception as e:
            log.error(f"Failed to detect orphaned positions: {e}")

    # ════════════════════════════════════════════════════════════════
    # SHARED ENTRY FINALIZATION
    # ════════════════════════════════════════════════════════════════

    def _finalize_entry(
        self,
        coin: str,
        fill_price: float,
        fill_size: float,
        is_long: bool,
        partial_tp_pct: float,
        full_tp_pct: float,
        sl_pct: float,
        strategy: str,
        signal: Signal,
        timeframe: str,
        max_hold_until: float = 0,
    ) -> bool:
        """Place TP/SL orders and register position after limit fill.

        Shared by both scalp and swing entry flows.
        Uses ACTUAL fill price/size from exchange for accuracy.

        Returns True if position was registered, False on failure.
        """
        is_buy = is_long

        # ── Calculate TP/SL from actual fill price ──
        if is_long:
            partial_tp_price = fill_price * (1 + partial_tp_pct)
            tp_price = fill_price * (1 + full_tp_pct)
            sl_price = fill_price * (1 - sl_pct)
        else:
            partial_tp_price = fill_price * (1 - partial_tp_pct)
            tp_price = fill_price * (1 - full_tp_pct)
            sl_price = fill_price * (1 + sl_pct)

        # ── Partial TP: close 50% at TP1 (skip if partial_tp_pct is 0) ──
        partial_tp_oid = None
        if partial_tp_pct > 0:
            partial_tp_size = self._round_size(fill_size * 0.50, coin)
            remaining_size = self._round_size(
                fill_size - partial_tp_size, coin
            )

            # Check $10 minimum notional for each half
            min_notional = 10.0
            partial_notional = partial_tp_size * fill_price
            remaining_notional = remaining_size * fill_price

            if partial_tp_size > 0 and partial_notional >= min_notional and remaining_notional >= min_notional:
                partial_tp_oid = self._place_trigger_order(
                    coin, not is_buy, float(partial_tp_size),
                    float(partial_tp_price), "tp",
                )
                if partial_tp_oid:
                    partial_roe = partial_tp_pct * self.config.leverage
                    log.info(
                        f"📌 Partial TP: 50% ({partial_tp_size}) "
                        f"at {partial_tp_price:.2f} ({partial_roe:.0%} ROE)"
                    )
                    self.partial_tp[coin] = {
                        "order_id": partial_tp_oid,
                        "size": partial_tp_size,
                        "filled": False,
                    }
            else:
                if partial_tp_size > 0:
                    log.info(
                        f"📌 {coin}: Skipping partial TP — half notional "
                        f"${partial_notional:.2f}/${remaining_notional:.2f} "
                        f"below $10 min. Using single TP on full size."
                    )
                remaining_size = fill_size  # Use full size for single TP
        else:
            # No partial TP — use full position size for the single TP
            remaining_size = fill_size

        # ── Main TP on remaining size ──
        tp_oid = self._place_trigger_order(
            coin, not is_buy, float(remaining_size),
            float(tp_price), "tp",
        )

        # ── SL on full size (covers both halves until TP1 fills) ──
        sl_oid = self._place_trigger_order(
            coin, not is_buy, float(fill_size),
            float(sl_price), "sl",
        )

        # ── Verify SL order was placed ───────────────────────────
        if sl_oid:
            time.sleep(0.5)  # Brief delay for exchange to process
            try:
                open_orders = self.info.frontend_open_orders(self.address)
                sl_verified = any(str(o.get("oid")) == str(sl_oid) for o in open_orders)
                if sl_verified:
                    log.info(f"✅ SL order verified on exchange: {sl_oid}")
                    self.risk_mgr.mark_sl_verified(coin, timeframe)
                else:
                    log.warning(f"⚠️ SL order {sl_oid} not found in open orders - retrying...")
                    # Retry placing SL
                    sl_oid = self._place_trigger_order(
                        coin, not is_buy, float(fill_size),
                        float(sl_price), "sl",
                    )
            except Exception as e:
                log.warning(f"Could not verify SL order: {e}")
        else:
            log.error(f"❌ Failed to place SL order for {coin}!")

        # ── Register position ──
        pos = ActivePosition(
            coin=coin,
            direction="LONG" if is_long else "SHORT",
            entry_price=fill_price,
            size=fill_size,
            entry_time=time.time(),
            tp_price=tp_price,
            sl_price=sl_price,
            highest_price=fill_price,
            lowest_price=fill_price,
            tp_order_id=tp_oid,
            sl_order_id=sl_oid,
            strategy=strategy,
            signal_score=signal.score,
            timeframe=timeframe,
            max_hold_until=max_hold_until,
        )
        self.risk_mgr.register_position(pos)
        self._record_trade_entry(coin)

        return True

    # ════════════════════════════════════════════════════════════════
    # SCALP TRADING LOGIC (5m)
    # ════════════════════════════════════════════════════════════════

    def _evaluate_scalp_asset(self, coin: str) -> Optional[Signal]:
        """Fetch 5m data and evaluate scalp signals."""
        cache_key = f"{coin}_{self.config.candle_interval}"
        last_fetch = self.last_candle_fetch.get(cache_key, 0)

        if time.time() - last_fetch > 30:
            indicators = self._fetch_candles(
                coin, self.config.candle_interval
            )
            if indicators is not None:
                self.cached_indicators[cache_key] = indicators
                self.last_candle_fetch[cache_key] = time.time()

        indicators = self.cached_indicators.get(cache_key)
        if indicators is None:
            return None

        return self.signal_engine.evaluate(indicators)

    def _try_open_scalp(
        self, coin: str, signal: Signal, asset_cfg: AssetConfig,
    ):
        """Attempt to open a new scalp position via limit order."""

        # ── Risk manager check ──
        allowed, reason = self.risk_mgr.can_open_position(
            coin, asset_cfg, timeframe="5m"
        )
        if not allowed:
            # V3: Hard stop on circuit breaker triggers
            if "Consecutive losses" in reason:
                log.error(f"🛑 CIRCUIT BREAKER: {reason}")
                log.error("🛑 TRADING HALTED — Restart required to resume")
                self.running = False
            else:
                log.debug(f"⛔ {coin} [SCALP]: {reason}")
            return

        # ── Frequency check ──
        freq_ok, freq_reason = self._can_trade_frequency(coin)
        if not freq_ok:
            log.debug(f"⏳ {coin} [SCALP]: {freq_reason}")
            return

        # ── V5: Volatility regime gate — skip dead markets ──
        indicators = self.cached_indicators.get(f"{coin}_{self.config.candle_interval}")
        if indicators:
            try:
                atr_arr = indicators['atr'] if 'atr' in indicators else None
                if atr_arr is not None and len(atr_arr) > 0:
                    atr_val = float(atr_arr[-1])  # latest ATR value
                    current_price_val = self.prices.get(coin, 0)
                    if atr_val and current_price_val and current_price_val > 0:
                        atr_pct = atr_val / current_price_val * 100
                        if atr_pct < 0.10:
                            log.debug(f"📊 {coin} [SCALP] ATR {atr_pct:.3f}% < 0.10% — dead market, skipping")
                            return
            except (TypeError, IndexError, KeyError):
                pass

        # ── V5: 1h trend filter — skip strongly counter-trend scalps ──
        # V6.1 FIX: Swing indicators were never fetched because swing is disabled.
        # This made the 1h trend filter silently dead code. Now fetch 1h data directly.
        # V6.1 FIX 2: Fail SAFE — if 1h data can't be fetched, DON'T TRADE (was fail-open)
        swing_indicators = self.cached_swing_indicators.get(f"{coin}_swing")
        if not swing_indicators:
            # V6.1: Fetch 1h candles directly for trend filter (swing may be disabled)
            swing_indicators = self._fetch_swing_candles(coin)
        if not swing_indicators:
            # V6.1: Fail SAFE — no 1h trend data = no trade (was silently bypassing filter)
            log.warning(f"⚠️ {coin} [SCALP] Cannot fetch 1h trend data — skipping (fail-safe)")
            return
        if swing_indicators:
            try:
                swing_ema50_arr = swing_indicators['ema_50'] if 'ema_50' in swing_indicators else None
                swing_adx = swing_indicators.get('adx', 0) if isinstance(swing_indicators, dict) else 0
                # Use the last close from swing indicators (or fetch from prices)
                swing_close = self.prices.get(coin, 0)
                if swing_ema50_arr is not None and len(swing_ema50_arr) > 0 and swing_close:
                    swing_ema50 = float(swing_ema50_arr[-1])
                    if swing_ema50 > 0:
                        trend_dev = (swing_close - swing_ema50) / swing_ema50
                        # V6.1: Stronger trend filter — block counter-trend when 1h ADX > 25
                        if signal.direction == Direction.LONG and trend_dev < -0.003:
                            log.debug(f"📊 {coin} [SCALP] LONG skipped — 1h close {trend_dev*100:.2f}% below EMA50 (counter-trend)")
                            return
                        elif signal.direction == Direction.SHORT and trend_dev > 0.003:
                            log.debug(f"📊 {coin} [SCALP] SHORT skipped — 1h close {trend_dev*100:.2f}% above EMA50 (counter-trend, ADX={swing_adx:.0f})")
                            return
            except (TypeError, IndexError, KeyError):
                pass

        # ── Signal strength check ──
        if signal.score < asset_cfg.min_signal_score:
            log.debug(
                f"📊 {coin} [SCALP] {signal.direction.value} "
                f"score {signal.score}/{asset_cfg.min_signal_score} — "
                f"too weak"
            )
            return

        # ── Spread check ──
        spread = self._get_l2_spread(coin)
        if spread > asset_cfg.max_spread_pct:
            log.debug(
                f"📊 {coin} [SCALP] spread {float(spread):.4%} > "
                f"max {float(asset_cfg.max_spread_pct):.4%}"
            )
            return

        # ── V6.1 TIER 2: RETRACE ENTRY CONFIRMATION ──
        # Passivbot approach: wait for price to confirm direction before entering.
        # Check that the last 5m candle close direction aligns with signal direction.
        try:
            cached_ind = self.cached_indicators.get(f"{coin}_{self.config.candle_interval}")
            if cached_ind:
                raw_candles = cached_ind.get('raw_candles', []) if hasattr(cached_ind, 'get') else []
                if raw_candles and len(raw_candles) >= 2:
                    last_candle = raw_candles[-1]
                    last_close = float(last_candle.get('c', last_candle.get('close', 0)))
                    last_open = float(last_candle.get('o', last_candle.get('open', 0)))
                    candle_bullish = last_close > last_open
                    
                    signal_long = signal.direction == Direction.LONG
                    if signal_long and not candle_bullish:
                        log.debug(f"📊 {coin} [SCALP] retrace: last candle bearish vs LONG signal — waiting")
                        return
                    elif not signal_long and candle_bullish:
                        log.debug(f"📊 {coin} [SCALP] retrace: last candle bullish vs SHORT signal — waiting")
                        return
        except Exception:
            pass  # If retrace check fails, proceed (fail open, not fail closed)

        # ── Price + size ──
        current_price = self.prices.get(coin)
        if current_price is None or current_price <= 0:
            return

        equity = self._get_equity()
        if equity <= 0:
            log.error("Zero equity — cannot trade")
            return

        size = self.risk_mgr.calculate_position_size(
            coin, asset_cfg, equity, current_price,
            self.sz_decimals.get(coin, 4),
        )
        size = float(size)
        current_price = float(current_price)
        if size <= 0:
            log.debug(f"📊 {coin} [SCALP] position size too small")
            return

        is_long = signal.direction == Direction.LONG
        is_buy = is_long

        # ── TP/SL parameters from config ──
        # V6.1 TIER 2: ATR-based SL/TP — adapts to each coin's volatility
        # Uses ATR(14) × multiplier instead of fixed % per coin
        # Falls back to config % if ATR data unavailable
        full_tp_pct = asset_cfg.take_profit_pct
        sl_pct = asset_cfg.stop_loss_pct
        
        # Try to get ATR from cached indicators for dynamic SL/TP
        cached_ind = self.cached_indicators.get(f"{coin}_{self.config.candle_interval}")
        if cached_ind:
            try:
                atr_arr = cached_ind['atr'] if 'atr' in cached_ind else None
                if atr_arr is not None and len(atr_arr) > 0:
                    atr_val = float(atr_arr[-1])
                    if atr_val and current_price > 0:
                        atr_pct = atr_val / current_price  # ATR as fraction of price
                        if atr_pct > 0.001:  # Sanity check — ATR should be > 0.1%
                            # ATR-based SL: 1.5 × ATR, TP: 2.0 × ATR
                            # This adapts to volatility — wider stops in volatile markets, tighter in calm
                            atr_sl = atr_pct * 1.5
                            atr_tp = atr_pct * 2.0
                            # Use ATR-based values but cap them within 0.5× to 2× of config values
                            # (prevents extreme deviations from the tuned config)
                            min_sl = asset_cfg.stop_loss_pct * 0.5
                            max_sl = asset_cfg.stop_loss_pct * 2.0
                            min_tp = asset_cfg.take_profit_pct * 0.5
                            max_tp = asset_cfg.take_profit_pct * 2.0
                            sl_pct = max(min_sl, min(max_sl, atr_sl))
                            full_tp_pct = max(min_tp, min(max_tp, atr_tp))
                            log.info(f"📊 {coin} ATR-based SL/TP: SL={sl_pct:.4f} TP={full_tp_pct:.4f} (ATR={atr_pct:.4f}, config SL={asset_cfg.stop_loss_pct:.4f} TP={asset_cfg.take_profit_pct:.4f})")
            except Exception as e:
                log.debug(f"ATR SL/TP fallback to config: {e}")
        
        partial_tp_pct = 0  # No partial TP for scalps — keep full winner size

        partial_roe = partial_tp_pct * self.config.leverage
        full_roe = full_tp_pct * self.config.leverage
        sl_roe = sl_pct * self.config.leverage

        log.info(
            f"\n{'='*60}\n"
            f"🎯 SCALP SIGNAL: {signal.direction.value} {coin} | "
            f"Score: {signal.score}/{signal.max_score}\n"
            f"   Strategy: {signal.strategy}\n"
            f"   Reasons: {', '.join(signal.reasons[:4])}\n"
            f"   Price: {current_price:.2f} | Size: {size} | "
            f"Notional: ${size * current_price:.0f}\n"
            f"   TP1: ~{partial_tp_pct:.3%} ({partial_roe:.0%} ROE) "
            f"on 50%\n"
            f"   TP2: ~{full_tp_pct:.3%} ({full_roe:.0%} ROE) "
            f"on 50%\n"
            f"   SL:  ~{sl_pct:.3%} ({sl_roe:.0%} ROE) "
            f"→ moves to BE after TP1\n"
            f"   Entry: LIMIT ORDER (maker fee)\n"
            f"{'='*60}"
        )

        # ── Place limit order ──
        result = self._limit_open(coin, is_buy, size)
        if result is None:
            return

        # ── Check shutdown during wait ──
        if not self.running:
            log.info(f"🛑 Shutdown during entry — closing {coin}")
            self._close_position_on_exchange(coin)
            return

        fill_price = result.get("fill_price", current_price)
        fill_size = result.get("fill_size", size)

        log.info(
            f"✅ SCALP entry filled: {coin} @ {fill_price:.2f} "
            f"(size={fill_size})"
        )

        # ── Finalize: place TP/SL + register position ──
        self._finalize_entry(
            coin=coin,
            fill_price=fill_price,
            fill_size=fill_size,
            is_long=is_long,
            partial_tp_pct=partial_tp_pct,
            full_tp_pct=full_tp_pct,
            sl_pct=sl_pct,
            strategy=signal.strategy,
            signal=signal,
            timeframe="5m",
        )

    # ════════════════════════════════════════════════════════════════
    # SWING TRADING LOGIC (30m)
    # ════════════════════════════════════════════════════════════════

    def _fetch_swing_candles(self, coin: str) -> Optional[IndicatorSet]:
        """Fetch 30m candles for swing analysis with caching."""
        cache_key = f"{coin}_swing"
        last_fetch = self.last_swing_candle_fetch.get(cache_key, 0)

        if time.time() - last_fetch > 60:
            indicators = self._fetch_candles(
                coin,
                self.config.candle_interval_swing,
                self.config.swing_candles_lookback,
            )
            if indicators is not None:
                self.cached_swing_indicators[cache_key] = indicators
                self.last_swing_candle_fetch[cache_key] = time.time()

        return self.cached_swing_indicators.get(cache_key)

    def _evaluate_swing_asset(self, coin: str) -> Optional[Signal]:
        """Fetch 30m data and evaluate swing signals."""
        swing_cfg = self.config.swing_assets.get(coin)
        if not swing_cfg or not swing_cfg.enabled:
            return None

        now = time.time()
        last_eval = self.last_swing_eval.get(coin, 0)
        if now - last_eval < self.swing_eval_interval:
            return None
        self.last_swing_eval[coin] = now

        indicators_30m = self._fetch_swing_candles(coin)
        if indicators_30m is None:
            return None

        cache_key_5m = f"{coin}_{self.config.candle_interval}"
        indicators_5m = self.cached_indicators.get(cache_key_5m)

        return self.signal_engine.evaluate_swing(
            indicators_30m=indicators_30m,
            indicators_5m=indicators_5m,
            swing_config=swing_cfg,
        )

    def _try_open_swing(
        self, coin: str, signal: Signal, swing_cfg: SwingConfig,
    ):
        """Attempt to open a new swing position via limit order."""

        # ── Risk manager check ──
        allowed, reason = self.risk_mgr.can_open_position(
            coin, swing_cfg, timeframe="30m"
        )
        if not allowed:
            # V3: Hard stop on circuit breaker triggers
            if "Consecutive losses" in reason:
                log.error(f"🛑 CIRCUIT BREAKER: {reason}")
                log.error("🛑 TRADING HALTED — Restart required to resume")
                self.running = False
            else:
                log.debug(f"⛔ {coin} [SWING]: {reason}")
            return

        # ── Frequency check ──
        freq_ok, freq_reason = self._can_trade_frequency(coin)
        if not freq_ok:
            log.debug(f"⏳ {coin} [SWING]: {freq_reason}")
            return

        # ── Signal strength check ──
        if signal.score < swing_cfg.min_signal_score:
            log.debug(
                f"📊 {coin} [SWING] {signal.direction.value} "
                f"score {signal.score}/{swing_cfg.min_signal_score} — "
                f"too weak"
            )
            return

        # ── Spread check ──
        spread = self._get_l2_spread(coin)
        if spread > swing_cfg.max_spread_pct:
            log.debug(
                f"📊 {coin} [SWING] spread {float(spread):.4%} > "
                f"max {float(swing_cfg.max_spread_pct):.4%}"
            )
            return

        # ── Price + size ──
        current_price = self.prices.get(coin)
        if current_price is None or current_price <= 0:
            return

        equity = self._get_equity()
        if equity <= 0:
            log.error("Zero equity — cannot trade")
            return

        size = self.risk_mgr.calculate_position_size(
            coin, swing_cfg, equity, current_price,
            self.sz_decimals.get(coin, 4),
        )
        size = float(size)
        current_price = float(current_price)
        if size <= 0:
            log.debug(f"📊 {coin} [SWING] position size too small")
            return

        is_long = signal.direction == Direction.LONG
        is_buy = is_long

        # ── TP/SL parameters from swing config ──
        partial_tp_pct = swing_cfg.take_profit_pct * 0.50
        full_tp_pct = swing_cfg.take_profit_pct
        sl_pct = swing_cfg.stop_loss_pct
        max_hold_until = time.time() + (swing_cfg.max_hold_minutes * 60)

        partial_roe = partial_tp_pct * self.config.leverage
        full_roe = full_tp_pct * self.config.leverage
        sl_roe = sl_pct * self.config.leverage
        hold_hrs = swing_cfg.max_hold_minutes / 60

        log.info(
            f"\n{'='*60}\n"
            f"🔄 SWING SIGNAL: {signal.direction.value} {coin} | "
            f"Score: {signal.score}/{signal.max_score}\n"
            f"   Strategy: {signal.strategy}\n"
            f"   Reasons: {', '.join(signal.reasons[:5])}\n"
            f"   Price: {current_price:.2f} | Size: {size} | "
            f"Notional: ${size * current_price:.0f}\n"
            f"   TP1: ~{partial_tp_pct:.3%} ({partial_roe:.0%} ROE) "
            f"on 50%\n"
            f"   TP2: ~{full_tp_pct:.3%} ({full_roe:.0%} ROE) "
            f"on 50%\n"
            f"   SL:  ~{sl_pct:.3%} ({sl_roe:.0%} ROE) "
            f"→ moves to BE after TP1\n"
            f"   Max hold: {hold_hrs:.1f}h\n"
            f"   Entry: LIMIT ORDER (maker fee)\n"
            f"{'='*60}"
        )

        # ── Place limit order ──
        result = self._limit_open(coin, is_buy, size)
        if result is None:
            return

        if not self.running:
            log.info(f"🛑 Shutdown during entry — closing {coin}")
            self._close_position_on_exchange(coin)
            return

        fill_price = result.get("fill_price", current_price)
        fill_size = result.get("fill_size", size)

        log.info(
            f"✅ SWING entry filled: {coin} @ {fill_price:.2f} "
            f"(size={fill_size})"
        )

        # ── Finalize: place TP/SL + register position ──
        self._finalize_entry(
            coin=coin,
            fill_price=fill_price,
            fill_size=fill_size,
            is_long=is_long,
            partial_tp_pct=partial_tp_pct,
            full_tp_pct=full_tp_pct,
            sl_pct=sl_pct,
            strategy=signal.strategy,
            signal=signal,
            timeframe="30m",
            max_hold_until=max_hold_until,
        )

    # ════════════════════════════════════════════════════════════════
    # POSITION MANAGEMENT (both scalp + swing)
    # ════════════════════════════════════════════════════════════════

    def _manage_positions(self):
        """
        Main position management loop.
        Dynamically improves strategy based on recent win rate and parent account PnL.
        """
        # Load stats from risk manager to auto-tune risk
        stats = self.risk_mgr.get_stats()
        total_trades = stats.get('total_trades', 0)
        wr = stats.get('win_rate', 0) / 100 

        if total_trades >= 10:
            if wr > 0.55:
                self.config.max_position_pct = min(0.40, self.config.max_position_pct + 0.01)
            elif wr < 0.40:
                self.config.max_position_pct = max(0.20, self.config.max_position_pct - 0.02)
        
        # Original management logic
        for pos_key in list(self.risk_mgr.positions.keys()):
            pos = self.risk_mgr.positions.get(pos_key)
            if pos is None: continue

            coin = pos.coin
            current_price = self.prices.get(coin)
            if current_price is None: continue

            cfg = self._get_config_for_position(pos)
            if cfg is None: continue

            self.risk_mgr.update_trailing_stops(coin, current_price, cfg, timeframe=pos.timeframe)
            
            # ── EMERGENCY SL CHECK ──────────────────────────────────
            # If SL was breached but didn't trigger, force close immediately
            emergency_close, emergency_reason = self.risk_mgr.check_emergency_sl(
                coin, current_price, timeframe=pos.timeframe
            )
            if emergency_close:
                log.error(f"🚨 EMERGENCY CLOSE: {coin} - {emergency_reason}")
                order_ids = [pos.tp_order_id, pos.sl_order_id]
                self._cancel_orders(coin, order_ids)
                result = self._close_position_on_exchange(coin, pos)
                if result is not None:
                    self._cancel_all_coin_orders(coin)
                    self.risk_mgr.close_position(coin, current_price, emergency_reason, timeframe=pos.timeframe)
                    self._record_trade_exit(coin)
                    self._send_alert(f"🚨 EMERGENCY SL CLOSE: {coin}\n{emergency_reason}\nPrice: ${current_price:.2f}")
                continue
            
            exit_reason = self.risk_mgr.check_exit_conditions(coin, current_price, timeframe=pos.timeframe)
            
            if exit_reason:
                order_ids = [pos.tp_order_id, pos.sl_order_id]
                self._cancel_orders(coin, order_ids)
                # V6: Use limit order for trailing stop exits (maker fee 0.007% vs taker 0.035%)
                result = self._close_position_on_exchange(coin, pos, use_limit=True)
                if result is not None:
                    self._cancel_all_coin_orders(coin)
                    self.risk_mgr.close_position(coin, current_price, exit_reason, timeframe=pos.timeframe)
                    self._record_trade_exit(coin)

    def _send_alert(self, message: str):
        """Send alert notification (console + potential integrations)."""
        log.warning(f"🚨 ALERT: {message}")
        # TODO: Add WhatsApp/Telegram integration here
        print(f"\n{'='*60}")
        print(f"🚨 TRADING ALERT")
        print(f"{'='*60}")
        print(message)
        print(f"{'='*60}\n")

    # ═════
    # MAIN LOOP
    # ════════════════════════════════════════════════════════════════

    def _print_dashboard(self):
        """Print status dashboard to terminal."""
        stats = self.risk_mgr.get_stats()
        equity = self._get_equity()
        uptime = time.time() - self.start_time
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        # Process Status Check
        status_msg = "RUNNING (v3)" if self.running else "STOPPED"
        process_status = f"Process: {status_msg} | Uptime: {hours}h {minutes}m"
        # State Verification
        try:
            exch_pos = self._get_all_exchange_positions()
            state_file_health = "CLEAN" if len(self.risk_mgr.positions) == len(exch_pos) else "DESYNC"
        except:
            state_file_health = "ERROR"
        state_status = f"State: {state_file_health} | Daily PnL: ${self.risk_mgr.daily_pnl:>+7.2f}"
        # Get portfolio PnL for header
        unrealized_h, realized_h, total_pf_pnl = self._get_portfolio_pnl()
        print()
        print("----------------------------------------------------------")
        print(f"HYPERLIQUID SCALPER+SWING | Cycle #{self.cycle_count}")
        print("----------------------------------------------------------")
        print(process_status)
        print(state_status)
        print("----------------------------------------------------------")
        print(f"Total Balance: $ {equity:>9.2f} | Portfolio PnL: ${total_pf_pnl:>+8.2f}")
        print(f"                (${unrealized_h:>+.2f} unreal | ${realized_h:>+.2f} realized)")
        print(f"WR: {stats.get('win_rate', 0):.1f}% | Trades: {stats.get('total_trades', 0):<4} | Daily: ${self.risk_mgr.daily_pnl:>+.2f}")
        print("----------------------------------------------------------")

        positions_str = ""
        total_position_count = len(self.risk_mgr.positions)
        for pos_key, pos in self.risk_mgr.positions.items():
            coin = pos.coin
            price = self.prices.get(coin, 0)
            if pos.direction == "LONG":
                unrealized = ((price - pos.entry_price) / pos.entry_price * self.config.leverage)
            else:
                unrealized = ((pos.entry_price - price) / pos.entry_price * self.config.leverage)
            trail_str = f" | Trail: {float(pos.trailing_stop):.2f}" if pos.trailing_active else ""
            ptp = self.partial_tp.get(coin, {})
            ptp_str = " [TP1]" if ptp.get("filled") else ""
            tf_label = "SWING" if pos.timeframe == "30m" else "SCALP"
            positions_str += (f" {tf_label} {pos.direction} {coin}: Entry {float(pos.entry_price):.2f} -> {float(price):.2f} ({unrealized:+.1%}){trail_str}{ptp_str}\n")
        order_count = 0
        try:
            open_orders = self.info.frontend_open_orders(self.address)
            order_count = len(open_orders)
        except Exception:
            try:
                open_orders = self.info.open_orders(self.address)
                order_count = len(open_orders)
            except Exception:
                order_count = -1

        scalp_pnl = stats.get('scalp_pnl', 0)
        swing_pnl = stats.get('swing_pnl', 0)
        scalp_count = stats.get('scalp_trades', 0)
        swing_count = stats.get('swing_trades', 0)

        scalp_status = "ON" if self.config.enable_scalp else "OFF"
        swing_status = "ON" if self.config.enable_swing else "OFF"

        # Frequency info
        now = time.time()
        active_timestamps = [
            t for t in self.trade_timestamps if now - t < 3600
        ]
        trades_this_hour = len(active_timestamps)

        # Calculate portfolio PnL (unrealized + realized)
        available = self._get_free_margin()
        unrealized, realized, total_portfolio_pnl = self._get_portfolio_pnl()
        dashboard = f"""
┌────────────────────────────────────────────────────────────────┐
│ 🤖 HYPERLIQUID SCALPER+SWING │ Cycle #{self.cycle_count}                 │
├────────────────────────────────────────────────────────────────┤
│ Total Balance:  ${equity:>9.2f}  │ Uptime: {hours}h {minutes}m                  │
│ Available:      ${available:>9.2f}  │ Daily PnL: ${stats.get('daily_pnl', 0):>+7.2f}                   │
│ Portfolio PnL:  ${total_portfolio_pnl:>+9.2f}  (${unrealized:>+.2f} unreal, ${realized:>+.2f} realized)       │
│ Trades: {stats['total_trades']} | Win Rate: {float(stats['win_rate']):.0f}% | Rate: {trades_this_hour}/{self.max_trades_per_hour}/hr     │
├────────────────────────────────────────────────────────────────┤
│ ⚡ Scalp [{scalp_status}]: {scalp_count} trades | PnL: ${scalp_pnl:>+.2f}                │
│ 🔄 Swing [{swing_status}]: {swing_count} trades | PnL: ${swing_pnl:>+.2f}                │
├────────────────────────────────────────────────────────────────┤
│ Prices: {' │ '.join(f"{c} ${self.prices.get(c, 0):>7.2f}" for c in self.config.assets)} │
├────────────────────────────────────────────────────────────────┤
│ Positions ({total_position_count}/{self.config.max_concurrent_positions})  │ Open Orders: {order_count}                     │
{positions_str}└────────────────────────────────────────────────────────────────┘"""
        print(dashboard, flush=True)
        log.info(dashboard)

    def run(self):
        """Main trading loop."""
        import signal as sig_module

        self.running = True

        def _shutdown(sig, frame):
            log.info("\n🛑 Shutting down gracefully...")
            self.running = False

        sig_module.signal(sig_module.SIGINT, _shutdown)
        sig_module.signal(sig_module.SIGTERM, _shutdown)

        log.info("🚀 Trading bot started — entering main loop")
        log.info(f"   Assets: {list(self.config.assets.keys())}")
        log.info(
            f"   Leverage: {self.config.leverage}x | "
            f"Scalp: {self.config.candle_interval} | "
            f"Swing: {self.config.candle_interval_swing}"
        )
        log.info(
            f"   Scan: every {self.config.scan_interval_seconds}s | "
            f"Swing eval: every {self.swing_eval_interval}s"
        )
        log.info(
            f"   Frequency: {self.max_trades_per_hour}/hr max | "
            f"{self.global_cooldown_seconds}s global CD | "
            f"{self.coin_cooldown_seconds}s coin CD"
        )

        swing_coins = [
            c for c, sc in self.config.swing_assets.items()
            if sc.enabled
        ]
        if self.config.enable_swing:
            log.info(f"   Swing-enabled coins: {swing_coins}")

        last_daily_reset = datetime.now(timezone.utc).date()

        while self.running:
            try:
                self.cycle_count += 1

                today = datetime.now(timezone.utc).date()
                if today != last_daily_reset:
                    equity = self._get_equity()
                    self.risk_mgr.reset_daily(equity)
                    last_daily_reset = today

                self._get_mid_prices()
                if not self.prices:
                    log.warning("No prices available — retrying...")
                    time.sleep(5)
                    continue

                self._sync_exchange_positions()
                self._detect_orphaned_positions()  # V6.3: recover untracked positions with SL/TP
                self._manage_positions()
                
                # ── Periodic SL Verification (every 5 cycles) ─────────────
                if self.cycle_count % 5 == 0:
                    self._verify_all_sl_orders()

                for coin, asset_cfg in self.config.assets.items():
                    if not self.running:
                        break

                    if self._has_any_position(coin):
                        continue

                    opened_scalp = False

                    if self.config.enable_scalp:
                        # V6.1 TIER 2: Session filter — skip low-liquidity hours
                        skip_hours = getattr(self.config, 'skip_utc_hours', [])
                        if skip_hours:
                            import datetime as _dt
                            current_utc_hour = _dt.datetime.utcnow().hour
                            if current_utc_hour in skip_hours:
                                continue  # Skip this coin during low-liquidity hours
                        
                        signal = self._evaluate_scalp_asset(coin)
                        if (
                            signal is not None
                            and signal.direction != Direction.NONE
                        ):
                            self._try_open_scalp(coin, signal, asset_cfg)
                            if self._has_any_position(coin):
                                opened_scalp = True

                    if (
                        self.config.enable_swing
                        and not opened_scalp
                        and not self._has_any_position(coin)
                    ):
                        swing_cfg = self.config.swing_assets.get(coin)
                        if swing_cfg and swing_cfg.enabled:
                            swing_signal = self._evaluate_swing_asset(coin)
                            if (
                                swing_signal is not None
                                and swing_signal.direction != Direction.NONE
                            ):
                                self._try_open_swing(
                                    coin, swing_signal, swing_cfg
                                )

                if self.config.verbose and self.cycle_count % 3 == 0:
                    self._print_dashboard()

                time.sleep(self.config.scan_interval_seconds)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"❗ Main loop error: {e}", exc_info=True)
                time.sleep(10)

        self._shutdown_gracefully()

    def _shutdown_gracefully(self):
        """Close all positions and clean up."""
        log.info("🛑 Closing all positions...")

        for pos_key in list(self.risk_mgr.positions.keys()):
            pos = self.risk_mgr.positions[pos_key]
            coin = pos.coin

            order_ids = [pos.tp_order_id, pos.sl_order_id]
            ptp = self.partial_tp.get(coin)
            if ptp and ptp.get("order_id"):
                order_ids.append(ptp["order_id"])
            self._cancel_orders(coin, order_ids)

            result = self._close_position_on_exchange(coin, pos)
            if result is None:
                log.error(f"❌ Failed to close {coin} during shutdown")

            self._cancel_all_coin_orders(coin)
            price = self.prices.get(coin, pos.entry_price)
            self.risk_mgr.close_position(
                coin, price, "BOT_SHUTDOWN", timeframe=pos.timeframe
            )

        self.partial_tp.clear()

        stats = self.risk_mgr.get_stats()
        log.info(f"\n{'='*60}")
        log.info(f"📊 SESSION SUMMARY")
        log.info(f"   Total Trades:  {stats['total_trades']}")
        log.info(f"   Win Rate:      {float(stats['win_rate']):.0%}")
        log.info(f"   Total PnL:     ${stats['total_pnl']:+.2f}")
        log.info(f"   Session PnL:   ${stats.get('daily_pnl', 0):+.2f}")
        log.info(
            f"   Scalp:  {stats.get('scalp_trades', 0)} trades | "
            f"PnL: ${stats.get('scalp_pnl', 0):+.2f}"
        )
        log.info(
            f"   Swing:  {stats.get('swing_trades', 0)} trades | "
            f"PnL: ${stats.get('swing_pnl', 0):+.2f}"
        )
        log.info(f"{'='*60}")