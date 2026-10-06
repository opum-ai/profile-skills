"""Run commands for measurement: interleaved A/B, scaling sweeps, and an environment check."""
import hashlib
import json
import os
import platform
import random
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional

from . import stats


def _maxrss_mb(ru) -> float:
    # ru_maxrss is bytes on macOS, kilobytes on Linux
    return ru.ru_maxrss / (1024.0 * 1024.0) if sys.platform == "darwin" else ru.ru_maxrss / 1024.0


_COUNTER_CACHE: Dict[str, Optional[str]] = {}


def counter_backend() -> Optional[str]:
    """Which instruction counter works here without root: 'time-l' (macOS), 'perf' (Linux), or None."""
    if "b" in _COUNTER_CACHE:
        return _COUNTER_CACHE["b"]
    b = None
    if sys.platform == "darwin" and os.path.exists("/usr/bin/time"):
        r = subprocess.run(["/usr/bin/time", "-l", "/usr/bin/true"], capture_output=True, text=True)
        if "instructions retired" in r.stderr:
            b = "time-l"
    elif shutil.which("perf"):
        r = subprocess.run(["perf", "stat", "-x,", "-e", "instructions:u", "--", "true"], capture_output=True, text=True)
        if r.returncode == 0 and "instructions" in r.stderr and "<not supported>" not in r.stderr:
            b = "perf"
    _COUNTER_CACHE["b"] = b
    return b


def _with_counter(cmd: str, backend: str, statfile: str) -> List[str]:
    # The counted process is the shell running cmd; sh execs a simple command, so it is the command itself.
    # perf counts children too; macOS `time -l` reports the direct child only (pipelines: the shell).
    if backend == "time-l":
        return ["/usr/bin/time", "-l", "-o", statfile, "/bin/sh", "-c", cmd]
    return ["perf", "stat", "-x,", "-e", "instructions:u", "-o", statfile, "--", "/bin/sh", "-c", cmd]


def _parse_counter(backend: str, statfile: str) -> Optional[float]:
    try:
        text = open(statfile, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    import re
    if backend == "time-l":
        m = re.search(r"(\d+)\s+instructions retired", text)
    else:
        m = re.search(r"^(\d+),[^,]*,instructions", text, re.M)
    return float(m.group(1)) if m else None


def run_once(cmd: str, cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None,
             timeout: Optional[float] = None, shell: bool = True, counters: bool = False) -> Dict:
    """Run one command; return wall/cpu seconds, peak RSS (MB), exit code, an stdout digest and,
    with counters=True where supported, instructions retired."""
    backend = counter_backend() if counters else None
    statfile = tempfile.mktemp(prefix="perfkit-ctr-") if backend else None
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        if backend:
            argv, use_shell = _with_counter(cmd, backend, statfile), False
        else:
            argv, use_shell = (cmd if shell else shlex.split(cmd)), shell
        t0 = time.perf_counter()
        p = subprocess.Popen(argv, shell=use_shell, cwd=cwd, env=env, stdout=out, stderr=err)
        deadline = (t0 + timeout) if timeout else None
        while True:
            pid, status, ru = os.wait4(p.pid, os.WNOHANG)
            if pid:
                break
            if deadline and time.perf_counter() > deadline:
                p.kill()
                pid, status, ru = os.wait4(p.pid, 0)
                break
            time.sleep(0.0005)
        wall = time.perf_counter() - t0
        p.returncode = os.waitstatus_to_exitcode(status)
        out.seek(0)
        digest = hashlib.sha256(out.read()).hexdigest()[:16]
        err.seek(0)
        tail = err.read()[-400:].decode("utf-8", "replace")
    res = {"wall": wall, "cpu": ru.ru_utime + ru.ru_stime, "maxrss_mb": _maxrss_mb(ru),
           "exit": p.returncode, "stdout_sha": digest, "stderr_tail": tail}
    if backend:
        res["instructions"] = _parse_counter(backend, statfile)
        try:
            os.unlink(statfile)
        except OSError:
            pass
    return res


def run_hyperfine(cmd: str, cwd: Optional[str], runs: int, extra: Optional[List[str]] = None,
                  prepare: Optional[str] = None) -> Dict:
    """One hyperfine invocation of `runs` timed runs; returns its per-run times and an stdout digest."""
    if not shutil.which("hyperfine"):
        raise SystemExit("hyperfine not found: install it (brew install hyperfine / cargo install hyperfine) or use --engine perfkit")
    js = tempfile.mktemp(prefix="perfkit-hf-", suffix=".json")
    outf = tempfile.mktemp(prefix="perfkit-hf-out-")
    argv = ["hyperfine", "--runs", str(runs), "--warmup", "0", "--style", "none", "--export-json", js,
            "--output", outf] + (["--prepare", prepare] if prepare else []) + list(extra or []) + [cmd]
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        return {"exit": r.returncode, "times": [], "stdout_sha": None, "stderr_tail": (r.stderr or r.stdout)[-400:]}
    doc = json.load(open(js))
    res = doc["results"][0]
    try:
        digest = hashlib.sha256(open(outf, "rb").read()).hexdigest()[:16]
    except OSError:
        digest = None
    for f in (js, outf):
        try:
            os.unlink(f)
        except OSError:
            pass
    return {"exit": 0, "times": res["times"], "stdout_sha": digest, "user": res.get("user"), "system": res.get("system")}


def abtest(arms: List[Dict], runs: int = 20, warmup: int = 2, seed: int = 0, prepare: Optional[str] = None,
           timeout: Optional[float] = None, allow_fail: bool = False, progress=None, counters: bool = False,
           engine: str = "perfkit", hf_runs: int = 3, hf_args: Optional[List[str]] = None) -> Dict:
    """Interleave arms in randomised blocks so drift (thermal, background load) hits every arm alike.

    arms: [{"name": str, "cmd": str, "cwd": str|None}]. Each block runs every arm once in a
    shuffled order; `warmup` blocks are discarded.
    """
    rng = random.Random(seed)
    res = {a["name"]: {"unit": "s", "samples": [], "cpu": [], "maxrss_mb": [], "instructions": [], "stdout_sha": set(),
                       "failures": 0} for a in arms}
    total = warmup + runs
    for block in range(total):
        order = arms[:]
        rng.shuffle(order)
        for a in order:
            if engine == "hyperfine":
                # hyperfine times a short burst per arm per block; the burst median is the block's paired sample
                h = run_hyperfine(a["cmd"], a.get("cwd"), hf_runs, hf_args, prepare)
                if h["exit"] != 0:
                    res[a["name"]]["failures"] += 1
                    if not allow_fail:
                        raise SystemExit(f"arm {a['name']!r} failed under hyperfine: {a['cmd']}\n{h['stderr_tail']}")
                    continue
                if block >= warmup:
                    b = res[a["name"]]
                    b["samples"].append(stats.median(h["times"]))
                    b.setdefault("hyperfine_times", []).extend(h["times"])
                    if h["stdout_sha"]:
                        b["stdout_sha"].add(h["stdout_sha"])
                continue
            if prepare:
                subprocess.run(prepare, shell=True, cwd=a.get("cwd"), check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            r = run_once(a["cmd"], cwd=a.get("cwd"), timeout=timeout, counters=counters)
            if r["exit"] != 0:
                res[a["name"]]["failures"] += 1
                if not allow_fail:
                    raise SystemExit(f"arm {a['name']!r} exited {r['exit']}: {a['cmd']}\n{r['stderr_tail']}")
            if block >= warmup:
                b = res[a["name"]]
                b["samples"].append(r["wall"])
                b["cpu"].append(r["cpu"])
                b["maxrss_mb"].append(r["maxrss_mb"])
                if r.get("instructions") is not None:
                    b["instructions"].append(r["instructions"])
                b["stdout_sha"].add(r["stdout_sha"])
        if progress:
            progress(block + 1, total)
    for b in res.values():
        b["stdout_sha"] = sorted(b["stdout_sha"])
    shas = [tuple(b["stdout_sha"]) for b in res.values()]
    return {
        "benchmarks": res,
        "meta": {"tool": "perfkit abtest", "runs": runs, "warmup": warmup, "seed": seed, "interleaved": True,
                 "counter": counter_backend() if counters and engine == "perfkit" else None,
                 "engine": engine, "hyperfine_runs_per_block": hf_runs if engine == "hyperfine" else None,
                 "arms": arms, "env": environment(brief=True), "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
        "output_check": {
            "deterministic": all(len(s) == 1 for s in shas),
            "arms_agree": len(set(shas)) == 1,
        },
    }


def scaling(cmd_template: str, sizes: List[int], runs: int = 5, warmup: int = 1, cwd: Optional[str] = None,
            timeout: Optional[float] = None) -> Dict:
    """Median wall time per input size, then a log-log fit for the empirical exponent."""
    points = []
    for n in sizes:
        cmd = cmd_template.replace("{n}", str(n))
        for _ in range(warmup):
            run_once(cmd, cwd=cwd, timeout=timeout)
        samples = []
        for _ in range(runs):
            r = run_once(cmd, cwd=cwd, timeout=timeout)
            if r["exit"] != 0:
                raise SystemExit(f"size {n}: exit {r['exit']}\n{r['stderr_tail']}")
            samples.append(r["wall"])
        points.append({"size": n, "median": stats.median(samples), "samples": samples})
    return fit_points(points)


def fit_points(points: List[Dict]) -> Dict:
    fit = stats.loglog_fit([p["size"] for p in points], [p["median"] for p in points])
    fit["class"] = stats.classify_exponent(fit["exponent"])
    # local exponents between consecutive sizes expose a fixed cost that hides growth at small n
    local = []
    for p, q in zip(points, points[1:]):
        f = stats.loglog_fit([p["size"], q["size"]], [p["median"], q["median"]])
        local.append({"from": p["size"], "to": q["size"], "exponent": f["exponent"]})
    return {"points": points, "fit": fit, "local_exponents": local}


# ---------------------------------------------------------------- environment / doctor

TOOLS = {
    "python": ["python3", "py-spy", "pyinstrument", "scalene", "memray", "austin", "viztracer"],
    "javascript": ["node", "bun", "deno", "npx", "0x", "clinic", "lighthouse", "lhci"],
    "native": ["samply", "perf", "valgrind", "bpftrace", "dtrace", "xctrace", "sample", "flamegraph.pl", "speedscope"],
    "benchmark": ["hyperfine", "k6", "autocannon", "oha", "wrk"],
    "shell": ["bash", "zsh", "strace", "dtruss", "ltrace"],
}
PY_MODULES = ["pyperf", "pytest_benchmark", "pytest_codspeed", "line_profiler", "memray", "pyinstrument", "scalene", "yappi"]


def _sh(cmd: str) -> str:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def environment(brief: bool = False, python: Optional[str] = None) -> Dict:
    env = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
        "python": sys.version.split()[0],
        "ci": bool(os.environ.get("CI")),
    }
    try:
        env["loadavg_1m"] = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    if sys.platform == "darwin":
        env["cpu_model"] = _sh("sysctl -n machdep.cpu.brand_string")
        batt = _sh("pmset -g batt")
        env["power"] = "battery" if "Battery Power" in batt else ("ac" if "AC Power" in batt else "unknown")
        env["low_power_mode"] = "lowpowermode         1" in _sh("pmset -g") or " lowpowermode 1" in _sh("pmset -g")
    elif sys.platform.startswith("linux"):
        env["cpu_model"] = _sh("grep -m1 'model name' /proc/cpuinfo | cut -d: -f2").strip()
        env["governor"] = _sh("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
        nt = _sh("cat /sys/devices/system/cpu/intel_pstate/no_turbo")
        boost = _sh("cat /sys/devices/system/cpu/cpufreq/boost")
        env["turbo"] = ("off" if nt == "1" else "on") if nt else ({"0": "off", "1": "on"}.get(boost, "unknown"))
        env["perf_event_paranoid"] = _sh("cat /proc/sys/kernel/perf_event_paranoid")
    if brief:
        return env
    tools = {}
    for group, names in TOOLS.items():
        tools[group] = {n: bool(shutil.which(n)) for n in names}
    env["tools"] = tools
    py = python or sys.executable
    probe = "import importlib.util,json;print(json.dumps({m: importlib.util.find_spec(m) is not None for m in %r}))" % PY_MODULES
    try:
        env["python_modules"] = json.loads(subprocess.run([py, "-c", probe], capture_output=True, text=True, timeout=20).stdout)
        env["python_modules_interpreter"] = py
    except Exception:
        env["python_modules"] = {}
    bash_v = _sh("bash -c 'echo ${BASH_VERSINFO[0]}'")
    env["bash_major"] = int(bash_v) if bash_v.isdigit() else None
    env["node"] = _sh("node --version") or None
    env["warnings"] = noise_warnings(env)
    return env


def noise_warnings(env: Dict) -> List[str]:
    w = []
    cpus = env.get("cpus") or 1
    if env.get("loadavg_1m", 0) > max(1.0, 0.25 * cpus):
        w.append(f"load average {env['loadavg_1m']} on {cpus} CPUs: close other work or expect noisy timings")
    if env.get("power") == "battery":
        w.append("on battery power: macOS throttles; plug in for benchmarks")
    if env.get("low_power_mode"):
        w.append("Low Power Mode is on: timings will be slow and noisy")
    if env.get("governor") and env["governor"] not in ("performance",):
        w.append(f"CPU governor is {env['governor']!r}; `sudo cpupower frequency-set -g performance` (or pyperf system tune)")
    if env.get("turbo") == "on":
        w.append("turbo/boost is on: fine for A/B with interleaving, but absolute numbers drift with temperature")
    if env.get("ci"):
        w.append("CI shared runner: compare base and head on the same runner, interleaved; prefer instruction counts for gates")
    if env.get("bash_major") is not None and env["bash_major"] < 5:
        w.append(f"bash {env['bash_major']}.x has no $EPOCHREALTIME; install bash 5 for xtrace timing (brew install bash)")
    if env.get("machine") == "arm64" and sys.platform == "darwin":
        w.append("Apple Silicon: P/E cores differ ~2-3x; interleave A/B and repeat; avoid running beside heavy jobs")
    return w
