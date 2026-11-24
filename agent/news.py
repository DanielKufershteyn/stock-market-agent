import datetime as dt
import hashlib
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests

UTC = dt.timezone.utc
_sec_lock = threading.Lock()


def _id(ticker, title):
    norm = re.sub(r"\W+", " ", title.lower()).strip()[:90]
    return hashlib.md5(f"{ticker}|{norm}".encode()).hexdigest()[:16]


def _when(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            return dt.datetime(*e[k][:6], tzinfo=UTC)
    return None


def _items(feed, ticker, source=None, strip_suffix=False):
    out = []
    for e in feed.entries[:15]:
        title = (e.get("title") or "").strip()
        when = _when(e)
        if not title or not when:
            continue
        src = source or (e.get("source") or {}).get("title") or "News"
        if strip_suffix:
            title = re.sub(r"\s+-\s+[^-]+$", "", title)
        out.append({"id": _id(ticker, title), "ticker": ticker, "title": title,
                    "link": e.get("link", ""), "source": src,
                    "published": when.isoformat(timespec="seconds")})
    return out


def google_news(t):
    url = f"https://news.google.com/rss/search?q={t}+stock+when:2d&hl=en-US&gl=US&ceid=US:en"
    return _items(feedparser.parse(url), t, strip_suffix=True)


def yahoo_news(t):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={t}&region=US&lang=en-US"
    return _items(feedparser.parse(url), t, source="Yahoo Finance")


def edgar_8k(t):
    url = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={t}"
           f"&type=8-K&dateb=&owner=include&count=5&output=atom")
    with _sec_lock:                      # SEC asks for <10 requests/second
        time.sleep(0.2)
        r = requests.get(url, headers=sec_headers(), timeout=15)
    feed = feedparser.parse(r.content)
    out = []
    for e in feed.entries[:5]:
        when = _when(e)
        if not when:
            continue
        summ = re.sub(r"<[^>]+>", " ", e.get("summary", ""))
        summ = re.sub(r"\s+", " ", summ).strip()[:220]
        title = f"{t} 8-K filing: {summ}" if summ else f"{t} 8-K filing"
        out.append({"id": _id(t, "8k" + e.get("id", title)), "ticker": t, "title": title,
                    "link": e.get("link", ""), "source": "SEC 8-K",
                    "published": when.isoformat(timespec="seconds")})
    return out


def _safe(fn, t):
    try:
        return fn(t)
    except Exception as ex:
        print(f"[news] {fn.__name__} {t}: {ex}")
        return []


def sec_headers():
    return {"User-Agent": os.environ.get("SEC_USER_AGENT") or "swing-agent personal-use contact@example.com"}


def build_company_files(tickers):
    """From the SEC's official ticker file: ({cik: ticker}, {ticker: legal name}) for the watchlist."""
    r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=sec_headers(), timeout=30)
    r.raise_for_status()
    want, cik, names = set(tickers), {}, {}
    for v in r.json().values():
        if v["ticker"] in want:
            cik[str(v["cik_str"])] = v["ticker"]
            names[v["ticker"]] = v["title"]
    return cik, names


def edgar_current(cik_map, pages=2):
    """ONE feed of the newest 8-Ks from ALL companies -> which of our tickers just filed."""
    hits = set()
    for p in range(pages):
        url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company="
               f"&dateb=&owner=include&start={p * 100}&count=100&output=atom")
        try:
            feed = feedparser.parse(requests.get(url, headers=sec_headers(), timeout=15).content)
        except Exception as e:
            print("[edgar_current]", e)
            break
        for e in feed.entries:
            m = re.search(r"\((\d{10})\)", e.get("title", ""))
            if m and str(int(m.group(1))) in cik_map:
                hits.add(cik_map[str(int(m.group(1)))])
        time.sleep(0.2)
    return hits


def collect(tickers, max_age_hours=48, sources=(google_news, yahoo_news, edgar_8k), workers=8):
    cutoff = (dt.datetime.now(UTC) - dt.timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
    jobs = [(fn, t) for t in tickers for fn in sources]
    found, seen = [], set()
    with ThreadPoolExecutor(workers) as ex:
        for res in ex.map(lambda j: _safe(*j), jobs):
            for it in res:
                if it["published"] >= cutoff and it["id"] not in seen:
                    seen.add(it["id"])
                    found.append(it)
    return found


# ---------------- free RSS sources, matched to the watchlist ----------------
_SUFFIX = re.compile(r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings?|group|the|"
                     r"nv|ag|sa|lp|llc|pbc|class [a-c]|common stock|and|of)\b", re.I)
_GENERIC = {"target", "general", "united", "american", "first", "delta", "square", "block", "live", "north",
            "global", "digital", "energy", "financial", "technologies", "international", "national"}
_TICKER_STOP = {"NOW", "ARM", "CAT", "ALL", "FLY", "ONE", "CEO", "USA", "ETF", "IPO", "SEC", "FED", "GDP",
                "CPI", "AI", "EPS", "FDA", "NYSE", "FOMC"}
_MACRO = re.compile(r"\b(fed|fomc|powell|inflation|cpi|ppi|payrolls?|jobs report|unemployment|tariffs?|rate cuts?|"
                    r"rate hikes?|treasury yields?|recession|gdp|shutdown|opec|stocks?|wall street|s&p 500|nasdaq|dow)\b", re.I)


def clean_name(title):
    t = re.sub(r"/[A-Za-z]{1,3}/", " ", title or "")
    t = re.sub(r"[.,'\"]", " ", t)
    t = re.sub(r"\s+", " ", _SUFFIX.sub(" ", t)).strip().lower()
    words = t.split()
    while words and len(words[-1]) == 1:
        words.pop()
    return " ".join(words)


def make_matcher(tickers, names, aliases):
    rules = []
    for t in tickers:
        words = {a.lower() for a in (aliases or {}).get(t, [])}
        n = clean_name((names or {}).get(t, ""))
        if n and n not in _GENERIC and len(n) >= 4:
            words.add(n)
        name_rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
                             + r")(?![A-Za-z0-9])", re.I) if words else None
        cash_rx = re.compile(r"\$" + re.escape(t) + r"(?![A-Za-z0-9])", re.I)
        bare_rx = (re.compile(r"(?<![A-Za-z0-9$])" + re.escape(t) + r"(?![A-Za-z0-9])")
                   if len(t) >= 3 and t not in _TICKER_STOP else None)
        rules.append((t, name_rx, cash_rx, bare_rx))

    def match(text):
        return [t for t, nrx, crx, brx in rules
                if (nrx and nrx.search(text)) or crx.search(text) or (brx and brx.search(text))]
    return match


def collect_rss(feeds, matcher, max_age_hours=48, max_tickers=4):
    """Returns (items, health). health = {feed name: article count or 'error'}."""
    cutoff = (dt.datetime.now(UTC) - dt.timedelta(hours=max_age_hours)).isoformat(timespec="seconds")
    ua = {"User-Agent": "Mozilla/5.0 (compatible; swing-agent/1.0)"}
    items, health = [], {}
    for f in feeds or []:
        try:
            r = requests.get(f["url"], headers=ua, timeout=15)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            n = 0
            for e in feed.entries[:40]:
                title, when = (e.get("title") or "").strip(), _when(e)
                if not title or not when or when.isoformat(timespec="seconds") < cutoff:
                    continue
                summ = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", e.get("summary", "")))[:300]
                hits = matcher(title + " " + summ)
                if not hits:
                    hits = ["MACRO"] if (f.get("macro") or _MACRO.search(title)) else []
                if not hits or len(hits) > max_tickers:       # roundups mentioning many stocks are skipped
                    continue
                n += 1
                for t in hits:
                    items.append({"id": _id(t, title), "ticker": t, "title": title, "link": e.get("link", ""),
                                  "source": f["name"], "published": when.isoformat(timespec="seconds")})
            health[f["name"]] = n
        except Exception as ex:
            print(f"[rss] {f.get('name')}: {ex}")
            health[f.get("name", "?")] = "error"
    return items, health
