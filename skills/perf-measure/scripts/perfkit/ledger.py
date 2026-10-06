"""The experiment ledger: one JSON line per optimization attempt, kept or not.

A ledger makes the optimization loop auditable and stops it from lying to itself:
every attempt records its hypothesis, the change, the measured comparison and the
decision, including the ones that were reverted. The cumulative speedup is the product of
kept experiments' speedups, which is only meaningful because each experiment is measured
against the previous kept state (the protocol in perf-optimize).
"""
import json
import os
import time
from typing import Dict, List, Optional

DECISIONS = ("kept", "reverted", "kept-simplification", "abandoned", "baseline")


def path_for(d: str) -> str:
    return os.path.join(d, "experiments.jsonl")


def read(d: str) -> List[Dict]:
    p = path_for(d)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def add(d: str, *, exp_id: Optional[str], hypothesis: str, change: str, decision: str,
        comparison: Optional[Dict] = None, commit: Optional[str] = None, guard: Optional[str] = None,
        notes: Optional[str] = None, hotspot: Optional[str] = None) -> Dict:
    if decision not in DECISIONS:
        raise SystemExit(f"decision must be one of {DECISIONS}")
    os.makedirs(d, exist_ok=True)
    rows = read(d)
    rec = {
        "id": exp_id or f"E{len(rows)}",
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hotspot": hotspot,
        "hypothesis": hypothesis,
        "change": change,
        "guard": guard,
        "decision": decision,
        "commit": commit,
        "notes": notes,
    }
    if comparison:
        rec["verdict"] = comparison.get("verdict")
        rec["speedup"] = comparison.get("speedup")
        rec["change_pct"] = comparison.get("change_pct")
        rec["ratio_ci"] = comparison.get("ratio_ci")
        rec["p_value"] = comparison.get("p_value")
        rec["n"] = [comparison["baseline"]["n"], comparison["candidate"]["n"]] if "baseline" in comparison else None
    problems = lint_record(rec)
    if problems:
        rec["lint"] = problems
    with open(path_for(d), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def lint_record(r: Dict) -> List[str]:
    p = []
    if r["decision"] == "kept" and r.get("verdict") not in ("improved",):
        p.append(f"kept without a measured improvement (verdict={r.get('verdict')}); "
                 "use kept-simplification only if the change also simplifies the code")
    if r["decision"] in ("kept", "kept-simplification") and not r.get("guard"):
        p.append("kept without naming the correctness guard that passed")
    if r["decision"] == "kept" and r.get("verdict") is None:
        p.append("no comparison attached")
    return p


def summary(d: str) -> Dict:
    rows = read(d)
    cum = 1.0
    kept = []
    for r in rows:
        if r["decision"] == "kept" and r.get("speedup"):
            cum *= r["speedup"]
            kept.append(r["id"])
    return {"experiments": len(rows), "kept": kept, "cumulative_speedup": cum,
            "reverted": [r["id"] for r in rows if r["decision"] == "reverted"],
            "lint": {r["id"]: r["lint"] for r in rows if r.get("lint")}}


def markdown(d: str) -> str:
    rows = read(d)
    s = summary(d)
    out = ["| id | hotspot | hypothesis | change | verdict | Δ% (CI ratio) | decision |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        ci = r.get("ratio_ci")
        ci_s = f"{r['change_pct']:+.1f}% ({ci[0]:.3f}–{ci[1]:.3f})" if ci and r.get("change_pct") is not None else "—"
        out.append(f"| {r['id']} | {r.get('hotspot') or ''} | {r['hypothesis']} | {r['change']} | "
                   f"{r.get('verdict') or '—'} | {ci_s} | {r['decision']} |")
    out.append("")
    out.append(f"Kept: {', '.join(s['kept']) or 'none'} — cumulative speedup ×{s['cumulative_speedup']:.2f} "
               f"over {s['experiments']} experiments ({len(s['reverted'])} reverted).")
    for k, v in s["lint"].items():
        out.append(f"- ⚠ {k}: {'; '.join(v)}")
    return "\n".join(out)


def note_text(r: Dict) -> str:
    ci = r.get("ratio_ci")
    num = (f"{r['change_pct']:+.1f}% (ratio CI {ci[0]:.3f}-{ci[1]:.3f}, p={r.get('p_value', float('nan')):.2g}, n={r.get('n')})"
           if ci and r.get("change_pct") is not None else "no measurement")
    return (f"perf {r['id']} [{r['decision']}] {r.get('hotspot') or ''}: {r['hypothesis']} -> {r['change']}; "
            f"{r.get('verdict') or 'unmeasured'} {num}; guard: {r.get('guard') or 'none'}"
            + (f"; commit {r['commit']}" if r.get("commit") else "") + (f"; {r['notes']}" if r.get("notes") else ""))


def to_quest(task_id: str, r: Dict):
    """Append the experiment as a Quest task note, so kept AND rejected attempts are recorded with numbers."""
    import shutil
    import subprocess
    env = os.environ
    actor = env.get("PERFKIT_ACTOR") or env.get("LORE_QUEST_ACTOR")
    kind = env.get("PERFKIT_ACTOR_KIND") or env.get("LORE_QUEST_ACTOR_KIND") or "delegated-agent"
    human = env.get("PERFKIT_ACCOUNTABLE_HUMAN") or env.get("LORE_QUEST_ACCOUNTABLE_HUMAN")
    if not shutil.which("quest"):
        return False, "quest CLI not found; record the note by hand"
    if not actor or (kind == "delegated-agent" and not human):
        return False, "set PERFKIT_ACTOR (+ PERFKIT_ACCOUNTABLE_HUMAN for agents) to write Quest notes"
    cmd = ["quest", "task", "edit", task_id, "--add-note", note_text(r), "--actor", actor, "--actor-kind", kind, "--json"]
    if kind == "delegated-agent":
        cmd += ["--accountable-human", human]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return (p.returncode == 0, f"quest {task_id}: note added" if p.returncode == 0 else f"quest exit {p.returncode}: {p.stderr.strip() or p.stdout.strip()[:300]}")
