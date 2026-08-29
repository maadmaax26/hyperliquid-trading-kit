#!/usr/bin/env python3
"""
Hyperliquid Market Maker Bot — Backtesting Simulation
======================================================
Simulates the MM strategy on 5m historical candle data for kPEPE, kBONK, ARB.
Implements ADX-based dynamic spread, inventory skew, max-hold unwind,
fees & rebates, and per-coin equity tracking.

Limitations (overestimates fill frequency):
  - Orders fill if candle low/high crosses order price (no queue position)
  - All-or-nothing fills (no partial fills)
  - Unlimited liquidity at order price (no depth model)
  - Single order per side per candle (refresh = 1 per 5m candle)
"""
import json, os, math, time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

import numpy as np

# ─── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICE_DIR = os.path.join(BASE_DIR, "price_history")
RESULTS_FILE = os.path.join(BASE_DIR, "mm_backtest_results.json")

# ─── Config (mirrors mm_config.py) ──────────────────────────────────────
COINS = ["kPEPE", "kBONK", "ARB"]

# Per-coin half-spreads and limits
SPREAD_PCT = {"kPEPE": 0.0010, "kBONK": 0.0012, "ARB": 0.0012}
MIN_SPREAD = {"kPEPE": 0.0004, "kBONK": 0.0005, "ARB": 0.0005}
MAX_SPREAD = {"kPEPE": 0.0040, "kBONK": 0.0045, "ARB": 0.0040}
MAX_INV_PCT = 0.12        # 12% equity per asset
SKEW_FACTOR = 0.6
ORDER_SIZE_PCT = 0.035     # 3.5% equity per order
LEVERAGE = 3

# ADX thresholds
ADX_TREND = 25.0
ADX_STRONG = 40.0
ADX_RANGE = 20.0
TREND_MULT = 2.0
STRONG_MULT = 3.0
RANGE_MULT = 0.7

# Inventory management
UNWIND_THRESHOLD = 0.70    # 70% of max inventory → aggressive unwind
UNWIND_SPREAD_MULT = 0.5  # tighten unwind side by 0.5x
MAX_HOLD_MIN = 120         # force close after 120 minutes

# Fees
MAKER_FEE_PCT = 0.0001    # 0.01% per side
MAKER_REBATE_PCT = 0.00003 # 0.003% per side

# Risk
DAILY_LOSS_PCT = 0.10
EMERGENCY_INV_PCT = 0.90  # emergency close at 90% of max total inventory

# Backtest
START_EQUITY = 1000.0
CANDLE_MIN = 5             # 5m candles

# ─── Data structures ────────────────────────────────────────────────────
@dataclass
class Fill:
    ts: int
    coin: str
    side: str          # "buy" or "sell"
    price: float
    size: float        # notional in USD
    qty: float         # coin quantity
    fee: float
    rebate: float
    inventory_after: float

@dataclass
class Position:
    coin: str
    side: str          # "long" or "short"
    entry_price: float
    qty: float
    ts: int            # entry timestamp (ms)

@dataclass
class CoinState:
    inventory: float = 0.0       # signed: + long, - short
    fills: List[Fill] = field(default_factory=list)
    pnl: float = 0.0
    gross_pnl: float = 0.0
    fees_paid: float = 0.0
    rebates_earned: float = 0.0
    fills_buy: int = 0
    fills_sell: int = 0
    round_trips: int = 0
    max_inventory: float = 0.0
    inv_sum: float = 0.0
    inv_count: int = 0
    time_at_max: int = 0
    # Spread tracking
    spread_by_regime: Dict[str, list] = field(default_factory=lambda: {"range": [], "neutral": [], "trend": [], "strong_trend": []})
    fills_by_regime: Dict[str, int] = field(default_factory=lambda: {"range": 0, "neutral": 0, "trend": 0, "strong_trend": 0})
    candles_by_regime: Dict[str, int] = field(default_factory=lambda: {"range": 0, "neutral": 0, "trend": 0, "strong_trend": 0})
    avg_spread: float = 0.0
    spread_sum: float = 0.0
    spread_count: int = 0


# ─── Technical indicators ───────────────────────────────────────────────
def calc_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Calculate ADX (Average Directional Index) using Wilder's smoothing."""
    n = len(closes)
    adx = np.full(n, np.nan)

    if n < period * 2:
        return adx

    # True Range
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))

    # Directional Movement
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # Wilder's smoothing
    atr = np.full(n, np.nan)
    plus_di_arr = np.full(n, np.nan)
    minus_di_arr = np.full(n, np.nan)

    # First ATR = simple average of first `period` TRs
    atr[period] = np.mean(tr[1:period+1])
    smoothed_plus = np.sum(plus_dm[1:period+1])
    smoothed_minus = np.sum(minus_dm[1:period+1])

    for i in range(period + 1, n):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
        smoothed_plus = (smoothed_plus * (period - 1) + plus_dm[i]) / period
        smoothed_minus = (smoothed_minus * (period - 1) + minus_dm[i]) / period

        if atr[i] > 0 and not np.isnan(atr[i]):
            plus_di_arr[i] = 100 * smoothed_plus / atr[i]
            minus_di_arr[i] = 100 * smoothed_minus / atr[i]

    # DX
    dx = np.full(n, np.nan)
    for i in range(period, n):
        if not np.isnan(plus_di_arr[i]) and not np.isnan(minus_di_arr[i]):
            di_sum = plus_di_arr[i] + minus_di_arr[i]
            if di_sum > 0:
                dx[i] = 100 * abs(plus_di_arr[i] - minus_di_arr[i]) / di_sum

    # ADX = Wilder's smoothed DX
    first_adx_idx = period * 2
    if first_adx_idx < n and not np.isnan(dx[period:first_adx_idx]).any() is False:
        valid = dx[period:first_adx_idx]
        valid = valid[~np.isnan(valid)]
        if len(valid) > 0:
            adx[first_adx_idx] = np.mean(valid)
            for i in range(first_adx_idx + 1, n):
                if not np.isnan(adx[i-1]) and not np.isnan(dx[i]):
                    adx[i] = (adx[i-1] * (period - 1) + dx[i]) / period

    return adx


def calc_ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    ema = np.full(len(values), np.nan)
    if len(values) < period:
        return ema
    multiplier = 2.0 / (period + 1)
    ema[period - 1] = np.mean(values[:period])
    for i in range(period, len(values)):
        ema[i] = values[i] * multiplier + ema[i-1] * (1 - multiplier)
    return ema


def calc_volume_ratio(volumes: np.ndarray, period: int = 20) -> np.ndarray:
    """Volume ratio: current volume / rolling average."""
    ratio = np.full(len(volumes), 1.0)
    for i in range(period, len(volumes)):
        avg_vol = np.mean(volumes[i-period:i])
        if avg_vol > 0:
            ratio[i] = volumes[i] / avg_vol
    return ratio


# ─── Core backtest engine ────────────────────────────────────────────────
class BacktestEngine:
    def __init__(self, enhanced: bool = False):
        self.enhanced = enhanced
        self.equity = START_EQUITY
        self.start_equity = START_EQUITY
        self.coin_states: Dict[str, CoinState] = {c: CoinState() for c in COINS}
        self.all_fills: List[Fill] = []
        self.equity_curve: List[Tuple[int, float]] = []  # (ts, equity)
        self.daily_pnl: Dict[str, float] = defaultdict(float)  # date_str -> pnl
        self.positions: Dict[str, Optional[Position]] = {c: None for c in COINS}

        # Enhancement params
        self.vol_filter_threshold = 1.5 if enhanced else 0.0  # skip quoting in low vol
        self.trend_stop_mult = 2.5 if enhanced else 3.0      # reduce order size in trends
        self.fast_unwind_mult = 0.3 if enhanced else 0.5     # tighter unwind in enhanced
        self.size_scale_in_trend = 0.5 if enhanced else 1.0   # smaller orders in trends
        self.min_vol_for_quote = 0.5 if enhanced else 0.0    # min volume ratio to quote
        self.adx_short_circuit = True if enhanced else False  # don't quote in strong trends

    def load_data(self, coin: str) -> list:
        path = os.path.join(PRICE_DIR, f"{coin}_5m.json")
        with open(path) as f:
            data = json.load(f)
        # Normalize keys
        normalized = []
        for c in data:
            normalized.append({
                "t": c["t"],
                "o": float(c["o"]),
                "h": float(c["h"]),
                "l": float(c["l"]),
                "c": float(c["c"]),
                "v": float(c["v"]),
            })
        return normalized

    def get_adx_regime(self, adx_val: float) -> str:
        if np.isnan(adx_val):
            return "neutral"
        if adx_val >= ADX_STRONG:
            return "strong_trend"
        elif adx_val >= ADX_TREND:
            return "trend"
        elif adx_val < ADX_RANGE:
            return "range"
        else:
            return "neutral"

    def calc_spread(self, coin: str, adx_val: float, regime: str) -> float:
        base = SPREAD_PCT[coin]
        if regime == "strong_trend":
            spread = base * STRONG_MULT
        elif regime == "trend":
            spread = base * TREND_MULT
        elif regime == "range":
            spread = base * RANGE_MULT
        else:
            spread = base

        # Clamp to min/max
        spread = max(MIN_SPREAD[coin], min(MAX_SPREAD[coin], spread))
        return spread

    def calc_inventory_skew(self, coin: str, inventory: float, equity: float, spread: float, mid_price: float = 1.0) -> float:
        """Return price shift as fraction (positive = shift up)."""
        max_inv = equity * MAX_INV_PCT
        if max_inv <= 0:
            return 0.0
        # Convert inventory (coin qty) to notional (dollars) for ratio
        inv_notional = inventory * mid_price
        inv_ratio = inv_notional / max_inv  # -1 to +1
        # When long (positive inventory), shift orders DOWN (negative)
        # When short (negative inventory), shift orders UP (positive)
        skew = -inv_ratio * SKEW_FACTOR * spread

        # Double skew at 70%+ inventory (enhanced: even more aggressive)
        if abs(inv_ratio) >= UNWIND_THRESHOLD:
            skew_mult = 2.0 if not self.enhanced else 2.5
            skew = -inv_ratio * SKEW_FACTOR * spread * skew_mult
            # But cap the skew
            max_skew = spread * 3.0
            skew = max(-max_skew, min(max_skew, skew))

        return skew

    def run(self):
        # Load all coin data
        all_data = {}
        for coin in COINS:
            all_data[coin] = self.load_data(coin)

        # Find common time range (align by timestamp)
        # Each coin has ~5000 candles but slightly different start times
        # We'll iterate by index, using the candle at each index for each coin

        # Get min length
        min_len = min(len(all_data[c]) for c in COINS)
        print(f"Backtest period: {min_len} candles ({min_len * 5 / 60:.1f} hours)")

        # Calculate indicators for each coin
        indicators = {}
        for coin in COINS:
            data = all_data[coin]
            highs = np.array([c["h"] for c in data])
            lows = np.array([c["l"] for c in data])
            closes = np.array([c["c"] for c in data])
            volumes = np.array([c["v"] for c in data])

            adx = calc_adx(highs, lows, closes, 14)
            ema = calc_ema(closes, 20)
            vol_ratio = calc_volume_ratio(volumes, 20)

            indicators[coin] = {"adx": adx, "ema": ema, "vol_ratio": vol_ratio}
            print(f"  {coin}: ADX range [{np.nanmin(adx):.1f}, {np.nanmax(adx):.1f}], "
                  f"price [{closes[0]:.6f}, {closes[-1]:.6f}]")

        # Main simulation loop
        prev_date = None
        day_start_equity = START_EQUITY

        for i in range(min_len):
            ts = all_data[COINS[0]][i]["t"]
            date_str = time.strftime("%Y-%m-%d", time.gmtime(ts / 1000))

            # Daily loss check
            if prev_date is not None and date_str != prev_date:
                day_pnl = self.equity - day_start_equity
                if day_start_equity > 0:
                    day_ret = day_pnl / day_start_equity
                    if day_ret <= -DAILY_LOSS_PCT:
                        # Would stop trading — but we continue for backtest continuity
                        pass
                day_start_equity = self.equity
                prev_date = date_str
            else:
                prev_date = date_str

            # Check max hold time — force close old positions
            for coin in COINS:
                pos = self.positions[coin]
                if pos is not None:
                    hold_min = (ts - pos.ts) / (1000 * 60)
                    if hold_min >= MAX_HOLD_MIN:
                        self._force_close(coin, ts, all_data[coin][i]["c"], "max_hold")

            # Emergency inventory check
            total_inv_pct = sum(abs(self.coin_states[c].inventory) for c in COINS) / max(self.equity, 1)
            if total_inv_pct >= EMERGENCY_INV_PCT:
                for coin in COINS:
                    if abs(self.coin_states[coin].inventory) > 0:
                        self._force_close(coin, ts, all_data[coin][i]["c"], "emergency")

            # Process each coin
            for coin in COINS:
                candle = all_data[coin][i]
                cs = self.coin_states[coin]

                adx_val = indicators[coin]["adx"][i]
                vol_r = indicators[coin]["vol_ratio"][i]
                regime = self.get_adx_regime(adx_val)

                # Track regime stats
                cs.candles_by_regime[regime] += 1

                # Skip if ADX not yet available
                if np.isnan(adx_val):
                    continue

                # Enhancement: skip quoting in strong trends
                if self.adx_short_circuit and regime == "strong_trend":
                    # Only unwind if inventory exists
                    if abs(cs.inventory) > 0:
                        self._try_unwind(coin, candle, regime, spread_mult=self.fast_unwind_mult)
                    continue

                # Enhancement: volume filter — skip if volume too low
                if vol_r < self.min_vol_for_quote:
                    continue

                # Calculate spread
                spread = self.calc_spread(coin, adx_val, regime)

                # Calculate mid price (use close as proxy for mid)
                mid = candle["c"]

                # Calculate order size
                order_notional = self.equity * ORDER_SIZE_PCT
                # Enhancement: reduce size in trends
                if regime in ("trend", "strong_trend") and self.enhanced:
                    order_notional *= self.size_scale_in_trend

                # Minimum notional check ($10 on HL)
                if order_notional < 10.0:
                    order_notional = 10.0

                # Inventory skew
                skew = self.calc_inventory_skew(coin, cs.inventory, self.equity, spread, mid)

                # Unwind logic: if at 70%+ of max inventory, tighten the unwind side
                max_inv = self.equity * MAX_INV_PCT
                # inv_ratio: compare inventory notional (dollars) vs max_inv (dollars)
                inv_notional = cs.inventory * mid
                inv_ratio = inv_notional / max_inv if max_inv > 0 else 0

                # Determine if we should skip a side due to max inventory
                # Convert inventory (coin qty) to notional for comparison with max_inv (dollars)
                inv_notional = cs.inventory * mid
                can_buy = inv_notional + order_notional <= max_inv
                can_sell = inv_notional - order_notional >= -max_inv

                # Unwind: if inventory is long, tighten ask (sell side) to unwind
                bid_spread = spread
                ask_spread = spread

                if abs(inv_ratio) >= UNWIND_THRESHOLD:
                    if inv_ratio > 0:  # long → tighten ask
                        ask_spread = spread * self.fast_unwind_mult if self.enhanced else spread * UNWIND_SPREAD_MULT
                        can_buy = False  # stop adding to long
                    else:  # short → tighten bid
                        bid_spread = spread * self.fast_unwind_mult if self.enhanced else spread * UNWIND_SPREAD_MULT
                        can_sell = False  # stop adding to short

                # Apply skew to prices
                bid_price = mid * (1 - bid_spread + skew)
                ask_price = mid * (1 + ask_spread + skew)

                # Ensure bid < ask
                if bid_price >= ask_price:
                    bid_price = mid * (1 - MIN_SPREAD[coin])
                    ask_price = mid * (1 + MIN_SPREAD[coin])

                # Track spread stats
                actual_spread = (ask_price - bid_price) / (2 * mid)
                cs.spread_sum += actual_spread
                cs.spread_count += 1
                cs.spread_by_regime[regime].append(actual_spread)

                # Check fills
                filled = False

                # Bid fill: candle low <= bid price
                if can_buy and bid_price > 0 and candle["l"] <= bid_price:
                    qty = order_notional / bid_price
                    fee = order_notional * MAKER_FEE_PCT
                    rebate = order_notional * MAKER_REBATE_PCT

                    cs.inventory += qty
                    cs.fees_paid += fee
                    cs.rebates_earned += rebate
                    # Cash: pay notional for the asset, minus fee, plus rebate
                    self.equity -= order_notional  # buy cost
                    self.equity -= fee
                    self.equity += rebate

                    fill = Fill(ts=ts, coin=coin, side="buy", price=bid_price,
                                size=order_notional, qty=qty, fee=fee, rebate=rebate,
                                inventory_after=cs.inventory)
                    cs.fills.append(fill)
                    cs.fills_buy += 1
                    cs.fills_by_regime[regime] += 1
                    self.all_fills.append(fill)
                    filled = True

                    # Track position
                    self.positions[coin] = Position(coin=coin, side="long",
                                                     entry_price=bid_price, qty=qty, ts=ts)

                # Ask fill: candle high >= ask price
                if can_sell and ask_price > 0 and candle["h"] >= ask_price:
                    qty = order_notional / ask_price
                    fee = order_notional * MAKER_FEE_PCT
                    rebate = order_notional * MAKER_REBATE_PCT

                    cs.inventory -= qty
                    cs.fees_paid += fee
                    cs.rebates_earned += rebate
                    # Cash: receive notional for selling the asset, minus fee, plus rebate
                    self.equity += order_notional  # sell proceeds
                    self.equity -= fee
                    self.equity += rebate

                    fill = Fill(ts=ts, coin=coin, side="sell", price=ask_price,
                                size=order_notional, qty=qty, fee=fee, rebate=rebate,
                                inventory_after=cs.inventory)
                    cs.fills.append(fill)
                    cs.fills_sell += 1
                    cs.fills_by_regime[regime] += 1
                    self.all_fills.append(fill)
                    filled = True

                    self.positions[coin] = Position(coin=coin, side="short",
                                                     entry_price=ask_price, qty=qty, ts=ts)

                # Check for round trip (inventory crosses zero)
                self._check_round_trip(coin, candle["c"], ts)

                # Update inventory stats (in notional terms)
                inv_notional = abs(cs.inventory) * candle["c"]
                cs.inv_sum += inv_notional
                cs.inv_count += 1
                if inv_notional > cs.max_inventory:
                    cs.max_inventory = inv_notional
                if inv_notional >= max_inv * 0.95:
                    cs.time_at_max += 1

            # Mark-to-market equity
            mtm_equity = self._calc_mtm_equity(all_data, i)
            self.equity_curve.append((ts, mtm_equity))

            # Track daily PnL
            if len(self.equity_curve) >= 2:
                day_pnl = mtm_equity - (self.equity_curve[max(0, len(self.equity_curve)-2)][1])
                self.daily_pnl[date_str] += day_pnl

        # Close all positions at end
        for coin in COINS:
            if abs(self.coin_states[coin].inventory) > 0.01:
                final_price = all_data[coin][-1]["c"]
                self._force_close(coin, all_data[COINS[0]][-1]["t"], final_price, "end_of_sim")

        # Calculate final results
        self._calc_results()

    def _try_unwind(self, coin: str, candle: dict, regime: str, spread_mult: float):
        """Attempt to unwind inventory by placing tighter orders on the unwind side."""
        cs = self.coin_states[coin]
        if abs(cs.inventory) < 0.01:
            return

        mid = candle["c"]
        spread = SPREAD_PCT[coin] * spread_mult
        spread = max(MIN_SPREAD[coin], spread)

        order_notional = abs(cs.inventory) * mid * 0.5  # unwind half
        if order_notional < 10.0:
            order_notional = 10.0

        if cs.inventory > 0:  # long → sell to unwind
            ask_price = mid * (1 + spread)
            if candle["h"] >= ask_price:
                qty = order_notional / ask_price
                fee = order_notional * MAKER_FEE_PCT
                rebate = order_notional * MAKER_REBATE_PCT
                cs.inventory -= qty
                cs.fees_paid += fee
                cs.rebates_earned += rebate
                self.equity += order_notional  # sell proceeds
                self.equity -= fee
                self.equity += rebate
                fill = Fill(ts=candle["t"], coin=coin, side="sell", price=ask_price,
                            size=order_notional, qty=qty, fee=fee, rebate=rebate,
                            inventory_after=cs.inventory)
                cs.fills.append(fill)
                cs.fills_sell += 1
                cs.fills_by_regime[regime] += 1
                self.all_fills.append(fill)
        else:  # short → buy to unwind
            bid_price = mid * (1 - spread)
            if candle["l"] <= bid_price:
                qty = order_notional / bid_price
                fee = order_notional * MAKER_FEE_PCT
                rebate = order_notional * MAKER_REBATE_PCT
                cs.inventory += qty
                cs.fees_paid += fee
                cs.rebates_earned += rebate
                self.equity -= order_notional  # buy cost
                self.equity -= fee
                self.equity += rebate
                fill = Fill(ts=candle["t"], coin=coin, side="buy", price=bid_price,
                            size=order_notional, qty=qty, fee=fee, rebate=rebate,
                            inventory_after=cs.inventory)
                cs.fills.append(fill)
                cs.fills_buy += 1
                cs.fills_by_regime[regime] += 1
                self.all_fills.append(fill)

    def _force_close(self, coin: str, ts: int, price: float, reason: str):
        """Force close entire inventory at given price (taker-like, but we use maker fee for simplicity)."""
        cs = self.coin_states[coin]
        if abs(cs.inventory) < 0.01:
            self.positions[coin] = None
            return

        qty = abs(cs.inventory)
        notional = qty * price
        fee = notional * MAKER_FEE_PCT
        rebate = notional * MAKER_REBATE_PCT

        if cs.inventory > 0:
            # Sell to close long — receive notional
            cs.inventory -= qty
            side = "sell"
            self.equity += notional  # sell proceeds
        else:
            # Buy to close short — pay notional
            cs.inventory += qty
            side = "buy"
            self.equity -= notional  # buy cost

        cs.fees_paid += fee
        cs.rebates_earned += rebate
        self.equity -= fee
        self.equity += rebate

        fill = Fill(ts=ts, coin=coin, side=side, price=price,
                    size=notional, qty=qty, fee=fee, rebate=rebate,
                    inventory_after=cs.inventory)
        cs.fills.append(fill)
        self.all_fills.append(fill)
        self.positions[coin] = None

    def _check_round_trip(self, coin: str, mark_price: float, ts: int):
        """Check if inventory changed sign → completed a round trip, realize PnL."""
        cs = self.coin_states[coin]
        # We track round trips by counting buy-sell pairs that reduce inventory toward zero
        # Simple approach: count when a fill reduces |inventory|
        if len(cs.fills) < 2:
            return
        last_fill = cs.fills[-1]
        prev_inv = cs.fills[-2].inventory_after if len(cs.fills) >= 2 else 0
        curr_inv = last_fill.inventory_after

        # If the fill reduced absolute inventory, it's (partially) closing → round trip
        if abs(curr_inv) < abs(prev_inv):
            cs.round_trips += 1
            # Calculate realized PnL from this closing fill
            # Approximate: the fill captures spread relative to entry
            # Use mark-to-market approach
            if last_fill.side == "sell" and prev_inv > 0:
                # Closing a long: profit = (sell_price - avg_entry) * qty
                # Simplified: use spread capture
                pnl = last_fill.size * (last_fill.price - mark_price) / mark_price * 0  # placeholder
                # Better: realized = (sell_price - entry_price) * qty
                # We'll compute properly in results
            elif last_fill.side == "buy" and prev_inv < 0:
                pnl = 0  # placeholder

    def _calc_mtm_equity(self, all_data: dict, idx: int) -> float:
        """Calculate mark-to-market equity = cash + inventory value at mark price."""
        equity = self.equity  # cash position
        for coin in COINS:
            inv = self.coin_states[coin].inventory
            if abs(inv) > 0.01 and idx < len(all_data[coin]):
                mark = all_data[coin][idx]["c"]
                # Add market value of inventory (long = positive, short = negative)
                equity += inv * mark
        return equity

    def _calc_results(self):
        """Calculate final performance metrics."""
        # Total fills
        self.total_fills = len(self.all_fills)

        # Per-coin realized PnL using FIFO matching
        self.total_pnl = 0.0
        self.total_fees = 0.0
        self.total_rebates = 0.0
        self.total_round_trips = 0

        for coin in COINS:
            cs = self.coin_states[coin]
            cs.pnl = self._calc_coin_pnl(coin)
            self.total_pnl += cs.pnl
            self.total_fees += cs.fees_paid
            self.total_rebates += cs.rebates_earned
            self.total_round_trips += cs.round_trips

        # Final equity = last equity curve point (cash + inventory at mark)
        if len(self.equity_curve) > 0:
            self.final_equity = self.equity_curve[-1][1]
        else:
            self.final_equity = self.equity

        # Total PnL = final equity - start equity
        self.total_pnl = self.final_equity - self.start_equity

        # Recalculate per-coin PnL from equity change (simplified: use FIFO for per-coin)
        # Keep the FIFO PnL per coin for analysis
        fifo_total = sum(self.coin_states[c].pnl for c in COINS)
        if abs(fifo_total) > 0:
            # Scale per-coin PnL to match total
            scale = self.total_pnl / fifo_total if abs(fifo_total) > 0.01 else 1.0
            for coin in COINS:
                self.coin_states[coin].pnl *= scale

        # Calculate max drawdown
        eq_arr = np.array([e for _, e in self.equity_curve])
        if len(eq_arr) > 0:
            running_max = np.maximum.accumulate(eq_arr)
            drawdowns = (eq_arr - running_max) / running_max
            self.max_drawdown = abs(np.nanmin(drawdowns)) if len(drawdowns) > 0 else 0.0
        else:
            self.max_drawdown = 0.0

        # Sharpe ratio (from equity curve, per-5m returns)
        if len(eq_arr) > 1:
            returns = np.diff(eq_arr) / eq_arr[:-1]
            # Annualize: 5m candles → 288 per day → ~252 trading days
            periods_per_year = 288 * 365
            if np.std(returns) > 0:
                self.sharpe = np.mean(returns) / np.std(returns) * math.sqrt(periods_per_year)
            else:
                self.sharpe = 0.0
        else:
            self.sharpe = 0.0

    def _calc_coin_pnl(self, coin: str) -> float:
        """Calculate realized PnL for a coin using FIFO matching."""
        cs = self.coin_states[coin]
        pnl = 0.0
        buys = []  # queue of (price, qty) for long entries
        sells = []  # queue of (price, qty) for short entries

        for fill in cs.fills:
            if fill.side == "buy":
                if sells:  # closing a short
                    # Match with oldest short
                    remaining = fill.qty
                    while remaining > 0 and sells:
                        s_price, s_qty = sells[0]
                        matched = min(remaining, s_qty)
                        pnl += (s_price - fill.price) * matched  # short profit = sell high, buy low
                        sells[0] = (s_price, s_qty - matched)
                        if sells[0][1] <= 0:
                            sells.pop(0)
                        remaining -= matched
                    if remaining > 0:
                        buys.append((fill.price, remaining))
                else:
                    buys.append((fill.price, fill.qty))
            else:  # sell
                if buys:  # closing a long
                    remaining = fill.qty
                    while remaining > 0 and buys:
                        b_price, b_qty = buys[0]
                        matched = min(remaining, b_qty)
                        pnl += (fill.price - b_price) * matched  # long profit = sell high minus buy low
                        buys[0] = (b_price, b_qty - matched)
                        if buys[0][1] <= 0:
                            buys.pop(0)
                        remaining -= matched
                    if remaining > 0:
                        sells.append((fill.price, remaining))
                else:
                    sells.append((fill.price, fill.qty))

        # Subtract fees and add rebates (already tracked separately, but PnL should be gross)
        # Net PnL = gross PnL - fees + rebates
        cs.gross_pnl = pnl
        net_pnl = pnl - cs.fees_paid + cs.rebates_earned
        return net_pnl

    def generate_report(self) -> dict:
        """Generate comprehensive performance report."""
        report = {
            "start_equity": self.start_equity,
            "final_equity": round(self.final_equity, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_fills": self.total_fills,
            "round_trips": self.total_round_trips,
            "fees_paid": round(self.total_fees, 2),
            "rebates_earned": round(self.total_rebates, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "sharpe_ratio": round(self.sharpe, 2),
            "enhanced": self.enhanced,
            "per_coin": {},
            "daily_pnl": {},
            "equity_curve_summary": {},
        }

        # Per-coin breakdown
        for coin in COINS:
            cs = self.coin_states[coin]
            avg_inv = cs.inv_sum / max(cs.inv_count, 1)
            avg_spread = cs.spread_sum / max(cs.spread_count, 1)

            report["per_coin"][coin] = {
                "fills": len(cs.fills),
                "fills_buy": cs.fills_buy,
                "fills_sell": cs.fills_sell,
                "round_trips": cs.round_trips,
                "gross_pnl": round(cs.gross_pnl, 2),
                "fees_paid": round(cs.fees_paid, 2),
                "rebates_earned": round(cs.rebates_earned, 2),
                "net_pnl": round(cs.pnl, 2),
                "avg_inventory_notional": round(avg_inv, 2),
                "max_inventory_notional": round(cs.max_inventory, 2),
                "time_at_max_pct": round(cs.time_at_max / max(cs.inv_count, 1) * 100, 1),
                "avg_spread_pct": round(avg_spread * 100, 4),
                "fills_by_regime": cs.fills_by_regime,
                "candles_by_regime": cs.candles_by_regime,
                "spread_by_regime": {k: round(np.mean(v)*100, 4) if v else 0 for k, v in cs.spread_by_regime.items()},
                "fill_rate_by_regime": {k: round(cs.fills_by_regime[k] / max(cs.candles_by_regime[k], 1) * 100, 1)
                                        for k in cs.fills_by_regime},
            }

        # Daily PnL
        for date, pnl in sorted(self.daily_pnl.items()):
            report["daily_pnl"][date] = round(pnl, 2)

        # Equity curve summary
        eq_arr = np.array([e for _, e in self.equity_curve])
        if len(eq_arr) > 0:
            report["equity_curve_summary"] = {
                "start": round(eq_arr[0], 2),
                "end": round(eq_arr[-1], 2),
                "min": round(np.nanmin(eq_arr), 2),
                "max": round(np.nanmax(eq_arr), 2),
                "mean": round(np.nanmean(eq_arr), 2),
                "std": round(np.nanstd(eq_arr), 2),
                "data_points": len(eq_arr),
            }

        # Capture rate: PnL per fill
        report["capture_per_fill"] = round(self.total_pnl / max(self.total_fills, 1), 4)
        report["capture_per_round_trip"] = round(self.total_pnl / max(self.total_round_trips, 1), 4)

        return report


def print_report(report: dict, title: str = "BASELINE"):
    """Print detailed performance report."""
    print(f"\n{'='*70}")
    print(f"  HYPERLIQUID MM BOT BACKTEST — {title}")
    print(f"{'='*70}")
    print(f"\nStart Equity:        ${report['start_equity']:.2f}")
    print(f"Final Equity:        ${report['final_equity']:.2f}")
    print(f"Total PnL:           ${report['total_pnl']:.2f} ({report['total_pnl']/report['start_equity']*100:.2f}%)")
    print(f"Total Fills:         {report['total_fills']}")
    print(f"Round Trips:         {report['round_trips']}")
    print(f"Fees Paid:           ${report['fees_paid']:.4f}")
    print(f"Rebates Earned:      ${report['rebates_earned']:.4f}")
    print(f"Net Fees:            ${report['fees_paid'] - report['rebates_earned']:.4f}")
    print(f"Max Drawdown:        {report['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:        {report['sharpe_ratio']:.2f}")
    print(f"Capture/Fill:        ${report['capture_per_fill']:.4f}")
    print(f"Capture/Round Trip:  ${report['capture_per_round_trip']:.4f}")

    print(f"\n{'─'*70}")
    print(f"  PER-COIN BREAKDOWN")
    print(f"{'─'*70}")
    print(f"{'Coin':<8} {'Fills':>6} {'RT':>5} {'GrossPnL':>10} {'Fees':>8} {'Rebates':>9} {'NetPnL':>10} {'AvgInv':>9} {'MaxInv':>9} {'AtMax%':>7}")
    for coin in COINS:
        pc = report["per_coin"][coin]
        print(f"{coin:<8} {pc['fills']:>6} {pc['round_trips']:>5} "
              f"${pc['gross_pnl']:>8.2f} ${pc['fees_paid']:>6.2f} "
              f"${pc['rebates_earned']:>7.2f} ${pc['net_pnl']:>8.2f} "
              f"${pc['avg_inventory_notional']:>7.2f} ${pc['max_inventory_notional']:>7.2f} "
              f"{pc['time_at_max_pct']:>6.1f}%")

    print(f"\n{'─'*70}")
    print(f"  SPREAD & FILL ANALYSIS BY ADX REGIME")
    print(f"{'─'*70}")
    print(f"{'Coin':<8} {'Regime':<14} {'Candles':>8} {'Fills':>6} {'FillRate%':>9} {'AvgSpread%':>11}")
    for coin in COINS:
        pc = report["per_coin"][coin]
        for regime in ["range", "neutral", "trend", "strong_trend"]:
            candles = pc["candles_by_regime"].get(regime, 0)
            fills = pc["fills_by_regime"].get(regime, 0)
            fill_rate = pc["fill_rate_by_regime"].get(regime, 0)
            spread = pc["spread_by_regime"].get(regime, 0)
            print(f"{coin:<8} {regime:<14} {candles:>8} {fills:>6} {fill_rate:>8.1f}% {spread:>10.4f}%")

    print(f"\n{'─'*70}")
    print(f"  DAILY PnL BREAKDOWN")
    print(f"{'─'*70}")
    for date, pnl in sorted(report["daily_pnl"].items()):
        bar = "+" * int(max(pnl, 0) / 2) if pnl > 0 else "-" * int(abs(pnl) / 2)
        print(f"  {date}  ${pnl:>8.2f}  {bar}")

    print(f"\n{'─'*70}")
    print(f"  EQUITY CURVE SUMMARY")
    print(f"{'─'*70}")
    ec = report["equity_curve_summary"]
    print(f"  Data points: {ec['data_points']}")
    print(f"  Start:       ${ec['start']:.2f}")
    print(f"  End:         ${ec['end']:.2f}")
    print(f"  Min:         ${ec['min']:.2f}")
    print(f"  Max:         ${ec['max']:.2f}")
    print(f"  Mean:        ${ec['mean']:.2f}")
    print(f"  Std:         ${ec['std']:.2f}")


def main():
    # ─── Run baseline backtest ───────────────────────────────────────────
    print("=" * 70)
    print("  LOADING PRICE DATA...")
    print("=" * 70)

    engine = BacktestEngine(enhanced=False)
    engine.run()
    report = engine.generate_report()
    print_report(report, "BASELINE")

    # Save results
    results = {"baseline": report}

    # ─── Run enhanced backtest ───────────────────────────────────────────
    print(f"\n\n{'#'*70}")
    print(f"  RUNNING ENHANCED BACKTEST...")
    print(f"{'#'*70}")

    engine_enh = BacktestEngine(enhanced=True)
    engine_enh.run()
    report_enh = engine_enh.generate_report()
    print_report(report_enh, "ENHANCED")

    results["enhanced"] = report_enh

    # Save to JSON
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n\nResults saved to {RESULTS_FILE}")

    # Print comparison
    print(f"\n\n{'='*70}")
    print(f"  BASELINE vs ENHANCED COMPARISON")
    print(f"{'='*70}")
    print(f"{'Metric':<25} {'Baseline':>12} {'Enhanced':>12} {'Delta':>12}")
    print(f"{'─'*61}")
    print(f"{'Final Equity':<25} ${report['final_equity']:>10.2f} ${report_enh['final_equity']:>10.2f} ${report_enh['final_equity']-report['final_equity']:>10.2f}")
    print(f"{'Total PnL':<25} ${report['total_pnl']:>10.2f} ${report_enh['total_pnl']:>10.2f} ${report_enh['total_pnl']-report['total_pnl']:>10.2f}")
    print(f"{'Total Fills':<25} {report['total_fills']:>12} {report_enh['total_fills']:>12} {report_enh['total_fills']-report['total_fills']:>12}")
    print(f"{'Round Trips':<25} {report['round_trips']:>12} {report_enh['round_trips']:>12} {report_enh['round_trips']-report['round_trips']:>12}")
    print(f"{'Fees Paid':<25} ${report['fees_paid']:>10.4f} ${report_enh['fees_paid']:>10.4f} ${report_enh['fees_paid']-report['fees_paid']:>10.4f}")
    print(f"{'Rebates Earned':<25} ${report['rebates_earned']:>10.4f} ${report_enh['rebates_earned']:>10.4f} ${report_enh['rebates_earned']-report['rebates_earned']:>10.4f}")
    print(f"{'Max Drawdown':<25} {report['max_drawdown_pct']:>11.2f}% {report_enh['max_drawdown_pct']:>11.2f}% {report_enh['max_drawdown_pct']-report['max_drawdown_pct']:>11.2f}%")
    print(f"{'Sharpe Ratio':<25} {report['sharpe_ratio']:>12.2f} {report_enh['sharpe_ratio']:>12.2f} {report_enh['sharpe_ratio']-report['sharpe_ratio']:>12.2f}")


if __name__ == "__main__":
    main()