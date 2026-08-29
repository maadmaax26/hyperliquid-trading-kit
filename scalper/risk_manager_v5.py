"""
Enhanced Risk Management v5 - AI Stop Loss Protection
Adds SL verification, emergency monitoring, and fallback closes
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple
from config import BotConfig

log = logging.getLogger("risk_mgr")


@dataclass
class TradeRecord:
    coin: str
    direction: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    entry_time: float
    exit_time: float
    reason: str
    strategy: str = ""
    signal_score: int = 0
    timeframe: str = "5m"


@dataclass
class ActivePosition:
    coin: str
    direction: str
    entry_price: float
    size: float
    entry_time: float
    tp_price: float
    sl_price: float
    trailing_active: bool = False
    trailing_stop: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 999999.0
    tp_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    strategy: str = ""
    signal_score: int = 0
    timeframe: str = "5m"
    max_hold_until: float = 0.0
    sl_verified: bool = False  # Track if SL order was verified on exchange
    sl_place_time: float = 0.0  # When SL was placed
    highest_pnl: float = 0.0  # Track best PnL for BE move


class RiskManager:
    def __init__(self, config: BotConfig):
        self.config = config
        self.trade_history = []
        self.active_positions = {}
        self.positions = self.active_positions
        self.consecutive_losses = 0
        self.daily_pnl = 0
        self.sl_verify_failures = 0  # Track SL verification failures

    def reset_daily(self, equity: float = 0):
        """Reset daily statistics (called at day rollover)."""
        self.daily_pnl = 0
        log.info(f"📅 Daily stats reset | Equity: ${equity:.2f}")

    @staticmethod
    def position_key(coin: str, timeframe: str) -> str:
        return f"{coin}:{timeframe}"

    def register_position(self, pos: ActivePosition):
        key = self.position_key(pos.coin, pos.timeframe)
        self.active_positions[key] = pos
        log.info(f"📋 Registered {pos.coin} position: SL=${pos.sl_price:.2f}, "
                 f"TP=${pos.tp_price:.2f}, Verified={pos.sl_verified}")

    def mark_sl_verified(self, coin: str, timeframe: str = "5m"):
        """Mark that SL order was verified on exchange."""
        key = self.position_key(coin, timeframe)
        pos = self.active_positions.get(key)
        if pos:
            pos.sl_verified = True
            pos.sl_place_time = time.time()
            log.info(f"✅ SL verified for {coin} @ ${pos.sl_price:.2f}")

    def update_positions(self, current_price: float):
        """Legacy method - kept for compatibility."""
        pass

    def update_trailing_stops(self, coin: str, current_price: float, config, timeframe: str = "5m"):
        """Update trailing stop based on price movement."""
        key = self.position_key(coin, timeframe)
        pos = self.active_positions.get(key)
        if not pos:
            pos = self.active_positions.get(coin)
        if not pos:
            return

        # Track highest PnL for BE move logic
        if pos.direction == "LONG":
            unrealized = (current_price - pos.entry_price) / pos.entry_price
        else:
            unrealized = (pos.entry_price - current_price) / pos.entry_price
        
        if unrealized > pos.highest_pnl:
            pos.highest_pnl = unrealized

        # Read trailing parameters from the per-asset config (with sane fallbacks)
        trail_activation = getattr(config, 'trailing_activate_pct', 0.005)
        trail_dist = getattr(config, 'trailing_stop_pct', 0.002)

        if pos.direction == "LONG":
            if current_price > pos.entry_price * (1 + trail_activation):
                pos.trailing_active = True

            if pos.trailing_active:
                new_stop = current_price * (1 - trail_dist)
                if new_stop > pos.trailing_stop:
                    pos.trailing_stop = new_stop
                    log.info(f"📈 {coin} trailing stop updated: ${pos.trailing_stop:.2f}")

        elif pos.direction == "SHORT":
            if current_price < pos.entry_price * (1 - trail_activation):
                pos.trailing_active = True

            if pos.trailing_active:
                new_stop = current_price * (1 + trail_dist)
                if pos.trailing_stop == 0 or new_stop < pos.trailing_stop:
                    pos.trailing_stop = new_stop
                    log.info(f"📉 {coin} trailing stop updated: ${pos.trailing_stop:.2f}")

    def check_exit_conditions(self, coin: str, current_price: float, timeframe: str = "5m") -> Optional[str]:
        """Check if position should exit. Returns exit reason or None."""
        key = self.position_key(coin, timeframe)
        pos = self.active_positions.get(key)
        if not pos:
            pos = self.active_positions.get(coin)
        if not pos:
            return None

        # Max hold time check (100 minutes for scalps)
        hold_time = time.time() - pos.entry_time
        if timeframe == "5m":
            if hold_time > 6000:
                return "TIME_LIMIT"

        # Standard TP/SL checks
        if pos.direction == "LONG":
            if current_price >= pos.tp_price:
                return "TAKE_PROFIT"
            if current_price <= pos.sl_price:
                return "STOP_LOSS"
            if pos.trailing_active and current_price <= pos.trailing_stop:
                return f"TRAILING_STOP ({pos.trailing_stop:.2f})"

        elif pos.direction == "SHORT":
            if current_price <= pos.tp_price:
                return "TAKE_PROFIT"
            if current_price >= pos.sl_price:
                return "STOP_LOSS"
            if pos.trailing_active and current_price >= pos.trailing_stop:
                return f"TRAILING_STOP ({pos.trailing_stop:.2f})"

        return None

    def check_emergency_sl(self, coin: str, current_price: float, timeframe: str = "5m") -> Tuple[bool, str]:
        """
        EMERGENCY: Check if price breached SL but order didn't trigger.
        Returns (should_close: bool, reason: str)
        """
        key = self.position_key(coin, timeframe)
        pos = self.active_positions.get(key)
        if not pos:
            pos = self.active_positions.get(coin)
        if not pos:
            return False, ""

        # Check SL breach based on position side
        sl_breached = False
        breach_amount = 0

        if pos.direction == "LONG":
            if current_price <= pos.sl_price:
                sl_breached = True
                breach_amount = pos.sl_price - current_price
        else:  # SHORT
            if current_price >= pos.sl_price:
                sl_breached = True
                breach_amount = current_price - pos.sl_price

        if not sl_breached:
            return False, ""

        # SL was breached - check if we should emergency close
        sl_age = time.time() - pos.entry_time
        time_since_sl_placed = time.time() - pos.sl_place_time if pos.sl_place_time > 0 else sl_age

        # EMERGENCY CLOSE if:
        # 1. Price breached SL by more than 0.3%
        # 2. SL was placed >30 seconds ago (give exchange time to trigger)
        breach_pct = breach_amount / pos.sl_price if pos.sl_price > 0 else 0

        if breach_pct > 0.003 and time_since_sl_placed > 30:
            reason = (f"EMERGENCY_SL_CLOSE: SL=${pos.sl_price:.2f}, "
                     f"Price=${current_price:.2f}, Breach={breach_pct:.2%}")
            log.error(f"🚨 {coin}: {reason}")
            return True, reason

        # SL barely breached - wait briefly for exchange trigger
        if breach_pct > 0.001 and time_since_sl_placed > 60:
            reason = (f"EMERGENCY_SL_CLOSE (delayed): SL=${pos.sl_price:.2f}, "
                     f"Price=${current_price:.2f}, Age={time_since_sl_placed:.0f}s")
            log.error(f"🚨 {coin}: {reason}")
            return True, reason

        return False, ""

    def close_position(self, coin: str, current_price: float, reason: str, timeframe: str = "5m"):
        """Close a tracked position."""
        key = self.position_key(coin, timeframe)
        if key in self.active_positions:
            self._close_position(key, current_price, reason)
        elif coin in self.active_positions:
            self._close_position(coin, current_price, reason)

    def _close_position(self, key: str, current_price: float, reason: str):
        """Internal close logic."""
        pos = self.active_positions.pop(key, None)
        if not pos:
            return

        coin = pos.coin
        
        # Calculate PnL
        if pos.direction == "LONG":
            pnl = (current_price - pos.entry_price) * pos.size
            pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
        else:
            pnl = (pos.entry_price - current_price) * pos.size
            pnl_pct = ((pos.entry_price - current_price) / pos.entry_price) * 100

        trade = TradeRecord(
            coin=coin,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=current_price,
            size=pos.size,
            pnl=pnl,
            pnl_pct=pnl_pct,
            entry_time=pos.entry_time,
            exit_time=time.time(),
            reason=reason,
            strategy=pos.strategy,
            signal_score=pos.signal_score,
            timeframe=pos.timeframe
        )
        self.trade_history.append(trade)
        self._update_stats(trade)

        log.info(f"📊 {coin} CLOSED: ${pnl:+.2f} ({pnl_pct:+.2f}%) | Reason: {reason}")

    def _update_stats(self, trade: TradeRecord):
        self.daily_pnl += trade.pnl
        if trade.pnl > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1

    def calculate_position_size(self, coin: str, asset_cfg, equity: float, 
                                   current_price: float, sz_decimals: int = 4) -> float:
        """Calculate position size based on risk parameters."""
        # Get position size percentage from config
        position_size_pct = getattr(asset_cfg, 'position_size_pct', 0.25)
        leverage = getattr(self.config, 'leverage', 7)
        
        # Calculate raw size
        notional = equity * position_size_pct * leverage
        size = notional / current_price if current_price > 0 else 0
        
        # Round to proper decimals
        import math
        factor = 10 ** sz_decimals
        size = math.floor(size * factor) / factor
        
        return size

    def can_open_position(self, coin: str, asset_cfg=None, timeframe: str = "5m", 
                         signal_score: float = 0, current_price: float = 0, balance: float = 0) -> Tuple[bool, str]:
        """Check if new position can be opened. Supports both old and new call signatures."""
        
        # Handle both call signatures:
        # Old: can_open_position(coin, signal_score, current_price, balance)
        # New: can_open_position(coin, asset_cfg, timeframe="5m")
        
        # Check max open positions (using max_concurrent_positions from config)
        max_positions = getattr(self.config, 'max_concurrent_positions', 5)
        if len(self.active_positions) >= max_positions:
            return False, f"Max positions ({len(self.active_positions)}/{max_positions})"

        # Check daily loss limit (calculate USD from percentage)
        max_daily_loss_pct = getattr(self.config, 'max_daily_loss_pct', 0.10)
        # Estimate equity from balance if provided, or use a default
        equity = balance if balance > 0 else 1000  # fallback
        max_daily_loss_usd = equity * max_daily_loss_pct
        
        if self.daily_pnl < -max_daily_loss_usd:
            return False, f"Daily loss limit (${self.daily_pnl:.2f} < -${max_daily_loss_usd:.2f})"

        # Check consecutive losses limit
        max_consecutive = getattr(self.config, 'max_consecutive_losses', 3)
        if self.consecutive_losses >= max_consecutive:
            return False, f"Consecutive losses ({self.consecutive_losses}/{max_consecutive})"

        return True, "OK"

    def get_stats(self) -> Dict:
        """Return risk statistics."""
        total = len(self.trade_history)
        wins = len([t for t in self.trade_history if t.pnl > 0])
        win_rate = (wins / total * 100) if total > 0 else 0
        total_pnl = sum(t.pnl for t in self.trade_history)
        
        scalps = [t for t in self.trade_history if t.timeframe == "5m"]
        swings = [t for t in self.trade_history if t.timeframe == "30m"]
        
        return {
            "total_trades": total,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "open_positions": len(self.active_positions),
            "scalp_trades": len(scalps),
            "scalp_pnl": sum(t.pnl for t in scalps),
            "swing_trades": len(swings),
            "swing_pnl": sum(t.pnl for t in swings),
            "sl_verify_failures": self.sl_verify_failures,
        }

    def verify_sl_orders(self, coin: str, open_orders: List[Dict], timeframe: str = "5m") -> bool:
        """Verify SL order exists on exchange. Returns True if verified."""
        key = self.position_key(coin, timeframe)
        pos = self.active_positions.get(key)
        if not pos:
            pos = self.active_positions.get(coin)
        if not pos:
            return False

        if not pos.sl_order_id:
            log.warning(f"⚠️ {coin}: No SL order ID tracked")
            return False

        # Check if SL order exists in open orders
        sl_found = False
        for order in open_orders:
            oid = str(order.get("oid", ""))
            if oid == str(pos.sl_order_id):
                sl_found = True
                break

        if sl_found:
            pos.sl_verified = True
            return True
        else:
            # SL order not found - might have triggered or failed
            log.warning(f"⚠️ {coin}: SL order {pos.sl_order_id} not in open orders")
            self.sl_verify_failures += 1
            return False
