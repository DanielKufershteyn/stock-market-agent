"""FAST loop (every ~5 min). Live prices (incl. pre-market/after-hours) -> movers ->
news + 8-K + social for those movers -> one clear recommendation pushed to Telegram."""
import datetime as dt
import math
import os
import time

from . import alerts, llm, news as N, recommend as R, social, store
from .config import all_tickers, group_map, load_config
from .data import get_intraday, market_phase

UTC = dt.timezone.utc


def live_metrics(snap, intra):
    live = {}
    for t, b in snap.items():
        x = intra.get(t)
        if not x or x["age_min"] > 90 or not b.get("atr"):
            continue
        move = x["price"] - b["close"]
        pace = None
        if 0.1 <= x["elapsed"] < 1.0 and b.get("avg_vol"):
            pace = round(x["session_vol"] / (b["avg_vol"] * x["elapsed"]), 2)
        live[t] = {"price": round(x["price"], 2), "move_pct": round(move / b["close"] * 100, 2),
                   "move_atr": round(move / b["atr"], 2), "vol_pace": pace, "ts": x["ts"], "day": x["day"]}
    return live


def trigger_reason(b, lv, ac):
    reasons = []
    if abs(lv["move_atr"]) >= ac["spike_atr_mult"]:
        reasons.append("price move")
    if lv["vol_pace"] and lv["vol_pace"] >= ac["spike_volume_mult"]:
        reasons.append("volume surge")
    if lv["price"] > b["high20"] and b["trend"] == "up" and (lv["vol_pace"] or 0) >= 1.5:
        reasons.append("live breakout")
    return reasons


def main():
    cfg = load_config()
    tickers, groups = all_tickers(cfg), group_map(cfg)
    ac, tc = cfg["alerts"], cfg["trade"]
    now = dt.datetime.now(UTC)
    base = store.load("snapshot.json", {}).get("tickers")
    if not base:
        print("No baseline yet: run the scan workflow first.")
        return

    state = store.load("state.json", {"seen": [], "alerted": {}, "last_rec": {}, "llm_calls": {}})
    today = now.date().isoformat()
    state["llm_calls"] = {today: state.get("llm_calls", {}).get(today, 0)}
    llm.BUDGET = max(0, ac["llm_max_calls_per_day"] - state["llm_calls"][today])
    llm_calls_at_start = llm.CALLS
    alerted = {k: v for k, v in state["alerted"].items() if v >= (now - dt.timedelta(days=5)).date().isoformat()}
    seen = list(state["seen"])
    seen_set = set(seen)
    last_rec = state.get("last_rec", {})
    news_store = store.load("news.json", {"items": []})
    recs_store = store.load("recs.json", {"recs": []})
    first_run = not news_store["items"]
    sent = 0

    # 1) live prices -> who is moving?
    intra = get_intraday([t for t in tickers if t in base])
    live = live_metrics(base, intra)
    hot = {}
    for t, lv in live.items():
        r = trigger_reason(base[t], lv, ac)
        if r:
            hot[t] = r
    print(f"phase={market_phase()} live={len(live)} hot={len(hot)} {sorted(hot)[:8]}")

    # 2) news: movers first, a rotating slice for the rest, plus anything that just filed an 8-K
    size = ac["news_slice_size"]
    n_slices = max(1, math.ceil(len(tickers) / size))
    k = int(time.time() // 300) % n_slices
    fetch = list(dict.fromkeys(list(hot) + tickers[k * size:(k + 1) * size]))
    cik, names = store.load("cik_map.json", None), store.load("names.json", None)
    if not cik or not names:
        try:
            cik, names = N.build_company_files(tickers)
            store.save("cik_map.json", cik)
            store.save("names.json", names)
        except Exception as e:
            print("[sec] company list failed:", e)
            cik, names = cik or {}, names or {}
    matcher = N.make_matcher(tickers, names, cfg.get("aliases", {}))
    found = N.collect(fetch, sources=(N.google_news, N.yahoo_news))
    found = [i for i in found if i["ticker"] in matcher(i["title"])]     # drop loosely related search hits
    rss_health = {}
    try:
        rss_items, rss_health = N.collect_rss(cfg.get("rss_sources", []), matcher)
        found += rss_items
        print("rss articles matched:", len(rss_items), rss_health)
    except Exception as e:
        print("[rss] skipped:", e)
    try:
        filed = N.edgar_current(cik)
        if filed:
            found += N.collect(sorted(filed), sources=(N.edgar_8k,))
        print("8-K filers this pulse:", sorted(filed))
    except Exception as e:
        print("[edgar] skipped:", e)
    new = [i for i in found if i["id"] not in seen_set]
    new.sort(key=lambda i: (i["source"] != "SEC 8-K", i["ticker"] not in hot))
    batch = new[:ac["max_new_items_per_run"]]
    llm.score_news(batch)
    seen += [i["id"] for i in batch]
    cut7 = (now - dt.timedelta(days=7)).isoformat(timespec="seconds")
    items = sorted([i for i in news_store["items"] + batch if i["published"] >= cut7],
                   key=lambda i: i["published"], reverse=True)[:500]

    # 3) who deserves a recommendation?
    cut24 = (now - dt.timedelta(hours=24)).isoformat(timespec="seconds")
    by_t = {}
    for i in items:
        if i["published"] >= cut24:
            by_t.setdefault(i["ticker"], []).append(i)
    big_news = {i["ticker"] for i in batch if i["importance"] >= ac["min_news_importance"] and i["ticker"] in base}
    candidates = list(dict.fromkeys(sorted(hot, key=lambda t: -abs(live[t]["move_atr"])) + sorted(big_news)))
    new_recs = []
    for t in candidates:
        if first_run or sent >= ac["max_alerts_per_run"] or len(new_recs) >= ac["max_recs_per_pulse"]:
            break
        if t not in live:                       # big news but no fresh price: still need a price to plan
            continue
        prior = last_rec.get(t)
        top5 = any(i["importance"] >= 5 for i in batch if i["ticker"] == t)
        if prior and prior >= (now - dt.timedelta(minutes=ac["recommend_cooldown_min"])).isoformat() and not top5:
            continue
        soc = social.fetch(t, cfg, state)
        tn = sorted(by_t.get(t, []), key=lambda i: (-i.get("importance", 0), i["published"]))
        rec = R.recommend(t, base[t], live[t], tn, soc, tc)
        rec["trigger"] = hot.get(t, []) + (["news"] if t in big_news else [])
        new_recs.append(rec)
        last_rec[t] = now.isoformat(timespec="seconds")
        quiet = rec["action"] == "watch" and not (top5 or rec["conviction"] >= 3)
        key = f"rec|{t}|{live[t]['day']}|{rec['action']}"
        if not quiet and key not in alerted:
            alerted[key] = today
            if alerts.send(R.format_alert(rec)):
                sent += 1

    for i in batch:                                   # market-wide 5/5 news (Fed, tariffs...) has no stock to plan for
        if (i["ticker"] == "MACRO" and i["importance"] >= 5 and not first_run and sent < ac["max_alerts_per_run"]
                and f"macro|{i['id']}" not in alerted):
            alerted[f"macro|{i['id']}"] = today
            if alerts.send(f"🌐 MACRO | importance {i['importance']}/5 ({i['sentiment']})\n{i['title']}\n"
                           f"{i['summary']}\nWhy: {i['why']}\n{i['link']}"):
                sent += 1

    # 4) save
    recs = (new_recs + recs_store["recs"])[:100]
    stamp = now.isoformat(timespec="seconds")
    state["llm_calls"][today] += llm.CALLS - llm_calls_at_start
    store.save("news.json", {"updated": stamp, "items": items})
    store.save("live.json", {"updated": stamp, "phase": market_phase(), "tickers": live, "hot": hot})
    store.save("recs.json", {"updated": stamp, "recs": recs})
    store.save("state.json", {"seen": seen[-5000:], "alerted": alerted, "last_rec": last_rec,
                              "llm_calls": state["llm_calls"], "x_usage": state.get("x_usage", {})})
    store.save("status.json", {"updated": stamp, "phase": market_phase(), "live": len(live), "hot": len(hot),
                               "new_news": len(batch), "recs": len(new_recs), "alerts_sent": sent, "rss": rss_health,
                               "llm": llm.providers()})
    print(f"pulse ok: {len(live)} live, {len(hot)} hot, {len(batch)} new news, {len(new_recs)} recs, {sent} alerts")


if __name__ == "__main__":
    main()
