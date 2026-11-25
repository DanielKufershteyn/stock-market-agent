import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from agent import backtest as B, data as D, forecast as F, llm, recommend as R, screener as S, tradeplan as TP
from agent.config import all_tickers, group_map, load_config
from agent.levels import bt_kwargs

st.set_page_config(page_title="Swing Agent", page_icon="📈", layout="wide")
cfg = load_config()
tickers, groups = all_tickers(cfg), group_map(cfg)
bench, tc = cfg.get("benchmark", "SPY"), cfg["trade"]


def secret(name, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


REPO, GH_TOKEN = secret("GITHUB_REPO"), secret("GITHUB_TOKEN")
if secret("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = secret("GEMINI_API_KEY")


@st.cache_data(ttl=120)
def remote(name):
    if not REPO:
        return None
    h = {"Authorization": f"token {GH_TOKEN}"} if GH_TOKEN else {}
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{REPO}/data/{name}", headers=h, timeout=15)
        return r.json() if r.ok else None
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner="Pulling live prices...")
def live_frames():
    return D.get_many(tickers + [bench], period="3y")


PRESETS = {
    "Tight: stop 1.5 ATR, target 3 ATR, 10 days": dict(atr_stop=1.5, atr_tgt=3.0, max_hold=10),
    "Wider ATR: stop 2.5, target 5 ATR, 20 days": dict(atr_stop=2.5, atr_tgt=5.0, max_hold=20),
    "Target +15%, stop 5%, 40 days": dict(atr_stop=1.5, stop_pct=5, tgt_pct=15, max_hold=40),
    "Target +20%, stop 6%, 40 days": dict(atr_stop=1.5, stop_pct=6, tgt_pct=20, max_hold=40),
    "Target +25%, stop 8%, 60 days": dict(atr_stop=1.5, stop_pct=8, tgt_pct=25, max_hold=60),
}


@st.cache_data(ttl=3600, show_spinner="Backtesting every stock in the watchlist...")
def explore(setup, label, _frames):
    trades = []
    for t, df in _frames.items():
        if t not in groups:
            continue
        d = S.analyze(df)
        if d is None:
            continue
        tr = B.run_backtest(d, S.SETUPS[setup](d), cost=tc["cost_pct"], **PRESETS[label])
        if len(tr):
            trades.append(tr)
    if not trades:
        return {"n": 0}
    allt = pd.concat(trades, ignore_index=True)
    out = B.summarize(allt)
    out.pop("max_dd_pct", None)                    # meaningless when trades of different stocks are mixed
    for k in ("target", "stop", "time"):
        out[f"exit_{k}_%"] = round(100 * float((allt.reason == k).mean()), 1)
    return out


@st.cache_data(ttl=300, show_spinner="Scanning the watchlist live...")
def live_scan():
    fr = live_frames()
    return S.scan(fr, cfg, groups, fr.get(bench))


# ---------- sidebar ----------
st.sidebar.title("📈 Swing Agent")
account = st.sidebar.number_input("Account size ($)", 100, 10_000_000, 5000, step=500)
risk_pct = st.sidebar.slider("Risk per trade (%)", 0.25, 3.0, 1.0, 0.25)
max_pos = st.sidebar.slider("Max position size (% of account)", 5, 100, 25, 5)
if st.sidebar.button("🔄 Refresh now (live)"):
    st.cache_data.clear()
    st.session_state["force_live"] = True
if st.sidebar.button("Use agent data again"):
    st.session_state["force_live"] = False
force_live = st.session_state.get("force_live", False)

status = remote("status.json")
live_data, recs_data = remote("live.json"), remote("recs.json")
if status:
    st.sidebar.caption(f"Last pulse: {status['updated'][11:16]} UTC ({status['phase']})")
sig_remote, snap_remote = remote("signals.json"), remote("snapshot.json")
use_remote = bool(sig_remote) and not force_live
if use_remote:
    signals, snapshot = sig_remote["signals"], snap_remote["tickers"] if snap_remote else {}
    st.caption(f"Agent data, last update {sig_remote['updated']} UTC. "
               f"{'AI scoring on' if (status or {}).get('llm') else 'rule-based scoring (no LLM key)'}")
else:
    signals, snapshot = live_scan()
    st.caption("Live scan computed just now from Yahoo Finance (15-20 min delayed).")

tab0, tab1, tab2, tab3, tab4 = st.tabs(["⚡ Live", "🎯 Setups", "📰 News", "🗞 Briefing", "🔍 Deep dive"])

# ---------- live: recommendations + movers ----------
with tab0:
    if not (recs_data and live_data):
        st.info("No live data yet. Run the scan, then the pulse workflow once on GitHub, "
                "and set GITHUB_REPO in the app secrets.")
    else:
        st.caption(f"Pulse updated {live_data['updated']} UTC | market phase: {live_data['phase']}")
        st.subheader("Recommendations")
        shown = [r for r in recs_data["recs"] if r["action"] != "watch"][:15] or recs_data["recs"][:5]
        if not shown:
            st.write("Nothing actionable right now.")
        for r in shown:
            lv = r["levels"]
            ps = TP.position_size(lv["entry"], lv["stop"], account, risk_pct, max_pos)
            head = f"{R.ICON[r['action']]} **{r['ticker']}** | {R.LABEL[r['action']]} | conviction {r['conviction']}/5 | ${r['price']} ({r['move_pct']:+.1f}%) | {r['time'][11:16]} UTC"
            with st.expander(head, expanded=(r is shown[0])):
                st.write(r["why"])
                if r["action"] == "consider_long":
                    c = st.columns(5)
                    c[0].metric("Entry", lv["entry"]); c[1].metric("Stop", lv["stop"]); c[2].metric("Target", lv["target"])
                    c[3].metric("Shares", ps["shares"]); c[4].metric("Risk $", ps["risk_usd"])
                elif r["action"] == "wait_for_pullback":
                    st.write(f"Better entry zone: **{lv['pullback_zone'][0]} - {lv['pullback_zone'][1]}**")
                st.caption(f"Risk: {r['risk']}  |  Invalid if: {r['invalidation']}  |  by {r['source']}  |  trigger: {', '.join(r.get('trigger', []))}")
                for n in r["news"]:
                    st.markdown(f"- [{n['title']}]({n['link']}) ({n.get('importance')}/5)")
                soc = r.get("social") or {}
                if soc.get("stocktwits"):
                    stw = soc["stocktwits"]
                    st.caption(f"StockTwits: {stw['bullish']} bullish / {stw['bearish']} bearish, {stw['last_hour']} msgs in the last hour")
                if soc.get("x"):
                    for p in soc["x"]["top"]:
                        st.caption(f"X: {p['text']}")
        st.subheader("Biggest movers vs previous close")
        mv = pd.DataFrame(live_data["tickers"]).T
        if len(mv):
            mv["hot"] = [", ".join(live_data["hot"].get(t, [])) for t in mv.index]
            mv = mv[["price", "move_pct", "move_atr", "vol_pace", "hot"]]
            st.dataframe(mv.reindex(mv.move_atr.abs().sort_values(ascending=False).index).head(25), use_container_width=True)

# ---------- opportunities ----------
with tab1:
    if snapshot:
        n_set = len({x["ticker"] for x in signals})
        st.caption(f"{n_set} of {len(snapshot)} watchlist stocks have an active buy setup right now. "
                   f"The agent is a scanner, not an opinion on every stock: most stocks will say 'no signal' on most days.")
    if not signals:
        st.info("No setups right now. That's normal; in weak markets the screener should stay quiet.")
    for s in signals:
        p = s["plan"]
        ps = TP.position_size(p["entry"], p["stop"], account, risk_pct, max_pos)
        a = (s.get("backtest") or {}).get("all", {})
        hist = f" | history: {a['n']} trades, {a['win_rate']}% wins" if a.get("n") else ""
        with st.expander(f"**{s['ticker']}**  {s['setup']}  | score {s['score']} | ${s['close']}{hist}"):
            st.write(s["desc"])
            c = st.columns(5)
            c[0].metric("Entry zone", f"{p['entry_zone'][0]} - {p['entry_zone'][1]}")
            c[1].metric("Stop", p["stop"])
            c[2].metric("Target", p["target"])
            c[3].metric("Shares", ps["shares"])
            c[4].metric("Risk $", ps["risk_usd"])
            st.caption(f"R/R {p['rr']} | stop -{p['stop_pct']}% | target +{p['target_pct']}% | time stop {p['max_hold_days']} days | RSI {s['rsi']} | "
                       f"volume {s['vol_ratio']}x | vs {bench} (3m) {s['rel_strength_3m']:+.1f}%")
            bt = s.get("backtest")
            if bt and bt["all"].get("n"):
                st.dataframe(pd.DataFrame(bt).T.rename(index={"all": "All", "in": "First 70%", "out": "Latest 30%"}))
                st.caption("Same fixed rules on this stock's past. Small samples are noisy, and the past isn't a promise.")
    if snapshot:
        st.subheader("Watchlist overview")
        df = pd.DataFrame(snapshot).T
        df = df[["group", "close", "change_pct", "rsi", "vol_ratio", "rel_strength_3m", "trend"]]
        sel = st.multiselect("Sectors", sorted(df.group.unique()))
        if sel:
            df = df[df.group.isin(sel)]
        st.dataframe(df.sort_values("change_pct", ascending=False), use_container_width=True)

# ---------- news ----------
with tab2:
    news = remote("news.json")
    if not news:
        st.info("No news data yet. Run the 'collect' workflow on GitHub once, and set GITHUB_REPO in the app secrets.")
    else:
        c1, c2 = st.columns(2)
        min_imp = c1.slider("Minimum importance", 1, 5, 3)
        only = c2.multiselect("Tickers", sorted({i["ticker"] for i in news["items"]}))
        icons = {5: "🚨", 4: "🔴", 3: "🟡", 2: "⚪", 1: "⚪"}
        for i in news["items"]:
            if i.get("importance", 0) < min_imp or (only and i["ticker"] not in only):
                continue
            st.markdown(f"{icons.get(i['importance'], '⚪')} **{i['ticker']}** ({i['importance']}/5, {i.get('sentiment', '')}) "
                        f"[{i['title']}]({i['link']})  \n<small>{i['published'][:16]} UTC | {i['source']} | {i.get('why', '')}</small>",
                        unsafe_allow_html=True)

# ---------- briefing ----------
with tab3:
    br = remote("briefing.json")
    if br:
        st.caption(f"Generated {br['updated']} UTC")
        st.text(br["text"])
    else:
        st.info("No briefing yet. It's created daily after the US close.")

# ---------- deep dive ----------
with tab4:
    c1, c2, c3 = st.columns([2, 2, 1])
    pick = c1.selectbox("Watchlist ticker", tickers)
    custom = c2.text_input("...or any US ticker").strip().upper()
    horizon = c3.selectbox("Cone (trading days)", [5, 10], index=1)
    t = custom or pick
    df = D.get_history(t, "3y") if custom else live_frames().get(t)
    d = S.analyze(D.drop_partial(df))      # completed days only, same as the scan
    if d is None:
        st.warning(f"Not enough data for {t}.")
    else:
        plan = TP.make_plan(d, tc)
        cone = F.cone(d.Close, horizon=horizon)
        last = float(d.Close.iloc[-1])
        v = d.iloc[-120:]
        fig = go.Figure(go.Candlestick(x=v.index, open=v.Open, high=v.High, low=v.Low, close=v.Close, name="Price"))
        for col, color in [("SMA20", "#f5a623"), ("SMA50", "#4a90e2"), ("SMA200", "#9b59b6")]:
            fig.add_scatter(x=v.index, y=v[col], name=col, line=dict(width=1, color=color))
        x = [d.index[-1]] + list(pd.bdate_range(d.index[-1] + pd.Timedelta(days=1), periods=horizon))
        for lo, hi, alpha, nm in [("p5", "p95", 0.12, "90% range"), ("p16", "p84", 0.25, "68% range")]:
            fig.add_scatter(x=x, y=[last] + cone[hi], line=dict(width=0), showlegend=False, hoverinfo="skip")
            fig.add_scatter(x=x, y=[last] + cone[lo], fill="tonexty", name=nm, line=dict(width=0),
                            fillcolor=f"rgba(80,160,255,{alpha})")
        fig.add_scatter(x=x, y=[last] + cone["p50"], name="median path", line=dict(dash="dot", color="gray"))
        fig.add_hline(y=plan["stop"], line_dash="dash", line_color="red", annotation_text="stop")
        fig.add_hline(y=plan["target"], line_dash="dash", line_color="green", annotation_text="target")
        fig.update_layout(xaxis_rangeslider_visible=False, height=560, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"The shaded cone is a Monte Carlo range from this stock's own recent volatility, not a prediction. "
                   f"Chance of finishing {horizon} days higher: {cone['prob_up'] * 100:.0f}% (zero-drift model).")

        vd = S.verdict(d, tc)
        ps = TP.position_size(plan["entry"], plan["stop"], account, risk_pct, max_pos)
        if vd["state"] == "buy":
            st.success(f"✅ Buy setup active on {t}: {', '.join(vd['active'])}. Reward/risk {plan['rr']}. "
                       f"Position size below uses your account and risk settings.")
        elif vd["state"] == "low_rr":
            st.warning(f"⚠️ A setup is active ({', '.join(vd['active'])}) but the stop would be {plan['stop_pct']}% away "
                       f"for a {plan['target_pct']}% target (reward/risk {plan['rr']}). Too volatile: skip it.")
        else:
            st.error(f"⛔ No buy signal on {t}. Trend: {vd['trend']}. "
                     f"The numbers below are only a what-if calculator, not a recommendation.")
        if vd["state"] != "buy":
            with st.expander("What would make this a buy signal?"):
                for line in S.triggers(d):
                    st.write("• " + line)
        what_if = "" if vd["state"] == "buy" else "What-if: "
        m = st.columns(6)
        m[0].metric("Price", f"{last:.2f}")
        m[1].metric("RSI", f"{d.RSI.iloc[-1]:.0f}")
        m[2].metric("ATR (daily range)", f"{plan['atr']} ({plan['atr'] / last * 100:.1f}%)")
        m[3].metric(f"{what_if}Stop", f"{plan['stop']} (-{plan['stop_pct']}%)")
        m[4].metric(f"{what_if}Target", f"{plan['target']} (+{plan['target_pct']}%)")
        m[5].metric(f"{what_if}Shares", ps["shares"])
        st.caption(f"Position about ${ps['position_value']:,.0f} of your ${account:,.0f}, risking about ${ps['risk_usd']:,.0f} "
                   f"if the stop is hit (capped at {max_pos}% of the account per position). Reward/risk {plan['rr']}.")

        st.subheader("Backtest of each setup on this stock")
        rows = []
        for name, fn in S.SETUPS.items():
            res, _ = B.backtest_split(d, fn(d), **bt_kwargs(tc))
            for part, label in [("all", "All"), ("in", "First 70%"), ("out", "Latest 30%")]:
                rows.append({"setup": name, "period": label, **res[part]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        active = vd["active"]
        st.write("Active setups right now: " + (", ".join(active) if active else "none"))

        st.subheader("🎯 Target explorer: what do bigger targets really do?")
        st.caption("Tests each setting on EVERY stock in the watchlist (about 3 years of daily data), so the sample is "
                   "much bigger than one stock. Costs included. Past results are not a promise.")
        ex_setup = st.selectbox("Setup to test", list(S.SETUPS), key="ex_setup")
        if st.button("Run the comparison"):
            rows = []
            for label in PRESETS:
                rows.append({"settings": label, **explore(ex_setup, label, live_frames())})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption("Read it like this: win_rate is the share of winners; avg_r is the average result in units of risk "
                       "(above 0 = profitable after costs); exit_target_% is how often the target was actually reached.")

        if st.button("🤖 AI take on this ticker"):
            if not llm.available():
                st.warning("Add GEMINI_API_KEY to the app secrets to enable this.")
            else:
                n = remote("news.json") or {"items": []}
                heads = "\n".join(f"- {i['title']}" for i in n["items"] if i["ticker"] == t)[:1500]
                ctx = (f"Ticker {t}. Close {last:.2f}, RSI {d.RSI.iloc[-1]:.0f}, ATR {plan['atr']}, "
                       f"SMA20 {d.SMA20.iloc[-1]:.2f}, SMA50 {d.SMA50.iloc[-1]:.2f}, SMA200 {d.SMA200.iloc[-1]:.2f}. "
                       f"Active setups: {active or 'none'}. Stop {plan['stop']}, target {plan['target']}.\n"
                       f"Recent headlines:\n{heads or 'none'}")
                with st.spinner("Thinking..."):
                    try:
                        st.write(llm.analyze_ticker(ctx))
                    except Exception as e:
                        st.error(f"LLM error: {e}")

st.divider()
st.caption("Research tool only, not financial advice. Free data is delayed and can be wrong. You decide and you carry the risk.")
