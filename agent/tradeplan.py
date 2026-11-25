from .levels import exits


def make_plan(d, tc):
    last = d.iloc[-1]
    entry, atr = float(last["Close"]), float(last["ATR"])
    stop, target = exits(entry, atr, tc)
    return {
        "entry": round(entry, 2),
        "entry_zone": [round(entry - 0.25 * atr, 2), round(entry + 0.10 * atr, 2)],
        "stop": round(stop, 2), "target": round(target, 2),
        "stop_pct": round((entry - stop) / entry * 100, 1), "target_pct": round((target - entry) / entry * 100, 1),
        "rr": round((target - entry) / (entry - stop), 2),
        "atr": round(atr, 2),
        "max_hold_days": tc["max_hold_days"],
    }


def position_size(entry, stop, account, risk_pct):
    risk_per_share = entry - stop
    if risk_per_share <= 0 or account <= 0 or entry <= 0:
        return {"shares": 0, "position_value": 0.0, "risk_usd": 0.0}
    shares = int((account * risk_pct / 100) / risk_per_share)
    shares = max(0, min(shares, int(account // entry)))   # no leverage
    return {"shares": shares,
            "position_value": round(shares * entry, 2),
            "risk_usd": round(shares * risk_per_share, 2)}
