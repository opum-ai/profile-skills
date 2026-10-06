"""Build the nightly event report.

Input: CSV with header `event_id,user_id,region_code,kind,amount_cents,ts`.
Events can be delivered more than once (at-least-once queue); duplicates share an event_id
and must be counted once, keeping the first occurrence.
"""
import json
import logging
import re

log = logging.getLogger("reportgen")

KINDS = ("purchase", "refund", "signup", "view")
_HEADER = "event_id,user_id,region_code,kind,amount_cents,ts"


def validate_header(line):
    # Called once per file.
    pattern = re.compile(r"^" + re.escape(_HEADER) + r"$")
    if not pattern.match(line.strip()):
        raise ValueError(f"unexpected header: {line.strip()!r}")


def parse_line(line):
    parts = line.rstrip("\n").split(",")
    if len(parts) != 6:
        raise ValueError(f"malformed row: {line!r}")
    event_id, user_id, region_code, kind, amount, ts = parts
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    row = {
        "event_id": event_id,
        "user_id": user_id,
        "region_code": region_code,
        "kind": kind,
        "amount_cents": int(amount),
        "ts": int(ts),
    }
    log.debug(f"parsed row {json.dumps(row, sort_keys=True)}")
    return row


def load_events(path):
    with open(path, encoding="utf-8") as f:
        validate_header(f.readline())
        return [parse_line(line) for line in f if line.strip()]


def dedupe(events):
    seen = set()
    out = []
    for e in events:
        if e["event_id"] not in seen:
            seen.add(e["event_id"])
            out.append(e)
    return out


def region_name(code, lookup_path):
    with open(lookup_path, encoding="utf-8") as f:
        regions = json.load(f)
    return regions.get(code, "Unknown")


def enrich(events, lookup_path):
    if not events:
        return events
    with open(lookup_path, encoding="utf-8") as f:
        regions = json.load(f)
    for e in events:
        e["region"] = regions.get(e["region_code"], "Unknown")
    return events


def summarize(events):
    by_region = {}
    for e in events:
        r = by_region.setdefault(e["region"], {"events": 0, "users": [], "revenue_cents": 0, "refunds": 0})
        r["events"] += 1
        s = r.setdefault("_s", set())
        if e["user_id"] not in s:
            s.add(e["user_id"])
            r["users"].append(e["user_id"])
        if e["kind"] == "purchase":
            r["revenue_cents"] += e["amount_cents"]
        elif e["kind"] == "refund":
            r["revenue_cents"] -= e["amount_cents"]
            r["refunds"] += 1
    return by_region


def format_report(by_region):
    out = "region,events,unique_users,revenue,refunds\n"
    for region in sorted(by_region):
        r = by_region[region]
        out += f"{region},{r['events']},{len(r['users'])},{r['revenue_cents'] / 100:.2f},{r['refunds']}\n"
    return out


def build_report(path, lookup_path="data/regions.json"):
    events = load_events(path)
    events = dedupe(events)
    events = enrich(events, lookup_path)
    return format_report(summarize(events))
