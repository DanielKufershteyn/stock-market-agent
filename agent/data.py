import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

COLS = ["Open", "High", "Low", "Close", "Volume"]
NY = ZoneInfo("America/New_York")


def _clean(df):
    df = df[COLS].dropna(subset=["Close"])
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    return df


def market_phase(now=None):
    now = (now or dt.datetime.now(NY)).astimezone(NY)
    if now.weekday() >= 5:
        return "closed"
    t = now.time()
    if dt.time(4, 0) <= t < dt.time(9, 30):
        return "pre"
    if dt.time(9, 30) <= t < dt.time(16, 0):
        return "regular"
    if dt.time(16, 0) <= t < dt.time(20, 0):
        return "after"
    return "closed"


def drop_partial(df, now=None):
    """Drop today's still-forming daily bar so indicators only use completed days."""
    if df is None or len(df) == 0:
        return df
    now = (now or dt.datetime.now(NY)).astimezone(NY)
    if now.weekday() < 5 and df.index[-1].date() == now.date() and now.time() < dt.time(16, 15):
        return df.iloc[:-1]
    return df


def get_history(ticker, period="3y"):
    df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    return _clean(df) if len(df) else df


def _download(tickers, **kw):
    try:
        return yf.download(list(tickers), group_by="ticker", auto_adjust=True, progress=False,
                           threads=True, **kw)
    except Exception as e:
        print("download failed:", e)
        return None


def get_many(tickers, period="3y"):
    tickers = list(dict.fromkeys(tickers))
    out = {}
    raw = _download(tickers, period=period, interval="1d")
    if raw is None or raw.empty:
        return out
    if not isinstance(raw.columns, pd.MultiIndex):
        out[tickers[0]] = _clean(raw)
        return out
    for t in tickers:
        try:
            d = _clean(raw[t])
            if len(d) > 60:
                out[t] = d
        except Exception:
            pass
    return out


def get_intraday(tickers, interval="5m", bar_min=5):
    """Latest price incl. pre-market / after-hours, plus regular-session volume and
    how much of the 390-minute session has elapsed (to judge volume pace)."""
    tickers = list(dict.fromkeys(tickers))
    out = {}
    raw = _download(tickers, period="2d", interval=interval, prepost=True)
    if raw is None or raw.empty:
        return out
    multi = isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        try:
            df = (raw[t] if multi else raw).dropna(subset=["Close"]).copy()
            if df.empty:
                continue
            idx = df.index
            df.index = idx.tz_convert(NY) if idx.tz is not None else idx.tz_localize("UTC").tz_convert(NY)
            last_ts = df.index[-1]
            day = df[df.index.date == last_ts.date()]
            reg = day.between_time("09:30", "15:59")
            vol, elapsed = 0.0, 0.0
            if len(reg):
                vol = float(reg.Volume.sum())
                open_ts = reg.index[0].normalize() + pd.Timedelta(hours=9, minutes=30)
                elapsed = min(1.0, ((reg.index[-1] - open_ts).total_seconds() / 60 + bar_min) / 390)
            out[t] = {"price": float(df.Close.iloc[-1]), "ts": last_ts.isoformat(),
                      "age_min": (pd.Timestamp.now(tz=NY) - last_ts).total_seconds() / 60,
                      "session_vol": vol, "elapsed": float(elapsed), "day": str(last_ts.date())}
        except Exception:
            pass
    return out
