#!/usr/bin/env python3
"""ZEC-specific backtest with actual scalper signals."""

import json
import numpy as np
from collections import Counter

# Load data
with open('/home/efinney/hyperliquid-mm-bot/price_history/ZEC_5m.json') as f:
    candles_5m = json.loads(f.read())
with open('/home/efinney/hyperliquid-mm-bot/price_history/ZEC_1h.json') as f:
    candles_1h = json.loads(f.read())

closes = np.array([float(c['c']) for c in candles_5m])
highs = np.array([float(c['h']) for c in candles_5m])
lows = np.array([float(c['l']) for c in candles_5m])
opens = np.array([float(c['o']) for c in candles_5m])
volumes = np.array([float(c['v']) for c in candles_5m])

# 1h EMA50 for trend filter
closes_1h = np.array([float(c['c']) for c in candles_1h])
ema50_1h = np.zeros(len(closes_1h))
mult = 2 / (50 + 1)
ema50_1h[0] = closes_1h[0]
for i in range(1, len(closes_1h)):
    ema50_1h[i] = closes_1h[i] * mult + ema50_1h[i-1] * (1 - mult)

candle_1h_times = [int(c['t']) for c in candles_1h]

def get_1h_ema50(timestamp_ms):
    ts = timestamp_ms
    for i in range(len(candle_1h_times) - 1, -1, -1):
        if candle_1h_times[i] <= ts and i < len(ema50_1h):
            return ema50_1h[i]
    return closes_1h[0]

# Indicators
def calc_ema(data, period):
    ema = np.zeros(len(data))
    m = 2 / (period + 1)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = data[i] * m + ema[i-1] * (1 - m)
    return ema

def calc_rsi(closes, period=14):
    rsi = np.zeros(len(closes))
    for i in range(period, len(closes)):
        gains = []
        losses = []
        for j in range(i - period, i):
            change = closes[j+1] - closes[j]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            rsi[i] = 100
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100 - (100 / (1 + rs))
    return rsi

def calc_atr(highs, lows, closes, period=14):
    tr = np.maximum(highs - lows, np.maximum(
        abs(highs - np.roll(closes, 1)),
        abs(lows - np.roll(closes, 1))
    ))
    tr[0] = highs[0] - lows[0]
    atr = np.zeros(len(tr))
    atr[period-1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    return atr

def calc_bb(closes, period=20, num_std=2):
    bb_pos = np.zeros(len(closes))
    for i in range(period, len(closes)):
        window = closes[i-period:i]
        sma = np.mean(window)
        std = np.std(window)
        upper = sma + num_std * std
        lower = sma - num_std * std
        if upper > lower:
            bb_pos[i] = (closes[i] - lower) / (upper - lower)
    return bb_pos

def calc_adx(highs, lows, closes, period=14):
    plus_dm = np.zeros(len(closes))
    minus_dm = np.zeros(len(closes))
    tr = np.zeros(len(closes))
    for i in range(1, len(closes)):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        plus_dm[i] = up if up > down and up > 0 else 0
        minus_dm[i] = down if down > up and down > 0 else 0
        tr[i] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    atr = np.zeros(len(closes))
    dx = np.zeros(len(closes))
    adx = np.zeros(len(closes))
    for i in range(period, len(closes)):
        atr[i] = (atr[i-1]*(period-1) + tr[i]) / period if i > period else np.mean(tr[max(0,i-period):i+1])
        pdm = (plus_dm[i-1]*(period-1) + plus_dm[i]) / period if i > period else np.mean(plus_dm[max(0,i-period):i+1])
        mdm = (minus_dm[i-1]*(period-1) + minus_dm[i]) / period if i > period else np.mean(minus_dm[max(0,i-period):i+1])
        pdi = 100 * pdm / atr[i] if atr[i] > 0 else 0
        mdi = 100 * mdm / atr[i] if atr[i] > 0 else 0
        ds = pdi + mdi
        dx[i] = 100 * abs(pdi - mdi) / ds if ds > 0 else 0
        if i >= 2 * period:
            adx[i] = np.mean(dx[i-period:i+1])
    return adx

rsi = calc_rsi(closes)
ema9 = calc_ema(closes, 9)
ema21 = calc_ema(closes, 21)
atr = calc_atr(highs, lows, closes, 14)
atr_pct = atr / closes * 100
bb_pos = calc_bb(closes)
ema12 = calc_ema(closes, 12)
ema26 = calc_ema(closes, 26)
macd_line = ema12 - ema26
signal_line = calc_ema(macd_line, 9)
macd_hist = macd_line - signal_line
adx = calc_adx(highs, lows, closes)

vol_ma = np.convolve(volumes, np.ones(20)/20, mode='valid')
vol_ratio = np.zeros(len(volumes))
for i in range(20, len(volumes)):
    vol_ratio[i] = volumes[i] / vol_ratio[i-20] if vol_ratio[i-20] > 0 else 1

# ── Backtest configs ──────────────────────────────────────────────
configs = {
    'Current (TP=0.55, SL=0.30)': {
        'tp': 0.55, 'sl': 0.30, 'min_score': 10, 'trend_filter': False,
        'atr_gate': False, 'long_bias': False, 'cooldown': 180,
        'trail_activate': 0.40, 'trail_stop': 0.20,
    },
    'V5 (trend filter + ATR gate)': {
        'tp': 0.55, 'sl': 0.30, 'min_score': 10, 'trend_filter': True,
        'atr_gate': True, 'long_bias': False, 'cooldown': 180,
        'trail_activate': 0.40, 'trail_stop': 0.20,
    },
    'Opt-A (TP=0.50, SL=0.50, long bias)': {
        'tp': 0.50, 'sl': 0.50, 'min_score': 10, 'trend_filter': True,
        'atr_gate': True, 'long_bias': True, 'cooldown': 180,
        'trail_activate': 0.35, 'trail_stop': 0.15,
    },
    'Opt-B (TP=0.40, SL=0.50, tight trail)': {
        'tp': 0.40, 'sl': 0.50, 'min_score': 10, 'trend_filter': True,
        'atr_gate': True, 'long_bias': True, 'cooldown': 240,
        'trail_activate': 0.30, 'trail_stop': 0.10,
    },
    'Opt-C (TP=0.45, SL=0.40, wider trail)': {
        'tp': 0.45, 'sl': 0.40, 'min_score': 10, 'trend_filter': True,
        'atr_gate': True, 'long_bias': False, 'cooldown': 240,
        'trail_activate': 0.30, 'trail_stop': 0.20,
    },
    'Opt-D (TP=0.35, SL=0.30, fast scalp)': {
        'tp': 0.35, 'sl': 0.30, 'min_score': 10, 'trend_filter': True,
        'atr_gate': True, 'long_bias': True, 'cooldown': 300,
        'trail_activate': 0.25, 'trail_stop': 0.10,
    },
    'Opt-E (TP=0.45, SL=0.35, long bias, med trail)': {
        'tp': 0.45, 'sl': 0.35, 'min_score': 10, 'trend_filter': True,
        'atr_gate': True, 'long_bias': True, 'cooldown': 240,
        'trail_activate': 0.30, 'trail_stop': 0.15,
    },
}

print(f'=== ZEC BACKTEST ({len(candles_5m)} 5m candles, {len(candles_5m)*5/60/24:.0f} days) ===')
print()

for config_name, cfg in configs.items():
    trades = []
    last_trade_idx = 0
    equity = 1000.0
    position = None
    cooldown_candles = cfg['cooldown'] / 300  # 300s per 5m candle

    for i in range(60, len(candles_5m)):
        # Manage open position
        if position:
            entry = position['entry']
            direction = position['direction']
            entry_time = position['entry_idx']
            high = float(candles_5m[i]['h'])
            low = float(candles_5m[i]['l'])
            close = float(candles_5m[i]['c'])
            bars_held = i - entry_time

            tp_price = entry * (1 + cfg['tp']/100) if direction == 'LONG' else entry * (1 - cfg['tp']/100)
            sl_price = entry * (1 - cfg['sl']/100) if direction == 'LONG' else entry * (1 + cfg['sl']/100)

            # Trailing stop
            trail_active = False
            trail_stop_price = None
            if direction == 'LONG':
                max_fav = max(float(candles_5m[j]['h']) for j in range(entry_time, i+1))
                move_pct = (max_fav - entry) / entry * 100
                if move_pct >= cfg['trail_activate']:
                    trail_active = True
                    trail_stop_price = max_fav * (1 - cfg['trail_stop']/100)
            else:
                min_fav = min(float(candles_5m[j]['l']) for j in range(entry_time, i+1))
                move_pct = (entry - min_fav) / entry * 100
                if move_pct >= cfg['trail_activate']:
                    trail_active = True
                    trail_stop_price = min_fav * (1 + cfg['trail_stop']/100)

            exit_price = None
            exit_reason = None

            if direction == 'LONG':
                if trail_active and low <= trail_stop_price:
                    exit_price = trail_stop_price
                    exit_reason = 'TRAIL'
                elif low <= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                elif high >= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
            else:
                if trail_active and high >= trail_stop_price:
                    exit_price = trail_stop_price
                    exit_reason = 'TRAIL'
                elif high >= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                elif low <= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'

            if not exit_price and bars_held >= 20:
                exit_price = close
                exit_reason = 'TIME'

            if exit_price:
                if direction == 'LONG':
                    pnl_pct = (exit_price - entry) / entry * 100
                else:
                    pnl_pct = (entry - exit_price) / entry * 100
                pnl_pct -= 0.045  # fees
                size = equity * 0.175 * 7
                pnl_dollar = size * pnl_pct / 100
                equity += pnl_dollar
                trades.append({
                    'direction': direction, 'entry': entry, 'exit': exit_price,
                    'pnl': pnl_dollar, 'pnl_pct': pnl_pct, 'reason': exit_reason,
                    'idx': entry_time, 'bars': bars_held,
                })
                position = None
            continue

        # Cooldown
        if i - last_trade_idx < cooldown_candles:
            continue

        # ATR gate
        if cfg['atr_gate'] and atr_pct[i] < 0.10:
            continue

        # 1h trend filter
        trend_ema50 = get_1h_ema50(int(candles_5m[i]['t']))
        current_price = closes[i]
        trend_dev = (current_price - trend_ema50) / trend_ema50 if trend_ema50 > 0 else 0

        # Generate signals
        score_long = 5
        score_short = 5

        # RSI
        if rsi[i] < 30:
            score_long += 3
        elif rsi[i] < 40:
            score_long += 1
        if rsi[i] > 70:
            score_short += 3
        elif rsi[i] > 60:
            score_short += 1

        # EMA cross
        is_trending = adx[i] > 25
        if ema9[i] > ema21[i] * 1.001:
            score_long += 3 if is_trending else 1
        if ema9[i] < ema21[i] * 0.999:
            score_short += 3 if is_trending else 1

        # MACD
        if macd_line[i] > signal_line[i] and macd_hist[i] > 0:
            score_long += 3 if is_trending else 2
        if macd_line[i] < signal_line[i] and macd_hist[i] < 0:
            score_short += 3 if is_trending else 2

        # BB
        is_ranging = adx[i] < 20
        if bb_pos[i] < 0.1:
            score_long += 3 if is_ranging else 1
        if bb_pos[i] > 0.9:
            score_short += 3 if is_ranging else 1

        # Volume
        if vol_ratio[i] > 1.5:
            score_long += 1
            score_short += 1

        direction = None
        if score_long >= cfg['min_score'] and score_long >= score_short:
            direction = 'LONG'
        elif score_short >= cfg['min_score'] and score_short > score_long:
            direction = 'SHORT'

        if not direction:
            continue

        # Trend filter
        if cfg['trend_filter']:
            if direction == 'LONG' and trend_dev < -0.002:
                continue
            if direction == 'SHORT' and trend_dev > 0.002:
                continue

        # Long bias
        if cfg['long_bias'] and direction == 'SHORT' and score_short < 12:
            continue

        position = {
            'entry': closes[i],
            'direction': direction,
            'entry_idx': i,
        }
        last_trade_idx = i

    # Close remaining
    if position:
        entry = position['entry']
        direction = position['direction']
        close = closes[-1]
        if direction == 'LONG':
            pnl_pct = (close - entry) / entry * 100
        else:
            pnl_pct = (entry - close) / entry * 100
        pnl_pct -= 0.045
        size = equity * 0.175 * 7
        pnl_dollar = size * pnl_pct / 100
        equity += pnl_dollar
        trades.append({
            'direction': direction, 'entry': entry, 'exit': close,
            'pnl': pnl_dollar, 'pnl_pct': pnl_pct, 'reason': 'CLOSE',
            'idx': position['entry_idx'], 'bars': len(candles_5m) - position['entry_idx'],
        })

    # Stats
    if not trades:
        print(f'{config_name}: No trades')
        continue

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100
    total_pnl = sum(t['pnl'] for t in trades)

    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']
    long_wins = len([t for t in longs if t['pnl'] > 0])
    short_wins = len([t for t in shorts if t['pnl'] > 0])
    long_wr = long_wins / len(longs) * 100 if longs else 0
    short_wr = short_wins / len(shorts) * 100 if shorts else 0
    long_pnl = sum(t['pnl'] for t in longs)
    short_pnl = sum(t['pnl'] for t in shorts)

    reason_stats = {}
    for t in trades:
        r = t['reason']
        if r not in reason_stats:
            reason_stats[r] = {'count': 0, 'wins': 0, 'pnl': 0.0}
        reason_stats[r]['count'] += 1
        reason_stats[r]['wins'] += 1 if t['pnl'] > 0 else 0
        reason_stats[r]['pnl'] += t['pnl']

    # Max drawdown
    eq_curve = [1000.0]
    for t in trades:
        eq_curve.append(eq_curve[-1] + t['pnl'])
    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl'] for t in losses]) if losses else 0
    pf = sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses)) if losses and sum(t['pnl'] for t in losses) != 0 else 0

    reason_str = ' | '.join(
        f'{r}:{s["count"]}({s["wins"]}W,${s["pnl"]:.2f})'
        for r, s in sorted(reason_stats.items())
    )

    print(f'{config_name}')
    print(f'  Trades: {len(trades)} | WR: {wr:.1f}% | PnL: ${total_pnl:.2f} | Eq: ${equity:.2f} | MaxDD: {max_dd:.1f}% | PF: {pf:.2f}')
    print(f'  L: {len(longs)} ({long_wr:.0f}% WR ${long_pnl:.2f}) | S: {len(shorts)} ({short_wr:.0f}% WR ${short_pnl:.2f})')
    print(f'  AvgWin: ${avg_win:.2f} | AvgLoss: ${avg_loss:.2f}')
    print(f'  Exits: {reason_str}')
    print()