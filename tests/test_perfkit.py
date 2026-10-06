"""perfkit engine tests: statistics, format loaders, profile normalisation, ledger, gate.

Each test protects a behavior the skills rely on; expected values come from hand
calculation or textbook results, never from running perfkit.
"""
import json
import os
import random
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "perf-measure", "scripts")
sys.path.insert(0, SCRIPTS)

from perfkit import ledger, loaders, policy, profiles, stats  # noqa: E402

PK = os.path.join(SCRIPTS, "perfkit.py")


# ---------------------------------------------------------------- statistics

@pytest.mark.parametrize("xs,q,expected", [
    ([1, 2, 3, 4], 0.5, 2.5),
    ([1, 2, 3, 4], 0.25, 1.75),          # numpy type-7 interpolation
    ([5], 0.9, 5.0),
    ([3, 1, 2], 1.0, 3.0),
], ids=["median-even", "q1-interp", "single", "max"])
def test_quantile(xs, q, expected):
    assert stats.quantile(xs, q) == pytest.approx(expected)


def test_mann_whitney_textbook_values():
    # Fully separated samples of 10: U = 0, exact two-sided p = 1.08e-5; normal approx ~1.8e-4.
    a = list(range(10))
    b = list(range(100, 110))
    u, p = stats.mann_whitney(a, b)
    assert u == 0
    assert p < 0.001
    # Identical samples: no evidence of a difference.
    assert stats.mann_whitney(a, a)[1] == pytest.approx(1.0)


def _noisy(center, n, rng, rel=0.03):
    return [center * (1 + rng.gauss(0, rel)) for _ in range(n)]


@pytest.mark.parametrize("ratio,expected", [
    (0.80, "improved"),
    (1.25, "regressed"),
    (1.00, "equivalent"),
], ids=["20pct-faster", "25pct-slower", "same"])
def test_compare_verdicts(ratio, expected):
    rng = random.Random(7)
    a = _noisy(1.0, 40, rng, rel=0.01)
    b = _noisy(ratio, 40, rng, rel=0.01)
    c = stats.compare(a, b, min_effect=0.03)
    assert c["verdict"] == expected
    assert c["ratio_ci"][0] <= c["ratio"] <= c["ratio_ci"][1]


def test_compare_small_noisy_sample_is_inconclusive_and_says_how_many_runs():
    rng = random.Random(3)
    a = _noisy(1.0, 5, rng, rel=0.15)
    b = _noisy(0.97, 5, rng, rel=0.15)
    c = stats.compare(a, b, min_effect=0.02)
    assert c["verdict"] == "inconclusive"
    assert c["runs_needed"] > 5
    assert any("only 5 samples" in w for w in c["warnings"])


def test_compare_higher_is_better_flips_direction():
    rng = random.Random(1)
    ops_a = _noisy(1000, 30, rng, rel=0.01)
    ops_b = _noisy(1300, 30, rng, rel=0.01)
    assert stats.compare(ops_a, ops_b, lower_is_better=False)["verdict"] == "improved"


@pytest.mark.parametrize("k", [1.0, 2.0])
def test_loglog_fit_recovers_exponent(k):
    sizes = [1000, 2000, 4000, 8000]
    fit = stats.loglog_fit(sizes, [3e-9 * n ** k for n in sizes])
    assert fit["exponent"] == pytest.approx(k, abs=1e-9)
    assert fit["r2"] == pytest.approx(1.0)


# ---------------------------------------------------------------- loaders

LOADER_CASES = [
    ("hyperfine", {"results": [{"command": "old", "times": [1.0, 1.1]}, {"command": "new", "times": [0.5, 0.6]}]},
     {"old": [1.0, 1.1], "new": [0.5, 0.6]}),
    ("pyperf", {"metadata": {"name": "parse"}, "benchmarks": [{"runs": [{"warmups": [[1, 9.0]]}, {"values": [1.0, 2.0]}, {"values": [3.0]}]}]},
     {"parse": [1.0, 2.0, 3.0]}),
    ("pytest-benchmark", {"benchmarks": [{"name": "t", "fullname": "tests/b.py::t", "stats": {"data": [0.1, 0.2]}}]},
     {"tests/b.py::t": [0.1, 0.2]}),
    ("perfkit", {"benchmarks": {"A": {"unit": "s", "samples": [1, 2]}}}, {"A": [1.0, 2.0]}),
    ("generic", {"files": [{"groups": [{"benchmarks": [{"name": "sort", "samples": [4, 5]}]}]}]}, {"sort": [4.0, 5.0]}),
]


@pytest.mark.parametrize("kind,doc,expected", LOADER_CASES, ids=[c[0] for c in LOADER_CASES])
def test_loaders(tmp_path, kind, doc, expected):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(doc))
    assert loaders.detect(doc) == kind
    got = loaders.load(str(p))
    assert {k: v["samples"] for k, v in got.items()} == expected


def test_pytest_benchmark_without_raw_data_explains_the_fix(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"benchmarks": [{"name": "t", "stats": {"mean": 1.0}}]}))
    with pytest.raises(ValueError, match="--benchmark-save-data"):
        loaders.load(str(p))


# ---------------------------------------------------------------- profiles

def _cpuprofile():
    # root -> main -> {hot, cold}; samples: hot x3, cold x1, idle x1; 1 ms apart
    return {
        "nodes": [
            {"id": 1, "callFrame": {"functionName": "(root)", "url": "", "lineNumber": -1}, "children": [2, 5]},
            {"id": 2, "callFrame": {"functionName": "main", "url": "file:///app/m.js", "lineNumber": 0}, "children": [3, 4]},
            {"id": 3, "callFrame": {"functionName": "hot", "url": "file:///app/m.js", "lineNumber": 9}},
            {"id": 4, "callFrame": {"functionName": "cold", "url": "file:///app/m.js", "lineNumber": 19}},
            {"id": 5, "callFrame": {"functionName": "(idle)", "url": "", "lineNumber": -1}},
        ],
        "samples": [3, 3, 3, 4, 5],
        "timeDeltas": [0, 1000, 1000, 1000, 1000],
    }


def test_cpuprofile_self_total_and_amdahl():
    tab = profiles.table(profiles.load_cpuprofile(_cpuprofile()))
    rows = {r["frame"]: r for r in tab["rows"]}
    hot, main = rows["hot (/app/m.js:10)"], rows["main (/app/m.js:1)"]
    # 4 busy samples (idle excluded); last sample's weight falls back to the median delta
    assert tab["busy"] == pytest.approx(0.004)
    assert hot["self_pct"] == pytest.approx(75.0)
    assert main["total_pct"] == pytest.approx(100.0) and main["self"] == 0
    assert hot["amdahl_max_speedup"] == pytest.approx(4.0)


def test_chrome_trace_profile_chunks_and_long_tasks():
    cp = _cpuprofile()
    nodes = [dict(n, parent=p) for n, p in zip(cp["nodes"], [None, 1, 2, 2, 1])]
    for n in nodes:
        n.pop("children", None)
        if n["parent"] is None:
            del n["parent"]
    events = [
        {"name": "thread_name", "ph": "M", "pid": 1, "tid": 2, "args": {"name": "CrRendererMain"}},
        {"name": "ProfileChunk", "ph": "P", "pid": 1, "tid": 2, "id": "0x1",
         "args": {"data": {"cpuProfile": {"nodes": nodes, "samples": cp["samples"]}, "timeDeltas": cp["timeDeltas"]}}},
        {"name": "RunTask", "ph": "X", "pid": 1, "tid": 2, "ts": 0, "dur": 120_000},
        {"name": "Layout", "ph": "X", "pid": 1, "tid": 2, "ts": 10, "dur": 30_000},
        {"name": "RunTask", "ph": "X", "pid": 1, "tid": 2, "ts": 200_000, "dur": 10_000},
    ]
    prof = profiles.load_chrome_trace({"traceEvents": events})
    tab = profiles.table(prof)
    assert max(tab["rows"], key=lambda r: r["self"])["frame"].startswith("hot")
    lt = tab["extra"]["long_tasks"]
    assert lt == {"count": 1, "total_blocking_ms": 70.0, "longest_ms": 120.0}


def test_speedscope_evented_and_sampled_agree():
    shared = {"frames": [{"name": "main"}, {"name": "hot"}]}
    evented = {"shared": shared, "profiles": [{"type": "evented", "unit": "milliseconds", "startValue": 0, "endValue": 10,
               "events": [{"type": "O", "frame": 0, "at": 0}, {"type": "O", "frame": 1, "at": 2},
                          {"type": "C", "frame": 1, "at": 8}, {"type": "C", "frame": 0, "at": 10}]}]}
    sampled = {"shared": shared, "profiles": [{"type": "sampled", "unit": "milliseconds",
               "samples": [[0], [0, 1]], "weights": [4, 6]}]}
    for doc in (evented, sampled):
        rows = {r["frame"]: r for r in profiles.table(profiles.load_speedscope(doc))["rows"]}
        assert rows["hot"]["self_pct"] == pytest.approx(60.0)
        assert rows["main"]["total_pct"] == pytest.approx(100.0)


def test_fold_charges_library_time_to_project_caller():
    prof = profiles.load_collapsed("main (/app/a.py:1);json.loads (/usr/lib/python3.12/json/__init__.py:3) 9\n"
                                   "main (/app/a.py:1) 1\n")
    folded = profiles.fold(prof, profiles.project_filter("/app"))
    rows = {r["frame"]: r for r in profiles.table(folded)["rows"]}
    assert rows["main (/app/a.py:1)"]["self_pct"] == pytest.approx(100.0)


def test_xtrace_attributes_gap_to_earlier_line():
    log = "+ 100.000 s.sh:1 a\n+ 100.500 s.sh:2 b\n++ 100.600 s.sh:3 c\n+ 101.000 s.sh:4 end\n"
    rows = {r["frame"]: r for r in profiles.table(profiles.load_xtrace(log))["rows"]}
    assert rows["s.sh:1"]["self"] == pytest.approx(0.5)
    assert rows["s.sh:3"]["self"] == pytest.approx(0.4)
    assert rows["s.sh:2"]["total"] == pytest.approx(0.5)   # includes its nested line 3


def test_pstats_roundtrip(tmp_path):
    out = tmp_path / "p.prof"
    code = "def hot():\n    return sum(i*i for i in range(200000))\nhot()\n"
    src = tmp_path / "m.py"
    src.write_text(code)
    subprocess.run([sys.executable, "-m", "cProfile", "-o", str(out), str(src)], check=True)
    tab = profiles.table(profiles.load(str(out)))
    top_total = max((r for r in tab["rows"] if "hot" in r["frame"]), key=lambda r: r["total"])
    assert top_total["calls"] == 1 and top_total["total_pct"] > 50


# ---------------------------------------------------------------- ledger and gate

def test_ledger_flags_kept_without_improvement(tmp_path):
    d = str(tmp_path / "perf" / "x")
    rng = random.Random(0)
    good = stats.compare(_noisy(1, 20, rng, .01), _noisy(.5, 20, rng, .01))
    same = stats.compare(_noisy(1, 20, rng, .01), _noisy(1, 20, rng, .01))
    ledger.add(d, exp_id="E1", hypothesis="h", change="c", decision="kept", comparison=good, guard="pytest")
    rec = ledger.add(d, exp_id="E2", hypothesis="h", change="c", decision="kept", comparison=same)
    assert any("without a measured improvement" in p for p in rec["lint"])
    assert any("guard" in p for p in rec["lint"])
    s = ledger.summary(d)
    assert s["kept"] == ["E1", "E2"] and s["cumulative_speedup"] == pytest.approx(good["speedup"] * same["speedup"])


POLICY = """
version = 1
rigor = "R3"   # default
[stats]
max_regression = 0.05
min_runs = 10
[[tier]]
name = "hot"
benchmarks = ["parse*"]
rigor = "R4"
max_regression = 0.02
[[budget]]
metric = "bundle.main_kb"
max = 180
unit = "kB"
"""


def test_mini_toml_matches_tomllib():
    tomllib = pytest.importorskip("tomllib")
    assert policy.mini_toml(POLICY) == tomllib.loads(POLICY)


@pytest.mark.parametrize("name,ratio,n,bundle,ok", [
    ("render", 1.03, 20, 150, True),     # 3% < default 5% tolerance
    ("parse_big", 1.03, 20, 150, False), # hot tier: 2% tolerance
    ("render", 1.00, 5, 150, False),     # too few runs
    ("render", 1.00, 20, 200, False),    # over budget
], ids=["within-tolerance", "hot-tier-regression", "too-few-runs", "over-budget"])
def test_gate(name, ratio, n, bundle, ok):
    rng = random.Random(11)
    c = stats.compare(_noisy(1, n, rng, .002), _noisy(ratio, n, rng, .002))
    c["name"] = name
    res = policy.gate(policy.mini_toml(POLICY), [c], {"bundle.main_kb": bundle})
    assert res["ok"] is ok, res["failures"]


# ---------------------------------------------------------------- CLI end to end

def test_abtest_detects_output_difference(tmp_path):
    out = tmp_path / "ab.json"
    r = subprocess.run([sys.executable, PK, "abtest", "--a", "echo one", "--b", "echo two", "--runs", "3",
                        "--warmup", "0", "-o", str(out), "--quiet", "--require-same-output"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "OUTPUT DIFFERS" in r.stdout
    doc = json.loads(out.read_text())
    assert doc["output_check"]["arms_agree"] is False and len(doc["benchmarks"]["A"]["samples"]) == 3


def test_suite_and_gate_catch_planted_regression_and_ignore_head_policy(tmp_path):
    """End to end: base vs head checkouts, interleaved suite, gate reading the policy from git."""
    import shutil
    if not shutil.which("git"):
        pytest.skip("git required")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "work.py").write_text("import time, sys\ntime.sleep(0.02)\nprint('ok')\n")
    (repo / "perf-policy.toml").write_text(
        'version = 1\nrigor = "R3"\n[stats]\nmin_effect = 0.05\nmax_regression = 0.10\nmin_runs = 10\n'
        '[[benchmark]]\nname = "work"\ncmd = "python3 work.py"\nruns = 10\nwarmup = 1\n')
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    git("init", "-q"); git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    git("worktree", "add", "-q", str(tmp_path / "base"), "HEAD")
    # head: 3x slower, and it tries to loosen its own policy
    (repo / "work.py").write_text("import time, sys\ntime.sleep(0.06)\nprint('ok')\n")
    (repo / "perf-policy.toml").write_text((repo / "perf-policy.toml").read_text().replace("0.10", "9.0"))
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, PK, "suite", "--policy-ref", "HEAD", "--base", str(tmp_path / "base"),
                        "--head", str(repo), "--out-dir", str(out)], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    g = subprocess.run([sys.executable, PK, "gate", "--policy-ref", "HEAD", "--compare", str(out / "comparisons.json"),
                        "--metrics", str(out / "metrics.json")], cwd=repo, capture_output=True, text=True)
    assert g.returncode == 1 and "regressed" in g.stdout, g.stdout


ESCAPES = r'''
[[benchmark]]
name = "x"
cmd = "node -e \"console.log(1)\" # not a comment"   # real comment
lit = 'C:\path\n'
arr = ["a\"b", 'c#d', "e\\f", "\u00e9"]
'''


def test_mini_toml_handles_escapes_like_tomllib():
    # regression: the fallback parser passed \" through literally (found by the fastparse-ci-gate eval)
    tomllib = pytest.importorskip("tomllib")
    assert policy.mini_toml(ESCAPES) == tomllib.loads(ESCAPES)


def test_ci_template_runs_steps_with_pipefail():
    # regression: `gate | tee` under the default shell hid a failing gate
    yml = open(os.path.join(ROOT, "skills", "perf-ci", "assets", "github-actions.yml")).read()
    assert "shell: bash" in yml and "| tee" in yml


def test_rigor_comes_from_test_policy_tiers():
    # ADR-0004: test-policy.toml is the source of rigor; perf-policy may only raise it
    perf = policy.mini_toml('rigor = "R2"\n[[benchmark]]\nname = "parse"\ncmd = "x"\npaths = ["src/core/parse.py"]\n')
    test = policy.mini_toml('rigor = "R3"\n[[adequacy.tier]]\nname = "critical"\npaths = ["src/core/*"]\nrigor = "R4"\n')
    levels = policy.test_policy_levels(test, policy.benchmark_paths(perf, "parse"))
    assert policy.effective_rigor(perf, None, None, levels) == "R4"
    assert policy.effective_rigor(perf, None, None, policy.test_policy_levels(test, ["docs/x.md"])) == "R3"


def test_ledger_note_text_carries_numbers_for_rejected_experiments():
    rng = random.Random(4)
    same = stats.compare(_noisy(1, 20, rng, .01), _noisy(1, 20, rng, .01))
    rec = {"id": "E2", "decision": "reverted", "hotspot": "f", "hypothesis": "h", "change": "c", "guard": "pytest",
           "verdict": same["verdict"], "change_pct": same["change_pct"], "ratio_ci": same["ratio_ci"],
           "p_value": same["p_value"], "n": [20, 20]}
    text = ledger.note_text(rec)
    assert "[reverted]" in text and "ratio CI" in text and "n=[20, 20]" in text


def test_paired_analysis_cancels_shared_drift():
    # Both arms drift together (thermal/background load); B is truly 5% faster in every block.
    # Unpaired tests drown in the drift; per-block ratios see the 5% clearly.
    rng = random.Random(9)
    drift = [1 + 0.4 * rng.random() for _ in range(20)]
    a = [d * (1 + rng.gauss(0, .005)) for d in drift]
    b = [d * 0.95 * (1 + rng.gauss(0, .005)) for d in drift]
    assert stats.compare(a, b, min_effect=0.02)["verdict"] != "improved"
    pc = stats.compare(a, b, min_effect=0.02, paired=True)
    assert pc["verdict"] == "improved" and pc["ratio"] == pytest.approx(0.95, abs=0.01)


@pytest.mark.parametrize("d,expect_small", [([0.1] * 15, True), ([0.1, -0.1] * 8, False)])
def test_wilcoxon_signed_rank(d, expect_small):
    p = stats.wilcoxon_signed_rank(d)
    assert (p < 0.01) is expect_small


def _trace_events():
    cp = _cpuprofile()
    nodes = [dict(n, parent=p) for n, p in zip(cp["nodes"], [None, 1, 2, 2, 1])]
    for n in nodes:
        n.pop("children", None)
        if n["parent"] is None:
            del n["parent"]
    return [
        {"name": "thread_name", "ph": "M", "pid": 1, "tid": 2, "args": {"name": "CrRendererMain"}},
        {"name": "thread_name", "ph": "M", "pid": 1, "tid": 3, "args": {"name": "Compositor"}},
        {"name": "ProfileChunk", "ph": "P", "pid": 1, "tid": 2, "id": "0x1",
         "args": {"data": {"cpuProfile": {"nodes": nodes, "samples": cp["samples"]}, "timeDeltas": cp["timeDeltas"]}}},
        {"name": "RunTask", "ph": "X", "pid": 1, "tid": 2, "ts": 0, "dur": 120_000},
        {"name": "Layout", "ph": "X", "pid": 1, "tid": 2, "ts": 10, "dur": 30_000},
        {"name": "Paint", "ph": "X", "pid": 1, "tid": 3, "ts": 10, "dur": 99_000},       # other thread: excluded
        {"name": "UpdateCounters", "ph": "I", "pid": 1, "tid": 2, "ts": 5, "args": {"data": {"x": "{,]"}}},
    ]


@pytest.mark.parametrize("layout", ["one-event-per-line", "single-line", "bare-array"])
def test_chrome_trace_file_layouts_give_the_same_table(tmp_path, layout):
    # pins profiles.load() for Chrome traces: every layout Chrome/Playwright/Puppeteer write must agree
    ev = _trace_events()
    p = tmp_path / "t.trace.json"
    if layout == "one-event-per-line":
        p.write_text('{"traceEvents":[\n' + ",\n".join(json.dumps(e) for e in ev) + "],\n\"metadata\": {}}\n")
    elif layout == "single-line":
        p.write_text(json.dumps({"traceEvents": ev}))
    else:
        p.write_text(json.dumps(ev))
    got = profiles.table(profiles.load(str(p)))
    want = profiles.table(profiles.load_chrome_trace({"traceEvents": ev}))
    key = lambda t: (sorted((r["frame"], round(r["self"], 9), round(r["total"], 9)) for r in t["rows"]), t["extra"])
    assert key(got) == key(want)
    assert want["extra"]["main_thread_events_ms"][0]["name"] == "RunTask"


def test_hotspot_output_is_deterministic_across_processes(tmp_path):
    # regression: ties were ordered by set() iteration, which changes with PYTHONHASHSEED (found by the PSKI-15 harness)
    p = tmp_path / "x.folded"
    p.write_text("".join(f"main;f{i} 1\n" for i in range(30)))
    outs = {subprocess.run([sys.executable, PK, "hotspots", str(p), "--top", "10"], capture_output=True, text=True,
                           env=dict(os.environ, PYTHONHASHSEED=str(seed))).stdout for seed in (1, 2, 3)}
    assert len(outs) == 1
