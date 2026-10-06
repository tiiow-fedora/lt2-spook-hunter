#!/usr/bin/env python3
"""LT2 server age tracker.

Roblox's public server list has no age field, so this records when each server id was
FIRST SEEN. A server that has stayed in the list for N hours is at least N hours old.
Run it from cron every ~10 minutes; it needs no dependencies.

Files (next to this script):
  state.json  - {"tracking_since": epoch, "servers": {id: {"first": epoch, "last": epoch}}}
  alive.json  - servers seen on the latest poll, oldest first, with age_hours_min
Caveat: servers that already existed when tracking began get first_seen = tracking start,
so their age_hours_min is a lower bound that only becomes useful after hours of tracking.

Usage:  python3 lt2_tracker.py            # poll once and update the files
        python3 lt2_tracker.py --summary  # print a short summary of alive.json
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

PLACE_ID = 13822889
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")
ALIVE = os.path.join(HERE, "alive.json")
URL = "https://games.roblox.com/v1/games/%d/servers/Public?sortOrder=Asc&limit=100" % PLACE_ID
MAX_PAGES = 40            # ~4000 servers is far more than LT2 has
PAGE_DELAY = 2.0          # seconds between pages; the API rate-limits (HTTP 429)
PRUNE_AFTER = 3 * 3600    # forget a server after it has been missing this long


def fetch_page(cursor):
    url = URL + ("&cursor=" + cursor if cursor else "")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (lt2-tracker)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def poll():
    servers, cursor = [], None
    for page in range(MAX_PAGES):
        for attempt in range(4):
            try:
                data = fetch_page(cursor)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    time.sleep(20 * (attempt + 1))
                    continue
                print("poll stopped on HTTP %s after %d servers" % (e.code, len(servers)))
                return servers, False
            except Exception as e:
                print("poll stopped on %r after %d servers" % (e, len(servers)))
                return servers, False
        servers.extend(data.get("data", []))
        cursor = data.get("nextPageCursor")
        if not cursor:
            return servers, True
        time.sleep(PAGE_DELAY)
    return servers, True


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {"tracking_since": time.time(), "servers": {}}


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def update():
    now = time.time()
    state = load_state()
    seen, complete = poll()
    if not seen:
        print("no servers fetched; state unchanged")
        return 1
    known = state["servers"]
    for s in seen:
        rec = known.setdefault(s["id"], {"first": now, "last": now})
        rec["last"] = now
    # Only prune after a COMPLETE poll, so a partial one can't make live servers look new.
    if complete:
        for sid in [k for k, v in known.items() if now - v["last"] > PRUNE_AFTER]:
            del known[sid]
    alive = []
    for s in seen:
        rec = known[s["id"]]
        alive.append({
            "id": s["id"],
            "playing": s.get("playing"),
            "max": s.get("maxPlayers"),
            "first_seen": int(rec["first"]),
            "age_hours_min": round(max(0.0, now - rec["first"]) / 3600.0, 2),
        })
    alive.sort(key=lambda a: -a["age_hours_min"])
    save_json(STATE, state)
    save_json(ALIVE, {
        "updated": int(now),
        "tracking_since": int(state["tracking_since"]),
        "tracking_hours": round(max(0.0, now - state["tracking_since"]) / 3600.0, 2),
        "complete_poll": complete,
        "servers": alive,
    })
    print("%s polled %d servers (complete=%s), tracking %.1fh, oldest seen %.1fh" % (
        time.strftime("%Y-%m-%d %H:%M:%S"), len(seen), complete,
        max(0.0, now - state["tracking_since"]) / 3600.0, alive[0]["age_hours_min"]))
    return 0


def summary():
    with open(ALIVE) as f:
        a = json.load(f)
    ages = [s["age_hours_min"] for s in a["servers"]]
    print("tracking %.1fh, %d servers alive" % (a["tracking_hours"], len(ages)))
    for h in (1, 3, 6, 9, 12):
        print("  >= %2dh: %d" % (h, sum(1 for x in ages if x >= h)))


if __name__ == "__main__":
    sys.exit(summary() or 0 if "--summary" in sys.argv else update())
