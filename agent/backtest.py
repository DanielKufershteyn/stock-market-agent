import numpy as np
import pandas as pd


def run_backtest(d, signal, atr_stop=1.5, atr_tgt=3.0, max_hold=10, cost=0.001):
    """Enter next open after a signal. Exit on stop / target / time. If stop and
    target hit in the same bar, assume the stop (conservative). One trade at a time."""
    o, h, l, c, atr = (d[k].values for k in ("Open", "High", "Low", "Close", "ATR"))
    sig = signal.fillna(False).values
    idx, n = d.index, len(d)
    trades, i = [], 0
    while i < n - 1:
        if sig[i] and not np.isnan(atr[i]) and o[i + 1] > 0:
            entry = o[i + 1]
            risk = atr_stop * atr[i]
            stop, tgt = entry - risk, entry + atr_tgt * atr[i]
            last = min(i + max_hold, n - 1)
            exit_px, exit_j, reason = c[last], last, "time"
            for j in range(i + 1, last + 1):
                if o[j] <= stop:
                    exit_px, exit_j, reason = o[j], j, "stop"; break
                if l[j] <= stop:
                    exit_px, exit_j, reason = stop, j, "stop"; break
                if h[j] >= tgt:
                    exit_px, exit_j, reason = max(tgt, o[j]), j, "target"; break
            ret = exit_px / entry - 1 - 2 * cost
            r = (exit_px - entry - 2 * cost * entry) / risk
            trades.append(dict(entry_date=idx[i + 1], exit_date=idx[exit_j],
                               entry=entry, exit=exit_px, ret=ret, r=r, reason=reason))
            i = exit_j + 1
        else:
            i += 1
    return pd.DataFrame(trades)


def summarize(t):
    if t is None or len(t) == 0:
        return {"n": 0}
    wins, losses = t[t.ret > 0], t[t.ret <= 0]
    gl = abs(losses.ret.sum())
    pf = float(wins.ret.sum() / gl) if gl > 0 else None
    eq = (1 + t.ret).cumprod()
    return {"n": int(len(t)),
            "win_rate": round(100 * len(wins) / len(t), 1),
            "avg_ret_pct": round(100 * float(t.ret.mean()), 2),
            "avg_r": round(float(t.r.mean()), 2),
            "profit_factor": round(pf, 2) if pf is not None else None,
            "max_dd_pct": round(100 * float((eq / eq.cummax() - 1).min()), 1)}


def backtest_split(d, signal, split=0.7, **kw):
    """Parameters are fixed (never tuned), so comparing the early 70% of history
    with the latest 30% is a stability check, not a fitted result."""
    t = run_backtest(d, signal, **kw)
    if len(t) == 0:
        return {"all": {"n": 0}, "in": {"n": 0}, "out": {"n": 0}}, t
    cut = d.index[int(len(d) * split)]
    return ({"all": summarize(t),
             "in": summarize(t[t.entry_date < cut]),
             "out": summarize(t[t.entry_date >= cut])}, t)
