import os
import subprocess
import sys

import pytest

from reportgen.report import build_report, dedupe, parse_line, summarize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def write(tmp_path, rows):
    p = tmp_path / "e.csv"
    p.write_text("event_id,user_id,region_code,kind,amount_cents,ts\n" + "".join(r + "\n" for r in rows))
    return str(p)


def lookup():
    return os.path.join(ROOT, "data", "regions.json")


def test_duplicates_counted_once_first_wins(tmp_path):
    p = write(tmp_path, ["e1,u1,us-east,purchase,1000,1", "e1,u1,us-east,purchase,1000,1", "e2,u2,us-east,refund,300,2"])
    assert build_report(p, lookup()) == "region,events,unique_users,revenue,refunds\nUS East,2,2,7.00,1\n"


def test_unknown_region(tmp_path):
    p = write(tmp_path, ["e1,u1,zz-nowhere,view,0,1"])
    assert "Unknown,1,1,0.00,0" in build_report(p, lookup())


def test_regions_sorted(tmp_path):
    p = write(tmp_path, ["e1,u1,us-west,view,0,1", "e2,u1,eu-west,view,0,2"])
    lines = build_report(p, lookup()).splitlines()[1:]
    assert [l.split(",")[0] for l in lines] == ["EU West", "US West"]


@pytest.mark.parametrize("row", ["e1,u1,us-east,purchase,10", "e1,u1,us-east,bogus,1,1", "e1,u1,us-east,purchase,x,1"])
def test_malformed_rows_raise(row):
    with pytest.raises(ValueError):
        parse_line(row)


def test_bad_header(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("id,user\n")
    with pytest.raises(ValueError):
        build_report(str(p), lookup())


def test_dedupe_keeps_order():
    evs = [{"event_id": i} for i in ["b", "a", "b", "c", "a"]]
    assert [e["event_id"] for e in dedupe(evs)] == ["b", "a", "c"]


def test_cli_matches_function():
    out = subprocess.run([sys.executable, "-m", "reportgen", "data/events.csv"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert out == build_report(os.path.join(ROOT, "data", "events.csv"), lookup())
