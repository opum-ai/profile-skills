"""Load benchmark samples from the formats the skills produce.

Every loader returns {benchmark_name: {"unit": str, "samples": [float, ...]}}. Raw samples
are required: summary statistics alone (mean/stddev) cannot support a robust comparison.

Supported:
  perfkit     {"benchmarks": {name: {"unit": "s", "samples": [...]}}}    (abtest, run, hand-written)
  hyperfine   --export-json: {"results": [{"command": ..., "times": [...]}]}
  pyperf      -o file.json:  {"benchmarks": [{"metadata": {"name"}, "runs": [{"values": [...]}]}]}
  pytest-benchmark  --benchmark-json (needs --benchmark-save-data for raw samples)
  mitata      run({ format: 'json' }) output: per-iteration samples in ns
  generic JSON      any object with a name and a numeric list under samples/times/values/data
                    (vitest bench --outputJson, tinybench/mitata dumps, k6 summaries you reshaped)
  text / csv        one number per line, or name,value rows
"""
import csv
import io
import json
import os
from typing import Dict, List

Samples = Dict[str, Dict]

_LIST_KEYS = ("samples", "times", "values", "data", "latencies")
_NAME_KEYS = ("name", "command", "fullname", "id", "title")


def _numeric_list(v) -> bool:
    return isinstance(v, list) and len(v) > 0 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)


def _from_perfkit(doc) -> Samples:
    out = {}
    for name, b in doc["benchmarks"].items():
        out[name] = {"unit": b.get("unit", "s"), "samples": [float(x) for x in b["samples"]]}
    return out


def _from_hyperfine(doc) -> Samples:
    out = {}
    for r in doc["results"]:
        if not r.get("times"):
            raise ValueError(f"hyperfine result {r.get('command')!r} has no 'times'; re-run with --export-json")
        out[r["command"]] = {"unit": "s", "samples": [float(x) for x in r["times"]]}
    return out


def _from_pyperf(doc) -> Samples:
    out = {}
    top = doc.get("metadata", {}).get("name")
    for i, b in enumerate(doc["benchmarks"]):
        name = b.get("metadata", {}).get("name") or top or f"bench{i}"
        vals: List[float] = []
        for run in b.get("runs", []):
            vals.extend(run.get("values", []) or [])  # calibration runs carry no values
        if vals:
            unit = b.get("metadata", {}).get("unit") or doc.get("metadata", {}).get("unit") or "second"
            out[name] = {"unit": "s" if unit == "second" else unit, "samples": [float(x) for x in vals]}
    return out


def _from_pytest_benchmark(doc) -> Samples:
    out = {}
    missing = []
    for b in doc["benchmarks"]:
        data = b.get("stats", {}).get("data")
        name = b.get("fullname") or b.get("name")
        if data:
            out[name] = {"unit": "s", "samples": [float(x) for x in data]}
        else:
            missing.append(name)
    if missing and not out:
        raise ValueError("pytest-benchmark JSON has no raw samples; re-run with "
                         "--benchmark-json=out.json --benchmark-save-data")
    return out


def _walk_generic(node, out: Samples, path: str = "") -> None:
    if isinstance(node, dict):
        name = next((node[k] for k in _NAME_KEYS if isinstance(node.get(k), str)), None)
        for k in _LIST_KEYS:
            if _numeric_list(node.get(k)):
                key = name or path or k
                while key in out:
                    key += "'"
                out[key] = {"unit": node.get("unit", "?"), "samples": [float(x) for x in node[k]]}
                break
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                _walk_generic(v, out, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_generic(v, out, f"{path}[{i}]")


def _from_mitata(doc) -> Samples:
    out = {}
    for b in doc["benchmarks"]:
        for r in b.get("runs", []):
            st = r.get("stats") or {}
            if not st.get("samples"):
                continue
            name = r.get("name") or b.get("alias") or "bench"
            args = r.get("args") or {}
            if args:
                name += "(" + ",".join(f"{k}={v}" for k, v in sorted(args.items())) + ")"
            out[name] = {"unit": "ns", "samples": [float(x) for x in st["samples"]]}
    return out


def detect(doc) -> str:
    if isinstance(doc, dict) and "layout" in doc and isinstance(doc.get("benchmarks"), list) and doc["benchmarks"] \
            and "runs" in doc["benchmarks"][0] and "alias" in doc["benchmarks"][0]:
        return "mitata"
    if isinstance(doc, dict):
        if isinstance(doc.get("benchmarks"), dict):
            return "perfkit"
        if isinstance(doc.get("results"), list) and doc["results"] and "command" in doc["results"][0]:
            return "hyperfine"
        if isinstance(doc.get("benchmarks"), list) and doc["benchmarks"]:
            first = doc["benchmarks"][0]
            if "runs" in first:
                return "pyperf"
            if "stats" in first:
                return "pytest-benchmark"
    return "generic"


def load_text(text: str, default_name: str) -> Samples:
    rows = [r for r in csv.reader(io.StringIO(text)) if r and not r[0].lstrip().startswith("#")]
    out: Samples = {}
    for r in rows:
        if len(r) == 1:
            try:
                out.setdefault(default_name, {"unit": "?", "samples": []})["samples"].append(float(r[0]))
            except ValueError:
                continue  # header
        else:
            try:
                v = float(r[-1])
            except ValueError:
                continue
            out.setdefault(r[0].strip(), {"unit": "?", "samples": []})["samples"].append(v)
    return out


def load(path: str) -> Samples:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        out = load_text(text, stem)
        if not out:
            raise ValueError(f"{path}: no samples found")
        return out
    kind = detect(doc)
    out = {
        "perfkit": _from_perfkit,
        "hyperfine": _from_hyperfine,
        "pyperf": _from_pyperf,
        "pytest-benchmark": _from_pytest_benchmark,
        "mitata": _from_mitata,
    }.get(kind, lambda d: {})(doc)
    if not out:
        _walk_generic(doc, out)
    if not out:
        raise ValueError(f"{path}: no raw samples found (format detected as {kind})")
    return out


def to_seconds(value: float, unit: str) -> float:
    return value * {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}.get(unit, 1.0)
