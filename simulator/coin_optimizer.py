#!/usr/bin/env python3
"""Backtest all scalper coins to find optimal TP/SL/trailing params."""

import json
import numpy as np
import sys

def load_candles(coin):
    base = '/home/efinney/hyperliquid-mm-bot/price_history'
    with open(f'{base}/{coin}_5m.json') as f:
        c5m = json.loads(f.read())
    with open(f'{base}/{coin}_1h.json') as f:
        c1h = json.loads(f.read())
    return c5m, c1h

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
        gains, losses = [], []
        for j in range(i - period, i):
            change = closes[j+1] - closes[j]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        ag = np.mean(gains); al = np.mean(losses)
        rsi[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return rsi

def calc_atr(highs, lows, closes, period=14):
    tr = np.maximum(highs - lows, np.maximum(
        abs(highs - np.roll(closes, 1)), abs(lows - np.roll(closes, 1))))
    tr[0] = highs[0] - lows[0]
    atr = np.zeros(len(tr))
    atr[period-1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    return atr

def calc_bb(closes, period=20, num_std=2):
    bb_pos = np.zeros(len(closes))
    for i in range(period, len(closes)):
        w = closes[i-period:i]
        sma = np.mean(w); std = np.std(w)
        u = sma + num_std * std; l = sma - num_std * std
        if u > l:
            bb_pos[i] = (closes[i] - l) / (u - l)
    return bb_pos

def calc_adx(highs, lows, closes, period=14):
    pdm = np.zeros(len(closes)); mdm = np.zeros(len(closes)); tr = np.zeros(len(closes))
    for i in range(1, len(closes)):
        up = highs[i] - highs[i-1]; down = lows[i-1] - lows[i]
        pdm[i] = up if up > down and up > 0 else 0
        mdm[i] = down if down > up and down > 0 else 0
        tr[i] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    atr = np.zeros(len(closes)); dx = np.zeros(len(closes)); adx = np.zeros(len(closes))
    for i in range(period, len(closes)):
        atr[i] = (atr[i-1]*(period-1)+tr[i])/period if i > period else np.mean(tr[max(0,i-period):i+1])
        p = (pdm[i-1]*(period-1)+pdm[i])/period if i > period else np.mean(pdm[max(0,i-period):i+1])
        m = (mdm[i-1]*(period-1)+mdm[i])/period if i > period else np.mean(mdm[max(0,i-period):i+1])
        pdi = 100*p/atr[i] if atr[i] > 0 else 0; mdi = 100*m/atr[i] if atr[i] > 0 else 0
        ds = pdi+mdi; dx[i] = 100*abs(pdi-mdi)/ds if ds > 0 else 0
        if i >= 2*period: adx[i] = np.mean(dx[i-period:i+1])
    return adx

def run_backtest(candles_5m, candles_1h, tp, sl, trail_act, trail_stop, cooldown, min_score=10):
    closes = np.array([float(c['c']) for c in candles_5m])
    highs = np.array([float(c['h']) for c in candles_5m])
    lows = np.array([float(c['l']) for c in candles_5m])
    volumes = np.array([float(c['v']) for c in candles_5m])

    # 1h EMA50
    closes_1h = np.array([float(c['c']) for c in candles_1h])
    ema50_1h = np.zeros(len(closes_1h))
    mult = 2 / (50 + 1)
    ema50_1h[0] = closes_1h[0]
    for i in range(1, len(closes_1h)):
        ema50_1h[i] = closes_1h[i] * mult + ema50_1h[i-1] * (1 - mult)
    c1h_times = [int(c['t']) for c in candles_1h]

    def get_1h_ema50(ts):
        for i in range(len(c1h_times)-1, -1, -1):
            if c1h_times[i] <= ts:
                return ema50_1h[i]
        return closes_1h[0]

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
        vol_ratio[i] = volumes[i] / vol_ma[i-20] if vol_ma[i-20] > 0 else 1

    trades = []
    last_idx = 0
    equity = 1000.0
    position = None
    cd = cooldown / 300

    for i in range(60, len(candles_5m)):
        if position:
            entry = position['entry']; direction = position['direction']
            et = position['entry_idx']; bh = i - et
            high = float(candles_5m[i]['h']); low = float(candles_5m[i]['l'])
            close = float(candles_5m[i]['c'])
            tp_p = entry * (1 + tp/100) if direction == 'LONG' else entry * (1 - tp/100)
            sl_p = entry * (1 - sl/100) if direction == 'LONG' else entry * (1 + sl/100)
            trail_active = False; trail_price = None
            if direction == 'LONG':
                mf = max(float(candles_5m[j]['h']) for j in range(et, i+1))
                if (mf - entry) / entry * 100 >= trail_act:
                    trail_active = True; trail_price = mf * (1 - trail_stop/100)
            else:
                mf = min(float(candles_5m[j]['l']) for j in range(et, i+1))
                if (entry - mf) / entry * 100 >= trail_act:
                    trail_active = True; trail_price = mf * (1 + trail_stop/100)
            ep = None; er = None
            if direction == 'LONG':
                if trail_active and low <= trail_price: ep = trail_price; er = 'TRAIL'
                elif low <= sl_p: ep = sl_p; er = 'SL'
                elif high >= tp_p: ep = tp_p; er = 'TP'
            else:
                if trail_active and high >= trail_price: ep = trail_price; er = 'TRAIL'
                elif high >= sl_p: ep = sl_p; er = 'SL'
                elif low <= tp_p: ep = tp_p; er = 'TP'
            if not ep and bh >= 20: ep = close; er = 'TIME'
            if ep:
                pp = (ep - entry) / entry * 100 if direction == 'LONG' else (entry - ep) / entry * 100
                pp -= 0.045
                sz = equity * 0.175 * 7
                pd = sz * pp / 100
                equity += pd
                trades.append({'dir': direction, 'pnl': pd, 'reason': er})
                position = None
            continue
        if i - last_idx < cd: continue
        if atr_pct[i] < 0.10: continue
        te = get_1h_ema50(int(candles_5m[i]['t']))
        td = (closes[i] - te) / te if te > 0 else 0
        sl_ = 5; ss_ = 5
        if rsi[i] < 30: sl_ += 3
        elif rsi[i] < 40: sl_ += 1
        if rsi[i] > 70: ss_ += 3
        elif rsi[i] > 60: ss_ += 1
        it = adx[i] > 25; ir = adx[i] < 20
        if ema9[i] > ema21[i] * 1.001: sl_ += 3 if it else 1
        if ema9[i] < ema21[i] * 0.999: ss_ += 3 if it else 1
        if macd_line[i] > signal_line[i] and macd_hist[i] > 0: sl_ += 3 if it else 2
        if macd_line[i] < signal_line[i] and macd_hist[i] < 0: ss_ += 3 if it else 2
        if bb_pos[i] < 0.1: sl_ += 3 if ir else 1
        if bb_pos[i] > 0.9: ss_ += 3 if ir else 1
        if vol_ratio[i] > 1.5: sl_ += 1; ss_ += 1
        direction = None
        if sl_ >= min_score and sl_ >= ss_: direction = 'LONG'
        elif ss_ >= min_score and ss_ > sl_: direction = 'SHORT'
        if not direction: continue
        if direction == 'LONG' and td < -0.002: continue
        if direction == 'SHORT' and td > 0.002: continue
        position = {'entry': closes[i], 'direction': direction, 'entry_idx': i}
        last_idx = i

    if position:
        close = closes[-1]
        pp = (close - position['entry']) / position['entry'] * 100 if position['direction'] == 'LONG' else (position['entry'] - close) / position['entry'] * 100
        pp -= 0.045
        sz = equity * 0.175 * 7
        pd = sz * pp / 100
        equity += pd
        trades.append({'dir': position['direction'], 'pnl': pd, 'reason': 'CLOSE'})

    if not trades:
        return None
    w = [t for t in trades if t['pnl'] > 0]
    l = [t for t in trades if t['pnl'] <= 0]
    wr = len(w) / len(trades) * 100
    pnl = sum(t['pnl'] for t in trades)
    eq = [1000.0]
    for t in trades: eq.append(eq[-1] + t['pnl'])
    peak = eq[0]; mdd = 0
    for v in eq:
        peak = max(peak, v); dd = (peak - v) / peak * 100 if peak > 0 else 0; mdd = max(mdd, dd)
    pf = sum(t['pnl'] for t in w) / abs(sum(t['pnl'] for t in l)) if l and sum(t['pnl'] for t in l) != 0 else 0
    longs = [t for t in trades if t['dir'] == 'LONG']
    shorts = [t for t in trades if t['dir'] == 'SHORT']
    lw = len([t for t in longs if t['pnl'] > 0])
    sw = len([t for t in shorts if t['pnl'] > 0])
    return {
        'trades': len(trades), 'wr': wr, 'pnl': pnl, 'eq': equity, 'mdd': mdd, 'pf': pf,
        'longs': len(longs), 'long_wr': lw/len(longs)*100 if longs else 0,
        'shorts': len(shorts), 'short_wr': sw/len(shorts)*100 if shorts else 0,
        'long_pnl': sum(t['pnl'] for t in longs), 'short_pnl': sum(t['pnl'] for t in shorts),
    }

# ── Current configs ──────────────────────────────────────────────
current = {
    'BTC':  {'tp': 0.42, 'sl': 0.25, 'trail_act': 0.30, 'trail_stop': 0.15, 'cd': 120},
    'ETH':  {'tp': 0.50, 'sl': 0.30, 'trail_act': 0.35, 'trail_stop': 0.15, 'cd': 120},
    'SOL':  {'tp': 0.60, 'sl': 0.40, 'trail_act': 0.45, 'trail_stop': 0.20, 'cd': 120},
    'XRP':  {'tp': 0.45, 'sl': 0.25, 'trail_act': 0.35, 'trail_stop': 0.15, 'cd': 120},
    'ZEC':  {'tp': 0.55, 'sl': 0.30, 'trail_act': 0.40, 'trail_stop': 0.20, 'cd': 180},  # old config (before opt)
}

# ── Optimization grid ───────────────────────────────────────────
# For each coin, test current + variants with tighter TP + earlier/tighter trailing
def optimize_coin(coin):
    c5m, c1h = load_candles(coin)
    closes = np.array([float(c['c']) for c in c5m])
    highs = np.array([float(c['h']) for c in c5m])
    lows = np.array([float(c['l']) for c in c5m])
    atr = calc_atr(highs, lows, closes, 14)
    atr_pct = np.median(atr/closes*100)

    print(f'\n{"="*70}')
    print(f'  {coin} — {len(c5m)} candles, median 5m ATR={atr_pct:.3f}%')
    print(f'{"="*70}')

    # Current config
    cur = current[coin]
    r = run_backtest(c5m, c1h, cur['tp'], cur['sl'], cur['trail_act'], cur['trail_stop'], cur['cd'])
    if r:
        print(f'  CURRENT (TP={cur["tp"]}, SL={cur["sl"]}, trail={cur["trail_act"]}/{cur["trail_stop"]}, cd={cur["cd"]}):')
        print(f'    Trades: {r["trades"]} | WR: {r["wr"]:.1f}% | PnL: ${r["pnl"]:.2f} | MaxDD: {r["mdd"]:.1f}% | PF: {r["pf"]:.2f}')
        print(f'    L: {r["longs"]} ({r["long_wr"]:.0f}% ${r["long_pnl"]:.2f}) | S: {r["shorts"]} ({r["short_wr"]:.0f}% ${r["short_pnl"]:.2f})')

    # Test variants — tighter TP, earlier trailing, tighter trail stop
    # Scale based on coin's ATR
    variants = []
    for tp_mult in [0.5, 0.7, 0.85, 1.0]:
        for trail_act_mult in [0.5, 0.65, 0.8]:
            for trail_stop_mult in [0.3, 0.5, 0.65]:
                tp = round(cur['tp'] * tp_mult, 2)
                sl = cur['sl']
                ta = round(cur['trail_act'] * trail_act_mult, 2)
                ts = round(cur['trail_stop'] * trail_stop_mult, 2)
                if ta >= tp: continue  # trail must activate before TP
                if ts >= ta: continue
                for cd in [cur['cd'], cur['cd'] + 60, cur['cd'] + 120]:
                    variants.append((tp, sl, ta, ts, cd))

    best = None
    best_score = -999
    results = []
    for tp, sl, ta, ts, cd in variants:
        r = run_backtest(c5m, c1h, tp, sl, ta, ts, cd)
        if r and r['trades'] >= 10:
            # Score: prioritize PF * log(trades) - mdd penalty
            score = r['pf'] * np.log(max(r['trades'], 10)) - r['mdd'] * 0.1
            results.append((score, tp, sl, ta, ts, cd, r))
            if score > best_score:
                best_score = score
                best = (tp, sl, ta, ts, cd, r)

    # Sort and show top 5
    results.sort(key=lambda x: x[0], reverse=True)
    print(f'\n  TOP 5 OPTIMIZED:')
    for rank, (score, tp, sl, ta, ts, cd, r) in enumerate(results[:5], 1):
        marker = ' <== BEST' if rank == 1 else ''
        print(f'    {rank}. TP={tp:.2f}% SL={sl:.2f}% trail={ta:.2f}/{ts:.2f} cd={cd}s: '
              f'{r["trades"]} trades | {r["wr"]:.1f}% WR | ${r["pnl"]:.2f} | DD={r["mdd"]:.1f}% | PF={r["pf"]:.2f}'
              f' | L:{r["longs"]}({r["long_wr"]:.0f}%) S:{r["shorts"]}({r["short_wr"]:.0f}%){marker}')

    return best

# ── Run for each coin ──────────────────────────────────────────
results = {}
for coin in ['BTC', 'ETH', 'SOL', 'XRP', 'ZEC']:
    best = optimize_coin(coin)
    if best:
        results[coin] = best

# ── Summary ────────────────────────────────────────────────────
print(f'\n{"="*70}')
print(f'  OPTIMIZATION SUMMARY')
print(f'{"="*70}')
print(f'{"Coin":>5} {"TP%":>6} {"SL%":>6} {"TrailA%":>8} {"TrailS%":>8} {"CD":>5} {"Trades":>7} {"WR%":>6} {"PnL":>10} {"DD%":>6} {"PF":>6}')
for coin, (tp, sl, ta, ts, cd, r) in results.items():
    print(f'{coin:>5} {tp:>5.2f}% {sl:>5.2f}% {ta:>7.2f}% {ts:>7.2f}% {cd:>4}s {r["trades"]:>7} {r["wr"]:>5.1f}% ${r["pnl"]:>8.2f} {r["mdd"]:>5.1f}% {r["pf"]:>5.2f}')