"""TURBO MODE for an always-on machine (e.g. Oracle Cloud Always Free VM, a Raspberry Pi, an old PC).
Runs the same pulse every ~60 s during extended hours, and the heavy scan 3x per trading day.
Optionally publishes to the `data` branch every 5 min so the Streamlit app stays current."""
import datetime as dt
import os
import subprocess
import time
import traceback

from . import run_pulse, run_scan
from .data import market_phase

SCAN_TIMES = ("12:30", "17:30", "21:30")     # UTC, same as the GitHub schedule
OWNED = ["news.json", "live.json", "recs.json", "state.json", "status.json", "cik_map.json",
         "signals.json", "snapshot.json", "state_scan.json", "status_scan.json"]


def publish():
    if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        subprocess.run(["bash", "scripts/publish.sh", *OWNED], check=False)


def main():
    every = int(os.environ.get("PULSE_SECONDS", "60"))
    done, last_pub = set(), 0.0
    while True:
        t0 = time.time()
        now = dt.datetime.now(dt.timezone.utc)
        try:
            for hhmm in SCAN_TIMES:
                key = (now.date(), hhmm)
                if now.weekday() < 5 and now.strftime("%H:%M") >= hhmm and key not in done:
                    done.add(key)
                    run_scan.main()
            if market_phase() != "closed" or int(t0) % 1800 < every:
                run_pulse.main()
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            traceback.print_exc()
        if time.time() - last_pub > 300:
            publish()
            last_pub = time.time()
        time.sleep(max(5, every - (time.time() - t0)))


if __name__ == "__main__":
    main()
