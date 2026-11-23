# Swing Agent v2

Free research assistant for US swing trading across ~130 stocks in 18 sectors. It does NOT place trades.

```
FAST  pulse (every 5 min, pre-market to after-hours)
      live prices -> who moved? -> news + 8-K + social for THOSE stocks -> recommendation -> Telegram
SLOW  scan (3x per trading day)
      5y daily data, indicators, setups, backtests -> baseline the pulse compares against
APP   Streamlit: Live recommendations, Setups, News, Briefing, Deep dive (chart, backtest, probability cone)
```

## Setup (about 30 minutes, free)
1. **GitHub**: create a **public** repo (unlimited free Actions minutes) and upload this folder.
2. **Gemini key** (free): https://aistudio.google.com/apikey
3. **Telegram**: `@BotFather` -> `/newbot` -> token. Message your bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": ...}`.
4. **Repo -> Settings -> Secrets and variables -> Actions**: add secrets `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `SEC_USER_AGENT` (`YourName you@email.com`). Optional: `X_BEARER_TOKEN` (see below).
5. **Settings -> Actions -> General -> Workflow permissions**: Read and write.
6. **Actions tab**: run `scan` first (creates the baseline), then `pulse`, then `briefing`.
   (The first pulse only seeds data and sends no alerts, so you aren't flooded with old news.)
7. **App**: share.streamlit.io -> your repo -> `app.py`; in Secrets paste
   `GITHUB_REPO = "you/repo"` and `GEMINI_API_KEY = "..."`. Add the link to your phone's home screen.

## How a recommendation is made
A stock is "hot" when it moves more than 2x its daily ATR (pre-market and after-hours included), when its volume runs
3x ahead of normal pace, or when it breaks its 20-day high on volume in an uptrend. Then the agent pulls fresh news,
fresh SEC 8-Ks and social chatter for that stock only, computes entry/stop/target in Python (the LLM never invents
prices), and asks Gemini for one of: **consider long / wait for pullback / watch / avoid**, with conviction 1-5, a reason,
the main risk, and what would invalidate it. Without an LLM key it falls back to transparent rules.
Each stock gets at most one recommendation per 2 hours unless new 5/5 news arrives.

## X (Twitter) - optional and NOT free
X has no free read tier any more: pay-per-use, about $0.005 per post read. The agent only queries X for stocks that are
already moving, 10 posts per query (~$0.05), with a hard cap of 200 posts/day (~$1/day max, usually far less).
To enable: buy credits at the X developer console, add secret `X_BEARER_TOKEN`, set `social.x.enabled: true`.
Free alternative that is on by default: StockTwits public stream (unofficial; GitHub's servers are sometimes blocked, in which case it is skipped).
Social chatter is noisy and easy to manipulate. It only adds context to the recommendation; it never triggers one.

## Speed, honestly
- GitHub cron: every 5 min in theory, 5-15 min of lag in practice (GitHub delays scheduled jobs under load). Fine for swing trading.
- Turbo mode: run `python -m agent.run_loop` on any always-on machine (Oracle Cloud Always Free VM, Raspberry Pi).
  It pulses every 60 s. See `deploy/swing-agent.service`. Alerts then arrive about 1-2 min after a move.
  The data source is still Yahoo (delayed up to ~15 min on some tickers), so "real-time" is not on offer for free.
- Early-warning trick: price moves are the fastest signal (news sites lag), so the pulse starts from prices, not headlines.

## Keep it alive for 3 years
GitHub pauses scheduled workflows after ~60 days without repo activity; `keepalive.yml` commits monthly to prevent it.
Check the Actions tab once a month anyway. If Yahoo's library breaks, bump the `yfinance` version.

## Limits
Free data is delayed and sometimes wrong. Setups are simple rules, backtests are small samples, the probability cone is a
range not a forecast, free LLM quotas change (the agent caps its own usage). Not financial advice.
