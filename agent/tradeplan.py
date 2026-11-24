def make_plan(d, atr_stop=1.5, atr_tgt=3.0, max_hold=10):
    last = d.iloc[-1]
    entry, atr = float(last["Close"]), float(last["ATR"])
    return {
        "entry": round(entry, 2),
        "entry_zone": [round(entry - 0.25 * atr, 2), round(entry + 0.10 * atr, 2)],
        "stop": round(entry - atr_stop * atr, 2),
        "target": round(entry + atr_tgt * atr, 2),
        "rr": round(atr_tgt / atr_stop, 2),
        "atr": round(atr, 2),
        "max_hold_days": max_hold,
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
