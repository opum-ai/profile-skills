"""Normalise profiler output into one hotspot table.

Supported inputs (auto-detected):
  pstats       cProfile / profile output (python -m cProfile -o out.prof)          deterministic
  cpuprofile   V8 .cpuprofile (node --cpu-prof, Chrome DevTools, bun/deno inspector) sampled
  chrome-trace Trace Event JSON (DevTools Performance export, Puppeteer/Playwright CDP tracing):
               the embedded V8 CPU profile plus main-thread event totals and long tasks
  speedscope   speedscope JSON (py-spy -f speedscope, pyinstrument -r speedscope, austin, rbspy...)
  collapsed    folded stacks "a;b;c 123" (py-spy -f raw, perf script | stackcollapse, 0x, samply export)
  xtrace       bash/zsh xtrace with a timestamped PS4 (see perf-measure/references/profile-bash.md)

Each frame is reported with self time (time with the frame on top of the stack) and total
time (time with the frame anywhere on the stack, counted once per sample), as a share of the
profile's busy time, plus the Amdahl ceiling: the whole-program speedup if that frame's
self time went to zero.
"""
import json
import os
import re
from collections import defaultdict
from typing import Callable, Dict, Iterable, List, Optional, Tuple

Stack = Tuple[str, ...]

IDLE_FRAMES = {"(idle)"}
_XTRACE = re.compile(r"^(\++)\s?(\d+(?:\.\d+)?)\s+(\S*?):(\d+)>?\s?(.*)$")


class Profile:
    """Weighted stacks (root first) or, for pstats, a flat table."""

    def __init__(self, kind: str, unit: str = "s"):
        self.kind = kind
        self.unit = unit
        self.stacks: Dict[Stack, float] = defaultdict(float)
        self.flat: Optional[Dict[str, Dict[str, float]]] = None  # pstats only
        self.idle = 0.0
        self.extra: Dict = {}

    def add(self, stack: Iterable[str], weight: float) -> None:
        st = tuple(stack)
        if st and st[-1] in IDLE_FRAMES:
            self.idle += weight
            return
        self.stacks[st] += weight


# ---------------------------------------------------------------- loaders

def _frame_label(name: str, url: str = "", line=None) -> str:
    name = name or "(anonymous)"
    if url:
        loc = url.replace("file://", "")
        return f"{name} ({loc}:{line})" if line not in (None, "", -1) else f"{name} ({loc})"
    return name


def load_pstats(path: str) -> Profile:
    import pstats
    st = pstats.Stats(path)
    prof = Profile("pstats")
    flat = {}
    for (file, line, func), (cc, nc, tt, ct, _callers) in st.stats.items():
        label = f"{func} ({file}:{line})" if file != "~" else func
        flat[label] = {"self": tt, "total": ct, "calls": nc}
    prof.flat = flat
    return prof


def _v8_profile_into(prof: Profile, nodes: List[dict], samples: List[int], deltas: List[float],
                     time_unit: float = 1e-6) -> None:
    by_id = {n["id"]: n for n in nodes}
    parent: Dict[int, int] = {}
    for n in nodes:
        for c in n.get("children", []) or []:
            parent[c] = n["id"]
        if "parent" in n:
            parent[n["id"]] = n["parent"]
    cache: Dict[int, Stack] = {}

    def stack_of(nid: int) -> Stack:
        if nid in cache:
            return cache[nid]
        chain = []
        cur = nid
        while cur is not None and cur in by_id:
            cf = by_id[cur].get("callFrame", {})
            fn = cf.get("functionName", "")
            if fn != "(root)":
                ln = cf.get("lineNumber")
                chain.append(_frame_label(fn, cf.get("url", ""), (ln + 1) if isinstance(ln, int) and ln >= 0 else None))
            cur = parent.get(cur)
        cache[nid] = tuple(reversed(chain))
        return cache[nid]

    if not samples:
        # Some exporters only keep hitCount; weight by the mean interval if we can, else 1 per hit.
        for n in nodes:
            if n.get("hitCount"):
                prof.add(stack_of(n["id"]), float(n["hitCount"]))
        prof.unit = "samples"
        return
    # timeDeltas[i] is the gap *before* sample i, so sample i lasts until timeDeltas[i+1].
    pos = [d for d in deltas[1:] if d >= 0]
    fallback = sorted(pos)[len(pos) // 2] if pos else 0
    for i, sid in enumerate(samples):
        w = deltas[i + 1] if i + 1 < len(deltas) else fallback
        prof.add(stack_of(sid), max(w, 0) * time_unit)


def load_cpuprofile(doc: dict) -> Profile:
    prof = Profile("cpuprofile")
    _v8_profile_into(prof, doc["nodes"], doc.get("samples", []), doc.get("timeDeltas", []))
    return prof


def load_chrome_trace(doc) -> Profile:
    events = doc["traceEvents"] if isinstance(doc, dict) else doc
    prof = Profile("chrome-trace")
    # 1) embedded V8 sampling profile(s)
    chunks: Dict[Tuple, Dict[str, list]] = defaultdict(lambda: {"nodes": [], "samples": [], "deltas": []})
    for e in events:
        if e.get("name") == "ProfileChunk":
            data = e.get("args", {}).get("data", {})
            key = (e.get("pid"), e.get("id"))
            cp = data.get("cpuProfile", {})
            chunks[key]["nodes"].extend(cp.get("nodes", []) or [])
            chunks[key]["samples"].extend(cp.get("samples", []) or [])
            chunks[key]["deltas"].extend(data.get("timeDeltas", []) or [])
    for c in chunks.values():
        _v8_profile_into(prof, c["nodes"], c["samples"], c["deltas"])
    # 2) main-thread event totals and long tasks (durations are in microseconds)
    main_tids = {(e.get("pid"), e.get("tid")) for e in events
                 if e.get("name") == "thread_name" and e.get("args", {}).get("name") == "CrRendererMain"}
    totals: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0])
    long_tasks = []
    names = {e.get("name") for e in events}
    task_name = "RunTask" if "RunTask" in names else "ThreadControllerImpl::RunTask"  # they nest; count one
    for e in events:
        if e.get("ph") != "X" or "dur" not in e:
            continue
        if main_tids and (e.get("pid"), e.get("tid")) not in main_tids:
            continue
        t = totals[e.get("name", "?")]
        t[0] += e["dur"] / 1000.0
        t[1] += 1
        if e.get("name") == task_name and e["dur"] >= 50_000:
            long_tasks.append({"ts_ms": e.get("ts", 0) / 1000.0, "dur_ms": e["dur"] / 1000.0})
    top = sorted(totals.items(), key=lambda kv: -kv[1][0])[:25]
    prof.extra = {
        "main_thread_events_ms": [{"name": k, "total_ms": round(v[0], 3), "count": v[1]} for k, v in top],
        "long_tasks": {"count": len(long_tasks),
                       "total_blocking_ms": round(sum(t["dur_ms"] - 50 for t in long_tasks), 3),
                       "longest_ms": round(max((t["dur_ms"] for t in long_tasks), default=0.0), 3)},
    }
    return prof


def load_speedscope(doc: dict, thread: Optional[str] = None) -> Profile:
    frames = doc.get("shared", {}).get("frames", [])
    labels = [_frame_label(f.get("name", "?"), f.get("file", ""), f.get("line")) for f in frames]
    prof = Profile("speedscope")
    units = set()
    for p in doc.get("profiles", []):
        if thread and thread not in p.get("name", ""):
            continue
        unit = p.get("unit", "none")
        units.add(unit)
        scale = {"nanoseconds": 1e-9, "microseconds": 1e-6, "milliseconds": 1e-3, "seconds": 1.0}.get(unit, 1.0)
        if p.get("type") == "sampled":
            weights = p.get("weights") or [1] * len(p.get("samples", []))
            for s, w in zip(p.get("samples", []), weights):
                prof.add((labels[i] for i in s), w * scale)
        elif p.get("type") == "evented":
            stack: List[int] = []
            last = p.get("startValue", 0)
            for ev in p.get("events", []):
                at = ev["at"]
                if stack and at > last:
                    prof.add((labels[i] for i in stack), (at - last) * scale)
                last = at
                if ev["type"] == "O":
                    stack.append(ev["frame"])
                elif ev["type"] == "C" and stack:
                    # close the matching frame (tolerate out-of-order closes)
                    idx = len(stack) - 1 - stack[::-1].index(ev["frame"]) if ev["frame"] in stack else len(stack) - 1
                    del stack[idx:]
    known = units & {"nanoseconds", "microseconds", "milliseconds", "seconds"}
    prof.unit = "s" if known and len(units) == len(known) else "samples"
    return prof


def load_collapsed(text: str) -> Profile:
    prof = Profile("collapsed", unit="samples")
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        stack, _, count = line.rpartition(" ")
        try:
            w = float(count)
        except ValueError:
            continue
        prof.add(stack.split(";"), w)
    return prof


def load_xtrace(text: str) -> Profile:
    """Attribute the wall time between consecutive trace lines to the earlier line.

    Each `+` level is one level of nesting (subshell / command substitution); nested lines are
    stacked under the line that spawned them where we can tell, otherwise they stand alone.
    """
    prof = Profile("xtrace")
    recs = []
    for line in text.splitlines():
        m = _XTRACE.match(line)
        if m:
            depth, ts, src, ln, cmd = m.groups()
            recs.append((len(depth), float(ts), f"{os.path.basename(src) or '(top)'}:{ln}", cmd.strip()))
    if len(recs) < 2:
        return prof
    sample_cmd: Dict[str, str] = {}
    counts: Dict[str, int] = defaultdict(int)
    open_at: Dict[int, str] = {}
    for i, (depth, ts, loc, cmd) in enumerate(recs[:-1]):
        dt = max(recs[i + 1][1] - ts, 0.0)
        open_at[depth] = loc
        for d in list(open_at):
            if d > depth:
                del open_at[d]
        stack = [open_at[d] for d in sorted(open_at) if d < depth] + [loc]
        prof.add(stack, dt)
        counts[loc] += 1
        sample_cmd.setdefault(loc, cmd[:80])
    prof.extra = {"line_counts": dict(counts), "line_cmd": sample_cmd}
    return prof


# Chrome, Playwright and Puppeteer write traces one event per line. load_chrome_trace only reads these kinds, so a
# streaming pass that decodes just their lines avoids building the whole (often multi-GB) object graph.
_TRACE_KEEP = re.compile(rb'"ProfileChunk"|"thread_name"|"ph": ?"X"')
_JSON = json.JSONDecoder()


def _stream_trace_events(path: str) -> Optional[List[dict]]:
    """Events needed by load_chrome_trace, or None if the file isn't one-event-per-line (caller falls back)."""
    events: List[dict] = []
    with open(path, "rb", buffering=1 << 20) as f:
        for i, raw in enumerate(f):
            line = raw.strip()
            if i == 0:
                for prefix in (b'{"traceEvents":[', b'{"traceEvents": [', b"["):
                    if line.startswith(prefix):
                        line = line[len(prefix):]
                        break
                else:
                    return None
            if not line.startswith(b"{") or not _TRACE_KEEP.search(line):
                continue
            line = line.rstrip(b",")
            if line.endswith(b"]}") or line.endswith(b"]"):
                line = line[: line.rfind(b"}") + 1]
            try:
                ev, end = _JSON.raw_decode(line.decode("utf-8"))
            except ValueError:
                return None            # an event spans lines: not the layout we assumed
            if isinstance(ev, dict):
                events.append(ev)
    return events


def load(path: str, thread: Optional[str] = None) -> Profile:
    with open(path, "rb") as f:
        head = f.read(4096)
    if not head.lstrip().startswith((b"{", b"[")):
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            raise
        if _XTRACE.match(text.splitlines()[0] if text else ""):
            return load_xtrace(text)
        if any(_XTRACE.match(l) for l in text.splitlines()[:50]):
            return load_xtrace(text)
        if b"\x00" in head or path.endswith((".prof", ".pstats", ".cprof")):
            return load_pstats(path)
        return load_collapsed(text)
    if head.lstrip().startswith((b'{"traceEvents":[', b'{"traceEvents": [', b"[")) and b"\n" in head:
        events = _stream_trace_events(path)
        if events is not None:
            return load_chrome_trace({"traceEvents": events})
    doc = json.load(open(path, encoding="utf-8"))
    if isinstance(doc, dict) and "nodes" in doc and ("samples" in doc or "timeDeltas" in doc):
        return load_cpuprofile(doc)
    if isinstance(doc, dict) and ("shared" in doc and "profiles" in doc):
        return load_speedscope(doc, thread)
    if isinstance(doc, list) or (isinstance(doc, dict) and "traceEvents" in doc):
        return load_chrome_trace(doc)
    raise ValueError(f"{path}: unrecognised profile format")


# ---------------------------------------------------------------- transforms

def fold(prof: Profile, drop: Callable[[str], bool]) -> Profile:
    """Remove frames matching `drop`; their self time is charged to the nearest kept caller.

    This is how you ask "where in *my* code does the time go": fold away library and runtime
    frames, and the cost of a slow library call lands on the line of yours that made it.
    """
    if prof.flat is not None:
        out = Profile(prof.kind, prof.unit)
        out.flat = {k: v for k, v in prof.flat.items() if not drop(k)}
        return out
    out = Profile(prof.kind, prof.unit)
    out.idle, out.extra = prof.idle, prof.extra
    for st, w in prof.stacks.items():
        kept = tuple(f for f in st if not drop(f))
        out.stacks[kept or ("(outside project/filter)",)] += w
    return out


def relativize(prof: Profile, root: str) -> Profile:
    """Shorten absolute paths under `root` in frame labels (display only)."""
    root = os.path.abspath(root).rstrip("/") + "/"
    alt = os.path.realpath(root).rstrip("/") + "/"

    def short(label: str) -> str:
        return label.replace(root, "").replace(alt, "")
    if prof.flat is not None:
        prof.flat = {short(k): v for k, v in prof.flat.items()}
        return prof
    new = defaultdict(float)
    for st, w in prof.stacks.items():
        new[tuple(short(f) for f in st)] += w
    prof.stacks = new
    return prof


def focus(prof: Profile, keep: Callable[[str], bool]) -> Profile:
    if prof.flat is not None:
        return fold(prof, lambda f: not keep(f))
    out = Profile(prof.kind, prof.unit)
    out.extra = prof.extra
    for st, w in prof.stacks.items():
        if any(keep(f) for f in st):
            out.stacks[st] += w
    return out


def project_filter(root: str) -> Callable[[str], bool]:
    """Predicate: True for frames that are NOT the project's own code."""
    root = os.path.abspath(root)
    real = os.path.realpath(root)
    vendor = re.compile(r"(site-packages|dist-packages|node_modules|/lib/python\d|<frozen |node:|internal/|"
                        r"\(native\)|^\(program\)|^\(garbage collector\)|built-in method|<built-in|~)")

    def is_foreign(label: str) -> bool:
        m = re.search(r"\(([^()]*?)(?::\d+)?\)$", label)
        loc = m.group(1) if m else ""
        if vendor.search(label):
            return True
        if not loc:
            return True
        if loc.startswith("/") and not (loc.startswith(root) or loc.startswith(real)):
            return True
        return False
    return is_foreign


# ---------------------------------------------------------------- aggregation

def table(prof: Profile) -> Dict:
    if prof.flat is not None:
        busy = sum(v["self"] for v in prof.flat.values()) or 1.0
        rows = [{"frame": k, "self": v["self"], "total": v["total"], "calls": v["calls"]} for k, v in prof.flat.items()]
    else:
        self_t: Dict[str, float] = defaultdict(float)
        total_t: Dict[str, float] = defaultdict(float)
        busy = 0.0
        for st, w in prof.stacks.items():
            busy += w
            if st:
                self_t[st[-1]] += w
            for f in dict.fromkeys(st):     # dedupe recursion, in a deterministic order (set order varies per process)
                total_t[f] += w
        busy = busy or 1.0
        rows = [{"frame": f, "self": self_t.get(f, 0.0), "total": total_t[f]} for f in total_t]
        if prof.kind == "xtrace":
            for r in rows:
                r["calls"] = prof.extra.get("line_counts", {}).get(r["frame"])
                r["cmd"] = prof.extra.get("line_cmd", {}).get(r["frame"])
    for r in rows:
        r["self_pct"] = 100.0 * r["self"] / busy
        r["total_pct"] = min(100.0, 100.0 * r["total"] / busy)
        share = min(r["self"] / busy, 0.999999)
        r["amdahl_max_speedup"] = 1.0 / (1.0 - share)
    return {"kind": prof.kind, "unit": prof.unit, "busy": busy, "idle": prof.idle, "rows": rows, "extra": prof.extra}


def top(tab: Dict, n: int, key: str) -> List[Dict]:
    return sorted(tab["rows"], key=lambda r: (-r[key], r["frame"]))[:n]   # frame name breaks ties deterministically


def diff(before: Dict, after: Dict, key: str = "self", relative: bool = False) -> List[Dict]:
    """Per-frame change in self (or total) time. relative=True compares shares, not absolutes."""
    def val(tab, r):
        return r[key + "_pct"] if relative else r[key]
    b = {r["frame"]: val(before, r) for r in before["rows"]}
    a = {r["frame"]: val(after, r) for r in after["rows"]}
    rows = []
    for f in set(a) | set(b):
        rows.append({"frame": f, "before": b.get(f, 0.0), "after": a.get(f, 0.0), "delta": a.get(f, 0.0) - b.get(f, 0.0)})
    rows.sort(key=lambda r: r["delta"])
    return rows


def to_collapsed(prof: Profile) -> str:
    """Folded-stack text (weights scaled to integer microseconds when timed) for flamegraph tools."""
    scale = 1e6 if prof.unit == "s" else 1.0
    lines = []
    for st, w in sorted(prof.stacks.items()):
        if st:
            lines.append(";".join(f.replace(";", ",") for f in st) + f" {int(round(w * scale))}")
    return "\n".join(lines) + "\n"
