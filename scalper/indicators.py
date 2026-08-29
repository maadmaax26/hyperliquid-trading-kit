"""
Technical Indicators for Scalping Bot
"""

import numpy as np
from typing import Dict, Tuple


class IndicatorSet:
    """Technical analysis indicators."""

    def __init__(self, *args, **kwargs):
        """
        Initialize indicator set.

        Supports:
            IndicatorSet()
            IndicatorSet(opens, highs, lows, closes, vols)  — from bot.py line 170
            IndicatorSet(closes, highs, lows, volumes)
            IndicatorSet(config)
        """
        self.config = None
        self.result = {}

        if len(args) == 5:
            # bot.py: IndicatorSet(opens, highs, lows, closes, vols)
            opens = list(args[0])
            highs = list(args[1])
            lows = list(args[2])
            closes = list(args[3])
            volumes = list(args[4])
            self.result = self.calculate_all(closes, highs, lows, volumes)
        elif len(args) == 4:
            closes = list(args[0])
            highs = list(args[1])
            lows = list(args[2])
            volumes = list(args[3])
            self.result = self.calculate_all(closes, highs, lows, volumes)
        elif len(args) == 1:
            self.config = args[0]

    def __getitem__(self, key):
        """Allow dict-style access: indicators['rsi']"""
        return self.result[key]

    def __contains__(self, key):
        """Allow 'in' checks: 'rsi' in indicators"""
        return key in self.result

    def get(self, key, default=None):
        """Allow .get() access: indicators.get('rsi', 50)"""
        return self.result.get(key, default)

    def keys(self):
        return self.result.keys()

    def values(self):
        return self.result.values()

    def items(self):
        return self.result.items()

    def __bool__(self):
        return bool(self.result)

    def __repr__(self):
        if self.result:
            rsi = self.result.get('rsi', '?')
            adx = self.result.get('adx', '?')
            return f"<IndicatorSet rsi={rsi:.1f} adx={adx:.1f}>"
        return "<IndicatorSet (empty)>"

    # ═══════════════════════════════════════════════════════════
    # MAIN CALCULATION
    # ═══════════════════════════════════════════════════════════

    def calculate_all(self, closes: list, highs: list, lows: list, volumes: list) -> Dict:
        """Calculate all indicators needed for signal generation."""

        closes_arr = np.array(closes, dtype=float)
        highs_arr = np.array(highs, dtype=float)
        lows_arr = np.array(lows, dtype=float)
        volumes_arr = np.array(volumes, dtype=float)

        # EMAs
        ema_9 = self._ema(closes_arr, 9)
        ema_21 = self._ema(closes_arr, 21)
        ema_50 = self._ema(closes_arr, 50)

        # RSI
        rsi = self._rsi(closes_arr, 14)

        # MACD
        macd, macd_signal, macd_hist = self._macd(closes_arr)

        # Bollinger Bands
        bb_middle, bb_upper, bb_lower = self._bollinger_bands(closes_arr, 20, 2)
        bb_width = (bb_upper - bb_lower) / bb_middle if bb_middle > 0 else 0
        
        # Calculate bb_width_avg (last 20 periods)
        # We need to compute historical bb_widths for the average
        # Simplified: if we don't have historical widths in this slice, we just use current
        bb_width_avg = bb_width 

        # ADX
        adx = self._adx(highs_arr, lows_arr, closes_arr, 14)
        
        # Refine ADX logic to favor stronger trends (ADX > 30)
        # Note: The raw ADX value is calculated in _adx. 
        # Signals.py will use indicators['adx'] > 30 for trend strength logic.
        
        # ATR
        atr = self._atr(highs_arr, lows_arr, closes_arr, 14)

        # Volume analysis
        vol_sma = np.mean(volumes_arr[-20:]) if len(volumes_arr) >= 20 else np.mean(volumes_arr)
        vol_ratio = float(volumes_arr[-1] / vol_sma) if vol_sma > 0 else 1.0

        # ── NEW: RSI Divergence ──────────────────────────────────
        rsi_bull_div, rsi_bear_div = self._rsi_divergence(closes_arr, rsi, lookback=20)

        # ── NEW: VWAP ────────────────────────────────────────────
        vwap = self._vwap(highs_arr, lows_arr, closes_arr, volumes_arr)
        price_vs_vwap = (closes_arr[-1] - vwap) / vwap if vwap > 0 else 0.0

        # ── NEW: OBV (On Balance Volume) + divergence ────────────
        obv = self._obv(closes_arr, volumes_arr)
        obv_bull_div, obv_bear_div = self._obv_divergence(closes_arr, obv, lookback=20)
        # OBV slope: positive = accumulation, negative = distribution
        obv_slope = self._slope_normalized(obv, period=10)

        # ── NEW: Stochastic RSI ──────────────────────────────────
        stoch_k, stoch_d = self._stochastic_rsi(rsi, period=14, smooth_k=3, smooth_d=3)

        # ── NEW: Pivot Points (support/resistance) ───────────────
        pivot, s1, s2, r1, r2 = self._pivot_points(highs_arr, lows_arr, closes_arr)

        self.result = {
            'ema_9': float(ema_9[-1]),
            'ema_21': float(ema_21[-1]),
            'ema_50': float(ema_50[-1]),
            'ema_9_prev': float(ema_9[-2]) if len(ema_9) > 1 else float(ema_9[-1]),
            'ema_21_prev': float(ema_21[-2]) if len(ema_21) > 1 else float(ema_21[-1]),
            'rsi': float(rsi[-1]),
            'rsi_prev': float(rsi[-2]) if len(rsi) > 1 else float(rsi[-1]),
            'macd': float(macd[-1]),
            'macd_signal': float(macd_signal[-1]),
            'macd_histogram': float(macd_hist[-1]),
            'macd_histogram_prev': float(macd_hist[-2]) if len(macd_hist) > 1 else float(macd_hist[-1]),
            'bb_upper': float(bb_upper),
            'bb_middle': float(bb_middle),
            'bb_lower': float(bb_lower),
            'bb_width': float(bb_width),
            'bb_width_avg': float(bb_width_avg),
            'adx': float(adx[-1]),
            'atr': float(atr[-1]),
            'volume_ratio': float(vol_ratio),
            'price': float(closes_arr[-1]),
            # ── New trend-change indicators ──
            'rsi_bull_divergence': rsi_bull_div,      # True = price making lower lows but RSI making higher lows
            'rsi_bear_divergence': rsi_bear_div,      # True = price making higher highs but RSI making lower highs
            'vwap': float(vwap),                      # Volume Weighted Average Price
            'price_vs_vwap': float(price_vs_vwap),    # % distance from VWAP (+ above, - below)
            'obv_bull_divergence': obv_bull_div,       # True = price falling but OBV rising (accumulation)
            'obv_bear_divergence': obv_bear_div,       # True = price rising but OBV falling (distribution)
            'obv_slope': float(obv_slope),             # OBV momentum direction (-1 to +1)
            'stoch_rsi_k': float(stoch_k),             # Stochastic RSI %K (0-100)
            'stoch_rsi_d': float(stoch_d),             # Stochastic RSI %D (0-100)
            'pivot': float(pivot),                     # Pivot point
            'support_1': float(s1),                    # First support level
            'support_2': float(s2),                    # Second support level
            'resistance_1': float(r1),                 # First resistance level
            'resistance_2': float(r2),                 # Second resistance level
        }

        return self.result

    # ═══════════════════════════════════════════════════════════
    # INDICATOR CALCULATIONS
    # ═══════════════════════════════════════════════════════════

    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """Exponential Moving Average."""
        if len(data) < period:
            return np.array([data[-1]] * len(data))

        ema = np.zeros(len(data))
        ema[period - 1] = np.mean(data[:period])
        multiplier = 2.0 / (period + 1)

        for i in range(period, len(data)):
            ema[i] = (data[i] * multiplier) + (ema[i - 1] * (1 - multiplier))

        return ema

    def _rsi(self, data: np.ndarray, period: int = 14) -> np.ndarray:
        """Relative Strength Index."""
        if len(data) < period + 1:
            return np.array([50.0] * len(data))

        deltas = np.diff(data)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.zeros(len(data))
        avg_loss = np.zeros(len(data))

        avg_gain[period] = np.mean(gains[:period])
        avg_loss[period] = np.mean(losses[:period])

        for i in range(period + 1, len(data)):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

        rs = np.divide(avg_gain, avg_loss, out=np.full_like(avg_gain, 100.0), where=avg_loss != 0)
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _macd(
        self, data: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """MACD indicator."""
        ema_fast = self._ema(data, fast)
        ema_slow = self._ema(data, slow)
        macd_line = ema_fast - ema_slow
        signal_line = self._ema(macd_line, signal)
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def _bollinger_bands(
        self, data: np.ndarray, period: int = 20, std_dev: float = 2.0
    ) -> Tuple[float, float, float]:
        """Bollinger Bands."""
        if len(data) < period:
            middle = float(np.mean(data))
            std = float(np.std(data))
        else:
            middle = float(np.mean(data[-period:]))
            std = float(np.std(data[-period:]))

        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)

        return middle, upper, lower

    def _atr(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
    ) -> np.ndarray:
        """Average True Range."""
        if len(highs) < 2:
            return np.array([0.0])

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1])
            )
        )

        atr = np.zeros(len(tr) + 1)
        if len(tr) >= period:
            atr[period] = np.mean(tr[:period])

        for i in range(period + 1, len(atr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period

        return atr

    def _adx(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
    ) -> np.ndarray:
        """Average Directional Index."""
        if len(highs) < period + 1:
            return np.array([0.0] * len(highs))

        dm_plus = np.maximum(highs[1:] - highs[:-1], 0)
        dm_minus = np.maximum(lows[:-1] - lows[1:], 0)

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1])
            )
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

        adx = np.zeros(len(dx) + 1)
        if len(dx) >= period:
            adx[period] = np.mean(dx[:period])

        for i in range(period + 1, len(adx)):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i - 1]) / period

        return adx

    # ═══════════════════════════════════════════════════════════
    # NEW: TREND CHANGE INDICATORS
    # ═══════════════════════════════════════════════════════════

    def _rsi_divergence(
        self, closes: np.ndarray, rsi: np.ndarray, lookback: int = 20
    ) -> Tuple[bool, bool]:
        """
        Detect RSI divergence — the strongest early warning for trend reversals.

        Bullish divergence: price makes lower low, RSI makes higher low
            → downtrend weakening, likely reversal up
        Bearish divergence: price makes higher high, RSI makes lower high
            → uptrend weakening, likely reversal down

        Uses swing highs/lows within the lookback window.
        """
        if len(closes) < lookback + 5 or len(rsi) < lookback + 5:
            return False, False

        n = len(closes)
        window = min(lookback, n - 2)

        # Find swing lows (for bullish divergence)
        # A swing low is a point lower than its neighbors
        price_lows = []
        rsi_lows = []
        for i in range(n - window, n - 1):
            if i < 1:
                continue
            if closes[i] <= closes[i - 1] and closes[i] <= closes[i + 1]:
                price_lows.append((i, closes[i], rsi[i]))

        # Find swing highs (for bearish divergence)
        price_highs = []
        for i in range(n - window, n - 1):
            if i < 1:
                continue
            if closes[i] >= closes[i - 1] and closes[i] >= closes[i + 1]:
                price_highs.append((i, closes[i], rsi[i]))

        bull_div = False
        bear_div = False

        # Bullish: compare last two swing lows
        if len(price_lows) >= 2:
            prev_low = price_lows[-2]
            curr_low = price_lows[-1]
            # Price made lower low, but RSI made higher low
            if curr_low[1] < prev_low[1] and curr_low[2] > prev_low[2]:
                bull_div = True

        # Bearish: compare last two swing highs
        if len(price_highs) >= 2:
            prev_high = price_highs[-2]
            curr_high = price_highs[-1]
            # Price made higher high, but RSI made lower high
            if curr_high[1] > prev_high[1] and curr_high[2] < prev_high[2]:
                bear_div = True

        return bull_div, bear_div

    def _vwap(
        self, highs: np.ndarray, lows: np.ndarray,
        closes: np.ndarray, volumes: np.ndarray
    ) -> float:
        """
        Volume Weighted Average Price.

        Institutional benchmark — price above VWAP = bullish, below = bearish.
        Price crossing VWAP with volume confirms trend shifts.
        Uses a rolling session (last 78 bars ≈ 6.5hrs on 5m, full day on 30m).
        """
        # Use last 78 candles as "session" (6.5 hours on 5m ≈ trading session)
        session_len = min(78, len(closes))
        typical_price = (highs[-session_len:] + lows[-session_len:] + closes[-session_len:]) / 3.0
        vol_slice = volumes[-session_len:]

        cum_vol = np.cumsum(vol_slice)
        cum_tp_vol = np.cumsum(typical_price * vol_slice)

        if cum_vol[-1] > 0:
            return float(cum_tp_vol[-1] / cum_vol[-1])
        return float(closes[-1])

    def _obv(self, closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
        """
        On Balance Volume — tracks cumulative volume flow.

        Rising OBV = accumulation (smart money buying)
        Falling OBV = distribution (smart money selling)
        OBV diverging from price = trend change imminent.
        """
        if len(closes) < 2:
            return np.array([0.0])

        obv = np.zeros(len(closes))
        obv[0] = volumes[0]

        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                obv[i] = obv[i - 1] + volumes[i]
            elif closes[i] < closes[i - 1]:
                obv[i] = obv[i - 1] - volumes[i]
            else:
                obv[i] = obv[i - 1]

        return obv

    def _obv_divergence(
        self, closes: np.ndarray, obv: np.ndarray, lookback: int = 20
    ) -> Tuple[bool, bool]:
        """
        OBV divergence — when price and volume flow disagree.

        Bullish: price trending down but OBV trending up (accumulation)
        Bearish: price trending up but OBV trending down (distribution)
        """
        if len(closes) < lookback or len(obv) < lookback:
            return False, False

        # Compare slopes over lookback period
        price_slope = self._slope_normalized(closes, lookback)
        obv_slope_val = self._slope_normalized(obv, lookback)

        # Thresholds to avoid noise
        threshold = 0.1

        # Bullish: price falling, OBV rising
        bull_div = price_slope < -threshold and obv_slope_val > threshold
        # Bearish: price rising, OBV falling
        bear_div = price_slope > threshold and obv_slope_val < -threshold

        return bull_div, bear_div

    def _slope_normalized(self, data: np.ndarray, period: int = 10) -> float:
        """
        Normalized slope of a data series over N periods.
        Returns value between -1 and +1 using arctangent normalization.
        """
        if len(data) < period:
            return 0.0

        segment = data[-period:]
        x = np.arange(period, dtype=float)
        # Linear regression slope
        x_mean = x.mean()
        y_mean = segment.mean()
        if y_mean == 0:
            return 0.0

        numer = np.sum((x - x_mean) * (segment - y_mean))
        denom = np.sum((x - x_mean) ** 2)
        if denom == 0:
            return 0.0

        slope = numer / denom
        # Normalize relative to mean value
        normalized = slope / abs(y_mean)
        # Squash to -1..+1 via tanh
        return float(np.tanh(normalized * 100))

    def _stochastic_rsi(
        self, rsi: np.ndarray, period: int = 14,
        smooth_k: int = 3, smooth_d: int = 3
    ) -> Tuple[float, float]:
        """
        Stochastic RSI — applies Stochastic formula to RSI values.

        More sensitive than regular RSI at extremes.
        %K < 20 = oversold (buy), %K > 80 = overbought (sell)
        %K crossing above %D = bullish, below = bearish

        Best on 5m for catching quick reversals at extremes.
        """
        if len(rsi) < period + smooth_k + smooth_d:
            return 50.0, 50.0

        # StochRSI = (RSI - min(RSI, N)) / (max(RSI, N) - min(RSI, N))
        stoch_rsi = np.zeros(len(rsi))
        for i in range(period - 1, len(rsi)):
            rsi_window = rsi[i - period + 1: i + 1]
            rsi_min = np.min(rsi_window)
            rsi_max = np.max(rsi_window)
            rng = rsi_max - rsi_min
            if rng > 0:
                stoch_rsi[i] = ((rsi[i] - rsi_min) / rng) * 100
            else:
                stoch_rsi[i] = 50.0

        # %K = SMA of StochRSI
        if len(stoch_rsi) >= smooth_k:
            k_values = np.convolve(
                stoch_rsi, np.ones(smooth_k) / smooth_k, mode='valid'
            )
            k = float(k_values[-1]) if len(k_values) > 0 else 50.0
        else:
            k = float(stoch_rsi[-1])

        # %D = SMA of %K (we approximate from the stoch_rsi convolution)
        if len(stoch_rsi) >= smooth_k + smooth_d:
            k_series = np.convolve(
                stoch_rsi, np.ones(smooth_k) / smooth_k, mode='valid'
            )
            d_series = np.convolve(
                k_series, np.ones(smooth_d) / smooth_d, mode='valid'
            )
            d = float(d_series[-1]) if len(d_series) > 0 else k
        else:
            d = k

        return max(0, min(100, k)), max(0, min(100, d))

    def _pivot_points(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> Tuple[float, float, float, float, float]:
        """
        Standard Pivot Points from previous candle's H/L/C.

        Provides dynamic support/resistance levels.
        Price bouncing off S1/S2 = support holding (bullish)
        Price rejected at R1/R2 = resistance holding (bearish)
        Price breaking through pivot = trend shift.

        Uses the last completed candle (index -2) for calculation.
        """
        if len(highs) < 2:
            p = float(closes[-1])
            return p, p, p, p, p

        # Use previous candle's high, low, close
        h = float(highs[-2])
        l = float(lows[-2])
        c = float(closes[-2])

        pivot = (h + l + c) / 3.0
        s1 = (2 * pivot) - h        # Support 1
        s2 = pivot - (h - l)         # Support 2
        r1 = (2 * pivot) - l         # Resistance 1
        r2 = pivot + (h - l)         # Resistance 2

        return pivot, s1, s2, r1, r2


# Aliases for compatibility
TechnicalIndicators = IndicatorSet