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
    if log.isEnabledFor(logging.DEBUG):
        log.debug("parsed row %s", json.dumps(row, sort_keys=True))
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
        seen = r.setdefault("_seen", set())
        r["events"] += 1
        if e["user_id"] not in seen:
            seen.add(e["user_id"])
            r["users"].append(e["user_id"])
        if e["kind"] == "purchase":
            r["revenue_cents"] += e["amount_cents"]
        elif e["kind"] == "refund":
            r["revenue_cents"] -= e["amount_cents"]
            r["refunds"] += 1
    for r in by_region.values():
        r.pop("_seen", None)
    return by_region


def format_report(by_region):
    out = "region,events,unique_users,revenue,refunds\n"
    for region in sorted(by_region):
        r = by_region[region]
        out += f"{region},{r['events']},{len(r['users'])},{r['revenue_cents'] / 100:.2f},{r['refunds']}\n"
    return out


def build_report(path, lookup_path="data/regions.json"):
    """One streaming pass: every row is validated in file order (same errors, raised before the lookup file is read),
    duplicates are dropped (first occurrence wins), and totals are kept per region code; codes are mapped to names
    afterwards, merging codes that share a name (e.g. all unknown codes become "Unknown") in first-seen order."""
    seen = set()
    per_code = {}                 # code -> [events, users(list), users_seen(set), revenue, refunds], first-seen order
    with open(path, encoding="utf-8") as f:
        validate_header(f.readline())
        for line in f:
            if not line.strip():
                continue
            e = parse_line(line)
            if e["event_id"] in seen:
                continue
            seen.add(e["event_id"])
            c = per_code.get(e["region_code"])
            if c is None:
                c = per_code[e["region_code"]] = [0, [], set(), 0, 0]
            c[0] += 1
            if e["user_id"] not in c[2]:
                c[2].add(e["user_id"])
                c[1].append(e["user_id"])
            if e["kind"] == "purchase":
                c[3] += e["amount_cents"]
            elif e["kind"] == "refund":
                c[3] -= e["amount_cents"]
                c[4] += 1
    if not per_code:
        return format_report({})
    with open(lookup_path, encoding="utf-8") as f:
        regions = json.load(f)
    by_region = {}
    for code, (n, users, _, rev, refunds) in per_code.items():
        name = regions.get(code, "Unknown")
        r = by_region.setdefault(name, {"events": 0, "users": [], "_seen": set(), "revenue_cents": 0, "refunds": 0})
        r["events"] += n
        for u in users:
            if u not in r["_seen"]:
                r["_seen"].add(u)
                r["users"].append(u)
        r["revenue_cents"] += rev
        r["refunds"] += refunds
    return format_report(by_region)
