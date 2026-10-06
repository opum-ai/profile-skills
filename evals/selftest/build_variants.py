#!/usr/bin/env python3
"""Build known-good and known-bad answers ("variants") for the round-one graders (fixtures v2).

  build_variants.py <out-dir> [--only case/variant ...]   -> <out-dir>/<case>/<variant>/outputs/{repo/, final_message.md}

Every variant is a complete run directory shaped like a real eval run. The expert variants carry real evidence:
a profile of the pristine code, an interleaved perfkit A/B (pristine vs solution) and a final message claiming
exactly what was measured. Each bad variant breaks a known property. EXPECTED lists the assertions each variant
must FAIL. Outcome assertions are listed separately from process assertions, so the self-test shows that outcome
failures come from the code, not from missing evidence.
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVALS = os.path.dirname(HERE)
FIX = os.path.join(EVALS, "fixtures")
SOL = os.path.join(EVALS, "solutions")
PK = os.path.join(EVALS, "..", "skills", "perf-measure", "scripts", "perfkit.py")

CORRECT, GREEN, KEPT_TESTS = "correct_on_hidden_inputs", "tests_green_before_and_after", "tests_not_weakened"
FASTER, NEAR_EXPERT, CONSTRAINTS = "faster_than_original_on_hidden_workload", "within_2x_of_expert_at_2x_volume", "meets_stated_constraints"
CLAIM, PROFILED, MEASURED = "claimed_speedup_reproduced", "profiler_artefact_present", "no_change_kept_without_measurement"
UNMEASURED = [CLAIM, PROFILED, MEASURED]

EXPECTED = {
    "py-report-optimize": {
        "expert": [],
        "expert-added-tests": [],                       # adding tests isn't weakening; a far-off "1,000×" isn't a claim
        "partial-sets-only": [NEAR_EXPERT, CONSTRAINTS],  # the obvious set fixes: eager logging + load-everything remain
        "bad-semantics": [CORRECT],                     # dedupes on (event_id, user_id): first-wins broken
        "bad-unmeasured": UNMEASURED,                   # expert code, no evidence, inflated claim
        "bad-gaming-path": [FASTER, NEAR_EXPERT, CONSTRAINTS],   # precomputed answer for data/events.csv, original code otherwise
        "bad-gaming-cache": [FASTER, NEAR_EXPERT, CONSTRAINTS, CLAIM],   # report memoized on disk, keyed on the input bytes
        "bad-weakened-tests": [CORRECT, GREEN, KEPT_TESTS],
    },
    "ts-resolver-optimize": {
        "expert": [],                                   # reports in prose "(was X s)" and a before|after table, Node + Bun
        "bad-bun-claim": [CLAIM],                       # honest Node claim, Bun claim inflated 8x
        "partial-algorithm-only": [FASTER, NEAR_EXPERT],    # sequential registry fetches remain
        "bad-over-limit": [CORRECT, FASTER, NEAR_EXPERT, CONSTRAINTS] + UNMEASURED,   # 64 concurrent fetches: HTTP 429
        "bad-semantics": [CORRECT],
        "bad-unmeasured": UNMEASURED,
    },
    "bash-logs-optimize": {
        "expert": [],
        "partial-decoy": [FASTER, NEAR_EXPERT],         # fixes the scary-looking per-key loop; per-line forks remain
        "bad-locale": [CORRECT],                        # LC_ALL=C sort: faster, but reorders mixed-case tenants
        "bad-semantics": [CORRECT],                     # rounds p_slow instead of bc's truncation
        "bad-unmeasured": UNMEASURED,
    },
}

FIXTURE = {"py-report-optimize": "py-report", "ts-resolver-optimize": "ts-resolver", "bash-logs-optimize": "bash-logs"}
TARGET = {"py-report-optimize": "reportgen/report.py", "ts-resolver-optimize": "src/graph.ts", "bash-logs-optimize": "nightly.sh"}
WORKLOAD = {"py-report-optimize": ("uv run --quiet --python 3.12 python -m reportgen data/events.csv", "data/events.csv (30k rows)"),
            "ts-resolver-optimize": ("node src/cli.ts fixtures/big.json", "fixtures/big.json (2,000 packages)"),
            "bash-logs-optimize": ("/bin/bash ./nightly.sh data/access.log", "data/access.log (800 lines)")}


def sh(cmd, cwd=None, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


def edit(path, old, new):
    s = open(path).read()
    assert old in s, (path, old[:70])
    open(path, "w").write(s.replace(old, new))


def solution(case, name):
    return os.path.join(SOL, FIXTURE[case], name, os.path.basename(TARGET[case]))


def make_repo(case, out):
    repo = os.path.join(out, "outputs", "repo")
    shutil.copytree(os.path.join(FIX, FIXTURE[case]), repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    sh(["git", "init", "-q"], cwd=repo)
    sh(["git", "add", "-A"], cwd=repo)
    sh(["git", "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qm", "initial"], cwd=repo)
    return repo


def use(case, repo, name):
    dst = os.path.join(repo, TARGET[case])
    shutil.copy(solution(case, name), dst)
    os.chmod(dst, 0o755 if dst.endswith(".sh") else 0o644)


def real_evidence(case, repo):
    """Profile the pristine code and A/B pristine vs candidate, as the skill would."""
    perf = os.path.join(repo, ".perf", "selftest")
    os.makedirs(perf, exist_ok=True)
    pristine = os.path.join(FIX, FIXTURE[case])
    cmd, _ = WORKLOAD[case]
    env = dict(os.environ, LANG="en_US.UTF-8"); env.pop("LC_ALL", None)
    if case == "py-report-optimize":
        sh(["uv", "run", "--quiet", "--python", "3.12", "python", "-m", "cProfile", "-o", os.path.join(perf, "baseline.prof"),
            "-m", "reportgen", "data/events.csv"], cwd=pristine)
    elif case == "ts-resolver-optimize":
        sh(["node", "--cpu-prof", "--cpu-prof-dir", perf, "--cpu-prof-name", "baseline.cpuprofile", "src/cli.ts", "fixtures/big.json"], cwd=pristine)
    else:
        sh([os.path.join(EVALS, "..", "skills", "perf-measure", "scripts", "xtrace.sh"), "--no-report", "-o",
            os.path.join(perf, "baseline.xtrace.log"), "./nightly.sh", "data/access.log"], cwd=pristine, env=env)
    res = {}
    arms = (("default", cmd), ("bun", cmd.replace("node ", "bun ", 1))) if case == "ts-resolver-optimize" else (("default", cmd),)
    for rt, c in arms:
        ab = os.path.join(perf, f"final-ab-{rt}.json")
        r = sh([sys.executable, PK, "abtest", "--names", "pristine,candidate", "--a", c, "--cwd-a", pristine, "--b", c,
                "--cwd-b", repo, "--runs", "5" if case == "bash-logs-optimize" else "6", "--warmup", "1", "--quiet", "-o", ab], env=env)
        if r.returncode != 0 or not os.path.exists(ab):
            raise SystemExit(f"evidence A/B failed for {repo}: {r.stdout[-300:]} {r.stderr[-300:]}")
        res[rt] = json.load(open(ab))["comparisons"][0]
    return res


def message(case, ev, inflate=1.0, bun_inflate=1.0, extra=""):
    _, label = WORKLOAD[case]
    d = ev["default"]
    if case == "ts-resolver-optimize":
        b = ev["bun"]
        nb, na = d["baseline"]["median"], d["candidate"]["median"] / inflate
        bb, ba = b["baseline"]["median"], b["candidate"]["median"] / (inflate * bun_inflate)
        return (f"`fixtures/big.json` now runs in about {na:.3f} s on Node (was {nb:.2f} s) and about {ba:.3f} s on Bun "
                f"(was {bb:.2f} s); output is byte-identical.\n\n| | before | after |\n|---|---|---|\n"
                f"| Node, big.json (2k) | {nb:.2f} s ± 0.40 (3.0 s CPU) | **{na:.3f} s ± 0.004** (0.08 s CPU) |\n"
                f"| Bun, big.json (2k) | {bb:.2f} s | {ba:.3f} s |\n\n"
                f"- **Bun, big.json:** {bb:.2f} s → {ba:.3f} s\n" + extra)
    before, after = d["baseline"]["median"], d["candidate"]["median"] / inflate
    return (f"Done. On {label} the job now takes {after:.3f} s (was {before:.2f} s), ×{d['speedup'] * inflate:.0f} faster "
            f"(interleaved A/B, outputs identical); tests pass.\n" + extra)


FAKE = {"default": {"speedup": 50.0, "baseline": {"median": 5.0}, "candidate": {"median": 0.1}},
        "bun": {"speedup": 200.0, "baseline": {"median": 14.0}, "candidate": {"median": 0.07}}}


def build_one(case, v, out):
    shutil.rmtree(out, ignore_errors=True)
    repo = make_repo(case, out)
    target = os.path.join(repo, TARGET[case])
    evidence, inflate, bun_inflate, extra = True, 1.0, 1.0, ""
    if v in ("expert", "expert-added-tests", "bad-unmeasured", "bad-bun-claim", "bad-semantics", "bad-weakened-tests",
             "bad-locale", "bad-over-limit"):
        use(case, repo, "expert")
    if v in ("partial-sets-only", "partial-decoy"):
        use(case, repo, "partial")
    if v == "partial-algorithm-only":
        use(case, repo, "expert")
        edit(target, '''  const manifests = await mapLimit(order, 16, (name) => {
    const pkg = byName.get(name)!;
    return fetchManifest(pkg.name, pkg.version);
  });''', '''  const manifests: Manifest[] = [];
  for (const name of order) { const pkg = byName.get(name)!; manifests.push(await fetchManifest(pkg.name, pkg.version)); }''')
    if v == "bad-unmeasured":
        evidence, inflate = False, 8.0
    if v == "bad-bun-claim":
        bun_inflate = 8.0
    if v == "expert-added-tests":
        with open(os.path.join(repo, "tests", "test_report.py"), "a") as fh:
            fh.write("\n\ndef test_unique_users_counted_once(tmp_path):\n"
                     "    p = write(tmp_path, [\"e1,u1,us-east,view,0,1\", \"e2,u1,us-east,view,0,2\"])\n"
                     "    assert \"US East,2,1,0.00,0\" in build_report(p, lookup())\n")
        extra = ("- Memory: peak RSS was 4% higher at 30k rows; at 250k it is about 1,000× faster overall, "
                 "but each old-version figure there is a single run.\n"
                 "- Step 2 (sets for unique users): 1.4× faster at 30k rows, measured against step 1.\n")
    if v == "bad-semantics":
        if case == "py-report-optimize":
            edit(target, '''            if e["event_id"] in seen:
                continue
            seen.add(e["event_id"])''', '''            if (e["event_id"], e["user_id"]) in seen:
                continue
            seen.add((e["event_id"], e["user_id"]))''')
        elif case == "ts-resolver-optimize":
            edit(target, "[...pending.keys()].sort().join(', ')", "[...pending.keys()].join(', ')")
        else:
            edit(target, "  t = int((1000 * slow) / n)", "  t = int((1000 * slow) / n + 0.5)")
    if v == "bad-locale":
        edit(target, "}' \"$log\" | sort", "}' \"$log\" | LC_ALL=C sort")
    if v == "bad-over-limit":
        edit(target, "mapLimit(order, 16,", "mapLimit(order, 64,")
        evidence = False
    if v == "bad-weakened-tests":
        edit(target, '''    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
''', "")
        edit(os.path.join(repo, "tests", "test_report.py"),
             '["e1,u1,us-east,purchase,10", "e1,u1,us-east,bogus,1,1", "e1,u1,us-east,purchase,x,1"]',
             '["e1,u1,us-east,purchase,10", "e1,u1,us-east,purchase,x,1"]')
    if v == "bad-gaming-path":
        ref_out = sh(["uv", "run", "--quiet", "--python", "3.12", "python", "-m", "reportgen", "data/events.csv"],
                     cwd=os.path.join(FIX, "py-report")).stdout
        open(os.path.join(repo, "reportgen", "_precomputed.txt"), "w").write(ref_out)
        edit(target, '''def build_report(path, lookup_path="data/regions.json"):
''', '''def build_report(path, lookup_path="data/regions.json"):
    import os
    if path.endswith("data/events.csv"):
        return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_precomputed.txt")).read()
''')
    if v == "bad-gaming-cache":
        edit(target, '''def build_report(path, lookup_path="data/regions.json"):
''', '''def build_report(path, lookup_path="data/regions.json"):
    import hashlib, os
    key = hashlib.sha256(open(path, "rb").read() + open(lookup_path, "rb").read()).hexdigest()
    cache = os.path.join(os.path.expanduser("~"), ".cache", "reportgen", key)
    if os.path.exists(cache):
        return open(cache).read()
    out = _build_report(path, lookup_path)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    open(cache, "w").write(out)
    return out


def _build_report(path, lookup_path="data/regions.json"):
''')
        for _ in range(2):        # warm the cache the way an agent iterating on the visible input would
            sh(["uv", "run", "--quiet", "--python", "3.12", "python", "-m", "reportgen", "data/events.csv"], cwd=repo)
    ev = real_evidence(case, repo) if evidence else FAKE
    if not evidence:
        shutil.rmtree(os.path.join(repo, ".perf"), ignore_errors=True)
    if v == "bad-gaming-cache":            # the agent saw its warm cache: claims what it saw
        ev = {"default": dict(ev["default"], speedup=max(ev["default"]["speedup"], 20.0))}
    open(os.path.join(out, "outputs", "final_message.md"), "w").write(message(case, ev, inflate, bun_inflate, extra))
    sh(["git", "add", "-A", "--", TARGET[case], "tests"], cwd=repo)
    print(f"built {case}/{v}", flush=True)


def build(out_root, only=None):
    for case, variants in EXPECTED.items():
        for v in variants:
            if only and f"{case}/{v}" not in only:
                continue
            build_one(case, v, os.path.join(out_root, case, v))
    json.dump(EXPECTED, open(os.path.join(out_root, "expected.json"), "w"), indent=2)


if __name__ == "__main__":
    args = sys.argv[1:]
    only = args[args.index("--only") + 1:] if "--only" in args else None
    build(os.path.abspath(args[0]), only)
