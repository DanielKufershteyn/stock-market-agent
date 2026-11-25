import numpy as np
import pandas as pd

from . import indicators as I
from .backtest import backtest_split
from .data import drop_partial
from .levels import bt_kwargs
from .tradeplan import make_plan


def sig_pullback(d):
    uptrend = (d.Close > d.SMA50) & (d.SMA20 > d.SMA50) & (d.SMA50 > d.SMA200)
    near20 = (d.Low <= d.SMA20 + 0.25 * d.ATR) & (d.Close >= d.SMA20 - 0.5 * d.ATR)
    return uptrend & near20 & d.RSI.between(35, 52)


def sig_breakout(d):
    return (d.Close > d.High20) & (d.Volume > 1.5 * d.VolAvg20) & (d.Close > d.SMA50) & (d.RSI < 80)


def sig_oversold(d):
    return (d.RSI < 30) & (d.Close > d.SMA200) & (d.Close > d.Close.shift(1))


SETUPS = {"pullback": sig_pullback, "breakout": sig_breakout, "oversold_bounce": sig_oversold}
SETUP_DESC = {
    "pullback": "Uptrend pulling back to the 20-day average, RSI cooled off",
    "breakout": "Close above the prior 20-day high on strong volume",
    "oversold_bounce": "RSI under 30 inside a long-term uptrend, first up day",
}


def analyze(df):
    if df is None or len(df) < 210:
        return None
    d = I.add_indicators(df)
    if pd.isna(d.ATR.iloc[-1]) or pd.isna(d.SMA200.iloc[-1]):
        return None
    return d


def _score(rs, vol_ratio, above200):
    s = 50 + float(np.clip(rs * 100, -15, 15)) + float(np.clip((vol_ratio - 1) * 5, -5, 10))
    return int(np.clip(s + (5 if above200 else 0), 0, 100))


def scan(frames, cfg, groups, bench_df=None, with_backtest=True):
    tc = cfg["trade"]
    rb = None
    if bench_df is not None and len(bench_df) > 64:
        rb = float(bench_df.Close.iloc[-1] / bench_df.Close.iloc[-64] - 1)
    signals, snap = [], {}
    for t, df in frames.items():
        if t not in groups:
            continue
        d = analyze(drop_partial(df))   # completed days only
        if d is None:
            continue
        last, prev = d.iloc[-1], d.iloc[-2]
        rs = float(d.Close.iloc[-1] / d.Close.iloc[-64] - 1 - rb) if rb is not None else 0.0
        vr = float(last.Volume / prev.VolAvg20) if prev.VolAvg20 > 0 else 0.0
        move_atr = float((last.Close - prev.Close) / prev.ATR) if prev.ATR > 0 else 0.0
        if last.Close > last.SMA50 > last.SMA200:
            trend = "up"
        elif last.Close < last.SMA50 < last.SMA200:
            trend = "down"
        else:
            trend = "mixed"
        snap[t] = {"group": groups[t], "close": round(float(last.Close), 2),
                   "change_pct": round(float(last.Close / prev.Close - 1) * 100, 2),
                   "move_atr": round(move_atr, 2), "rsi": round(float(last.RSI), 1),
                   "atr_pct": round(float(last.ATR / last.Close) * 100, 2),
                   "vol_ratio": round(vr, 2), "rel_strength_3m": round(rs * 100, 1),
                   "trend": trend, "last_bar": str(d.index[-1].date()),
                   "atr": round(float(last.ATR), 4), "avg_vol": float(last.VolAvg20),
                   "sma20": round(float(last.SMA20), 2), "sma50": round(float(last.SMA50), 2),
                   "sma200": round(float(last.SMA200), 2), "high20": round(float(d.High.iloc[-20:].max()), 2)}
        for name, fn in SETUPS.items():
            sig = fn(d)
            if not bool(sig.iloc[-1]):
                continue
            plan = make_plan(d, tc)
            if plan["rr"] < tc.get("min_rr", 0):      # stop too wide for the target: not worth it
                continue
            bt = None
            if with_backtest:
                bt, _ = backtest_split(d, sig, **bt_kwargs(tc))
            signals.append({"ticker": t, "group": groups[t], "setup": name,
                            "desc": SETUP_DESC[name],
                            "score": _score(rs, vr, bool(last.Close > last.SMA200)),
                            "close": snap[t]["close"], "rsi": snap[t]["rsi"],
                            "vol_ratio": snap[t]["vol_ratio"], "rel_strength_3m": snap[t]["rel_strength_3m"],
                            "last_bar": snap[t]["last_bar"], "plan": plan, "backtest": bt})
    signals.sort(key=lambda s: -s["score"])
    return signals, snap


def verdict(d, tc):
    """One honest answer for a single stock: is there a buy signal AND is the risk/reward acceptable?"""
    plan = make_plan(d, tc)
    active = [n for n, fn in SETUPS.items() if bool(fn(d).iloc[-1])]
    last = d.iloc[-1]
    trend = "up" if last.Close > last.SMA50 > last.SMA200 else "down" if last.Close < last.SMA50 < last.SMA200 else "mixed"
    state = "none" if not active else ("buy" if plan["rr"] >= tc.get("min_rr", 0) else "low_rr")
    return {"state": state, "active": active, "trend": trend, "plan": plan}
