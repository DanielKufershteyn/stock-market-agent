import numpy as np


def cone(close, horizon=10, sims=5000, lookback=252, zero_drift=True, seed=7):
    """Bootstrap Monte Carlo of daily log returns. It shows a RANGE of plausible
    outcomes, not a prediction. Zero drift by default so it doesn't extrapolate trends."""
    r = np.log(close / close.shift(1)).dropna().values[-lookback:]
    if zero_drift:
        r = r - r.mean()
    rng = np.random.default_rng(seed)
    paths = float(close.iloc[-1]) * np.exp(np.cumsum(rng.choice(r, size=(sims, horizon)), axis=1))
    qs = [5, 16, 50, 84, 95]
    pct = np.percentile(paths, qs, axis=0)
    res = {f"p{q}": [float(x) for x in pct[i]] for i, q in enumerate(qs)}
    res["prob_up"] = float((paths[:, -1] > close.iloc[-1]).mean())
    return res
