"""
Enhanced Signal Generation v4.1 - VWAP Mean Reversion Added
Multi-confluence signals with VWAP, volume, and trend filters
"""

import numpy as np
from enum import Enum
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"

class SignalType(Enum):
    SCALP = "SCALP"
    SWING = "SWING"

class Signal:
    """Trading signal with direction, score, and metadata."""
    def __init__(
        self, 
        direction: Direction, 
        score: int, 
        max_score: int,
        strategy: str,
        timeframe: str,
        reasons: List[str] = None
    ):
        self.direction = direction
        self.score = score
        self.max_score = max_score
        self.strategy = strategy
        self.timeframe = timeframe
        self.reasons = reasons or []
    
    def __repr__(self):
        return f"Signal({self.direction.value}, score={self.score}/{self.max_score}, strategy={self.strategy})"


@dataclass
class VWAPConfig:
    """Configuration for VWAP mean reversion signals"""
    deviation_threshold: float = 1.5  # Std dev from VWAP
    volume_threshold: float = 1.5      # Volume ratio threshold
    min_trend_strength: float = 0.3   # Minimum trend alignment
    vwap_period: int = 20              # VWAP lookback period


class SignalEngine:
    """Main signal evaluation engine for scalp and swing strategies."""
    
    def __init__(self):
        self.disabled_strategies = {"SWING_BREAKOUT", "SWING_REVERSAL"}
        self.vwap_config = VWAPConfig()
    
    def calculate_vwap(self, candles: List[Dict]) -> Tuple[float, float, float]:
        """
        Calculate VWAP and standard deviation.
        
        Returns: (vwap_value, std_dev, current_deviation)
        """
        if not candles or len(candles) < 20:
            return 0.0, 0.0, 0.0
        
        # Calculate VWAP: sum(TP * volume) / sum(volume)
        typical_prices = []
        volumes = []
        
        for c in candles[-self.vwap_config.vwap_period:]:
            h = float(c.get('h', c.get('high', 0)))
            l = float(c.get('l', c.get('low', 0)))
            close = float(c.get('c', c.get('close', 0)))
            v = float(c.get('v', c.get('volume', 0)))
            
            tp = (h + l + close) / 3
            typical_prices.append(tp)
            volumes.append(v)
        
        if not volumes or sum(volumes) == 0:
            return 0.0, 0.0, 0.0
        
        # Calculate VWAP
        vwap = sum(tp * v for tp, v in zip(typical_prices, volumes)) / sum(volumes)
        
        # Calculate standard deviation
        variance = sum((tp - vwap) ** 2 * v for tp, v in zip(typical_prices, volumes)) / sum(volumes)
        std_dev = variance ** 0.5
        
        # Current deviation in std dev units
        current_price = typical_prices[-1]
        deviation = (current_price - vwap) / std_dev if std_dev > 0 else 0
        
        return vwap, std_dev, deviation
    
    def calculate_volume_ratio(self, candles: List[Dict]) -> float:
        """Calculate current volume vs 20-period average"""
        if not candles or len(candles) < 20:
            return 1.0
        
        volumes = [float(c.get('v', c.get('volume', 0))) for c in candles]
        current_vol = volumes[-1]
        avg_vol = np.mean(volumes[-20:])
        
        return current_vol / avg_vol if avg_vol > 0 else 1.0
    
    def get_trend_direction(self, candles: List[Dict], period: int = 50) -> Tuple[str, float]:
        """
        Determine trend direction and strength from higher timeframe.
        
        Returns: (direction: "bullish"/"bearish"/"neutral", strength: 0-1)
        """
        if not candles or len(candles) < period:
            return "neutral", 0.0
        
        closes = [float(c.get('c', c.get('close', 0))) for c in candles]
        
        # Calculate EMAs
        ema_9 = self._calculate_ema(closes, 9)
        ema_21 = self._calculate_ema(closes, 21)
        ema_50 = self._calculate_ema(closes, 50) if len(closes) >= 50 else ema_21
        
        if not ema_9 or not ema_21:
            return "neutral", 0.0
        
        current_price = closes[-1]
        
        # Trend determination
        if ema_9[-1] > ema_21[-1] and ema_21[-1] > ema_50[-1] if isinstance(ema_50, list) else ema_21[-1] > ema_50:
            direction = "bullish"
            strength = min(1.0, (current_price / ema_50[-1] if isinstance(ema_50, list) else ema_50) - 1) * 10 if current_price > (ema_50[-1] if isinstance(ema_50, list) else ema_50) else 0.3
        elif ema_9[-1] < ema_21[-1] and ema_21[-1] < (ema_50[-1] if isinstance(ema_50, list) else ema_50):
            direction = "bearish"
            strength = min(1.0, 1 - current_price / (ema_50[-1] if isinstance(ema_50, list) else ema_50)) * 10 if current_price < (ema_50[-1] if isinstance(ema_50, list) else ema_50) else 0.3
        else:
            direction = "neutral"
            strength = 0.0
        
        return direction, min(1.0, strength)
    
    def _calculate_ema(self, data: List[float], period: int) -> Optional[List[float]]:
        """Calculate exponential moving average"""
        if len(data) < period:
            return None
        
        alpha = 2 / (period + 1)
        ema = [data[0]]
        
        for i in range(1, len(data)):
            ema.append(alpha * data[i] + (1 - alpha) * ema[-1])
        
        return ema
    
    def evaluate(self, indicators) -> Optional[Signal]:
        """Evaluate 5m scalp signals including VWAP mean reversion."""
        signals = []
        
        # Generate multi-confluence signals (existing)
        multi_signals = self._generate_scalp_signals(indicators)
        signals.extend(multi_signals)
        
        # Generate VWAP mean reversion signals
        # Check if we have raw candles for VWAP calculation
        raw_candles = indicators.get('raw_candles', []) if isinstance(indicators, dict) else []
        if raw_candles:
            vwap_signals = self._generate_vwap_signals(raw_candles)
            signals.extend(vwap_signals)
        
        # ══════════════════════════════════════════════════════════════
        # V6: MOMENTUM BREAKOUT — trend-following signal for strong moves
        # Generates LONGs in uptrends, SHORTs in downtrends
        # Complements mean-reversion signals (which work in ranges)
        # ══════════════════════════════════════════════════════════════
        momentum_signals = self._generate_momentum_signals(indicators)
        signals.extend(momentum_signals)
        
        # ══════════════════════════════════════════════════════════════
        # V6.1 TIER 2: EMA PULLBACK — trend continuation on pullback
        # Enters when price pulls back to 21 EMA in an established trend
        # Higher WR than crossover entries (waits for retest, not chasing)
        # ══════════════════════════════════════════════════════════════
        pullback_signals = self._generate_pullback_signals(indicators)
        signals.extend(pullback_signals)
        
        # V6.1 TIER 2: MULTI-STRATEGY VOTING — require 2+ independent strategies to agree
        # Ultra-scalping-bot's key insight: only trade when multiple strategies agree
        # This filters out single-strategy false signals
        if not signals:
            return Signal(
                direction=Direction.NONE,
                score=0,
                max_score=12,
                strategy="NONE",
                timeframe="5m",
                reasons=["No signal"]
            )
        
        # Count how many strategies say LONG vs SHORT
        long_signals = [s for s in signals if s.direction == Direction.LONG]
        short_signals = [s for s in signals if s.direction == Direction.SHORT]
        
        # VOTING: require 2+ strategies agreeing on direction
        # If only 1 strategy fires, it's a weak signal — skip
        # Exception: high-score single signal (score >= 11) can still trade alone
        VOTE_THRESHOLD = 2
        SINGLE_SIGNAL_EXCEPTION = 11  # Very strong single signal can trade alone
        
        if len(long_signals) >= VOTE_THRESHOLD:
            best = max(long_signals, key=lambda x: x.score)
            best.reasons.append(f"VOTE: {len(long_signals)} strategies agree LONG")
            return best
        elif len(short_signals) >= VOTE_THRESHOLD:
            best = max(short_signals, key=lambda x: x.score)
            best.reasons.append(f"VOTE: {len(short_signals)} strategies agree SHORT")
            return best
        elif long_signals and long_signals[0].score >= SINGLE_SIGNAL_EXCEPTION:
            best = max(long_signals, key=lambda x: x.score)
            best.reasons.append(f"SINGLE: score {best.score} >= {SINGLE_SIGNAL_EXCEPTION} (exception)")
            return best
        elif short_signals and short_signals[0].score >= SINGLE_SIGNAL_EXCEPTION:
            best = max(short_signals, key=lambda x: x.score)
            best.reasons.append(f"SINGLE: score {best.score} >= {SINGLE_SIGNAL_EXCEPTION} (exception)")
            return best
        else:
            # No voting agreement and no strong single signal
            best_score = max(s.score for s in signals) if signals else 0
            return Signal(
                direction=Direction.NONE,
                score=best_score,
                max_score=12,
                strategy="VOTE_BLOCKED",
                timeframe="5m",
                reasons=[f"Vote blocked: {len(long_signals)}L/{len(short_signals)}S, max score {best_score}"]
            )
    
    def evaluate_swing(self, indicators_30m, indicators_5m, swing_config) -> Optional[Signal]:
        """Evaluate 30m swing signals."""
        signals = self._generate_swing_signals(indicators_30m)
        if not signals:
            return Signal(
                direction=Direction.NONE,
                score=0,
                max_score=12,
                strategy="NONE", 
                timeframe="30m",
                reasons=["No swing signal"]
            )
        best = max(signals, key=lambda x: x.score)
        return best
    
    def _generate_scalp_signals(self, data: Dict) -> List[Signal]:
        """Generate scalp signals with score >= 7 threshold.
        AI ENHANCED (v4): Added MACD confluence for multi-signal confirmation.
        ADX FILTER (v5): Use ADX to separate trending vs ranging markets.
          - ADX > 25: favor trend-follow signals (EMA cross, MACD momentum)
          - ADX < 20: favor mean-reversion signals (BB, RSI extremes)
          - ADX 20-25: neutral, allow both
        V6.1 TIER 1: Volume gate (HARD GATE) + RSI extreme block (HARD GATE)
        """
        signals = []
        
        # Get indicator values
        rsi = data.get('rsi_14', 50) if hasattr(data, 'get') else 50
        ema_fast = data.get('ema_9', 0) if hasattr(data, 'get') else 0
        ema_slow = data.get('ema_21', 0) if hasattr(data, 'get') else 0
        macd = data.get('macd', 0) if hasattr(data, 'get') else 0
        macd_signal = data.get('macd_signal', 0) if hasattr(data, 'get') else 0
        macd_histogram = data.get('macd_histogram', 0) if hasattr(data, 'get') else 0
        bb_position = data.get('bb_position', 0.5) if hasattr(data, 'get') else 0.5
        volume_ratio = data.get('volume_ratio', 1.0) if hasattr(data, 'get') else 1.0
        adx = data.get('adx', 0) if hasattr(data, 'get') else 0
        
        # ── V6.1 TIER 1: VOLUME GATE (HARD GATE) ──
        # Every top scalping bot requires volume > 1.3x average.
        # Low volume = noise = false signals. Block all signals when volume is low.
        VOLUME_GATE = 1.3
        if volume_ratio < VOLUME_GATE:
            return signals  # No signals generated when volume is below gate
        
        # ADX regime classification
        is_trending = adx > 25
        is_ranging = adx < 20

        # Track confluence factors
        long_factors = []
        short_factors = []
        
        # ── V6.1 TIER 1: RSI EXTREME BLOCK (HARD GATE) ──
        # Block LONG when RSI > 72 (buying the top), block SHORT when RSI < 28 (selling the bottom)
        # These are HARD blocks — no score, no entry, period.
        RSI_LONG_BLOCK = 72   # No LONG if RSI > this
        RSI_SHORT_BLOCK = 28  # No SHORT if RSI < this
        
        # RSI signals
        if rsi < 30:
            long_factors.append(("RSI_OVERSOLD", 3, "RSI oversold (<30)"))
        elif rsi > 70:
            short_factors.append(("RSI_OVERBOUGHT", 3, "RSI overbought (>70)"))
        elif rsi < 40:
            long_factors.append(("RSI_WEAK", 1, "RSI weak"))
        elif rsi > 60:
            short_factors.append(("RSI_STRONG", 1, "RSI strong"))
        
        # EMA signals (trend-following — boosted in trending markets, penalized in ranging)
        if ema_fast > ema_slow * 1.001:
            score = 3 if is_trending else 1
            long_factors.append(("EMA_BULL", score, f"EMA bullish cross (ADX={adx:.0f})"))
        elif ema_fast < ema_slow * 0.999:
            score = 3 if is_trending else 1
            short_factors.append(("EMA_BEAR", score, f"EMA bearish cross (ADX={adx:.0f})"))
        
        # AI ENHANCED: MACD signals for scalp (multi-confluence, ADX-aware)
        # V6 FIX: MACD_MOM is now a SEPARATE if, not elif — fires alongside MACD_BULL
        # as momentum confirmation. Previously elif made it dead code when MACD_BULL fired.
        if macd > macd_signal and macd_histogram > 0:
            score = 3 if is_trending else 2
            long_factors.append(("MACD_BULL", score, "MACD bullish cross + histogram"))
        elif macd < macd_signal and macd_histogram < 0:
            score = 3 if is_trending else 2
            short_factors.append(("MACD_BEAR", score, "MACD bearish cross + histogram"))

        # V6: MACD momentum as INDEPENDENT bonus factor (was elif — never fired with MACD_BULL)
        if macd > 0 and macd > macd_signal and macd_histogram > 0:
            long_factors.append(("MACD_MOM", 2, "MACD positive momentum"))
        elif macd < 0 and macd < macd_signal and macd_histogram < 0:
            short_factors.append(("MACD_MOM", 2, "MACD negative momentum"))
        
        # Bollinger Band position (mean reversion — boosted in ranging markets, penalized in trends)
        if bb_position < 0.1:
            score = 3 if is_ranging else 1
            long_factors.append(("BB_LOW", score, f"Price at BB lower band (ADX={adx:.0f})"))
        elif bb_position > 0.9:
            score = 3 if is_ranging else 1
            short_factors.append(("BB_HIGH", score, f"Price at BB upper band (ADX={adx:.0f})"))
        
        # Volume confirmation
        if volume_ratio > 1.5:
            if long_factors:
                long_factors.append(("VOL_CONFIRM", 1, "High volume confirm"))
            if short_factors:
                short_factors.append(("VOL_CONFIRM", 1, "High volume confirm"))
        
        # V6.1 TIER 1: RSI extreme block — remove LONG factors if RSI > 72, SHORT if RSI < 28
        if rsi > RSI_LONG_BLOCK:
            long_factors = []  # Block LONG — too overbought
        if rsi < RSI_SHORT_BLOCK:
            short_factors = []  # Block SHORT — too oversold
        
        # AI ENHANCED: Require minimum 2 confluence factors for entry
        # This filters out weak single-indicator signals
        if len(long_factors) >= 2:
            total_score = min(12, 5 + sum(f[1] for f in long_factors))
            reasons = [f[2] for f in long_factors]
            strategy_names = "+".join(f[0] for f in long_factors[:3])
            signals.append(Signal(
                direction=Direction.LONG,
                score=total_score,
                max_score=12,
                strategy=f"MULTI_CONFLUENCE:{strategy_names}",
                timeframe="5m",
                reasons=reasons
            ))
        
        if len(short_factors) >= 2:
            total_score = min(12, 5 + sum(f[1] for f in short_factors))
            reasons = [f[2] for f in short_factors]
            strategy_names = "+".join(f[0] for f in short_factors[:3])
            signals.append(Signal(
                direction=Direction.SHORT,
                score=total_score,
                max_score=12,
                strategy=f"MULTI_CONFLUENCE:{strategy_names}",
                timeframe="5m",
                reasons=reasons
            ))
        
        return signals
    
    def _generate_momentum_signals(self, data: Dict) -> List[Signal]:
        """V6: Generate trend-following momentum signals.
        
        This complements the mean-reversion signals above. In strong trends,
        mean-reversion signals generate counter-trend trades that get blocked
        by the 1h trend filter. This signal generates WITH-trend entries:
        
        LONG when: ADX > 25 (trending) + EMA9 > EMA21 (bullish) + MACD histogram rising
        SHORT when: ADX > 25 (trending) + EMA9 < EMA21 (bearish) + MACD histogram falling
        
        Key difference from confluence signals: these use momentum continuation,
        not reversal. RSI >60 is treated as bullish confirmation (strong momentum),
        not as an overbought short signal.
        
        V6.1 TIER 1: Volume gate + RSI extreme block applied to momentum signals too.
        """
        signals = []
        
        # Get indicator values
        rsi = data.get('rsi_14', 50) if hasattr(data, 'get') else 50
        ema_fast = data.get('ema_9', 0) if hasattr(data, 'get') else 0
        ema_slow = data.get('ema_21', 0) if hasattr(data, 'get') else 0
        macd = data.get('macd', 0) if hasattr(data, 'get') else 0
        macd_signal = data.get('macd_signal', 0) if hasattr(data, 'get') else 0
        macd_histogram = data.get('macd_histogram', 0) if hasattr(data, 'get') else 0
        volume_ratio = data.get('volume_ratio', 1.0) if hasattr(data, 'get') else 1.0
        adx = data.get('adx', 0) if hasattr(data, 'get') else 0
        bb_position = data.get('bb_position', 0.5) if hasattr(data, 'get') else 0.5
        
        # ── V6.1 TIER 1: VOLUME GATE (HARD GATE) ──
        VOLUME_GATE = 1.3
        if volume_ratio < VOLUME_GATE:
            return signals
        
        # Need ADX > 25 to confirm trending market
        if adx < 25:
            return signals
        
        # ── V6.1 TIER 1: RSI EXTREME BLOCK (HARD GATE) ──
        # In momentum mode, block LONG if RSI > 80 (extreme overbought even in trend)
        # Block SHORT if RSI < 20 (extreme oversold even in downtrend)
        RSI_LONG_EXTREME = 80   # Momentum LONG allowed up to 80 (trend can stay overbought)
        RSI_SHORT_EXTREME = 20  # Momentum SHORT allowed down to 20
        
        long_factors = []
        short_factors = []
        
        # ── LONG momentum: uptrend continuation ──
        if ema_fast > ema_slow:
            # EMA bullish alignment
            long_factors.append(("MOM_EMA_BULL", 3, f"EMA9>EMA21 bullish (ADX={adx:.0f})"))
            
            # MACD bullish momentum (histogram rising = accelerating)
            if macd > macd_signal and macd_histogram > 0:
                long_factors.append(("MOM_MACD_BULL", 3, "MACD bullish + histogram rising"))
            elif macd > 0 and macd > macd_signal:
                long_factors.append(("MOM_MACD_BULL", 2, "MACD positive momentum"))
            
            # RSI in bullish zone (50-80 = strong momentum, NOT overbought)
            if 50 < rsi < 80:
                long_factors.append(("MOM_RSI_BULL", 2, f"RSI bullish momentum ({rsi:.0f})"))
            elif rsi >= 80:
                # Extremely overbought but in strong trend — still valid but weaker
                long_factors.append(("MOM_RSI_EXTREME", 1, f"RSI extreme ({rsi:.0f}) — momentum but risky"))
            
            # Volume confirmation
            if volume_ratio > 1.5:
                long_factors.append(("MOM_VOL", 1, f"Volume spike {volume_ratio:.1f}x"))
            
            # BB position: riding upper band = strong trend
            if bb_position > 0.7:
                long_factors.append(("MOM_BB_UPPER", 1, "Price riding BB upper — trend strength"))
        
        # ── SHORT momentum: downtrend continuation ──
        elif ema_fast < ema_slow:
            # EMA bearish alignment
            short_factors.append(("MOM_EMA_BEAR", 3, f"EMA9<EMA21 bearish (ADX={adx:.0f})"))
            
            # MACD bearish momentum (histogram falling = accelerating down)
            if macd < macd_signal and macd_histogram < 0:
                short_factors.append(("MOM_MACD_BEAR", 3, "MACD bearish + histogram falling"))
            elif macd < 0 and macd < macd_signal:
                short_factors.append(("MOM_MACD_BEAR", 2, "MACD negative momentum"))
            
            # RSI in bearish zone (20-50 = strong downside momentum)
            if 20 < rsi < 50:
                short_factors.append(("MOM_RSI_BEAR", 2, f"RSI bearish momentum ({rsi:.0f})"))
            elif rsi <= 20:
                short_factors.append(("MOM_RSI_EXTREME", 1, f"RSI extreme ({rsi:.0f}) — momentum but risky"))
            
            # Volume confirmation
            if volume_ratio > 1.5:
                short_factors.append(("MOM_VOL", 1, f"Volume spike {volume_ratio:.1f}x"))
            
            # BB position: riding lower band = strong downtrend
            if bb_position < 0.3:
                short_factors.append(("MOM_BB_LOWER", 1, "Price riding BB lower — trend strength"))
        
        # V6.1 TIER 1: RSI extreme block for momentum signals
        if rsi > RSI_LONG_EXTREME:
            long_factors = []  # Block LONG — extremely overbought even for momentum
        if rsi < RSI_SHORT_EXTREME:
            short_factors = []  # Block SHORT — extremely oversold even for momentum
        
        # Require 2+ factors for entry (same threshold as confluence signals)
        if len(long_factors) >= 2:
            total_score = min(12, 5 + sum(f[1] for f in long_factors))
            reasons = [f[2] for f in long_factors]
            strategy_names = "+".join(f[0] for f in long_factors[:3])
            signals.append(Signal(
                direction=Direction.LONG,
                score=total_score,
                max_score=12,
                strategy=f"MOMENTUM:{strategy_names}",
                timeframe="5m",
                reasons=reasons
            ))
        
        if len(short_factors) >= 2:
            total_score = min(12, 5 + sum(f[1] for f in short_factors))
            reasons = [f[2] for f in short_factors]
            strategy_names = "+".join(f[0] for f in short_factors[:3])
            signals.append(Signal(
                direction=Direction.SHORT,
                score=total_score,
                max_score=12,
                strategy=f"MOMENTUM:{strategy_names}",
                timeframe="5m",
                reasons=reasons
            ))
        
        return signals
    
    def _generate_pullback_signals(self, data: Dict) -> List[Signal]:
        """V6.1 TIER 2: EMA pullback entry — trend continuation on pullback to 21 EMA.
        
        Enters when price pulls back to near the 21 EMA while the trend is still intact
        (EMA9 > EMA21 > EMA50 for LONG, reverse for SHORT). This is a higher-probability
        entry than chasing crossovers — it waits for a retest of the mean in a trend.
        
        LONG: EMA9 > EMA21 (trend up) + price near 21 EMA (pullback) + RSI 40-65 (not overbought)
        SHORT: EMA9 < EMA21 (trend down) + price near 21 EMA (pullback) + RSI 35-60 (not oversold)
        """
        signals = []
        
        rsi = data.get('rsi_14', 50) if hasattr(data, 'get') else 50
        ema_fast = data.get('ema_9', 0) if hasattr(data, 'get') else 0
        ema_slow = data.get('ema_21', 0) if hasattr(data, 'get') else 0
        ema_50 = data.get('ema_50', 0) if hasattr(data, 'get') else 0
        volume_ratio = data.get('volume_ratio', 1.0) if hasattr(data, 'get') else 1.0
        adx = data.get('adx', 0) if hasattr(data, 'get') else 0
        bb_position = data.get('bb_position', 0.5) if hasattr(data, 'get') else 0.5
        
        # Volume gate (same as other strategies)
        if volume_ratio < 1.3:
            return signals
        
        # Need some trend (ADX > 20)
        if adx < 20:
            return signals
        
        # Get current price from bb_position or raw close
        # We need to estimate distance from 21 EMA
        # ema_slow IS the 21 EMA. Price is near it if bb_position is mid-range
        # Use EMA proximity: price within 0.3% of 21 EMA = pullback zone
        PULLBACK_THRESHOLD = 0.003  # 0.3% from 21 EMA
        
        long_factors = []
        short_factors = []
        
        # ── LONG pullback: uptrend + price pulled back to 21 EMA ──
        if ema_fast > ema_slow and ema_slow > (ema_50 if ema_50 else 0):
            # Bullish EMA stack (9 > 21 > 50) — confirmed uptrend
            # Check if price is near 21 EMA (pullback zone)
            # bb_position near 0.5 = price at middle of BB = near EMA
            if 0.3 < bb_position < 0.7:
                long_factors.append(("PB_EMA_TOUCH", 3, f"Price pulled back to 21 EMA (BB={bb_position:.2f})"))
                long_factors.append(("PB_TREND_UP", 3, f"EMA9>EMA21>EMA50 bullish stack (ADX={adx:.0f})"))
                
                if 40 < rsi < 65:
                    long_factors.append(("PB_RSI_OK", 2, f"RSI in healthy zone ({rsi:.0f})"))
                elif rsi >= 72:
                    long_factors = []  # Block — too overbought even for pullback
                else:
                    long_factors.append(("PB_RSI_WEAK", 1, f"RSI neutral ({rsi:.0f})"))
                
                if volume_ratio > 1.5:
                    long_factors.append(("PB_VOL", 1, f"Volume spike {volume_ratio:.1f}x"))
        
        # ── SHORT pullback: downtrend + price pulled back to 21 EMA ──
        elif ema_fast < ema_slow and ema_slow < (ema_50 if ema_50 else float('inf')):
            # Bearish EMA stack (9 < 21 < 50) — confirmed downtrend
            if 0.3 < bb_position < 0.7:
                short_factors.append(("PB_EMA_TOUCH", 3, f"Price pulled back to 21 EMA (BB={bb_position:.2f})"))
                short_factors.append(("PB_TREND_DN", 3, f"EMA9<EMA21<EMA50 bearish stack (ADX={adx:.0f})"))
                
                if 35 < rsi < 60:
                    short_factors.append(("PB_RSI_OK", 2, f"RSI in healthy zone ({rsi:.0f})"))
                elif rsi <= 28:
                    short_factors = []  # Block — too oversold even for pullback
                else:
                    short_factors.append(("PB_RSI_WEAK", 1, f"RSI neutral ({rsi:.0f})"))
                
                if volume_ratio > 1.5:
                    short_factors.append(("PB_VOL", 1, f"Volume spike {volume_ratio:.1f}x"))
        
        # Require 2+ factors
        if len(long_factors) >= 2:
            total_score = min(12, 5 + sum(f[1] for f in long_factors))
            reasons = [f[2] for f in long_factors]
            strategy_names = "+".join(f[0] for f in long_factors[:3])
            signals.append(Signal(
                direction=Direction.LONG,
                score=total_score,
                max_score=12,
                strategy=f"PULLBACK:{strategy_names}",
                timeframe="5m",
                reasons=reasons
            ))
        
        if len(short_factors) >= 2:
            total_score = min(12, 5 + sum(f[1] for f in short_factors))
            reasons = [f[2] for f in short_factors]
            strategy_names = "+".join(f[0] for f in short_factors[:3])
            signals.append(Signal(
                direction=Direction.SHORT,
                score=total_score,
                max_score=12,
                strategy=f"PULLBACK:{strategy_names}",
                timeframe="5m",
                reasons=reasons
            ))
        
        return signals
    
    def _generate_swing_signals(self, data: Dict) -> List[Signal]:
        """Generate swing signals with multi-factor confluence.
        
        Swing signals require 2+ confirming factors (like scalp signals).
        Factors include: MACD momentum, EMA trend alignment, ADX strength,
        RSI direction, and volume confirmation.
        """
        signals = []
        
        # Get indicator values
        macd = data.get('macd', 0) if hasattr(data, 'get') else 0
        macd_signal = data.get('macd_signal', 0) if hasattr(data, 'get') else 0
        macd_histogram = data.get('macd_histogram', 0) if hasattr(data, 'get') else 0
        ema_fast = data.get('ema_9', 0) if hasattr(data, 'get') else 0
        ema_slow = data.get('ema_21', 0) if hasattr(data, 'get') else 0
        ema_50 = data.get('ema_50', 0) if hasattr(data, 'get') else 0
        rsi = data.get('rsi', 50) if hasattr(data, 'get') else 50
        adx = data.get('adx', 0) if hasattr(data, 'get') else 0
        volume_ratio = data.get('volume_ratio', 1.0) if hasattr(data, 'get') else 1.0
        rsi_bull_div = data.get('rsi_bull_divergence', False) if hasattr(data, 'get') else False
        rsi_bear_div = data.get('rsi_bear_divergence', False) if hasattr(data, 'get') else False
        obv_slope = data.get('obv_slope', 0) if hasattr(data, 'get') else 0

        long_factors = []
        short_factors = []

        # MACD momentum (primary swing signal)
        if macd > macd_signal and macd > 0:
            long_factors.append(("MACD_BULL", 3, "MACD bullish momentum (30m)"))
        elif macd < macd_signal and macd < 0:
            short_factors.append(("MACD_BEAR", 3, "MACD bearish momentum (30m)"))

        # EMA trend alignment (9 > 21 > 50 = strong bullish, etc.)
        if ema_fast > ema_slow and ema_slow > ema_50:
            long_factors.append(("EMA_TREND_BULL", 3, f"EMA bullish stack (9>21>50, ADX={adx:.0f})"))
        elif ema_fast < ema_slow and ema_slow < ema_50:
            short_factors.append(("EMA_TREND_BEAR", 3, f"EMA bearish stack (9<21<50, ADX={adx:.0f})"))

        # ADX trend strength — only boost signals when trend is strong
        if adx > 25:
            if macd > macd_signal:
                long_factors.append(("ADX_STRONG", 2, f"Strong trend (ADX={adx:.0f})"))
            elif macd < macd_signal:
                short_factors.append(("ADX_STRONG", 2, f"Strong trend (ADX={adx:.0f})"))

        # RSI direction (not extreme, just confirming momentum)
        if 50 < rsi < 70:
            long_factors.append(("RSI_BULL", 1, f"RSI bullish zone ({rsi:.0f})"))
        elif 30 < rsi < 50:
            short_factors.append(("RSI_BEAR", 1, f"RSI bearish zone ({rsi:.0f})"))

        # RSI divergence (early reversal detection)
        if rsi_bull_div:
            long_factors.append(("RSI_BULL_DIV", 2, "RSI bullish divergence"))
        if rsi_bear_div:
            short_factors.append(("RSI_BEAR_DIV", 2, "RSI bearish divergence"))

        # Volume confirmation
        if volume_ratio > 1.5:
            if long_factors:
                long_factors.append(("VOL_CONFIRM", 1, f"Volume spike {volume_ratio:.1f}x"))
            if short_factors:
                short_factors.append(("VOL_CONFIRM", 1, f"Volume spike {volume_ratio:.1f}x"))

        # OBV slope (smart money flow)
        if obv_slope > 0.2:
            long_factors.append(("OBV_ACCUM", 1, f"OBV accumulation (slope={obv_slope:.2f})"))
        elif obv_slope < -0.2:
            short_factors.append(("OBV_DIST", 1, f"OBV distribution (slope={obv_slope:.2f})"))

        # Require minimum 2 confluence factors for swing entry
        if len(long_factors) >= 2:
            total_score = min(12, 5 + sum(f[1] for f in long_factors))
            reasons = [f[2] for f in long_factors]
            strategy_names = "+".join(f[0] for f in long_factors[:3])
            signals.append(Signal(
                direction=Direction.LONG,
                score=total_score,
                max_score=12,
                strategy=f"SWING_CONFLUENCE:{strategy_names}",
                timeframe="30m",
                reasons=reasons
            ))

        if len(short_factors) >= 2:
            total_score = min(12, 5 + sum(f[1] for f in short_factors))
            reasons = [f[2] for f in short_factors]
            strategy_names = "+".join(f[0] for f in short_factors[:3])
            signals.append(Signal(
                direction=Direction.SHORT,
                score=total_score,
                max_score=12,
                strategy=f"SWING_CONFLUENCE:{strategy_names}",
                timeframe="30m",
                reasons=reasons
            ))

        return signals
    
    def _generate_vwap_signals(self, candles: List[Dict], higher_tf_candles: List[Dict] = None) -> List[Signal]:
        """
        Generate VWAP mean reversion signals with volume and trend filters.
        
        Strategy: Price extends >1.5 std dev from VWAP with volume spike + trend alignment
        Expected win rate: 60-70% with proper filters
        """
        signals = []
        
        if not candles or len(candles) < 20:
            return signals
        
        # Calculate VWAP metrics
        vwap, std_dev, deviation = self.calculate_vwap(candles)
        volume_ratio = self.calculate_volume_ratio(candles)
        
        # Get trend from higher timeframe (default to bullish if not provided)
        if higher_tf_candles and len(higher_tf_candles) >= 20:
            trend, trend_strength = self.get_trend_direction(higher_tf_candles)
        else:
            # Use same candles for trend if no HTF data
            trend, trend_strength = self.get_trend_direction(candles)
        
        # Check filter conditions
        deviation_ok = abs(deviation) >= self.vwap_config.deviation_threshold
        volume_ok = volume_ratio >= self.vwap_config.volume_threshold
        trend_ok = trend_strength >= self.vwap_config.min_trend_strength
        
        # Build reasons
        reasons = []
        
        # LONG signal: Price below VWAP, mean reversion up
        # Only take LONG if trend is bullish or neutral (not strongly bearish)
        if deviation < -self.vwap_config.deviation_threshold and deviation_ok:
            reasons.append(f"Price {abs(deviation):.1f}σ below VWAP")
            
            if volume_ok:
                reasons.append(f"Volume spike {volume_ratio:.1f}x")
            
            if trend in ["bullish", "neutral"] and trend_ok:
                reasons.append(f"Trend aligned: {trend} ({trend_strength:.0%})")
                
                # Calculate score based on filters
                score = 6  # Base VWAP score
                if volume_ok:
                    score += 2
                if trend_ok and trend == "bullish":
                    score += 2
                if abs(deviation) > 2.0:  # Stronger deviation
                    score += 1
                
                signals.append(Signal(
                    direction=Direction.LONG,
                    score=min(10, score),
                    max_score=10,
                    strategy="VWAP_MEAN_REVERSION",
                    timeframe="5m",
                    reasons=reasons
                ))
        
        # SHORT signal: Price above VWAP, mean reversion down
        # Only take SHORT if trend is bearish or neutral (not strongly bullish)
        elif deviation > self.vwap_config.deviation_threshold and deviation_ok:
            reasons.append(f"Price {deviation:.1f}σ above VWAP")
            
            if volume_ok:
                reasons.append(f"Volume spike {volume_ratio:.1f}x")
            
            if trend in ["bearish", "neutral"] and trend_ok:
                reasons.append(f"Trend aligned: {trend} ({trend_strength:.0%})")
                
                # Calculate score
                score = 6
                if volume_ok:
                    score += 2
                if trend_ok and trend == "bearish":
                    score += 2
                if abs(deviation) > 2.0:
                    score += 1
                
                signals.append(Signal(
                    direction=Direction.SHORT,
                    score=min(10, score),
                    max_score=10,
                    strategy="VWAP_MEAN_REVERSION",
                    timeframe="5m",
                    reasons=reasons
                ))
        
        return signals

# Backward compatibility alias
SignalGenerator = SignalEngine