"""Turns (daily baseline + live price + news + chatter) into one clear action."""
import datetime as dt

import numpy as np

from . import llm, social
from .levels import exits

UTC = dt.timezone.utc
LABEL = {"consider_long": "CONSIDER LONG", "wait_for_pullback": "WAIT FOR PULLBACK",
         "watch": "WATCH", "avoid": "AVOID / CAUTION"}
ICON = {"consider_long": "💡", "wait_for_pullback": "⏳", "watch": "👀", "avoid": "⚠️"}


def levels(price, base, tc):
    atr = base["atr"]
    stop, target = exits(price, atr, tc)
    return {"entry": round(price, 2), "stop": round(stop, 2), "target": round(target, 2),
            "stop_pct": round((price - stop) / price * 100, 1), "target_pct": round((target - price) / price * 100, 1),
            "rr": round((target - price) / (price - stop), 2),
            "pullback_zone": [round(base["sma20"] - 0.25 * atr, 2), round(base["sma20"] + 0.10 * atr, 2)]}


def rule_read(base, live, items):
    price, atr = live["price"], base["atr"]
    move_atr = (price - base["close"]) / atr if atr else 0.0
    pace = live.get("vol_pace")
    fresh = [i for i in items if i.get("importance", 0) >= 3]
    bull = sum(i.get("sentiment") == "bullish" for i in fresh)
    bear = sum(i.get("sentiment") == "bearish" for i in fresh)
    pts, why = 2, []
    if base["trend"] == "up":
        pts += 1; why.append("uptrend (above 50 and 200-day averages)")
    elif base["trend"] == "down":
        pts -= 1; why.append("downtrend")
    if pace and pace >= 2:
        pts += 1; why.append(f"volume {pace:.1f}x its normal pace")
    if bull > bear:
        pts += 1; why.append("bullish news flow")
    elif bear > bull:
        pts -= 1; why.append("bearish news flow")
    breakout = price > base["high20"]
    if breakout:
        pts += 1; why.append("trading above its prior 20-day high")
    extended = base["rsi"] >= 75 or price > base["sma20"] + 3 * atr
    if extended:
        pts -= 1; why.append("already extended above its averages")

    if move_atr >= 2:
        if bear > bull or base["trend"] == "down":
            action = "watch"
        elif extended:
            action = "wait_for_pullback"
        else:
            action = "consider_long" if pts >= 4 else "watch"
    elif move_atr <= -2:
        action = "watch" if (base["trend"] == "up" and bull >= bear and base["rsi"] < 35) else "avoid"
    else:
        action = "consider_long" if (breakout and pts >= 4 and not extended) else "watch"
    return {"action": action, "conviction": int(np.clip(pts, 1, 5)),
            "why": "; ".join(why) or "unusual move without a clear catalyst",
            "risk": "Gaps and news-driven moves can fade fast; size for the stop, not the hope.",
            "invalidation": f"Falls back below the previous close of {base['close']}."}


def _context(t, base, live, items, soc):
    r = rule_read(base, live, items)
    heads = "\n".join(f"- ({i.get('importance')}/5, {i.get('sentiment')}) {i['title']}" for i in items[:6]) or "none"
    return (f"Ticker {t} ({base['group']}). Live price {live['price']:.2f} vs previous close {base['close']} "
            f"({live['move_pct']:+.1f}%, {live['move_atr']:+.1f}x daily ATR). Volume pace: "
            f"{live['vol_pace'] if live.get('vol_pace') else 'n/a (outside regular session)'}x normal.\n"
            f"Trend {base['trend']}, RSI {base['rsi']}, SMA20 {base['sma20']}, SMA50 {base['sma50']}, "
            f"SMA200 {base['sma200']}, prior 20-day high {base['high20']}, 3-month strength vs SPY "
            f"{base['rel_strength_3m']:+.1f}%.\n"
            f"Rule-based first read: {r['action']} (conviction {r['conviction']}): {r['why']}.\n"
            f"Recent headlines (scored):\n<untrusted>\n{heads}\n</untrusted>\n"
            f"Social chatter:\n<untrusted>\n{social.describe(soc) or 'none'}\n</untrusted>")


def recommend(t, base, live, items, soc, tc):
    rec = rule_read(base, live, items)
    rec["source"] = "rules"
    if llm.available():
        try:
            out = llm.recommend(_context(t, base, live, items, soc))
            if out:
                rec.update(out)
                rec["source"] = "llm"
        except Exception as e:
            print("[llm] recommend failed, using rules:", e)
    rec.update({"ticker": t, "group": base["group"], "price": round(live["price"], 2),
                "move_pct": live["move_pct"], "move_atr": live["move_atr"], "vol_pace": live.get("vol_pace"),
                "trend": base["trend"], "levels": levels(live["price"], base, tc),
                "news": [{"title": i["title"], "link": i.get("link", ""), "importance": i.get("importance"),
                          "sentiment": i.get("sentiment")} for i in items[:3]],
                "social": soc, "time": dt.datetime.now(UTC).isoformat(timespec="seconds")})
    return rec


def format_alert(r):
    lv = r["levels"]
    pace = f", volume {r['vol_pace']:.1f}x pace" if r.get("vol_pace") else ""
    lines = [f"{ICON[r['action']]} {r['ticker']} | {LABEL[r['action']]} (conviction {r['conviction']}/5)",
             f"Now ${r['price']} ({r['move_pct']:+.1f}%, {r['move_atr']:+.1f}x ATR){pace} | trend {r['trend']}",
             f"Why: {r['why']}"]
    if r["action"] == "consider_long":
        lines.append(f"Plan: entry ~{lv['entry']} | stop {lv['stop']} (-{lv['stop_pct']}%) | "
                     f"target {lv['target']} (+{lv['target_pct']}%) | R/R {lv['rr']}")
    elif r["action"] == "wait_for_pullback":
        lines.append(f"Better entry zone: {lv['pullback_zone'][0]} - {lv['pullback_zone'][1]} (20-day average)")
    lines.append(f"Risk: {r['risk']}")
    lines.append(f"Invalid if: {r['invalidation']}")
    for n in r["news"][:2]:
        lines.append(f"- {n['title']}")
    soc = social.describe(r.get("social"))
    if soc:
        lines.append(soc.split("\n")[0])
    lines.append("(Research, not advice. Check the live price on Colmex first.)")
    return "\n".join(lines)
