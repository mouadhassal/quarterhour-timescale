"""Download Nord Pool day-ahead prices for EE, FI, LV and LT from Elering's open API (EUR/MWh).

    python data/fetch.py            # writes data/prices.csv (UTC timestamps, 15-minute resolution)

Elering publishes these on dashboard.elering.ee as open data. The day-ahead market moved
to 15-minute products on 1 October 2025; the window below starts there.
"""
import csv
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

START = datetime(2025, 10, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 1, tzinfo=timezone.utc)
ZONES = ["ee", "fi", "lv", "lt"]
OUT = Path(__file__).parent / "prices.csv"


def get(a, b):
    url = ("https://dashboard.elering.ee/api/nps/price?start="
           f"{a:%Y-%m-%dT%H:%M:%S.000Z}&end={b:%Y-%m-%dT%H:%M:%S.000Z}")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)["data"]
        except Exception:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(url)


def main():
    rows = {}
    a = START
    while a < END:
        b = min(a + timedelta(days=10), END)
        d = get(a, b - timedelta(seconds=1))
        for z in ZONES:
            for x in d.get(z, []):
                rows.setdefault(x["timestamp"], {})[z] = x["price"]
        a = b
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_utc", *ZONES])
        for ts in sorted(rows):
            w.writerow([ts, *[rows[ts].get(z, "") for z in ZONES]])
    print(f"{len(rows)} quarter-hours -> {OUT}")


if __name__ == "__main__":
    main()
