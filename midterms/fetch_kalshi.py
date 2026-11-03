#!/usr/bin/env python3
"""Pull Kalshi midterm odds into midterms/kalshi.json.

Kalshi's public API refuses browser requests (any request carrying an Origin
header gets a 403) and rate-limits hard, so this runs server-side on a GitHub
Actions schedule and the page reads the committed JSON over raw.githubusercontent.
"""
import json, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = "https://api.elections.kalshi.com/trade-api/v2/markets?limit=20&event_ticker="
OUT = sys.argv[1] if len(sys.argv) > 1 else "midterms/kalshi.json"

EVENTS = [
    "CONTROLS-2026", "CONTROLH-2026", "KXBALANCEPOWERCOMBO-27FEB",
    # Senate races
    "SENATETX-26", "SENATEME-26", "SENATEOHS-26", "SENATENC-26", "SENATEIA-26",
    "SENATEAK-26", "SENATEKS-26", "SENATENE-26", "SENATESC-26", "SENATEMI-26",
    "SENATEGA-26", "SENATENH-26", "SENATEMN-26", "SENATEFL-26", "SENATEMS-26",
    "SENATELA-26", "SENATEMT-26",
    # Governor races (party markets)
    "GOVPARTYGA-26", "GOVPARTYKS-26", "GOVPARTYNV-26", "GOVPARTYFL-26",
    "GOVPARTYTX-26", "GOVPARTYVT-26", "GOVPARTYAK-26", "GOVPARTYOH-26",
    "GOVPARTYIA-26", "GOVPARTYWI-26", "GOVPARTYAZ-26", "GOVPARTYMI-26",
    "GOVPARTYOR-26", "GOVPARTYNH-26", "GOVPARTYNE-26", "GOVPARTYOK-26",
]

def get(url, tries=4):
    wait = 8
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                d = json.load(r)
            if "error" in d and d["error"].get("code") == "too_many_requests":
                raise urllib.error.HTTPError(url, 429, "rate limited", {}, None)
            return d
        except urllib.error.HTTPError as e:
            if e.code in (429, 403) and i < tries - 1:
                time.sleep(wait); wait *= 2; continue
            print(f"  fail {url}: {e}", file=sys.stderr); return None
        except Exception as e:
            print(f"  fail {url}: {e}", file=sys.stderr)
            if i < tries - 1: time.sleep(wait); wait *= 2; continue
            return None

def f(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def mid(m):
    b, a = f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars"))
    if b is not None and a is not None and a > 0: return round((a + b) / 2, 4)
    return f(m.get("last_price_dollars"))

# Keep what was there before so a rate-limited run degrades gracefully.
try:
    prev = json.load(open(OUT))
except Exception:
    prev = {"events": {}}
out = {"source": "Kalshi public API", "fetched_at": None, "events": dict(prev.get("events", {}))}

for ev in EVENTS:
    d = get(BASE + ev)
    time.sleep(6)  # unauthenticated rate limit is strict
    if not d or not d.get("markets"):
        continue
    out["events"][ev] = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "markets": [{
            "ticker": m["ticker"],
            "label": m.get("yes_sub_title") or m.get("title"),
            "mid": mid(m),
            "last": f(m.get("last_price_dollars")),
            "bid": f(m.get("yes_bid_dollars")),
            "ask": f(m.get("yes_ask_dollars")),
            "volume": f(m.get("volume_fp")),
            "status": m.get("status"),
        } for m in d["markets"]],
    }
    print(f"ok {ev}: " + ", ".join(f"{m['ticker'].split('-')[-1]}={mid(m)}" for m in d["markets"]))

out["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
json.dump(out, open(OUT, "w"), indent=1)
print(f"wrote {OUT} with {len(out['events'])} events")
