import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))


def _default(o):
    return o.item() if hasattr(o, "item") else str(o)


def load(name, default):
    try:
        return json.loads((DATA_DIR / name).read_text())
    except Exception:
        return default


def save(name, obj):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / name).write_text(json.dumps(obj, indent=1, default=_default))
