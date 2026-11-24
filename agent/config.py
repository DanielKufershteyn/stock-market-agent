import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_config():
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def all_tickers(cfg):
    out = []
    for ts in cfg["watchlist"].values():
        for t in ts:
            if t not in out:
                out.append(t)
    return out


def group_map(cfg):
    m = {}
    for g, ts in cfg["watchlist"].items():
        for t in ts:
            m.setdefault(t, g)
    return m
