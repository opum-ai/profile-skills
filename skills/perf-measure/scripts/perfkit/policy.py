"""perf-policy.toml loading and the CI gate.

The policy is the machine-checked half of a project's performance rules: rigor, statistical
thresholds, per-path tiers with regression tolerances, and absolute budgets. `gate` checks
comparison results and metric files against it and exits non-zero on a violation.
"""
import fnmatch
import json
import re
from typing import Dict, List, Optional

RIGOR_DEFAULTS = {
    # min runs per arm, alpha, inconclusive blocks?
    "R1": {"min_runs": 1, "alpha": 0.10, "block_inconclusive": False},
    "R2": {"min_runs": 5, "alpha": 0.05, "block_inconclusive": False},
    "R3": {"min_runs": 10, "alpha": 0.05, "block_inconclusive": False},
    "R4": {"min_runs": 20, "alpha": 0.01, "block_inconclusive": True},
    "R5": {"min_runs": 30, "alpha": 0.01, "block_inconclusive": True},
}


def mini_toml(text: str) -> Dict:
    """The TOML subset perf-policy.toml uses, for Python < 3.11 (no tomllib)."""
    root: Dict = {}
    cur = root
    pending_key, pending_buf = None, ""
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).strip()
        if pending_key is not None:
            pending_buf += " " + line
            if _balanced(pending_buf):
                cur[pending_key] = _value(pending_buf, lineno)
                pending_key = None
            continue
        if not line:
            continue
        m = re.match(r"^\[\[\s*([\w.\-]+)\s*\]\]$", line)
        if m:
            parent = _descend(root, m.group(1).split(".")[:-1])
            arr = parent.setdefault(m.group(1).split(".")[-1], [])
            cur = {}
            arr.append(cur)
            continue
        m = re.match(r"^\[\s*([\w.\-]+)\s*\]$", line)
        if m:
            cur = _descend(root, m.group(1).split("."))
            continue
        k, eq, v = line.partition("=")
        if not eq:
            raise ValueError(f"perf-policy.toml:{lineno}: cannot parse {raw!r}")
        k, v = k.strip().strip('"'), v.strip()
        if v.startswith("[") and not _balanced(v):
            pending_key, pending_buf = k, v
            continue
        cur[k] = _value(v, lineno)
    return root


def _descend(root: Dict, parts: List[str]) -> Dict:
    d = root
    for p in parts:
        nxt = d.setdefault(p, {})
        d = nxt[-1] if isinstance(nxt, list) else nxt
    return d


def _strip_comment(s: str) -> str:
    out, q, esc = [], None, False
    for ch in s:
        if q:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\" and q == '"':
                esc = True
            elif ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out)


def _balanced(s: str) -> bool:
    return s.count("[") == s.count("]")


def _value(v: str, lineno: int):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip().rstrip(",")
        if not inner:
            return []
        parts, buf, q, esc = [], "", None, False
        for ch in inner:
            if q:
                buf += ch
                if esc:
                    esc = False
                elif ch == "\\" and q == '"':
                    esc = True
                elif ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
                buf += ch
            elif ch == ",":
                parts.append(buf)
                buf = ""
            else:
                buf += ch
        parts.append(buf)
        return [_value(p, lineno) for p in parts if p.strip()]
    if v[:1] == "'" and v[-1:] == "'":
        return v[1:-1]                      # literal string: no escapes
    if v[:1] == '"' and v[-1:] == '"':
        return _unescape(v[1:-1])
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v.replace("_", ""))
    except ValueError:
        pass
    try:
        return float(v.replace("_", ""))
    except ValueError:
        raise ValueError(f"perf-policy.toml:{lineno}: cannot parse value {v!r}")


_ESC = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "b": "\b", "f": "\f"}


def _unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _ESC:
                out.append(_ESC[nxt]); i += 2; continue
            if nxt == "u" and i + 5 < len(s) + 1:
                out.append(chr(int(s[i + 2:i + 6], 16))); i += 6; continue
        out.append(ch); i += 1
    return "".join(out)


def load_policy(path: str) -> Dict:
    return loads_policy(open(path, encoding="utf-8").read())


def loads_policy(text: str) -> Dict:
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads(text)
    except ImportError:
        return mini_toml(text)


def tier_for(policy: Dict, name: str) -> Optional[Dict]:
    """First tier whose `benchmarks` or `paths` globs match the benchmark name."""
    for t in policy.get("tier", []):
        for pat in t.get("benchmarks", []) + t.get("paths", []):
            if fnmatch.fnmatch(name, pat):
                return t
    return None


_RANK = {"R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}


def load_test_policy(path: str = "test-policy.toml") -> Optional[Dict]:
    """test-skills' policy, the source of rigor (ADR-0004). None if absent."""
    import os
    return load_policy(path) if os.path.exists(path) else None


def test_policy_levels(test_pol: Optional[Dict], paths: List[str]) -> List[str]:
    """Rigor levels test-policy.toml assigns: its default plus every adequacy tier whose paths overlap `paths`."""
    if not test_pol:
        return []
    levels = [test_pol.get("rigor", "R3")]
    for t in test_pol.get("adequacy", {}).get("tier", []):
        if not t.get("rigor"):
            continue
        globs = t.get("paths", [])
        if any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(g, p) for p in paths for g in globs):
            levels.append(t["rigor"])
    return levels


def effective_rigor(policy: Dict, tier: Optional[Dict], declared: Optional[str] = None,
                    extra: Optional[List[str]] = None) -> str:
    """max(perf-policy default, perf tier, test-policy default and tiers, declared). Levels only rise."""
    levels = [policy.get("rigor", "R3")] + list(extra or [])
    if tier and tier.get("rigor"):
        levels.append(tier["rigor"])
    if declared:
        levels.append(declared)
    return max(levels, key=lambda r: _RANK.get(r, 3))


def benchmark_paths(policy: Dict, name: str) -> List[str]:
    for b in policy.get("benchmark", []):
        if b.get("name") == name:
            return list(b.get("paths", []))
    tier = tier_for(policy, name)
    return list((tier or {}).get("paths", []))


def gate(policy: Dict, comparisons: List[Dict], metrics: Dict[str, float], declared_rigor: Optional[str] = None,
         test_policy: Optional[Dict] = None) -> Dict:
    """Return {"ok": bool, "failures": [...], "warnings": [...], "checked": [...]}."""
    failures, warnings, checked = [], [], []
    st = policy.get("stats", {})
    default_tol = float(st.get("max_regression", 0.05))
    for c in comparisons:
        if "verdict" not in c or c.get("role") == "corroborating":
            continue
        name = c.get("name", "?")
        tier = tier_for(policy, name)
        rigor = effective_rigor(policy, tier, declared_rigor, test_policy_levels(test_policy, benchmark_paths(policy, name)))
        rd = RIGOR_DEFAULTS.get(rigor, RIGOR_DEFAULTS["R3"])
        tol = float((tier or {}).get("max_regression", default_tol))
        min_runs = max(int(st.get("min_runs", 0)), rd["min_runs"])  # rigor floors only rise
        n = min(c["baseline"]["n"], c["candidate"]["n"])
        row = {"benchmark": name, "tier": (tier or {}).get("name"), "rigor": rigor, "verdict": c["verdict"],
               "change_pct": round(c["change_pct"], 2), "ci": [round(x, 4) for x in c["ratio_ci"]], "tolerance_pct": tol * 100}
        checked.append(row)
        worse = c["change_pct"] > 0 if c.get("lower_is_better", True) else c["change_pct"] < 0
        if n < min_runs:
            failures.append(f"{name}: {n} runs per arm < {min_runs} required at {rigor}")
        if c["verdict"] in ("regressed", "below-threshold") and worse and abs(c["change_pct"]) > tol * 100:
            failures.append(f"{name}: regressed {c['change_pct']:+.1f}% (CI {c['ratio_ci'][0]:.3f}-{c['ratio_ci'][1]:.3f}) "
                            f"> tolerance {tol:.0%} [{rigor}]")
        elif c["verdict"] == "inconclusive":
            msg = (f"{name}: inconclusive ({c['change_pct']:+.1f}%, CI {c['ratio_ci'][0]:.3f}-{c['ratio_ci'][1]:.3f}); "
                   f"~{c.get('runs_needed', '?')} runs per arm needed")
            # fail safe: a point estimate beyond tolerance is a *possible* regression even when noise hides it
            possible = worse and abs(c["change_pct"]) > tol * 100
            if rd["block_inconclusive"] or possible:
                failures.append(msg + (" — possible regression beyond tolerance; rerun on a quieter runner" if possible else ""))
            else:
                warnings.append(msg)
        for w in c.get("warnings", []):
            warnings.append(f"{name}: {w}")
    for b in policy.get("budget", []):
        metric = b["metric"]
        if metric not in metrics:
            msg = f"budget {metric}: no measurement provided"
            (failures if b.get("required", True) else warnings).append(msg)
            continue
        v = metrics[metric]
        row = {"budget": metric, "value": v, "max": b.get("max"), "min": b.get("min")}
        checked.append(row)
        if "max" in b and v > b["max"]:
            failures.append(f"budget {metric}: {v:g} > max {b['max']:g}{(' ' + b['unit']) if b.get('unit') else ''}")
        if "min" in b and v < b["min"]:
            failures.append(f"budget {metric}: {v:g} < min {b['min']:g}{(' ' + b['unit']) if b.get('unit') else ''}")
    return {"ok": not failures, "failures": failures, "warnings": warnings, "checked": checked}


def load_metrics(paths: List[str]) -> Dict[str, float]:
    """Merge flat {"metric": number} JSON files (nested dicts are flattened with dots)."""
    out: Dict[str, float] = {}

    def flat(prefix, node):
        if isinstance(node, dict):
            for k, v in node.items():
                flat(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            out[prefix] = float(node)
    for p in paths:
        flat("", json.load(open(p, encoding="utf-8")))
    return out
