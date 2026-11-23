"""Runs once after the US close: builds the daily briefing and sends it to Telegram."""
import datetime as dt

from . import alerts, llm, store

UTC = dt.timezone.utc


def build_digest(sig, snap, news, recs=None):
    lines = []
    tickers = snap.get("tickers", {})
    if tickers:
        ups = sum(1 for s in tickers.values() if s["trend"] == "up")
        downs = sum(1 for s in tickers.values() if s["trend"] == "down")
        avg = sum(s["change_pct"] for s in tickers.values()) / len(tickers)
        lines.append(f"Watchlist: {ups} uptrend, {downs} downtrend, {len(tickers)} total, avg day change {avg:+.2f}%")
        movers = sorted(tickers.items(), key=lambda kv: -abs(kv[1]["change_pct"]))[:5]
        lines.append("Biggest movers: " + ", ".join(f"{t} {s['change_pct']:+.1f}%" for t, s in movers))
    lines.append("Setups:")
    for s in sig.get("signals", [])[:6]:
        a = (s.get("backtest") or {}).get("all", {})
        bt = f", history on this stock: {a['n']} trades, {a['win_rate']}% wins" if a.get("n") else ""
        p = s["plan"]
        lines.append(f"- {s['ticker']} {s['setup']} score {s['score']}: entry {p['entry']}, stop {p['stop']}, "
                     f"target {p['target']}{bt}")
    if not sig.get("signals"):
        lines.append("- none today")
    cut = (dt.datetime.now(UTC) - dt.timedelta(hours=26)).isoformat(timespec="seconds")
    top = [i for i in news.get("items", []) if i["published"] >= cut and i.get("importance", 0) >= 3]
    top.sort(key=lambda i: -i["importance"])
    lines.append("Live recommendations in the last 26h:")
    rc = (dt.datetime.now(UTC) - dt.timedelta(hours=26)).isoformat(timespec="seconds")
    rr = [r for r in (recs or {}).get("recs", []) if r["time"] >= rc and r["action"] != "watch"][:6]
    for r in rr:
        lines.append(f"- {r['ticker']} {r['action']} (conviction {r['conviction']}): {r['why']}")
    if not rr:
        lines.append("- none")
    lines.append("Important news:")
    for i in top[:8]:
        lines.append(f"- [{i['ticker']}] ({i['importance']}/5, {i.get('sentiment', '')}) {i['title']}")
    if not top:
        lines.append("- none")
    return "\n".join(lines)


def main():
    sig, snap, news, recs = (store.load(n, {}) for n in ("signals.json", "snapshot.json", "news.json", "recs.json"))
    digest = build_digest(sig, snap, news, recs)
    text = None
    if llm.available():
        try:
            text = llm.briefing(digest)
        except Exception as e:
            print("[llm] briefing failed:", e)
    text = text or digest
    now = dt.datetime.now(UTC)
    store.save("briefing.json", {"updated": now.isoformat(timespec="seconds"), "text": text, "digest": digest})
    alerts.send_telegram("🗞 Daily briefing\n\n" + text)
    print("briefing done")


if __name__ == "__main__":
    main()
