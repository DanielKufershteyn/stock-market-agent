"""One place that decides stop / target, so alerts, plans and backtests always agree.
ATR mode:     stop = entry - atr_stop*ATR,  target = entry + atr_target*ATR
Percent mode: (set stop_pct AND target_pct in config.yaml) target = entry*(1+target_pct%),
              stop = entry - max(stop_pct% of entry, atr_stop*ATR)  <- never tighter than normal daily noise"""


def exits(entry, atr, tc):
    if tc.get("stop_pct") and tc.get("target_pct"):
        risk = max(entry * tc["stop_pct"] / 100, tc["atr_stop"] * atr)
        return entry - risk, entry * (1 + tc["target_pct"] / 100)
    return entry - tc["atr_stop"] * atr, entry + tc.get("atr_target", 3.0) * atr


def bt_kwargs(tc):
    return dict(atr_stop=tc["atr_stop"], atr_tgt=tc.get("atr_target", 3.0), stop_pct=tc.get("stop_pct"),
                tgt_pct=tc.get("target_pct"), max_hold=tc["max_hold_days"], cost=tc["cost_pct"])
