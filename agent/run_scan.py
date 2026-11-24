"""SLOW loop (3x per trading day). Heavy part: 5y of daily data, indicators, setups, backtests.
Writes the baseline that the fast pulse compares live prices against."""
import datetime as dt

from . import alerts, screener as S, store
from .config import all_tickers, group_map, load_config
from .data import get_many

UTC = dt.timezone.utc


def main():
    cfg = load_config()
    tickers, groups, bench = all_tickers(cfg), group_map(cfg), cfg.get("benchmark", "SPY")
    ac = cfg["alerts"]
    now = dt.datetime.now(UTC)
    first_run = not store.load("signals.json", {}).get("signals") and not store.load("state_scan.json", {})
    state = store.load("state_scan.json", {"alerted": {}})
    cutoff = (now - dt.timedelta(days=5)).date().isoformat()
    alerted = {k: v for k, v in state["alerted"].items() if v >= cutoff}

    frames = get_many(tickers + [bench], period="5y")
    if not frames:
        raise SystemExit("No price data returned (Yahoo problem?). Keeping the old baseline.")
    signals, snap = S.scan(frames, cfg, groups, frames.get(bench))
    stamp = now.isoformat(timespec="seconds")
    store.save("signals.json", {"updated": stamp, "signals": signals})
    store.save("snapshot.json", {"updated": stamp, "tickers": snap})

    sent = 0
    for sg in signals:
        key = f"setup|{sg['ticker']}|{sg['setup']}|{sg['last_bar']}"
        if first_run or sg["score"] < ac["min_setup_score"] or key in alerted or sent >= ac["max_alerts_per_run"]:
            continue
        alerted[key] = now.date().isoformat()
        p, a = sg["plan"], (sg.get("backtest") or {}).get("all", {})
        hist = f"\nHistory on this stock: {a['n']} trades, {a['win_rate']}% wins" if a.get("n") else ""
        if alerts.send(f"📈 Setup: {sg['ticker']} {sg['setup']} (score {sg['score']})\n{sg['desc']}\n"
                                f"Entry ~{p['entry']} | Stop {p['stop']} | Target {p['target']} (R/R {p['rr']})"
                                f"{hist}\n(Research, not advice.)"):
            sent += 1
    store.save("state_scan.json", {"alerted": alerted})
    store.save("status_scan.json", {"updated": stamp, "tickers": len(snap), "signals": len(signals), "alerts_sent": sent})
    print(f"scan ok: {len(snap)} tickers, {len(signals)} setups, {sent} alerts")


if __name__ == "__main__":
    main()
