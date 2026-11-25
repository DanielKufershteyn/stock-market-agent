"""Social chatter. Both sources are OPTIONAL and best-effort; failures return None.
- StockTwits: free public symbol stream (unofficial; cloud IPs are sometimes blocked).
- X (Twitter): paid pay-per-use API (about $0.005 per post read, no free tier). Off by default,
  hard-capped by max_posts_per_day, and only queried for stocks that are already moving."""
import datetime as dt
import os

import requests

UTC = dt.timezone.utc
UA = "Mozilla/5.0 (compatible; swing-agent/1.0)"


def stocktwits(t):
    try:
        r = requests.get(f"https://api.stocktwits.com/api/2/streams/symbol/{t}.json",
                         headers={"User-Agent": UA}, timeout=10)
        if not r.ok:
            print(f"[stocktwits] {t}: HTTP {r.status_code}")
            return None
        msgs = r.json().get("messages", [])
    except Exception as e:
        print("[stocktwits]", e)
        return None
    cut = dt.datetime.now(UTC) - dt.timedelta(hours=1)
    bull = bear = recent = 0
    for m in msgs:
        s = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        bull += s == "Bullish"
        bear += s == "Bearish"
        try:
            if dt.datetime.fromisoformat(m["created_at"].replace("Z", "+00:00")) >= cut:
                recent += 1
        except Exception:
            pass
    return {"source": "stocktwits", "messages": len(msgs), "last_hour": recent, "bullish": bull,
            "bearish": bear, "samples": [str(m.get("body", ""))[:160] for m in msgs[:3]]}


def x_recent(t, token):
    q = f'("{t} stock" OR "{t} shares" OR "{t} earnings") -is:retweet lang:en'
    try:
        r = requests.get("https://api.x.com/2/tweets/search/recent",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15,
                         params={"query": q, "max_results": 10, "tweet.fields": "created_at,public_metrics"})
        if not r.ok:
            print(f"[x] {t}: HTTP {r.status_code} {r.text[:150]}")
            return None
        data = r.json().get("data", [])
    except Exception as e:
        print("[x]", e)
        return None

    def eng(p):
        m = p.get("public_metrics", {})
        return m.get("like_count", 0) + 2 * m.get("retweet_count", 0) + m.get("reply_count", 0)
    data.sort(key=eng, reverse=True)
    return {"source": "x", "posts": len(data),
            "top": [{"text": p["text"][:200], "likes": p.get("public_metrics", {}).get("like_count", 0)}
                    for p in data[:3]]}


def fetch(t, cfg, state):
    """Returns {"stocktwits": {...}|None, "x": {...}|None}. Mutates state['x_usage'] for budgeting."""
    sc, out = cfg.get("social", {}), {"stocktwits": None, "x": None}
    if sc.get("stocktwits"):
        out["stocktwits"] = stocktwits(t)
    xc, token = sc.get("x", {}), os.environ.get("X_BEARER_TOKEN")
    if xc.get("enabled") and token:
        today = dt.date.today().isoformat()
        usage = state.setdefault("x_usage", {})
        for k in [k for k in usage if k != today]:
            usage.pop(k)
        if usage.get(today, 0) + 10 <= xc.get("max_posts_per_day", 200):
            res = x_recent(t, token)
            if res is not None:
                usage[today] = usage.get(today, 0) + max(res["posts"], 1)
                out["x"] = res
    return out


def describe(soc):
    """Short text for prompts / alerts."""
    parts = []
    st = (soc or {}).get("stocktwits")
    if st:
        parts.append(f"StockTwits: {st['bullish']} bullish vs {st['bearish']} bearish of last {st['messages']} msgs, "
                     f"{st['last_hour']} in the last hour")
    x = (soc or {}).get("x")
    if x and x["top"]:
        parts.append("X top posts: " + " | ".join(p["text"].replace("\n", " ") for p in x["top"]))
    return "\n".join(parts)
