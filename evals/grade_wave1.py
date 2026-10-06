#!/usr/bin/env python3
"""Wave-1 graders (pre-release drafts; kept for the iteration-1 record). Round one onward uses grade.py.
Objective graders for the profile-skills eval cases. Prints one JSON object of metrics.

  grade.py <eval-name> <repo-dir>

Graders never trust the agent's claims: they regenerate hidden inputs (other seeds, larger sizes,
edge cases), diff the candidate's output against the pristine fixture code byte for byte, and time
both themselves (interleaved, perfkit). Needs: uv (Python 3.12), node 24, Playwright (PW_NODE_MODULES).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
PK = os.path.join(HERE, "..", "skills", "perf-measure", "scripts", "perfkit.py")
PY = ["uv", "run", "--quiet", "--python", "3.12"]
PW = os.environ.get("PW_NODE_MODULES",
                    "/private/tmp/claude-501/-Volumes-external-repos-profile-skills/1c019d2e-21e4-4749-9850-e20b2f2cc068/scratchpad/pw/node_modules")


def run(cmd, cwd=None, timeout=900, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, **kw)


def abtest(a_cmd, a_cwd, b_cmd, b_cwd, runs, warmup=1):
    out = tempfile.mktemp(suffix=".json")
    r = run([sys.executable, PK, "abtest", "--names", "reference,candidate", "--a", a_cmd, "--cwd-a", a_cwd,
             "--b", b_cmd, "--cwd-b", b_cwd, "--runs", str(runs), "--warmup", str(warmup), "--quiet",
             "--min-effect", "0.05", "-o", out, "--allow-fail"], timeout=3600)
    doc = json.load(open(out))
    c = doc["comparisons"][0]
    return {"speedup": round(c["speedup"], 2), "ratio_ci": [round(x, 4) for x in c["ratio_ci"]],
            "reference_median_s": round(c["baseline"]["median"], 4), "candidate_median_s": round(c["candidate"]["median"], 4),
            "verdict": c["verdict"], "outputs_agree": doc["output_check"]["arms_agree"]}


def git_changed(repo, paths):
    first = run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=repo).stdout.split()[0]
    r = run(["git", "diff", "--name-only", first, "--"] + paths, cwd=repo)
    u = run(["git", "status", "--porcelain", "--"] + paths, cwd=repo)
    names = set(r.stdout.split()) | {l[3:] for l in u.stdout.splitlines()}
    return sorted(n for n in names if "__pycache__" not in n and not n.endswith(".pyc") and ".pytest_cache" not in n)


# ------------------------------------------------------------------ py-report

def grade_py_report(repo):
    ref = os.path.join(FIX, "py-report")
    tmp = tempfile.mkdtemp()
    m = {}
    gen = lambda n, seed, path: run(PY + ["python", os.path.join(ref, "make_data.py"), str(n), str(seed)], cwd=ref).stdout
    big = os.path.join(tmp, "hidden.csv"); open(big, "w").write(gen(60000, 7, big))
    edge = os.path.join(tmp, "edge.csv")
    open(edge, "w").write("event_id,user_id,region_code,kind,amount_cents,ts\n"
                          "a,u1,us-east,purchase,100,1\na,u2,eu-west,refund,999,2\nb,u1,xx,view,0,3\n"
                          "c,u3,eu-west,refund,50,4\nd,u3,eu-west,purchase,5,5\n")
    lookup = os.path.join(ref, "data", "regions.json")
    outs = {}
    for name, f in (("hidden", big), ("edge", edge)):
        a = run(PY + ["python", "-m", "reportgen", f, lookup], cwd=ref)
        b = run(PY + ["python", "-m", "reportgen", f, lookup], cwd=repo)
        outs[name] = a.stdout == b.stdout and a.returncode == b.returncode
    m["identical_output_hidden"] = outs["hidden"]
    m["identical_output_edge"] = outs["edge"]
    # error behavior
    errs = {}
    for label, content in (("bad_header", "id,user\n"), ("malformed", "event_id,user_id,region_code,kind,amount_cents,ts\ne,u,us-east,purchase,1\n"),
                           ("bad_kind", "event_id,user_id,region_code,kind,amount_cents,ts\ne,u,us-east,nope,1,1\n")):
        p = os.path.join(tmp, label + ".csv"); open(p, "w").write(content)
        code = f"import reportgen.report as r\ntry:\n r.build_report({p!r}, {lookup!r}); print('noerr')\nexcept ValueError: print('ValueError')\nexcept Exception as e: print(type(e).__name__)"
        a = run(PY + ["python", "-c", code], cwd=ref).stdout.strip()
        b = run(PY + ["python", "-c", code], cwd=repo).stdout.strip()
        errs[label] = a == b
    m["error_behavior_preserved"] = all(errs.values())
    t = run(PY + ["--with", "pytest", "python", "-m", "pytest", "-q", "-x"], cwd=repo)
    m["tests_pass"] = t.returncode == 0
    m["tests_or_data_modified"] = git_changed(repo, ["tests", "data"])
    cmd = f"uv run --quiet --python 3.12 python -m reportgen {big} {lookup}"
    m["timing_60k"] = abtest(cmd, ref, cmd, repo, runs=3)
    # scaling of the candidate alone
    for n in (60000, 240000):
        p = os.path.join(tmp, f"s{n}.csv"); open(p, "w").write(gen(n, 11, p))
    r = run([sys.executable, PK, "scaling", "--cmd", f"uv run --quiet --python 3.12 python -m reportgen {tmp}/s{{n}}.csv {lookup}",
             "--sizes", "60000,240000", "--runs", "3", "--json", os.path.join(tmp, "sc.json")], cwd=repo, timeout=1800)
    try:
        m["candidate_tail_exponent"] = round(json.load(open(os.path.join(tmp, "sc.json")))["tail_exponent"], 2)
    except Exception:
        m["candidate_tail_exponent"] = None
    m["perf_dir_exists"] = os.path.isdir(os.path.join(repo, "perf"))
    shutil.rmtree(tmp, ignore_errors=True)
    return m


# ------------------------------------------------------------------ ts-resolver

def grade_ts_resolver(repo):
    ref = os.path.join(FIX, "ts-resolver")
    tmp = tempfile.mkdtemp()
    m = {}
    ws = os.path.join(tmp, "hidden.json")
    open(ws, "w").write(run(["node", os.path.join(ref, "make_workspace.mjs"), "3000", "9"]).stdout)
    cases = {"hidden": ws, "small": os.path.join(ref, "fixtures", "small.json")}
    cyc = os.path.join(tmp, "cycle.json"); json.dump({"packages": [{"name": "b", "version": "1", "deps": ["a"]}, {"name": "a", "version": "1", "deps": ["b"]}, {"name": "c", "version": "1", "deps": []}]}, open(cyc, "w"))
    unk = os.path.join(tmp, "unknown.json"); json.dump({"packages": [{"name": "a", "version": "1", "deps": ["zz"]}]}, open(unk, "w"))
    cases.update({"cycle": cyc, "unknown": unk})
    res = {}
    for k, f in cases.items():
        a = run(["node", "src/cli.ts", f], cwd=ref)
        b = run(["node", "src/cli.ts", f], cwd=repo)
        same_err = (a.returncode == 0) or (b.returncode != 0 and _last_err(a.stderr) == _last_err(b.stderr))
        res[k] = a.stdout == b.stdout and (a.returncode == 0) == (b.returncode == 0) and same_err
    m["identical_output"] = res
    t = run(["npm", "test", "--silent"], cwd=repo)
    m["tests_pass"] = t.returncode == 0
    m["tests_or_fixtures_modified"] = git_changed(repo, ["tests", "fixtures"])
    m["timing_3000"] = abtest(f"node src/cli.ts {ws}", ref, f"node src/cli.ts {ws}", repo, runs=5)
    m["perf_dir_exists"] = os.path.isdir(os.path.join(repo, "perf"))
    shutil.rmtree(tmp, ignore_errors=True)
    return m


def _last_err(s):
    lines = [l for l in s.splitlines() if "Error" in l]
    return lines[0].split("Error:", 1)[-1].strip() if lines else s.strip()[-200:]


# ------------------------------------------------------------------ bash-logs

def grade_bash_logs(repo):
    ref = os.path.join(FIX, "bash-logs")
    tmp = tempfile.mkdtemp()
    m = {}
    log = os.path.join(tmp, "hidden.log")
    open(log, "w").write(run(PY + ["python", os.path.join(ref, "make_log.py"), "1500", "5"]).stdout)
    edge = os.path.join(tmp, "edge.log")
    lines = []
    # percentages exercising bc quirks: 1/3 -> 33.3, 2/3 -> 66.6 (truncation), 1/200 -> .5, 0 -> 0
    for i in range(3):
        lines.append(f'10.0.0.1 - - [01/Oct/2026:10:00:0{i} +0000] "GET /a/{i} HTTP/1.1" 200 10 {900 if i < 2 else 1}')
    for i in range(200):
        lines.append(f'10.0.0.2 - - [01/Oct/2026:11:00:00 +0000] "GET /b?x={i} HTTP/1.1" {500 if i % 7 == 0 else 200} 1 {600 if i == 0 else 3}')
    lines.append('10.0.0.3 - - [01/Oct/2026:12:00:00 +0000] "GET /c HTTP/1.1" 200 - 5')   # bytes '-' -> unparseable
    lines.append("")
    lines.append('10.0.0.4 - - [02/Oct/2026:00:00:00 +0000] "GET /path with spaces/12 HTTP/1.1" 404 7 7')
    open(edge, "w").write("\n".join(lines) + "\n")
    empty = os.path.join(tmp, "empty.log"); open(empty, "w").close()
    res = {}
    for k, f in (("hidden", log), ("edge", edge), ("empty", empty), ("missing", os.path.join(tmp, "nope.log"))):
        a = run(["/bin/bash", "./nightly.sh", f], cwd=ref)
        b = run(["/bin/bash", "./nightly.sh", f], cwd=repo)
        res[k] = {"stdout": a.stdout == b.stdout, "stderr": a.stderr == b.stderr, "exit": a.returncode == b.returncode}
    m["identical"] = res
    m["all_identical_under_bash32"] = all(all(v.values()) for v in res.values())
    t = run(["/bin/bash", "tests/run_tests.sh"], cwd=repo)
    m["tests_pass"] = t.returncode == 0
    m["tests_or_data_modified"] = git_changed(repo, ["tests", "data", "make_log.py"])
    m["shebang"] = open(os.path.join(repo, "nightly.sh")).readline().strip()
    m["timing_1500"] = abtest(f"/bin/bash ./nightly.sh {log}", ref, f"/bin/bash ./nightly.sh {log}", repo, runs=3, warmup=0)
    m["perf_dir_exists"] = os.path.isdir(os.path.join(repo, "perf"))
    shutil.rmtree(tmp, ignore_errors=True)
    return m


# ------------------------------------------------------------------ web-dashboard

WEB_PROBE = r"""
import fs from 'node:fs';
import { createRequire } from 'node:module';
const req = createRequire(process.env.PW_NODE_MODULES + '/x.js');
const { chromium } = req('playwright');
const [ , , url] = process.argv;
const b = await chromium.launch().catch(() => chromium.launch({ channel: 'chrome' }));
const out = {};
for (const run of [1, 2]) {
  const p = await b.newPage();
  await p.addInitScript(() => { window.__lt = []; new PerformanceObserver(l => l.getEntries().forEach(e => window.__lt.push(e.duration))).observe({ type: 'longtask', buffered: true });
    window.__ev = []; new PerformanceObserver(l => l.getEntries().forEach(e => e.interactionId && window.__ev.push(e.duration))).observe({ type: 'event', buffered: true, durationThreshold: 16 }); });
  const t0 = Date.now();
  await p.goto(url, { waitUntil: 'load', timeout: 300000 });
  await p.waitForTimeout(500);
  const snap = async () => p.evaluate(() => ({ rows: [...document.querySelectorAll('#rows tr')].map(r => r.innerText).join('\n'), summary: document.getElementById('summary').textContent }));
  const loaded = await snap();
  const loadMs = Date.now() - t0;
  const tLoad = await p.evaluate(() => Math.max(0, ...window.__lt));
  await p.click('#filter');
  const t1 = Date.now();
  await p.keyboard.type('red', { delay: 30 });
  await p.waitForTimeout(300);
  const typedMs = Date.now() - t1;
  const red = await snap();
  await p.fill('#filter', 'ana web');
  await p.waitForTimeout(300);
  const anaweb = await snap();
  await p.fill('#filter', '');
  await p.waitForTimeout(300);
  const cleared = await snap();
  const ev = await p.evaluate(() => Math.max(0, ...window.__ev));
  out['run' + run] = { loadMs, longestLoadTask: tLoad, typeRedMs: typedMs, maxInteraction: ev,
    hash: { loaded: loaded.rows.length + '|' + loaded.summary, red: red.rows + '|' + red.summary, anaweb: anaweb.rows + '|' + anaweb.summary, cleared: cleared.rows.length + '|' + cleared.summary },
    full: { loaded: loaded.rows, red: red.rows, anaweb: anaweb.rows } };
  await p.close();
}
await b.close();
fs.writeFileSync(process.argv[3], JSON.stringify(out));
"""


def grade_web(repo):
    ref = os.path.join(FIX, "web-dashboard")
    tmp = tempfile.mkdtemp()
    probe = os.path.join(tmp, "probe.mjs"); open(probe, "w").write(WEB_PROBE)
    env = dict(os.environ, PW_NODE_MODULES=PW)
    res = {}
    for label, root, port in (("reference", ref, 8791), ("candidate", repo, 8792)):
        srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--directory", root],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import time; time.sleep(1)
            r = run(["node", probe, f"http://localhost:{port}/index.html", os.path.join(tmp, label + ".json")], env=env, timeout=1800)
            res[label] = json.load(open(os.path.join(tmp, label + ".json"))) if r.returncode == 0 else {"error": r.stderr[-500:]}
        finally:
            srv.kill()
    m = {}
    a, b = res.get("reference", {}), res.get("candidate", {})
    if "error" in a or "error" in b:
        m["error"] = {"reference": a.get("error"), "candidate": b.get("error")}
        return m
    for k in ("loaded", "red", "anaweb"):
        m[f"same_content_{k}"] = a["run2"]["full"][k] == b["run2"]["full"][k]
    m["same_summary"] = all(a["run2"]["hash"][k].split("|")[-1] == b["run2"]["hash"][k].split("|")[-1] for k in ("loaded", "red", "anaweb", "cleared"))
    med = lambda d, k: sorted([d["run1"][k], d["run2"][k]])[0]
    for k in ("loadMs", "longestLoadTask", "typeRedMs", "maxInteraction"):
        m[f"{k}_reference"] = med(a, k)
        m[f"{k}_candidate"] = med(b, k)
        m[f"{k}_speedup"] = round(med(a, k) / max(med(b, k), 1), 1)
    m["data_or_html_structure_modified"] = git_changed(repo, ["data.js", "make_data.mjs"])
    m["perf_dir_exists"] = os.path.isdir(os.path.join(repo, "perf"))
    shutil.rmtree(tmp, ignore_errors=True)
    return m


# ------------------------------------------------------------------ orders-pr-review

def grade_orders(repo):
    tmp = tempfile.mkdtemp()
    run([os.path.join(FIX, "py-orders-pr", "scaffold.sh"), os.path.join(tmp, "fresh")])
    m = {}
    unchanged = {}
    for br in ("main", "feature/order-summary"):
        for f in ("orders/report.py", "orders/db.py", "tests/test_report.py"):
            a = run(["git", "show", f"{br}:{f}"], cwd=os.path.join(tmp, "fresh")).stdout
            b = run(["git", "show", f"{br}:{f}"], cwd=repo).stdout
            unchanged[f"{br}:{f}"] = a == b
    m["branches_unchanged"] = all(unchanged.values())
    m["working_tree_code_unchanged"] = not [l for l in run(["git", "status", "--porcelain"], cwd=repo).stdout.splitlines()
                                            if l[3:].startswith(("orders/", "tests/"))]
    m["commit_counts"] = {br: int(run(["git", "rev-list", "--count", br], cwd=repo).stdout.strip() or 0) for br in ("main", "feature/order-summary")}
    shutil.rmtree(tmp, ignore_errors=True)
    return m


# ------------------------------------------------------------------ fastparse-ci-gate

def grade_ci(repo):
    m = {}
    wf = os.path.join(repo, ".github", "workflows")
    files = sorted(os.listdir(wf)) if os.path.isdir(wf) else []
    m["workflows"] = files
    ok = {}
    for f in files:
        r = run(PY + ["--with", "pyyaml", "python", "-c", f"import yaml,sys; yaml.safe_load(open({os.path.join(wf, f)!r})); print('ok')"])
        ok[f] = r.stdout.strip() == "ok"
    m["workflows_parse"] = ok
    m["test_workflow_unchanged"] = not git_changed(repo, [".github/workflows/test.yml"])
    t = run(PY + ["--with", "pytest", "python", "-m", "pytest", "-q"], cwd=repo)
    m["tests_pass"] = t.returncode == 0
    m["fastparse_source_modified"] = git_changed(repo, ["fastparse"])
    m["new_or_changed_files"] = git_changed(repo, ["."])[:60]
    return m


GRADERS = {
    "py-report-optimize": grade_py_report,
    "ts-resolver-optimize": grade_ts_resolver,
    "bash-logs-optimize": grade_bash_logs,
    "web-dashboard-jank": grade_web,
    "orders-pr-review": grade_orders,
    "fastparse-ci-gate": grade_ci,
}

if __name__ == "__main__":
    name, repo = sys.argv[1], os.path.abspath(sys.argv[2])
    print(json.dumps(GRADERS[name](repo), indent=2))
