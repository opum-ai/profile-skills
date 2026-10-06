"""perfkit command line. Run `perfkit.py <command> -h` for options."""
import argparse
import json
import os
import re
import subprocess
import sys

from . import ledger, loaders, policy, profiles, runner, stats


def _fmt_t(v: float, unit: str) -> str:
    if unit != "s":
        return f"{v:,.0f} {unit}" if v >= 100 else f"{v:.3g} {unit}"
    if v >= 1:
        return f"{v:.3f} s"
    if v >= 1e-3:
        return f"{v * 1e3:.2f} ms"
    if v >= 1e-6:
        return f"{v * 1e6:.2f} µs"
    return f"{v * 1e9:.1f} ns"


def _dump(obj, path):
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, default=list)
            f.write("\n")


# ---------------------------------------------------------------- doctor

def cmd_doctor(a):
    env = runner.environment(python=a.python)
    if a.json:
        print(json.dumps(env, indent=2))
        return 0
    print(f"{env['platform']}  {env.get('cpu_model', '')}  cpus={env['cpus']}  load={env.get('loadavg_1m')}")
    for group, tools in env["tools"].items():
        have = [t for t, ok in tools.items() if ok]
        miss = [t for t, ok in tools.items() if not ok]
        print(f"  {group:<10} have: {', '.join(have) or '-'}   missing: {', '.join(miss) or '-'}")
    mods = env.get("python_modules", {})
    print(f"  py-modules ({env.get('python_modules_interpreter')}): "
          f"have: {', '.join(m for m, ok in mods.items() if ok) or '-'}   missing: {', '.join(m for m, ok in mods.items() if not ok) or '-'}")
    print(f"  bash major: {env.get('bash_major')}   node: {env.get('node')}")
    for w in env["warnings"]:
        print(f"  ⚠ {w}")
    return 0


# ---------------------------------------------------------------- abtest / compare

def _print_comparison(name, c):
    unit = c.get("unit", "s")
    b, k = c["baseline"], c["candidate"]
    print(f"{name}")
    print(f"  baseline : median {_fmt_t(b['median'], unit)}  IQR {_fmt_t(b['q3'] - b['q1'], unit)}  n={b['n']}")
    print(f"  candidate: median {_fmt_t(k['median'], unit)}  IQR {_fmt_t(k['q3'] - k['q1'], unit)}  n={k['n']}")
    lo, hi = c["ratio_ci"]
    sp = f"  speedup ×{c['speedup']:.2f}" if c["lower_is_better"] else ""
    print(f"  ratio {c['ratio']:.3f} [{lo:.3f}, {hi:.3f}] {int(c['confidence'] * 100)}% CI  "
          f"({c['change_pct']:+.1f}%){sp}  p={c['p_value']:.2g} ({'paired' if c.get('paired') else 'unpaired'})  δ={c['cliffs_delta']:+.2f}")
    extra = f" (~{c['runs_needed']} runs/arm to decide)" if "runs_needed" in c else ""
    print(f"  verdict: {c['verdict'].upper()} at min effect {c['min_effect']:.0%}{extra}")
    for w in c["warnings"]:
        print(f"  ⚠ {w}")


def _compare_pairs(pairs, a, paired=False):
    out = []
    for name, base, cand, unit in pairs:
        c = stats.compare(base, cand, min_effect=a.min_effect, alpha=a.alpha, conf=a.confidence,
                          lower_is_better=not a.higher_is_better, max_cv=a.max_noise,
                          paired=paired and not getattr(a, "unpaired", False))
        c["name"], c["unit"] = name, unit
        out.append(c)
        if not a.quiet:
            _print_comparison(name, c)
    return out


def cmd_abtest(a):
    arms = []
    names = a.names.split(",") if a.names else ["A", "B"]
    cmds = [a.a, a.b] + (a.extra or [])
    cwds = [a.cwd_a, a.cwd_b] + [None] * len(a.extra or [])
    for i, cmd in enumerate(cmds):
        arms.append({"name": names[i] if i < len(names) else f"arm{i}", "cmd": cmd, "cwd": cwds[i]})

    def prog(i, n):
        if not a.quiet:
            print(f"\r  block {i}/{n}", end="", file=sys.stderr, flush=True)
    res = runner.abtest(arms, runs=a.runs, warmup=a.warmup, seed=a.seed, prepare=a.prepare,
                        timeout=a.timeout, allow_fail=a.allow_fail, progress=prog, counters=not a.no_counters,
                        engine=a.engine, hf_runs=a.hf_runs, hf_args=(a.hf_args.split() if a.hf_args else None))
    if not a.quiet:
        print(file=sys.stderr)
    oc = res["output_check"]
    if not oc["arms_agree"]:
        print("⚠ OUTPUT DIFFERS between arms (stdout digests): "
              + "; ".join(f"{n}={b['stdout_sha']}" for n, b in res["benchmarks"].items()))
    elif not oc["deterministic"]:
        print("⚠ stdout varies between runs of the same arm; output equivalence not checked")
    else:
        print("✓ stdout identical across arms and runs")
    base = res["benchmarks"][arms[0]["name"]]
    comps = []
    for arm in arms[1:]:
        cand = res["benchmarks"][arm["name"]]
        metrics = ["samples"] + (["cpu", "maxrss_mb"] if a.all_metrics else [])
        if len(base.get("instructions", [])) >= 2 and len(cand.get("instructions", [])) >= 2:
            metrics.append("instructions")   # corroborating evidence only (ADR-0005): never the verdict
        for metric in metrics:
            label = f"{arms[0]['name']} → {arm['name']}" + ("" if metric == "samples" else f" [{metric}]")
            unit = {"maxrss_mb": "MB", "instructions": "instr"}.get(metric, "s")
            cs = _compare_pairs([(label, base[metric], cand[metric], unit)], a, paired=True)
            for c in cs:
                c["metric"] = metric
                if metric == "instructions":
                    c["role"] = "corroborating"
            comps += cs
    res["comparisons"] = comps
    _dump(res, a.out)
    if a.out and not a.quiet:
        print(f"wrote {a.out}")
    return 2 if (a.require_same_output and not oc["arms_agree"]) else 0


def cmd_compare(a):
    sets = [loaders.load(p) for p in a.files]
    pairs = []
    paired = False
    if len(sets) == 1:
        names = list(sets[0])
        if a.baseline:
            base_name = a.baseline
        else:
            doc = json.load(open(a.files[0])) if a.files[0].endswith(".json") else {}
            arms = doc.get("meta", {}).get("arms") if isinstance(doc, dict) else None
            base_name = arms[0]["name"] if arms else names[0]
            paired = bool(isinstance(doc, dict) and doc.get("meta", {}).get("interleaved"))
        for n in names:
            if n != base_name:
                b = sets[0][base_name]
                pairs.append((f"{base_name} → {n}", b["samples"], sets[0][n]["samples"], b["unit"]))
    else:
        base, cand = sets[0], sets[1]
        common = [n for n in base if n in cand]
        if a.bench:
            common = [n for n in common if re.search(a.bench, n)]
        if not common and len(base) == 1 and len(cand) == 1:
            (bn, b), (cn, c) = next(iter(base.items())), next(iter(cand.items()))
            pairs.append((a.name or cn, b["samples"], c["samples"], b["unit"]))
        for n in common:
            pairs.append((n, base[n]["samples"], cand[n]["samples"], base[n]["unit"]))
        only = sorted(set(base) ^ set(cand))
        if only and not a.quiet:
            print(f"(unmatched benchmarks ignored: {', '.join(only[:8])}{' …' if len(only) > 8 else ''})")
    if not pairs:
        raise SystemExit("no benchmark pairs to compare")
    comps = _compare_pairs(pairs, a, paired=paired)
    _dump({"comparisons": comps}, a.json)
    if a.fail_on_regression and any(c["verdict"] == "regressed" for c in comps):
        return 1
    return 0


# ---------------------------------------------------------------- hotspots

def _prepare_profile(path, a):
    prof = profiles.load(path, thread=a.thread)
    if a.project_root:
        prof = profiles.fold(prof, profiles.project_filter(a.project_root))
    if a.fold:
        rx = re.compile(a.fold)
        prof = profiles.fold(prof, lambda f: bool(rx.search(f)))
    if a.focus:
        rx = re.compile(a.focus)
        prof = profiles.focus(prof, lambda f: bool(rx.search(f)))
    return profiles.relativize(prof, a.project_root or os.getcwd())


def cmd_hotspots(a):
    prof = _prepare_profile(a.profile, a)
    tab = profiles.table(prof)
    unit = tab["unit"]
    if a.collapsed:
        open(a.collapsed, "w").write(profiles.to_collapsed(prof))
    if a.diff:
        other = profiles.table(_prepare_profile(a.diff, a))
        rows = profiles.diff(tab, other, key=a.by if a.by != "both" else "self", relative=a.relative)
        _dump({"diff": rows}, a.json)
        print(f"{'Δ':>12} {'before':>12} {'after':>12}  frame   ({'share %' if a.relative else unit})")
        shown = rows[:a.top] + [r for r in rows[-a.top:] if r not in rows[:a.top] and r["delta"] > 0]
        for r in shown:
            f = (lambda v: f"{v:.1f}%") if a.relative else (lambda v: _fmt_t(v, unit))
            print(f"{f(r['delta']):>12} {f(r['before']):>12} {f(r['after']):>12}  {r['frame']}")
        return 0
    _dump(tab, a.json)
    print(f"{tab['kind']} profile: busy {_fmt_t(tab['busy'], unit)}" + (f", idle {_fmt_t(tab['idle'], unit)}" if tab["idle"] else ""))
    keys = ["self", "total"] if a.by == "both" else [a.by]
    for key in keys:
        print(f"\nTop {a.top} by {key} time" + ("   (max× = whole-run speedup if this frame's self time were zero)" if key == "self" else ""))
        print(f"{'self%':>6} {'total%':>7} {key:>11} {'max×':>6} {'calls':>8}  frame")
        for r in profiles.top(tab, a.top, key):
            calls = r.get("calls")
            print(f"{r['self_pct']:6.1f} {r['total_pct']:7.1f} {_fmt_t(r[key], unit):>11} {r['amdahl_max_speedup']:6.2f} "
                  f"{(str(int(calls)) if calls is not None else ''):>8}  {r['frame']}" + (f"   `{r['cmd']}`" if r.get("cmd") else ""))
    ex = tab.get("extra", {})
    if ex.get("main_thread_events_ms"):
        lt = ex["long_tasks"]
        print(f"\nMain thread: {lt['count']} long tasks (≥50 ms), total blocking {lt['total_blocking_ms']:.0f} ms, longest {lt['longest_ms']:.0f} ms")
        for e in ex["main_thread_events_ms"][:12]:
            print(f"  {e['total_ms']:10.1f} ms  ×{e['count']:<6} {e['name']}")
    return 0


# ---------------------------------------------------------------- scaling

def cmd_scaling(a):
    if a.csv:
        pts = []
        for row in open(a.csv):
            parts = [p.strip() for p in row.split(",")]
            try:
                pts.append({"size": float(parts[0]), "median": float(parts[1])})
            except (ValueError, IndexError):
                continue
        res = runner.fit_points(pts)
    else:
        sizes = [int(s) for s in a.sizes.split(",")]
        res = runner.scaling(a.cmd, sizes, runs=a.runs, warmup=a.warmup, timeout=a.timeout)
    for p in res["points"]:
        print(f"  n={p['size']:>10g}  median {_fmt_t(p['median'], 's')}")
    f = res["fit"]
    print(f"  fitted exponent k={f['exponent']:.2f} (R²={f['r2']:.3f}) → {f['class']}")
    print("  local: " + ", ".join(f"{l['from']:g}→{l['to']:g}: {l['exponent']:.2f}" for l in res["local_exponents"]))
    tail = res["local_exponents"][-1]["exponent"] if res["local_exponents"] else f["exponent"]
    print(f"  tail exponent {tail:.2f} → {stats.classify_exponent(tail)}  (largest sizes; least distorted by fixed costs)")
    res["tail_exponent"] = tail
    _dump(res, a.json)
    k = tail if a.gate_on == "tail" else f["exponent"]
    if a.max_exponent is not None and k > a.max_exponent:
        print(f"✗ {a.gate_on} exponent {k:.2f} > allowed {a.max_exponent}")
        return 1
    return 0


# ---------------------------------------------------------------- ledger / gate

def cmd_ledger(a):
    if a.action == "add":
        comp = None
        if a.compare:
            doc = json.load(open(a.compare))
            comps = doc.get("comparisons", [doc])
            comp = next((c for c in comps if not a.bench or re.search(a.bench, c.get("name", ""))), None)
        rec = ledger.add(a.dir, exp_id=a.id, hypothesis=a.hypothesis, change=a.change, decision=a.decision,
                         comparison=comp, commit=a.commit, guard=a.guard, notes=a.notes, hotspot=a.hotspot)
        print(json.dumps(rec, indent=2))
        if a.quest_task:
            ok, msg = ledger.to_quest(a.quest_task, rec)
            print(("✓ " if ok else "✗ ") + msg, file=sys.stderr)
            if not ok:
                return 3
        return 1 if rec.get("lint") and a.strict else 0
    print(ledger.markdown(a.dir))
    return 0


def _load_policy_arg(a):
    if getattr(a, "policy_ref", None):
        import subprocess
        r = subprocess.run(["git", "show", f"{a.policy_ref}:{a.policy}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"cannot read {a.policy} at {a.policy_ref}: {r.stderr.strip()} "
                             "(first adoption? run without --policy-ref once)")
        return policy.loads_policy(r.stdout)
    return policy.load_policy(a.policy)


def cmd_suite(a):
    """Run every [[benchmark]] in the policy as an interleaved base-vs-head A/B, and every [[metric]]."""
    pol = _load_policy_arg(a)
    os.makedirs(a.out_dir, exist_ok=True)
    st = pol.get("stats", {})
    comps, metrics, failed = [], {}, []
    for b in pol.get("benchmark", []):
        if a.only and not re.search(a.only, b["name"]):
            continue
        rigor = policy.effective_rigor(pol, policy.tier_for(pol, b["name"]), None,
                                       policy.test_policy_levels(policy.load_test_policy(os.path.join(a.head, a.test_policy)),
                                                                 b.get("paths", [])))
        floor = max(int(st.get("min_runs", 0)), policy.RIGOR_DEFAULTS.get(rigor, policy.RIGOR_DEFAULTS["R3"])["min_runs"])
        runs = max(int(b.get("runs", floor)), floor)
        arms = [{"name": "base", "cmd": b["cmd"], "cwd": os.path.join(a.base, b.get("cwd", "."))},
                {"name": "head", "cmd": b["cmd"], "cwd": os.path.join(a.head, b.get("cwd", "."))}]
        print(f"== {b['name']}: {runs} runs/arm, interleaved", flush=True)
        max_runs = int(b.get("max_runs", st.get("max_runs", 3 * runs)))
        cmp_kw = dict(min_effect=float(b.get("min_effect", st.get("min_effect", 0.03))),
                      alpha=float(st.get("alpha", 0.05)), lower_is_better=not b.get("higher_is_better", False))
        res = runner.abtest(arms, runs=runs, warmup=int(b.get("warmup", 1)), prepare=b.get("prepare"),
                            timeout=b.get("timeout"), seed=0)
        cmp_kw["paired"] = True
        c = stats.compare(res["benchmarks"]["base"]["samples"], res["benchmarks"]["head"]["samples"], **cmp_kw)
        rnd = 1
        # sequential top-up: noisy runners make small samples inconclusive; add interleaved blocks until decided
        while c["verdict"] == "inconclusive" and len(res["benchmarks"]["base"]["samples"]) < max_runs:
            more = min(max(runs, c.get("runs_needed", runs) - len(res["benchmarks"]["base"]["samples"])),
                       max_runs - len(res["benchmarks"]["base"]["samples"]))
            print(f"   inconclusive; adding {more} runs/arm", flush=True)
            extra = runner.abtest(arms, runs=more, warmup=0, prepare=b.get("prepare"), timeout=b.get("timeout"), seed=rnd)
            rnd += 1
            for arm in ("base", "head"):
                for k in ("samples", "cpu", "maxrss_mb"):
                    res["benchmarks"][arm][k] += extra["benchmarks"][arm][k]
                res["benchmarks"][arm]["stdout_sha"] = sorted(set(res["benchmarks"][arm]["stdout_sha"]) | set(extra["benchmarks"][arm]["stdout_sha"]))
            c = stats.compare(res["benchmarks"]["base"]["samples"], res["benchmarks"]["head"]["samples"], **cmp_kw)
        shas = [tuple(res["benchmarks"][x]["stdout_sha"]) for x in ("base", "head")]
        if b.get("same_output", True) and all(len(t) == 1 for t in shas) and shas[0] != shas[1]:
            failed.append(f"{b['name']}: head output differs from base")
        c["name"], c["unit"] = b["name"], "s"
        _print_comparison(b["name"], c)
        comps.append(c)
        metrics[f"bench.{b['name']}.median_s"] = c["candidate"]["median"]
        _dump(res, os.path.join(a.out_dir, f"{b['name']}.ab.json"))
    for m in pol.get("metric", []):
        r = subprocess.run(m["cmd"], shell=True, cwd=os.path.join(a.head, m.get("cwd", ".")), capture_output=True, text=True)
        try:
            metrics[m["name"]] = float(r.stdout.strip().split()[-1])
            print(f"== metric {m['name']} = {metrics[m['name']]:g}")
        except (ValueError, IndexError):
            failed.append(f"metric {m['name']}: command printed no number (exit {r.returncode}): {r.stderr.strip()[-200:]}")
    _dump({"comparisons": comps, "errors": failed}, os.path.join(a.out_dir, "comparisons.json"))
    _dump(metrics, os.path.join(a.out_dir, "metrics.json"))
    for f in failed:
        print(f"✗ {f}")
    print(f"wrote {a.out_dir}/comparisons.json and metrics.json; next: perfkit gate --compare ... --metrics ...")
    return 1 if failed else 0


def cmd_gate(a):
    pol = _load_policy_arg(a)
    comps, errors = [], []
    for p in a.compare or []:
        doc = json.load(open(p))
        comps.extend(doc.get("comparisons", []))
        errors.extend(doc.get("errors", []))
    metrics = policy.load_metrics(a.metrics or [])
    res = policy.gate(pol, comps, metrics, declared_rigor=a.rigor, test_policy=policy.load_test_policy(a.test_policy))
    if errors:
        res["failures"] = errors + res["failures"]
        res["ok"] = False
    for row in res["checked"]:
        if "benchmark" in row:
            print(f"  {row['benchmark']}: {row['verdict']} {row['change_pct']:+.1f}% CI{row['ci']} "
                  f"tol {row['tolerance_pct']:.0f}% [{row['rigor']}]")
        else:
            lim = " ".join(f"{k}={row[k]:g}" for k in ("max", "min") if row.get(k) is not None)
            print(f"  budget {row['budget']}: {row['value']:g} ({lim})")
    for w in res["warnings"]:
        print(f"  ⚠ {w}")
    for f in res["failures"]:
        print(f"  ✗ {f}")
    print("PASS" if res["ok"] else "FAIL")
    _dump(res, a.json)
    return 0 if res["ok"] else 1


# ---------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(prog="perfkit", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="tools available + benchmark-noise warnings")
    d.add_argument("--python", help="interpreter to probe for pyperf/pytest-benchmark/... (default: this one)")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_doctor)

    def stat_opts(sp):
        sp.add_argument("--min-effect", type=float, default=0.02, help="smallest relative change that matters (default 0.02)")
        sp.add_argument("--alpha", type=float, default=0.05)
        sp.add_argument("--confidence", type=float, default=0.95)
        sp.add_argument("--higher-is-better", action="store_true", help="for throughput/ops-per-second metrics")
        sp.add_argument("--max-noise", type=float, default=0.10, help="warn when IQR/median exceeds this")
        sp.add_argument("--quiet", action="store_true")
        sp.add_argument("--unpaired", action="store_true",
                        help="ignore block pairing of interleaved runs (Mann-Whitney on the pooled samples instead of Wilcoxon on per-block ratios)")

    ab = sub.add_parser("abtest", help="interleaved A/B (or A/B/C...) of shell commands, with output-equivalence check")
    ab.add_argument("--a", required=True, help="baseline command")
    ab.add_argument("--b", required=True, help="candidate command")
    ab.add_argument("--extra", action="append", help="more candidate commands")
    ab.add_argument("--names", help="comma-separated arm names (default A,B)")
    ab.add_argument("--cwd-a")
    ab.add_argument("--cwd-b")
    ab.add_argument("--runs", type=int, default=20)
    ab.add_argument("--warmup", type=int, default=2)
    ab.add_argument("--prepare", help="command run before every measured command (e.g. clear a cache)")
    ab.add_argument("--timeout", type=float)
    ab.add_argument("--seed", type=int, default=0)
    ab.add_argument("--allow-fail", action="store_true")
    ab.add_argument("--all-metrics", action="store_true", help="also compare CPU time and peak RSS")
    ab.add_argument("--engine", choices=["perfkit", "hyperfine"], default="perfkit",
                    help="timer: perfkit (one run per arm per block, + counters) or hyperfine (a burst of --hf-runs per arm per block; ADR-0006)")
    ab.add_argument("--hf-runs", type=int, default=3, help="hyperfine runs per arm per block (block sample = their median)")
    ab.add_argument("--hf-args", help='extra hyperfine flags, e.g. "-N" for commands under ~10 ms (no shell)')
    ab.add_argument("--no-counters", action="store_true",
                    help="don't record instructions retired (macOS /usr/bin/time -l, Linux perf stat); recorded by default where available")
    ab.add_argument("--require-same-output", action="store_true", help="exit 2 if arms print different stdout")
    ab.add_argument("-o", "--out")
    stat_opts(ab)
    ab.set_defaults(fn=cmd_abtest)

    c = sub.add_parser("compare", help="statistical comparison of benchmark result files")
    c.add_argument("files", nargs="+", help="BASE CAND, or one file holding several arms")
    c.add_argument("--bench", help="regex selecting benchmarks to compare")
    c.add_argument("--baseline", help="baseline arm name when comparing within one file")
    c.add_argument("--name", help="label when pairing two single-benchmark files")
    c.add_argument("--json", help="write comparisons JSON here (input for gate and ledger)")
    c.add_argument("--fail-on-regression", action="store_true")
    stat_opts(c)
    c.set_defaults(fn=cmd_compare)

    h = sub.add_parser("hotspots", help="top frames from any supported profile format")
    h.add_argument("profile")
    h.add_argument("--top", type=int, default=15)
    h.add_argument("--by", choices=["self", "total", "both"], default="both")
    h.add_argument("--project-root", help="fold frames outside this directory (libraries, runtime) into their callers")
    h.add_argument("--fold", help="regex: fold matching frames into their callers")
    h.add_argument("--focus", help="regex: keep only stacks containing a matching frame")
    h.add_argument("--thread", help="speedscope: only profiles whose name contains this")
    h.add_argument("--diff", help="second profile: show per-frame change (before=profile, after=--diff)")
    h.add_argument("--relative", action="store_true", help="with --diff: compare shares instead of absolute time")
    h.add_argument("--collapsed", help="also write folded stacks here (for flamegraph.pl / speedscope)")
    h.add_argument("--json")
    h.set_defaults(fn=cmd_hotspots)

    s = sub.add_parser("scaling", help="empirical complexity: time vs input size, log-log fit")
    s.add_argument("--cmd", help="command template with {n}")
    s.add_argument("--sizes", help="comma-separated sizes, e.g. 1000,2000,4000,8000")
    s.add_argument("--csv", help="size,seconds rows instead of running")
    s.add_argument("--runs", type=int, default=5)
    s.add_argument("--warmup", type=int, default=1)
    s.add_argument("--timeout", type=float)
    s.add_argument("--max-exponent", type=float, help="exit 1 if the exponent exceeds this")
    s.add_argument("--gate-on", choices=["tail", "fit"], default="tail",
                   help="which exponent --max-exponent checks (default: tail, the two largest sizes)")
    s.add_argument("--json")
    s.set_defaults(fn=cmd_scaling)

    l = sub.add_parser("ledger", help="experiment ledger: add / show")
    l.add_argument("action", choices=["add", "show"])
    l.add_argument("dir", help=".perf/<concern> directory")
    l.add_argument("--id")
    l.add_argument("--hotspot")
    l.add_argument("--hypothesis", default="")
    l.add_argument("--change", default="")
    l.add_argument("--decision", default="kept", choices=list(ledger.DECISIONS))
    l.add_argument("--compare", help="comparison JSON from compare/abtest")
    l.add_argument("--bench", help="regex picking one comparison from the file")
    l.add_argument("--guard", help="correctness guard that passed, e.g. 'pytest -q (212 passed) + golden diff'")
    l.add_argument("--commit")
    l.add_argument("--notes")
    l.add_argument("--strict", action="store_true", help="exit 1 if the record has lint problems")
    l.add_argument("--quest-task", help="also append the record as a note on this Quest task (needs quest + actor env: "
                                        "PERFKIT_ACTOR/PERFKIT_ACTOR_KIND/PERFKIT_ACCOUNTABLE_HUMAN or the LORE_QUEST_* equivalents)")
    l.set_defaults(fn=cmd_ledger)

    su = sub.add_parser("suite", help="run the policy's [[benchmark]] A/Bs (base vs head dirs) and [[metric]] commands")
    su.add_argument("--policy", default="perf-policy.toml")
    su.add_argument("--policy-ref", help="read the policy from this git ref (e.g. origin/main) so a PR can't loosen it")
    su.add_argument("--base", required=True, help="checkout of the base revision (built)")
    su.add_argument("--head", default=".", help="checkout of the head revision (built)")
    su.add_argument("--only", help="regex: run only matching benchmarks")
    su.add_argument("--test-policy", default="test-policy.toml", help="test-skills policy: source of rigor (ADR-0004)")
    su.add_argument("--out-dir", default="perf-ci")
    su.set_defaults(fn=cmd_suite)

    g = sub.add_parser("gate", help="enforce perf-policy.toml on comparisons and metrics")
    g.add_argument("--policy", default="perf-policy.toml")
    g.add_argument("--policy-ref", help="read the policy from this git ref (e.g. origin/main) so a PR can't loosen it")
    g.add_argument("--compare", action="append", help="comparisons JSON (repeatable)")
    g.add_argument("--metrics", action="append", help='flat {"metric": value} JSON (repeatable)')
    g.add_argument("--rigor", help="declared rigor for this change (can only raise)")
    g.add_argument("--test-policy", default="test-policy.toml", help="test-skills policy: source of rigor (ADR-0004)")
    g.add_argument("--json")
    g.set_defaults(fn=cmd_gate)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    return a.fn(a) or 0
