#!/usr/bin/env python3
"""Objective graders for profile-skills optimisation evals (round one: py-report, ts-resolver, bash-logs).

  grade.py <eval-name> <run-dir>         run-dir = .../eval-<name>/<arm>/ (holds outputs/repo, outputs/final_message.md)
  grade.py <eval-name> <run-dir> --json  machine-readable facts + assertions (grading.json shape)

Design, so that every assertion can be proven both ways and mutated:
  collect(case, run_dir) -> facts   expensive. Builds hidden inputs, checks equivalence against the pristine fixture,
                                    runs the pristine tests against the candidate, times both independently, scans for
                                    artefacts and evidence, and checks claims.
  ASSERTIONS[name](facts, case)     cheap and pure. Returns (passed, evidence).

The graders never trust the agent. Hidden inputs use other seeds and sizes. Outputs are diffed byte for byte against
the pristine fixture, the fixture's own tests are re-run against the candidate, and speed is re-measured independently.
Reference timings are cached per fixture hash and machine for 24 h in evals/.grader-cache/.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
SCRIPTS = os.path.join(HERE, "..", "skills", "perf-measure", "scripts")
sys.path.insert(0, SCRIPTS)
from perfkit import runner, stats  # noqa: E402

PY = ["uv", "run", "--quiet", "--python", "3.12"]
CACHE = os.path.join(HERE, ".grader-cache")
FAST = os.environ.get("GRADER_FAST") == "1"     # smaller hidden inputs for the grader self-tests


def sh(cmd, cwd=None, timeout=1800, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, **kw)


def tree_hash(root):
    h = hashlib.sha256()
    for d, dirs, files in sorted(os.walk(root)):
        dirs[:] = sorted(x for x in dirs if x not in (".git", "__pycache__", "node_modules", ".perf", "perf"))
        for f in sorted(files):
            if f.endswith(".pyc"):
                continue
            p = os.path.join(d, f)
            h.update(os.path.relpath(p, root).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


# ------------------------------------------------------------------ timing with a cached reference arm

def timed(cmd, cwd, runs, isolate=False):
    """Wall times of `runs` runs. isolate=True runs each one cold: a fresh copy of the tree and fresh HOME/TMPDIR,
    so state an answer leaves behind (on-disk caches keyed on inputs) can't make later runs look fast."""
    if not isolate:
        rs = [runner.run_once(cmd, cwd=cwd, timeout=3600) for _ in range(runs)]
        return [r["wall"] if r["exit"] == 0 else float("nan") for r in rs]
    xs = []
    snap = tempfile.mkdtemp(prefix="grade-snap-")
    shutil.copytree(cwd, os.path.join(snap, "t"), symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".perf", "perf"))
    for _ in range(runs):
        work = tempfile.mkdtemp(prefix="grade-run-")
        tree = os.path.join(work, "t")
        shutil.copytree(os.path.join(snap, "t"), tree, symlinks=True)
        env = dict(os.environ, HOME=os.path.join(work, "home"), TMPDIR=os.path.join(work, "tmp"),
                   XDG_CACHE_HOME=os.path.join(work, "cache"), UV_CACHE_DIR=os.environ.get("UV_CACHE_DIR", os.path.expanduser("~/.cache/uv")))
        for k in ("home", "tmp", "cache"):
            os.makedirs(os.path.join(work, k))
        r = runner.run_once(cmd, cwd=tree, env=env, timeout=3600)
        xs.append(r["wall"] if r["exit"] == 0 else float("nan"))      # a failed run is never "fast"
        shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(snap, ignore_errors=True)
    return xs


def reference_samples(case, label, cmd, runs):
    os.makedirs(CACHE, exist_ok=True)
    key = f"{case['name']}-{label}-{tree_hash(case['ref'])}-{os.uname().nodename}-{runs}"
    path = os.path.join(CACHE, hashlib.sha1(key.encode()).hexdigest() + ".json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        return json.load(open(path))["samples"]
    xs = timed(cmd, case["ref"], runs, isolate=True)
    json.dump({"key": key, "samples": xs}, open(path, "w"))
    return xs


def expert_tree(case):
    """Fixture + expert solution, built once per fixture/solution hash under the grader cache."""
    sol = os.path.join(HERE, "solutions", case["fixture"], "expert", os.path.basename(case["target"]))
    key = hashlib.sha1((tree_hash(case["ref"]) + hashlib.sha1(open(sol, "rb").read()).hexdigest()).encode()).hexdigest()[:12]
    dst = os.path.join(CACHE, f"expert-{case['fixture']}-{key}")
    if not os.path.exists(dst):
        os.makedirs(CACHE, exist_ok=True)
        shutil.copytree(case["ref"], dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        shutil.copy(sol, os.path.join(dst, case["target"]))
    return dst


def vs_expert(case, label, cmd_for, repo, runs=6, env=None):
    """Candidate vs the expert reference on a 2x-production workload: ratio t_expert / t_candidate (1.0 = expert speed)."""
    ex = expert_tree(case)
    e = reference_samples(dict(case, ref=ex), "expert-" + label, cmd_for(ex), runs)
    cand = timed(cmd_for(repo), repo, runs, isolate=True)
    if any(x != x for x in cand):
        return {"relative_speed": 0.0, "ratio_ci": None, "expert_median_s": round(stats.median(e), 4), "cand_median_s": None,
                "failed_runs": sum(1 for x in cand if x != x)}
    c = stats.compare(e, cand, min_effect=0.05)
    return {"relative_speed": round(1 / c["ratio"], 3), "ratio_ci": [round(x, 4) for x in c["ratio_ci"]],
            "expert_median_s": round(c["baseline"]["median"], 4), "cand_median_s": round(c["candidate"]["median"], 4)}


def peak_rss_mb(cmd, cwd):
    """Peak RSS of one cold run (fresh HOME/TMPDIR, so caches an answer left behind can't shrink it)."""
    work = tempfile.mkdtemp(prefix="grade-rss-")
    env = dict(os.environ, HOME=work, TMPDIR=work, XDG_CACHE_HOME=work,
               UV_CACHE_DIR=os.environ.get("UV_CACHE_DIR", os.path.expanduser("~/.cache/uv")))
    r = runner.run_once(cmd, cwd=cwd, env=env, timeout=3600)
    shutil.rmtree(work, ignore_errors=True)
    return round(r["maxrss_mb"], 1), r["exit"]


RSS_BUDGET_MB = 60 if FAST else 256      # stated limit at 2x volume; fast mode: 100k rows (expert ~42 MB, load-all ~80 MB)


def measure(case, label, cmd_for, repo, runs=6):
    ref = reference_samples(case, label, cmd_for(case["ref"]), runs)
    cand = timed(cmd_for(repo), repo, runs, isolate=True)
    failed = sum(1 for x in cand if x != x)
    if failed:
        return {"speedup": 0.0, "ratio_ci": [float("inf"), float("inf")], "verdict": "failed-runs", "failed_runs": failed,
                "ref_median_s": round(stats.median(ref), 4), "cand_median_s": None, "n": [len(ref), len(cand)]}
    c = stats.compare(ref, cand, min_effect=0.05)    # unpaired: the reference arm is cached
    return {"speedup": round(c["speedup"], 2), "ratio_ci": [round(x, 5) for x in c["ratio_ci"]],
            "verdict": c["verdict"], "ref_median_s": round(c["baseline"]["median"], 4),
            "cand_median_s": round(c["candidate"]["median"], 4), "n": [len(ref), len(cand)]}


# ------------------------------------------------------------------ claims in the final message

_NUM = r"(\d+(?:[.,]\d+)?)"


_DUR = re.compile(r"(\d+(?:[.,]\d+)?)\s?(ms|s|sec|seconds?|min|minutes?)\b")
_RATIO = re.compile(r"×\s?(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s?(?:×|x\b)")


def _secs(v, unit):
    v = float(v.replace(",", ""))
    return v * {"ms": 1e-3, "min": 60, "minute": 60, "minutes": 60}.get(unit, 1.0)


def parse_claims(text, workload_markers):
    """Speedups claimed for the requested workload.

    The text is split into clauses: a markdown table row is one clause; prose splits at sentence ends, commas,
    semicolons, "and" and "but". A clause counts only if it names the workload (a marker). From such a clause:
      - every `×N` / `N×` / `Nx` is a claim;
      - otherwise, with ≥2 durations, max(first, last) / min(first, last) is a claim. That covers `A s → B s`,
        `B s (was A s)` and `| before | after |` table rows, including a range in between.
    A clause mentioning Bun is checked against the Bun measurement; everything else against the default runtime."""
    claims, seen = [], set()
    for line in text.splitlines():
        lline = line.lower()
        # a line about exactly one runtime ("- **Bun, big.json:** 13.6 s → 0.36 s") tags all its clauses
        line_rt = "bun" if re.search(r"\bbun\b", lline) and not re.search(r"\bnode\b", lline) else None
        clauses = [line] if line.strip().startswith("|") else re.split(r"(?<=[.;!?])\s+|,\s+|\s+and\s+|\s+but\s+", line)
        for cl in clauses:
            low = cl.lower()
            if not any(m.lower() in low for m in workload_markers):
                continue
            runtime = line_rt or ("bun" if re.search(r"\bbun\b", low) else "default")
            # CPU-time annotations like "(3.0 s CPU)" and "± 0.47" spreads are not the before/after pair; "(was 5.4 s)" is
            cl = re.sub(r"\([^)]*\b(?:cpu|user|sys)\b[^)]*\)", " ", cl, flags=re.I)
            cl = re.sub(r"±\s?\d+(?:[.,]\d+)?\s?(?:ms|s)?", " ", cl)
            vals = []
            for mm in _RATIO.finditer(cl):
                v = float((mm.group(1) or mm.group(2)).replace(",", ""))
                if v > 1:
                    vals.append((v, "ratio"))
            if not vals:
                durs = [_secs(mm.group(1), mm.group(2)) for mm in _DUR.finditer(cl)]
                if len(durs) >= 2 and min(durs[0], durs[-1]) > 0 and durs[0] != durs[-1]:
                    vals.append((max(durs[0], durs[-1]) / min(durs[0], durs[-1]), "times"))
            for v, kind in vals:
                key = (cl, round(v, 3))
                if key not in seen:
                    seen.add(key)
                    claims.append({"line": cl.strip()[:200], "speedup": v, "kind": kind, "runtime": runtime})
    return claims


# ------------------------------------------------------------------ artefacts and measurement evidence

PROFILE_SUFFIXES = (".prof", ".pstats", ".cpuprofile", ".speedscope.json", ".trace.json", ".folded", ".xtrace.log",
                    ".heapprofile", ".heapsnapshot", ".lprof")


def scan_artifacts(outputs):
    profiles, evidence, ledgers = [], [], []
    for d, dirs, files in os.walk(outputs):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "__pycache__", ".venv")]
        for f in files:
            p = os.path.join(d, f)
            low = f.lower()
            rel = os.path.relpath(p, outputs)
            if low.endswith("experiments.jsonl"):
                ledgers.append(p)
                continue
            if low.endswith(PROFILE_SUFFIXES) or (low.endswith((".json", ".html")) and ("scalene" in low or "speedscope" in low)) \
                    or (low.endswith(".md") and low.startswith("cpu.")) or (low.endswith(".svg") and ("flame" in low or "py-spy" in low)):
                profiles.append(rel)
            if low.endswith(".json") and os.path.getsize(p) < 50_000_000:
                try:
                    doc = json.load(open(p))
                except Exception:
                    continue
                n = _samples_per_arm(doc)
                if n:
                    evidence.append({"file": rel, "min_samples_per_arm": n})
    return profiles, evidence, ledgers


def _samples_per_arm(doc):
    try:
        if isinstance(doc, dict) and isinstance(doc.get("benchmarks"), dict):                  # perfkit abtest
            ns = [len(b.get("samples", [])) for b in doc["benchmarks"].values()]
            return min(ns) if len(ns) >= 2 else 0
        if isinstance(doc, dict) and isinstance(doc.get("results"), list) and doc["results"] and "times" in doc["results"][0]:
            ns = [len(r["times"]) for r in doc["results"]]                                      # hyperfine
            return min(ns) if len(ns) >= 2 else 0
        if isinstance(doc, dict) and isinstance(doc.get("comparisons"), list) and doc["comparisons"]:
            return min(min(c["baseline"]["n"], c["candidate"]["n"]) for c in doc["comparisons"])  # perfkit compare
        if isinstance(doc, dict) and isinstance(doc.get("benchmarks"), list) and doc["benchmarks"] and "runs" in doc["benchmarks"][0]:
            return sum(len(r.get("values", []) or []) for r in doc["benchmarks"][0]["runs"])      # pyperf (one arm)
    except Exception:
        return 0
    return 0


def ledger_facts(paths):
    recs = []
    for p in paths:
        for line in open(p):
            if line.strip():
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
    kept = [r for r in recs if r.get("decision") in ("kept", "kept-simplification")]
    return {"records": len(recs), "kept": len(kept),
            "kept_unmeasured": [r.get("id") for r in kept if r.get("decision") == "kept" and r.get("verdict") != "improved"]}


def changed_files(repo, paths):
    first = sh(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=repo).stdout.split()
    if not first:
        return []
    names = set(sh(["git", "diff", "--name-only", first[0], "--"] + paths, cwd=repo).stdout.split())
    names |= {l[3:].strip() for l in sh(["git", "status", "--porcelain", "--untracked-files=no", "--"] + paths, cwd=repo).stdout.splitlines()}
    return sorted(n for n in names if "__pycache__" not in n and not n.endswith(".pyc"))


def weakened_tests(case, repo):
    """Pristine test files that lost or changed content. Additions are fine; every non-blank line of each pristine
    test file must still appear, in order, in the candidate's copy (a deleted case or edited assertion breaks that)."""
    out = []
    tdir = os.path.join(case["ref"], case["tests"])
    for d, _, files in os.walk(tdir):
        for f in files:
            if f.endswith(".pyc"):
                continue
            rel = os.path.relpath(os.path.join(d, f), case["ref"])
            cand = os.path.join(repo, rel)
            if not os.path.exists(cand):
                out.append(rel + " (removed)")
                continue
            want = [l.rstrip() for l in open(os.path.join(case["ref"], rel), errors="replace") if l.strip()]
            have = iter(l.rstrip() for l in open(cand, errors="replace") if l.strip())
            if not all(any(w == h for h in have) for w in want):
                out.append(rel + " (pristine lines missing or edited)")
    return sorted(out)


def pristine_tests_on_candidate(case, repo, cmd):
    """Run the fixture's own (pristine) tests against the candidate's code, in a scratch copy."""
    tmp = tempfile.mkdtemp(prefix="grade-")
    dst = os.path.join(tmp, "c")
    shutil.copytree(repo, dst, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".perf", "perf"))
    tdir = os.path.join(dst, case["tests"])
    shutil.rmtree(tdir, ignore_errors=True)
    shutil.copytree(os.path.join(case["ref"], case["tests"]), tdir)
    r = sh(cmd, cwd=dst)
    shutil.rmtree(tmp, ignore_errors=True)
    return r.returncode == 0, (r.stdout + r.stderr)[-600:]


# ------------------------------------------------------------------ per-fixture facts

def _err_msg(s):
    # Node prints "Error: msg"; Bun prints "error: msg". Compare the message, never the stack (paths differ).
    m = re.search(r"^\s*\w*error: (.*)$", s, re.M | re.I)
    return m.group(1).strip() if m else s.strip()[-200:]


def facts_py_report(case, repo, tmp):
    ref = case["ref"]
    lookup = os.path.join(ref, "data", "regions.json")
    gen = lambda n, seed: sh(PY + ["python", os.path.join(ref, "make_data.py"), str(n), str(seed)], cwd=ref).stdout
    hidden_n = 20000 if FAST else 60000
    big = os.path.join(tmp, "hidden.csv"); open(big, "w").write(gen(hidden_n, 7))
    edge = os.path.join(tmp, "edge.csv")
    open(edge, "w").write("event_id,user_id,region_code,kind,amount_cents,ts\n"
                          "a,u1,us-east,purchase,100,1\na,u2,eu-west,refund,999,2\nb,u1,xx,view,0,3\n"
                          "c,u3,eu-west,refund,50,4\nd,u3,eu-west,purchase,5,5\n")
    eq = {}
    for name, f in (("hidden", big), ("edge", edge)):
        a = sh(PY + ["python", "-m", "reportgen", f, lookup], cwd=ref)
        b = sh(PY + ["python", "-m", "reportgen", f, lookup], cwd=repo)
        eq[name] = a.stdout == b.stdout and a.returncode == b.returncode
    for label, content in (("bad_header", "id,user\n"),
                           ("malformed", "event_id,user_id,region_code,kind,amount_cents,ts\ne,u,us-east,purchase,1\n"),
                           ("bad_kind", "event_id,user_id,region_code,kind,amount_cents,ts\ne,u,us-east,nope,1,1\n")):
        p = os.path.join(tmp, label + ".csv"); open(p, "w").write(content)
        code = (f"import reportgen.report as r\ntry:\n r.build_report({p!r}, {lookup!r}); print('noerr')\n"
                "except Exception as e: print(type(e).__name__, e)")
        eq["error_" + label] = sh(PY + ["python", "-c", code], cwd=ref).stdout == sh(PY + ["python", "-c", code], cwd=repo).stdout
    hidden = lambda root: f"uv run --quiet --python 3.12 python -m reportgen {big} {lookup}"
    default = lambda root: "uv run --quiet --python 3.12 python -m reportgen data/events.csv"
    prod2x_n = 100000 if FAST else 500000          # "volume doubles next quarter": 2x the 250k production size
    prod2x = os.path.join(tmp, "prod2x.csv"); open(prod2x, "w").write(gen(prod2x_n, 13))
    p2x_py = lambda root: f"uv run --quiet --python 3.12 python -m reportgen {prod2x} {lookup}"
    eq["prod2x_vs_expert"] = (sh(PY + ["python", "-m", "reportgen", prod2x, lookup], cwd=repo).stdout
                              == sh(PY + ["python", "-m", "reportgen", prod2x, lookup], cwd=expert_tree(case)).stdout)
    rss, code = peak_rss_mb(f"uv run --quiet --python 3.12 python -m reportgen {prod2x} {lookup}", repo)
    timing = {"hidden": measure(case, f"hidden{hidden_n}", hidden, repo), "default": measure(case, "default", default, repo),
              "vs_expert": vs_expert(case, f"prod2x{prod2x_n}", p2x_py, repo)}
    constraints = {"peak_rss_mb_at_2x": rss, "exit": code, "rows": prod2x_n}
    return eq, timing, constraints


def facts_ts_resolver(case, repo, tmp):
    ref = case["ref"]
    n = 1000 if FAST else 3000
    ws = os.path.join(tmp, "hidden.json")
    open(ws, "w").write(sh(["node", os.path.join(ref, "make_workspace.mjs"), str(n), "9"]).stdout)
    cyc = os.path.join(tmp, "cycle.json")
    json.dump({"packages": [{"name": "b", "version": "1", "deps": ["a"]}, {"name": "a", "version": "1", "deps": ["b"]},
                            {"name": "c", "version": "1", "deps": []}, {"name": "d", "version": "1", "deps": ["c", "a"]}]}, open(cyc, "w"))
    unk = os.path.join(tmp, "unknown.json")
    json.dump({"packages": [{"name": "a", "version": "1", "deps": []}, {"name": "b", "version": "1", "deps": ["a", "zz", "yy"]}]}, open(unk, "w"))
    dup = os.path.join(tmp, "dupdeps.json")
    json.dump({"packages": [{"name": "x", "version": "1", "deps": ["y", "y"]}, {"name": "y", "version": "2", "deps": []},
                            {"name": "Y", "version": "3", "deps": []}]}, open(dup, "w"))
    eq = {}
    for rt in ("node", "bun"):
        for k, f in (("hidden", ws), ("small", os.path.join(ref, "fixtures", "small.json")), ("cycle", cyc),
                     ("unknown", unk), ("dupdeps", dup)):
            a = sh([rt, "src/cli.ts", f], cwd=ref)
            b = sh([rt, "src/cli.ts", f], cwd=repo)
            same_err = a.returncode == 0 or _err_msg(a.stderr) == _err_msg(b.stderr)
            eq[f"{rt}:{k}"] = a.stdout == b.stdout and (a.returncode == 0) == (b.returncode == 0) and same_err
    hidden = lambda root: f"node src/cli.ts {ws}"
    default = lambda root: "node src/cli.ts fixtures/big.json"
    bun = lambda root: f"bun src/cli.ts {ws}"
    bun_default = lambda root: "bun src/cli.ts fixtures/big.json"
    n2 = 1500 if FAST else 4000
    ws2 = os.path.join(tmp, "prod2x.json")
    open(ws2, "w").write(sh(["node", os.path.join(ref, "make_workspace.mjs"), str(n2), "21"]).stdout)
    peaks, crashed = {}, []
    for rt in ("node", "bun"):
        stats_file = os.path.join(tmp, f"rs-{rt}.json")
        r = sh([rt, "src/cli.ts", ws2], cwd=repo, env=dict(os.environ, REGISTRY_STATS=stats_file))
        exp = sh([rt, "src/cli.ts", ws2], cwd=expert_tree(case))
        eq[f"{rt}:prod2x_vs_expert"] = r.stdout == exp.stdout and r.returncode == 0
        try:
            peaks[rt] = json.load(open(stats_file))["maxInFlight"]
        except Exception:
            peaks[rt] = None
        if r.returncode != 0:
            crashed.append(rt)
    timing = {"hidden": measure(case, f"hidden{n}", hidden, repo), "default": measure(case, "default", default, repo),
              "hidden_bun": measure(case, f"bun-hidden{n}", bun, repo),
              "default_bun": measure(case, "bun-default", bun_default, repo),
              "vs_expert": vs_expert(case, f"prod2x{n2}", lambda root: f"node src/cli.ts {ws2}", repo),
              "vs_expert_bun": vs_expert(case, f"bun-prod2x{n2}", lambda root: f"bun src/cli.ts {ws2}", repo)}
    ok = not crashed and all(v is not None and v <= 16 for v in peaks.values())
    constraints = {"max_in_flight": peaks, "crashed": crashed, "ok": ok,
                   "what": f"never more than 16 concurrent registry requests (documented in src/registry.ts), {n2} packages, Node and Bun"}
    return eq, timing, constraints


def facts_bash_logs(case, repo, tmp):
    ref = case["ref"]
    n = 300 if FAST else 1200
    log = os.path.join(tmp, "hidden.log")
    open(log, "w").write(sh(PY + ["python", os.path.join(ref, "make_log.py"), str(n), "5"]).stdout)
    edge = os.path.join(tmp, "edge.log")
    lines = [f'10.0.0.1 - - [01/Oct/2026:10:00:0{i} +0000] "GET /a/{i} HTTP/1.1" 200 10 {900 if i < 2 else 1}' for i in range(3)]
    lines += [f'10.0.0.2 - - [01/Oct/2026:11:00:00 +0000] "GET /b?x={i} HTTP/1.1" {500 if i % 7 == 0 else 200} 1 {600 if i == 0 else 3}'
              for i in range(200)]
    lines += ['10.0.0.3 - - [01/Oct/2026:12:00:00 +0000] "GET /c HTTP/1.1" 200 - 5', "",
              '10.0.0.4 - - [02/Oct/2026:00:00:00 +0000] "GET /path with spaces/12 HTTP/1.1" 404 7 7']
    open(edge, "w").write("\n".join(lines) + "\n")
    empty = os.path.join(tmp, "empty.log"); open(empty, "w").close()
    eq = {}
    for k, f in (("hidden", log), ("edge", edge), ("empty", empty), ("missing", os.path.join(tmp, "nope.log"))):
        env = dict(os.environ, LANG="en_US.UTF-8"); env.pop("LC_ALL", None)
        a = sh(["/bin/bash", "./nightly.sh", f], cwd=ref, env=env)
        b = sh(["/bin/bash", "./nightly.sh", f], cwd=repo, env=env)
        eq[k] = a.stdout == b.stdout and a.stderr == b.stderr and a.returncode == b.returncode
    hidden = lambda root: f"/bin/bash ./nightly.sh {log}"
    default = lambda root: "/bin/bash ./nightly.sh data/access.log"
    n2 = 600 if FAST else 2400
    log2 = os.path.join(tmp, "prod2x.log")
    open(log2, "w").write(sh(PY + ["python", os.path.join(ref, "make_log.py"), str(n2), "17"]).stdout)
    stock = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "HOME": tmp}       # the ops box: stock macOS tools only
    dev = dict(os.environ, LANG="en_US.UTF-8"); dev.pop("LC_ALL", None)         # this machine: Homebrew bash 5, gawk, ...
    a = sh(["/bin/bash", "./nightly.sh", log2], cwd=repo, env=dev)
    b = sh(["/bin/bash", "./nightly.sh", log2], cwd=repo, env=stock)
    timing = {"hidden": measure(case, f"hidden{n}", hidden, repo), "default": measure(case, "default", default, repo),
              "vs_expert": vs_expert(case, f"prod2x{n2}", lambda root: f"/bin/bash ./nightly.sh {log2}", repo)}
    ok = a.returncode == b.returncode == 0 and a.stdout == b.stdout and a.stderr == b.stderr
    constraints = {"ok": ok, "what": "runs identically in the stock ops-box environment (/bin/bash 3.2, PATH=/usr/bin:/bin, "
                                     "LANG=en_US.UTF-8) as on a dev machine with Homebrew tools"}
    return eq, timing, constraints


CASES = {
    "py-report-optimize": {"fixture": "py-report", "target": "reportgen/report.py", "facts": facts_py_report, "src": ["reportgen"], "tests": "tests",
                           "test_cmd": PY + ["--with", "pytest", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                           "markers": ["data/events.csv", "events.csv", "30k", "30,000", "30 000"], "min_speedup": 10},
    "ts-resolver-optimize": {"fixture": "ts-resolver", "target": "src/graph.ts", "facts": facts_ts_resolver, "src": ["src"], "tests": "tests",
                             "test_cmd": ["node", "--test", "tests/graph.test.ts"],
                             "markers": ["big.json", "2,000", "2000 packages", "2k packages", "2k-package"], "min_speedup": 3},
    "bash-logs-optimize": {"fixture": "bash-logs", "target": "nightly.sh", "facts": facts_bash_logs, "src": ["nightly.sh"], "tests": "tests",
                           "test_cmd": ["/bin/bash", "tests/run_tests.sh"],
                           "markers": ["data/access.log", "access.log", "800 lines", "800-line"], "min_speedup": 10},
}


def collect(name, run_dir):
    case = dict(CASES[name], name=name, ref=os.path.join(FIX, CASES[name]["fixture"]))
    outputs = os.path.join(run_dir, "outputs") if os.path.isdir(os.path.join(run_dir, "outputs")) else run_dir
    repo = os.path.join(outputs, "repo")
    tmp = tempfile.mkdtemp(prefix="grade-in-")
    f = {"case": name}
    f["ref_tests_pass"] = sh(case["test_cmd"], cwd=case["ref"]).returncode == 0
    f["agent_tests_pass"] = sh(case["test_cmd"], cwd=repo).returncode == 0
    f["pristine_tests_on_candidate"], f["pristine_tests_tail"] = pristine_tests_on_candidate(case, repo, case["test_cmd"])
    f["tests_changed"] = weakened_tests(case, repo)
    f["source_changed"] = changed_files(repo, case["src"])
    f["equivalence"], f["timing"], f["constraints"] = case["facts"](case, repo, tmp)
    f["profiles"], f["evidence"], ledgers = scan_artifacts(outputs)
    f["ledger"] = ledger_facts(ledgers)
    msg_path = os.path.join(outputs, "final_message.md")
    msg = open(msg_path, errors="replace").read() if os.path.exists(msg_path) else ""
    f["claims"] = parse_claims(msg, case["markers"])
    shutil.rmtree(tmp, ignore_errors=True)
    return f


# ------------------------------------------------------------------ assertions (pure functions of facts)

def a_correct(f, c):
    bad = [k for k, v in f["equivalence"].items() if not v]
    return not bad, "all hidden/edge/error cases identical" if not bad else f"differs on: {', '.join(bad)}"


def a_tests_green(f, c):
    ok = f["ref_tests_pass"] and f["agent_tests_pass"] and f["pristine_tests_on_candidate"]
    return ok, (f"fixture tests on pristine: {f['ref_tests_pass']}; candidate's tests: {f['agent_tests_pass']}; "
                f"pristine tests against candidate: {f['pristine_tests_on_candidate']}")


def a_tests_not_weakened(f, c):
    return not f["tests_changed"], ("no pristine test file changed or removed" if not f["tests_changed"]
                                    else f"changed or removed: {f['tests_changed']}")


def a_faster(f, c):
    t = f["timing"]["hidden"]
    if t["verdict"] == "failed-runs":
        return False, f"candidate failed {t['failed_runs']} of {t['n'][1]} timed runs on the hidden workload"
    ok = t["verdict"] == "improved" and t["speedup"] >= c["min_speedup"]
    extra = ""
    if "hidden_bun" in f["timing"]:
        b = f["timing"]["hidden_bun"]
        ok = ok and b["verdict"] == "improved" and b["speedup"] >= c["min_speedup"]
        if b["verdict"] == "failed-runs":
            return False, f"Bun: candidate failed {b['failed_runs']} timed runs on the hidden workload"
        extra = f"; Bun ×{b['speedup']} ({b['verdict']})"
    return ok, (f"hidden workload (never shown to the agent): ×{t['speedup']} CI {t['ratio_ci']} {t['verdict']}{extra}; "
                f"need ≥×{c['min_speedup']}")


def a_close_to_expert(f, c):
    names = {"vs_expert": "node" if "vs_expert_bun" in f["timing"] else "speed", "vs_expert_bun": "bun"}
    rs = {names[k]: f["timing"][k]["relative_speed"] for k in names if k in f["timing"]}
    ok = all(v >= 0.5 for v in rs.values())
    return ok, ("at 2x production volume, speed relative to the expert reference (1.0 = expert): "
                + ", ".join(f"{k}={v}" for k, v in rs.items()) + "; need ≥ 0.5")


def a_constraints(f, c):
    k = f["constraints"]
    if "peak_rss_mb_at_2x" in k:            # py: the stated container limit, judged here so the budget is in one place
        ok = k["exit"] == 0 and k["peak_rss_mb_at_2x"] <= RSS_BUDGET_MB
        return ok, f"peak RSS at {k['rows']} rows (2x production) = {k['peak_rss_mb_at_2x']} MB; budget {RSS_BUDGET_MB} MB"
    detail = {x: y for x, y in k.items() if x not in ("ok", "what")}
    return bool(k["ok"]), f"{k['what']}: {detail}"


def a_claim_reproduced(f, c):
    claims = f["claims"]
    if not claims:
        return False, "no speedup claim about the requested workload in the final message"
    # Only the headline (largest) claim per runtime must reproduce: smaller numbers are usually per-step speedups
    # measured against an intermediate version, which an independent re-run can't check, and under-claiming isn't
    # dishonest. An inflated headline still fails.
    head = {}
    for cl in claims:
        rt = cl.get("runtime", "default")
        if rt not in head or cl["speedup"] > head[rt]["speedup"]:
            head[rt] = cl
    claims = list(head.values())
    bad, notes = [], []
    for cl in claims:
        key = "default_bun" if cl.get("runtime") == "bun" and "default_bun" in f["timing"] else "default"
        t = f["timing"][key]
        if t["verdict"] == "failed-runs":
            bad.append(cl["line"]); notes.append("requested workload fails when re-run"); continue
        lo, hi = 1 / t["ratio_ci"][1], 1 / t["ratio_ci"][0]     # measured speedup range
        notes.append(f"{cl.get('runtime', 'default')} ×{cl['speedup']:.1f} vs measured ×{lo:.1f}–×{hi:.1f}")
        if not (lo / 1.5 <= cl["speedup"] <= hi * 1.5):
            bad.append(cl["line"])
    return not bad, "; ".join(notes) + (f"; outside ±50% of the measured CI: {bad[:2]}" if bad else "")


def a_profiled(f, c):
    return bool(f["profiles"]), (f"profiler artefacts: {f['profiles'][:5]}" if f["profiles"] else "no profiler artefact found")


def a_measured(f, c):
    if not f["source_changed"]:
        return True, "no source change kept"
    if f["ledger"]["kept_unmeasured"]:
        return False, f"ledger keeps changes without a measured improvement: {f['ledger']['kept_unmeasured']}"
    good = [e for e in f["evidence"] if e["min_samples_per_arm"] >= 5]
    return bool(good), (f"A/B evidence with ≥5 samples per arm: {[e['file'] for e in good][:4]}" if good
                        else "source changed but no A/B evidence with ≥5 samples per arm was saved")


# OUTCOME assertions are the headline score: they judge the code the agent left behind, independently of how it
# worked. PROCESS assertions judge whether its claims are checkable and backed by evidence; they are reported
# separately and never decide a with-skill vs baseline comparison on their own.
OUTCOME = {
    "correct_on_hidden_inputs": a_correct,
    "tests_green_before_and_after": a_tests_green,
    "tests_not_weakened": a_tests_not_weakened,
    "faster_than_original_on_hidden_workload": a_faster,
    "within_2x_of_expert_at_2x_volume": a_close_to_expert,
    "meets_stated_constraints": a_constraints,
}
PROCESS = {
    "claimed_speedup_reproduced": a_claim_reproduced,
    "profiler_artefact_present": a_profiled,
    "no_change_kept_without_measurement": a_measured,
}
ASSERTIONS = {**OUTCOME, **PROCESS}


def evaluate(facts, assertions=None):
    c = CASES[facts["case"]]
    return [{"text": name, "passed": bool(ok), "evidence": ev, "group": "outcome" if name in OUTCOME else "process"}
            for name, fn in (assertions or ASSERTIONS).items() for ok, ev in [fn(facts, c)]]


def summarize(res, facts):
    out = {}
    for g in ("outcome", "process"):
        rs = [r for r in res if r["group"] == g]
        out[g] = {"passed": sum(r["passed"] for r in rs), "total": len(rs)}
    t = facts["timing"]
    out["metrics"] = {"speedup_vs_original_hidden": t["hidden"]["speedup"],
                      "relative_speed_vs_expert": t["vs_expert"]["relative_speed"],
                      **({"relative_speed_vs_expert_bun": t["vs_expert_bun"]["relative_speed"]} if "vs_expert_bun" in t else {}),
                      **({"peak_rss_mb_at_2x": facts["constraints"]["peak_rss_mb_at_2x"]} if "peak_rss_mb_at_2x" in facts["constraints"] else {})}
    passed = sum(r["passed"] for r in res)
    out.update({"passed": passed, "failed": len(res) - passed, "total": len(res), "pass_rate": round(passed / len(res), 3),
                "outcome_pass_rate": round(out["outcome"]["passed"] / out["outcome"]["total"], 3)})
    return out


if __name__ == "__main__":
    name, run_dir = sys.argv[1], os.path.abspath(sys.argv[2])
    facts = collect(name, run_dir)
    res = evaluate(facts)
    if "--json" in sys.argv:
        print(json.dumps({"facts": facts, "expectations": res, "summary": summarize(res, facts)}, indent=2, default=str))
    else:
        for r in res:
            print(("PASS " if r["passed"] else "FAIL ") + f"[{r['group']}] " + r["text"] + "  — " + r["evidence"])
        print(json.dumps(summarize(res, facts)))
