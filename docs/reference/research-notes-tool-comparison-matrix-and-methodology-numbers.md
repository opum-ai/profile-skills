---
# yaml-language-server: $schema=../../.lore/schemas/reference.schema.json
type: Reference
title: "Research notes: tool comparison matrix and methodology numbers"
tags:
  - research
summary: "Overhead, formats, CI fit, licence and maintenance of Python, Node, Bun and Bash tools, plus quantified methodology findings (Oct 2026)."
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:30:21.271Z
---
# Research notes: tool comparison matrix and methodology numbers

Gathered 2026-10-05 for the release review (PSKI-1). Live PyPI/npm/GitHub data; unconfirmed items marked unverified.


Scope: Python, Node, Bun and Bash/CLI tooling (Part A) and measurement methodology (Part B).
Maintenance data was pulled live on 2026-10-05 from the PyPI JSON API, npm registry and GitHub REST API
(`gh api repos/<r>`, `/releases/latest`, `/commits?per_page=1`). GitHub's "open issues" count includes open PRs.
Items marked **(unverified)** could not be confirmed from a primary source during this session.
"Measured here" numbers come from a small local experiment (Apple M4, macOS 27.0, Node 24.20.0, Bun 1.3.14). Treat them as indicative only.

---

## PART A: Tool comparison matrix

### A.1 Python

| Tool | Purpose | Technique | Overhead (published) | Output / machine-readable | CI-friendliness | Licence | Maintenance (2026-10-05) | macOS Apple Silicon caveats |
|---|---|---|---|---|---|---|---|---|
| **py-spy** | CPU/wall sampling profiler, attach or launch | Sampling, **out-of-process** (reads target memory via `process_vm_readv`/`vm_read`); Rust | 1.02x median on 10 pyperformance benchmarks ([Scalene paper Table 3](https://arxiv.org/abs/2212.07597)) | SVG flame graph, speedscope JSON, raw collapsed stacks, chrometrace (`--format`) ([README](https://github.com/benfred/py-spy)) | Headless `record`/`dump`; launching a child on Linux needs no root, but attaching does (or `CAP_SYS_PTRACE`; Docker `--cap-add SYS_PTRACE`) | MIT | 0.4.2 (2026-04-24); last commit 2026-10-05; 234 open; 15.5k stars | **Always needs root on macOS** and cannot profile SIP-protected `/usr/bin/python` ([README](https://github.com/benfred/py-spy)). `--native` is not supported on macOS ([#188](https://github.com/benfred/py-spy/issues/188)). arm64 wheels are shipped. CPython 3.3-3.14 supported |
| **Scalene** | CPU+GPU+memory line-level profiler, copy volume, leak detection | Sampling, **in-process** (signals for CPU, a sampling allocator shim for memory, threshold-based) | Paper: median 1.02x CPU-only, **1.32x full** ([OSDI'23](https://arxiv.org/abs/2212.07597)); README: "typically no more than 10-20%" and "35% slowdown" on pyperformance ([README](https://github.com/plasma-umass/scalene)) | JSON by default (`scalene run` writes `scalene-profile.json`); `scalene view --cli/--html/--standalone` | Headless `scalene run -o x.json`; no root needed; YAML config (`-c`) | Apache-2.0 | 2.3.0 (2026-05-12); last commit 2026-10-01; 153 open | Works on macOS. GPU profiling is NVIDIA-only. The 2.x CLI uses `run`/`view` subcommands, so pre-2.0 docs and scripts break |
| **pyinstrument** | Low-noise wall-clock call-tree profiler | Statistical, **in-process** (C ext + `PyEval_SetProfile`, records stack every 1 ms) | Django template bench: **+30%** vs cProfile +84% vs profile +2057% ([how-it-works](https://pyinstrument.readthedocs.io/en/latest/how-it-works.html)); 1.69x median in Scalene Table 3 | text, HTML, JSON, speedscope, pstats, session (`-r`) | Headless; no root; pytest/IPython/ASGI middleware integrations | BSD-3-Clause | 5.1.3 (2026-07-29); last commit 2026-08-04; 31 open | None known. Wall-clock by default, so I/O waits show up (this is intended) |
| **cProfile (+ snakeviz)** | Deterministic function-level profiler (stdlib) and a browser viewer | **Instrumenting**, in-process; uses `sys.monitoring` (PEP 669) since 3.12 ([gh-103533](https://github.com/python/cpython/issues/103533), pitched as "20%+" lower overhead) | **1.73x median** (1.35-2.63x) on CPython 3.10 ([Scalene Table 3](https://arxiv.org/abs/2212.07597)) | Binary pstats (marshal), not JSON. snakeviz renders an HTML icicle/sunburst | `python -m cProfile -o out.prof`; snakeviz needs a browser/server, so in CI, export `.prof` artifacts and convert (e.g., flameprof/gprof2dot) | PSF-2.0 (cProfile); snakeviz BSD-3-Clause (from LICENSE text; GitHub reports NOASSERTION) | cProfile: in 3.15 it becomes an alias of `profiling.tracing` ([PEP 799](https://peps.python.org/pep-0799/)). snakeviz 2.2.2 (2024-11-09), last code commit 2024-11-09, 61 open, so **stale** | None specific |
| **line_profiler / kernprof** | Per-line timings of decorated/selected functions | **Instrumenting** (line events), in-process. 5.0 added `sys.monitoring` on 3.12+ ([CHANGELOG](https://github.com/pyutils/line_profiler/blob/main/CHANGELOG.rst)) | 2.21x median, up to 11.6x ([Scalene Table 3](https://arxiv.org/abs/2212.07597)) | `.lprof` (pickle) plus text via `python -m line_profiler -rmt`; no JSON (unverified) | Headless; `kernprof -l -p module` auto-profiling; TOML config | BSD-3-Clause (LICENSE text) | PyPI 5.0.2 (2026-02-23); main has unreleased 5.0.3; last commit 2026-09-15; 58 open | arm64 wheels. Not thread-aware ([Scalene §8.1](https://arxiv.org/abs/2212.07597)) |
| **memray** | Allocation tracer: peak memory, leaks, native allocations | **Tracing** (intercepts every allocation and records full Python ± native stack), in-process. Attach via gdb/lldb | **3.98x median** (2.43-5.36x) ([Scalene Table 3](https://arxiv.org/abs/2212.07597)). Docs: "native tracking is somewhat slower" ([overview](https://bloomberg.github.io/memray/overview.html)) | Binary capture → flamegraph HTML, table, tree, summary, `stats --json`, `transform` (gprof2dot/CSV) | Headless; `pytest-memray` with `limit_memory` markers fails tests on budget breach | Apache-2.0 | 1.20.0 (2026-08-07); last commit 2026-10-05; 46 open | **Linux/macOS only, no Windows.** On macOS, native stacks "are often difficult to read, and may be missing function calls". Cannot follow `spawn`/`exec` (macOS default multiprocessing start method). macOS 11+ ([supported envs](https://bloomberg.github.io/memray/supported_environments.html)) |
| **pytest-benchmark** | Microbenchmarks as pytest tests | Repeated timing in-process (`time.perf_counter`), calibrated rounds | n/a (harness). Defaults: min 5 rounds, 1.0 s max-time, warmup `auto` (on for PyPy) ([usage](https://pytest-benchmark.readthedocs.io/en/latest/usage.html)) | `--benchmark-json`, `--benchmark-autosave`, histograms | `--benchmark-compare-fail=mean:5%` fails the run. Compares against **stored history**, not a same-runner base, so it is risky on shared CI | BSD-2-Clause | 5.3.0 (2026-08-23); last commit 2026-08-23; 121 open | None |
| **pyperf** | Rigorous benchmark runner (multi-process) and system tuning | Spawns worker processes; **20 procs × 3 values + 1 warmup** (with a JIT: 6 × 10 + 10 warmups); 100 ms min-time calibration ([runner docs](https://github.com/psf/pyperf/blob/main/doc/runner.rst)) | n/a | JSON (`-o`), `pyperf stats/hist/compare_to --table` (md/rest) | `compare_to` uses a Student two-sample two-tailed t-test (95%) and `--min-speed` (default 0%) ([cli](https://pyperf.readthedocs.io/en/latest/cli.html)). `pyperf system tune` is Linux-only and needs root | MIT | 2.10.0 (2026-02-07); last commit 2026-10-01; 40 open | `system tune` has no macOS equivalent ([system](https://pyperf.readthedocs.io/en/latest/system.html)). Pins workers to isolated CPUs only when the kernel has isolcpus |
| **asv** | Benchmark history across commits, HTML dashboard | Builds envs per commit, runs timing/peakmem/track benchmarks | n/a | JSON results + static HTML site | `asv continuous base head` exits non-zero if anything worsened ([source](https://github.com/airspeed-velocity/asv/blob/main/asv/commands/continuous.py)). Change test is **factor 1.1 (10%)** AND Mann-Whitney U at **p under  0.002** ([_stats.py](https://github.com/airspeed-velocity/asv/blob/main/asv/_stats.py), [commands](https://asv.readthedocs.io/en/latest/commands.html)) | BSD-3-Clause | 0.6.6 (2026-06-27); last commit 2026-08-15; 162 open | None. `mem_` benchmarks are experimental |
| **profiling.sampling ("Tachyon", Py 3.15)** | Stdlib sampling profiler: run, attach, dump, live TUI | Sampling, **out-of-process** (remote memory reads); modes wall (default), cpu, gil, exception; default **1 kHz**, up to 1 MHz | Docs claim "virtually zero" overhead in non-blocking mode; `--blocking` adds overhead ([docs](https://docs.python.org/3.15/library/profiling.sampling.html)). No independent measurement found **(unverified)** | pstats, collapsed, flamegraph HTML, **gecko (Firefox Profiler)**, heatmap, binary + `replay` | Headless; Linux needs root/`CAP_SYS_PTRACE`/ptrace_scope; profiler and target must be the **same minor version** | PSF-2.0 | CPython **3.15.0rc3 tagged 2026-10-02**; 3.15.0 final not yet tagged on 2026-10-05 ([PEP 799](https://peps.python.org/pep-0799/), [What's New](https://docs.python.org/3.15/whatsnew/3.15.html)) | Needs `task_for_pid()`: root, the `com.apple.security.cs.debugger` entitlement, or SIP disabled. 3.15 also builds with frame pointers by default (PEP 831), which helps native unwinders |

Related: **yappi** (MIT; PyPI 1.7.6 2026-03-17 while GitHub has release v1.7.7 2026-05-22, a version mismatch) measured 3.17x (wall) and 3.62x (CPU) median overhead in Scalene Table 3, and was judged "among the most inaccurate".

### A.2 Node.js

| Tool | Purpose | Technique | Overhead | Output | CI-friendliness | Licence | Maintenance | Apple Silicon caveats |
|---|---|---|---|---|---|---|---|---|
| **`node --cpu-prof` / `--heap-prof`** | Built-in V8 CPU profile / sampling heap profile at exit | V8 sampling profiler, in-process (sampler thread). CPU default interval **1000 µs** (`--cpu-prof-interval`). Heap sampling default **512 KiB** (`--heap-prof-interval`) | No official figure **(unverified)**. Measured here (CPU-bound ~0.65 s script, 10 interleaved runs): **+0.8%** median at 1000 µs (within noise), **+4.7%** at 100 µs | `.cpuprofile` / `.heapprofile` JSON (Chrome DevTools format; speedscope reads it) | Stable since v22.4.0 / v20.16.0. Headless, no root, `--cpu-prof-dir`/`--diagnostic-dir` ([CLI docs v26.10.0](https://nodejs.org/api/cli.html)). Profile is written only on normal exit | MIT | Node 26.10.0 (2026-09-22), 24.21.0 LTS (2026-09-08) | None. Works on arm64 |
| **0x** | One-command flame graph | Default: V8 tick profiler (`--prof`). `--kernel-tracing` uses Linux `perf` | Not published **(unverified)** | HTML flame graph + profile folder; `--collect-only` / `--visualize-only` for CI ([README](https://github.com/davidmarkclements/0x)) | Headless with `--collect-only`; kernel tracing is Linux-only and needs perf privileges | MIT | 6.0.0 (2025-07-07); last commit 2025-07-07; 0 open. Requires Node ≥ 20. Low activity | `--kernel-tracing` is unavailable on macOS |
| **clinic.js** (doctor/flame/bubbleprof/heapprofiler) | Diagnostic suite | Mixed: async_hooks + sampling, in-process | n/a | HTML reports | Usable headless (`--collect-only`) **(unverified)** | MIT | 13.0.0 (2023-06-28); last commit 2024-09-19; 108 open. **README: "Clinic.js is not being actively maintained… results… may not be accurate"** ([repo](https://github.com/clinicjs/node-clinic)) | Avoid for new work |
| **tinybench** | Micro-benchmark library (also Vitest's engine) | In-process timing loop; default **100 ms time budget, ≥5 iterations**; optional timer-overhead subtraction | Docs warn sub-µs tasks are biased by clamping ([README](https://github.com/tinylibs/tinybench)) | Programmatic results (mean, p50/p75/p99, rme, MAD, ops/s), `bench.table()` | Library: you build pass/fail yourself. Has a CodSpeed plugin | MIT | 6.2.0 (2026-09-09); last commit 2026-10-04; 14 open | None |
| **mitata** | Micro-benchmark library (Node/Bun/Deno/browser/engine shells) | In-process. JIT-generated measurement loops, GC control (`gc('once'|'inner')`), DCE warnings | Claims picosecond-level resolution. Its own README comparison shows tinybench at 27.71 ns vs mitata 4.59 ns for the same op, i.e. harness overhead differs a lot between libraries ([README](https://github.com/evanwashere/mitata)) | Text with histograms/boxplots; `run({format:'json'})`, markdown | Library | MIT | npm 1.0.34 (2025-02-04); last commit 2025-02-17; 16 open. **Low activity (~20 months)** | `@mitata/counters` gives HW counters on Apple Silicon (Xcode needed, Instruments closed) and on Linux (`perf_event_paranoid ≤ 2`) |
| **Vitest bench** | Benchmarks inside the test runner (tinybench engine) | in-process | as tinybench | **v4**: `import { bench }` at module scope, `vitest bench`, marked **"Experimental"** ([v4 docs](https://v4.vitest.dev/guide/features.html)), `--outputJson`/`--compare` flags. **v5 (2026-09-03)**: `bench` is a **test-context fixture** (`test('x', async ({ bench }) => { await bench('x', fn).run() })`). `bench.compare()` with `toBeFasterThan`, `writeResult` / `bench.from()` baselines. `benchmark.reporters`, `benchmark.outputFile` and **`--compare` were removed**; output goes through the normal default/JSON reporters; pluggable benchmark providers ([Vitest 5 blog](https://vitest.dev/blog/vitest-5.html), [migration](https://vitest.dev/guide/migration/)) | Assertions can now fail CI directly | MIT | 5.0.3 (2026-09-30); v4 line 4.1.11; 367 open | None |
| **@platformatic/flame** | CPU + heap profiling with flame graphs and LLM-ready markdown | `@datadog/pprof` sampling, in-process. Auto-start or SIGUSR2 toggle | README: Express **+2.7% throughput / +3.9% latency** overhead ([repo](https://github.com/platformatic/flame)) | pprof `.pb`, WebGL HTML flame graph, **markdown hotspot report** | `flame run script.js` headless. Node ≥ 22.6.0 | **Licence mismatch: npm says MIT, GitHub says Apache-2.0** | 1.7.0 (2026-07-09); last commit 2026-10-05; 10 open; 179 stars (young) | Depends on a native addon (`@datadog/pprof`) prebuild for darwin-arm64 **(unverified)** |

### A.3 Bun

| Tool | Notes |
|---|---|
| **`bun --cpu-prof`** | Added in **v1.3.2**. Writes Chrome DevTools `.cpuprofile` ([v1.3.2 blog](https://bun.com/blog/bun-v1.3.2)). `--cpu-prof-name`, `--cpu-prof-dir`. **`--cpu-prof-interval`** (µs, default 1000) added in **v1.3.9** ([v1.3.9 blog](https://bun.sh/blog/bun-v1.3.9)). JSC sampling profiler, in-process |
| **`--cpu-prof-md` / `--heap-prof` / `--heap-prof-md`** | Added in **v1.3.7** ([blog](https://bun.com/blog/bun-v1.3.7)). The markdown output is "grep/LLM-friendly". Unlike Node, Bun's `--heap-prof` writes a **heap snapshot** at exit, not a sampling allocation profile ([benchmarking docs](https://bun.com/docs/project/benchmarking)) |
| Known accuracy bug | **Open issue [#44077](https://github.com/oven-sh/bun/issues/44077) (2026-09-26, Bun 1.4.2, macOS arm64): `--cpu-prof`/`--cpu-prof-md` bill event-loop idle time to the last JS frame as self time.** In the repro, `busy` gets 600 ms self time in a 603 ms profile, while Node reports 320/482 samples as `(idle)`. So I/O- or timer-heavy Bun profiles are misleading today. Also open: [#40184](https://github.com/oven-sh/bun/issues/40184), `bun test` accepts the profiling flags but produces no profile |
| Overhead | Not published. **Measured here (Bun 1.3.14):** +27% median (+7% on min) at 1000 µs and **+74% median (+28% min)** at 100 µs on the same script where Node showed +0.8% / +4.7%. That is a single machine with n=10 and high variance, so treat Bun profiles of short runs as distorted **(indicative only)** |
| **`bun:jsc`** | `heapStats()`, `generateHeapSnapshot()` (Safari/WebKit format), `profile(fn)` and `startSamplingProfiler(interval=1000 µs)` with raw `SamplingProfileStackTraces`, `estimateShallowMemoryUsageOf`, `serialize` ([bun:jsc reference](https://bun.com/reference/bun/jsc)). Native heap: `Bun.unsafe.mimallocDump()` |
| Benchmarking | Bun docs recommend **mitata** for microbenchmarks, **hyperfine** for CLIs, and **oha/bombardier/http_load_test** for HTTP. They warn that `autocannon` is not fast enough to load `Bun.serve()` ([docs](https://bun.com/docs/project/benchmarking)). There is **no `bun bench` command** (none in the docs or CLI; no tracking issue found) |
| `bun test` timing | The console reporter prints per-test durations (e.g., `[0.88ms]`). The docs say the JUnit reporter lacks "precise timestamp fields per test case" ([reporters](https://bun.com/docs/test/reporters)). Whether the `time=` attribute is populated is **unverified**. Default per-test timeout is 5000 ms |
| Maintenance / licence | Bun 1.4.2 (2026-09-05); last commit 2026-10-05; ~9.7k open issues+PRs. **MIT, but statically links LGPL-2 JavaScriptCore/WebKit** ([LICENSE.md](https://github.com/oven-sh/bun/blob/main/LICENSE.md)) |

### A.4 Bash / CLI

| Tool | Purpose / technique | Output | CI-friendliness | Licence | Maintenance | macOS caveats |
|---|---|---|---|---|---|---|
| **hyperfine** | Whole-process wall-clock benchmarking with `--warmup`, `--prepare`/`--conclude`, `--runs/--min-runs`, `-N` (no shell), parameter scans, outlier warnings | `--export-json/csv/markdown/asciidoc/orgmode`. JSON includes per-run times, exit codes and (on Unix) peak memory | Headless, no root. Non-zero exit if a command fails (unless `-i`). `scripts/welch_ttest.py` for A/B (1.21.0 fixed its interpretation) | MIT OR Apache-2.0 | **1.21.0 released 2026-10-05** (adds `$HYPERFINE_ITERATION`, per-command peak memory fix, Linux ARM64 musl) ([release](https://github.com/sharkdp/hyperfine/releases/tag/v1.21.0)); 59 open | None. Note `--shell=none` avoids ~ms shell spawn noise |
| **GNU `/usr/bin/time`** | rusage of a child: `-v`, `-f '%e %U %S %M'` | Text; `%M` max RSS in **KiB** | `-o file`; returns the child's exit status | GPL-3.0-or-later | 1.10 (2026-04-15; previous 1.9 was 2018) ([ftp.gnu.org](https://ftp.gnu.org/gnu/time/)) | Not installed on macOS (`brew install gnu-time` → `gtime`) |
| **BSD `/usr/bin/time` (macOS)** | `-l` prints the rusage struct; `-p` POSIX; `-o/-a` | Text. **"maximum resident set size" is in BYTES** (vs KiB in GNU). Recent macOS also prints `instructions retired`, `cycles elapsed`, `peak memory footprint` (observed on macOS 27.0 / M4) | Exit status is the child's; 126/127 on exec failure (`man time`) | BSD (Apple) | ships with OS | No `-f` format string. Parse by label |
| **shell `time` builtin** | bash/zsh keyword timing pipelines/functions | bash `TIMEFORMAT`; zsh `TIMEFMT` | No fork overhead for the measurement itself | bash GPL-3.0+ | n/a | macOS `/bin/bash` is **3.2.57** (observed), so 5.x features are missing |
| **PS4 + EPOCHREALTIME xtrace** | Per-line timestamps: `exec 5>trace; BASH_XTRACEFD=5; PS4='+ $EPOCHREALTIME ${BASH_SOURCE}:${LINENO} '; set -x` | Text trace → diff consecutive timestamps | No dependencies | — | `EPOCHREALTIME` needs **bash ≥ 5.0** ([bash manual](https://www.gnu.org/software/bash/manual/bash.html)) | Use Homebrew bash, or zsh (`zmodload zsh/datetime`; `$EPOCHREALTIME`). The common `PS4='$(date +%s.%N)'` pattern **forks per traced line**, which is a large observer effect. macOS 27's `date` now supports `%N` (observed locally); older macOS printed a literal `N` **(unverified)** |
| **`ts` (moreutils)** | Timestamp stdout lines: `-i` (incremental since previous line), `-s` (since start), `-m` (monotonic). `%.s/%.S/%.T` for sub-second resolution ([man](https://manpages.debian.org/testing/moreutils/ts.1.en.html)) | Text | Pipe-friendly; measures output arrival, not command boundaries (buffering skews it) | GPL-2.0 **(unverified)** | — | `brew install moreutils` |

---

## PART B: Methodology gaps

### B.1 Profiler overhead and distortion (the observer effect)

**Published overhead (Scalene OSDI'23 Table 3; CPython 3.10, 10 longest pyperformance benchmarks, interquartile mean of 10 runs)** ([arXiv 2212.07597](https://arxiv.org/abs/2212.07597)):

| Profiler | Kind | Median slowdown | Range |
|---|---|---|---|
| py-spy | sampling, out-of-process | 1.02x | 0.99-1.03x |
| Austin | sampling, out-of-process | 1.00x | 0.98-1.02x |
| Scalene CPU / full | sampling / +memory | 1.02x / 1.32x | full: 1.09-4.03x |
| pyinstrument | statistical via setprofile | 1.69x | 1.34-1.96x |
| cProfile | deterministic | 1.73x | 1.35-2.63x |
| line_profiler | deterministic (lines) | 2.21x | 1.01-11.59x |
| yappi wall / CPU | — | 3.17x / 3.62x | up to 33.25x |
| memray | allocation tracing | 3.98x | 2.43-5.36x |
| profile (pure Python) | deterministic | 15.1x | 10.4-55.7x |
| memory_profiler | RSS polling | ≥37.1x | >150x |

Overhead alone understates the problem. Overhead is **non-uniform**, so a deterministic profiler distorts *relative attribution*. Scalene's "function bias" microbenchmark found that trace-based profilers dilate time spent in calls. "In the worst case, one such profiler reports a function takes **80%** of execution time while in fact it only consumes **25%**" (§6.2). Sampling profilers tracked ground truth closely. Caveats: since 3.12, cProfile runs on PEP 669 `sys.monitoring` ([gh-103533](https://github.com/python/cpython/issues/103533)), and line_profiler ≥ 5.0 does too. The 2022 numbers are therefore an upper bound on modern CPython, and I found no published re-measurement on 3.12-3.15 **(gap)**.

**Coz (causal profiling)**: Coz runs "virtual speedup" experiments. It inserts pauses into all other threads to estimate the effect of speeding one line up. Mean overhead is **17.6%** on PARSEC (2.6% from debug-info startup, 4.8% from sampling, the rest from delays). Coz-guided changes gave Memcached **+9%**, SQLite **+25%**, and up to **+68%** on PARSEC, usually with under 10 changed lines ([Curtsinger & Berger, SOSP'15](https://arxiv.org/abs/1608.03676)). Coz is the corrective for "the hottest function isn't the one whose speedup shortens the critical path" in concurrent code. Licence BSD-2-Clause; v0.2.5 (2026-02-16).

**Sampling is not automatically right**:
- **Mytkowicz, Diwan, Hauswirth & Sweeney (PLDI 2010).** Four Java profilers (xprof, hprof, jprofile, yourkit) "often disagree on the identity of the hot methods". All of them violate the requirement that "to be correct, a sampling-based profiler must collect samples randomly" ([ACM](https://dl.acm.org/doi/10.1145/1806596.1806618)).
- **Safepoint bias.** JVM profilers that sample only at safepoints blame the nearest safepoint, not the hot loop. AsyncGetCallTrace-based async-profiler and Honest Profiler avoid this ([Burchell et al.](https://stefan-marr.de/downloads/mplr23-burchell-et-al-dont-trust-your-profiler.pdf)).
- **Burchell, Larose, Kaleba & Marr, "Don't Trust Your Profiler" (MPLR 2023).** Six modern Java profilers mostly agree with themselves over 30 runs (median max-min spread 2-8%). They still "cannot reliably agree on the set of top 5 hottest methods". Overhead was **1% to 5.4%**.
- **V8 / JSC sampling interval.** Node's default is 1 ms. Lowering it to 100 µs gives 10x the samples but raised overhead from ~0.8% to ~4.7% in my local Node test. On Bun 1.3.14, 100 µs raised it to ~+74% median, which is distorting. There is a sampling-error tradeoff:
  - With N samples, a frame's share p has standard error √(p(1-p)/N).
  - For a 1 s run at 1 kHz (N≈1000), a 5% frame is 5% ± 0.7 pp (1 SE).
  - A 1% frame is ±0.3 pp, i.e. ±30% relative.
  - Profile longer rather than faster.
- **Wall vs CPU attribution.** Bun issue #44077 (above) shows a profiler billing idle time to JS. pyinstrument and Tachyon default to wall time, which is correct for I/O-bound code but misleading when comparing CPU work.
- **Measurement bias from setup.** Mytkowicz et al. (ASPLOS 2009) showed that innocuous changes such as UNIX environment size and link order bias results, and recommend setup randomization ([ACM](https://dl.acm.org/doi/10.1145/1508244.1508275)).

### B.2 CPU pinning and frequency scaling

**Linux knobs and evidence:**
- **`isolcpus=` + `nohz_full=` + `rcu_nocbs=`** (kernel cmdline), then `taskset -c N`. Victor Stinner's measurement: a microbenchmark took **229 ms idle**, **372 ms on a busy system (+56%)**, and **230 ms on a busy system with CPU isolation** ([blog 2016](https://vstinner.github.io/journey-to-stable-benchmark-system.html)). pyperf: "isolating at least 1 core has a significant impact on the stability" and it auto-pins workers to isolated CPUs ([pyperf system](https://pyperf.readthedocs.io/en/latest/system.html)).
- **`pyperf system tune`**: sets the `performance` governor and min freq = max, disables Turbo (MSR or `intel_pstate/no_turbo`), stops irqbalance and sets IRQ affinity, sets `perf_event_max_sample_rate=1`, and checks AC power. On AMD use `/sys/devices/system/cpu/cpufreq/boost` (same idea).
- **Turbo**: Bakhvalov's example ran 32.4 B cycles at 2.706 GHz with Turbo vs 29.9 B at 2.294 GHz without. The first run on a cold chip turbos and the next does not, which is a classic A-then-B bias ([easyperf 2019](https://easyperf.net/blog/2019/08/02/Perf-measurement-environment-on-Linux)).
- **SMT / affinity**: `git status` variation went from **±4.17%** (4 HW threads) to **±2.71%** (1 thread, pinned), and cpu-migrations fell from 20 to 0 (same source). Isolate both SMT siblings. Disabling ASLR "in majority of cases doesn't help".
- **Ceiling**: on GitHub-hosted runners you cannot set boot params, governors or turbo (VMs). Only `taskset`/`nice` work. CodSpeed measured CV **2.66%** on GitHub-hosted runners vs **0.56%** on its tuned bare-metal "macro runners" (100 runs/suite, 2025-07-30) ([CodSpeed](https://codspeed.io/blog/benchmarks-in-ci-without-noise)).

**macOS (Apple Silicon):**
- **No pinning.** `THREAD_AFFINITY_POLICY` is a no-op on arm64 (`ml_get_max_affinity_sets` returns 0) ([Apple forum](https://developer.apple.com/forums/thread/703361), [affinity API notes](https://developer.apple.com/library/archive/releasenotes/Performance/RN-AffinityAPI/)).
- **Heterogeneous cores.** P/E cores (e.g., M4 here: `hw.perflevel0` = 4 Performance, `hw.perflevel1` = 6 Efficiency). The scheduler places threads by **QoS**. `taskpolicy -c utility|background|maintenance` *clamps* to lower QoS (E-cores), and `taskpolicy -b` sets `PRIO_DARWIN_BG` (`man taskpolicy`). These are useful for confining noise, never for the benchmark itself. Run benchmarks from a foreground terminal at default QoS. A bimodal timing distribution usually means P/E migration **(unverified as a published finding)**.
- **Power and thermal.** `pmset -g` shows `lowpowermode` (must be 0, and AC power). `pmset -g therm` shows thermal/performance warnings. `sudo powermetrics --samplers cpu_power,thermal` logs frequency/residency (needs root, so it is not CI-friendly). No published quantitative variance-reduction figures for macOS tuning were found **(gap)**. Mitigation is empirical: interleave A/B and report dispersion.
- **Hardware counters.** kperf via `@mitata/counters` (needs Xcode, Instruments closed) is the only cheap route to instruction counts. `/usr/bin/time -l` now prints `instructions retired`/`cycles elapsed` per process (observed). This is a noise-robust secondary metric.

### B.3 Warm-up and steady state

- **Barrett, Bolz-Tereick, Killick, Mount & Tratt, "Virtual Machine Warmup Blows Hot and Cold" (OOPSLA 2017)** ([arXiv](https://arxiv.org/abs/1602.00602), [HTML v6](https://soft-dev.org/pubs/html/barrett_bolz-tereick_killick_mount_tratt__virtual_machine_warmup_blows_hot_and_cold_v6/)):
  - Setup: 8 VMs (HotSpot, PyPy, V8, LuaJIT, Graal, HHVM, JRuby+Truffle, plus C/GCC baseline), **3,660 process executions × 2,000 in-process iterations** (30 process executions per pair).
  - Only **43.3-56.5%** of ⟨VM, benchmark⟩ pairs conform to the traditional warm-up model.
  - Only **30.0-43.5%** consistently reach a steady state of *peak* performance.
  - Other outcomes include *slowdown* (gets slower over time) and *no steady state*.
  - Different process executions of the same pair often behave differently ("bad inconsistency").
  - Method: automated changepoint analysis (PELT) to classify each run as flat / warmup / slowdown / no-steady-state.
- **Implications:**
  - **V8** (Ignition → Sparkplug → Maglev → TurboFan) and **JSC/Bun** (LLInt → Baseline → DFG → FTL) both tier-up and can deoptimize. A fixed "N warm-up iterations" is a guess, so inspect per-iteration time series for changepoints. mitata runs GC once after warm-up by default and flags dead-code-eliminated benchmarks. tinybench's 100 ms default budget can end before top-tier compilation for heavier functions.
  - **Repeat across processes, not only iterations.** Between-process variance (JIT decisions, ASLR, layout) is invisible to in-process repetition. pyperf's defaults encode this: 20 processes × 3 values (CPython), and 6 × 10 with 10 warm-ups for a JIT (PyPy).
  - **CPython**: the 3.11+ specializing interpreter quickens after a short warm-up. The 3.13+ experimental JIT (PEP 744) is off by default and must be enabled explicitly. 3.15's What's New says it was "significantly upgraded" ([What's New 3.15](https://docs.python.org/3.15/whatsnew/3.15.html)). Whether 3.15 enables it by default is **unverified**. Benchmark with the JIT both on and off, and expect warm-up effects with it on.
  - **PyPy**: pytest-benchmark auto-enables warm-up on PyPy.
  - **CLI tools**: there is no JIT steady state, but the page/disk cache is a warm-up (Bakhvalov: `git status` 2.57 s cold vs 0.40 s warm). Use hyperfine `--warmup` or `--prepare 'sync; echo 3 > /proc/sys/vm/drop_caches'` depending on which state you mean to measure.

### B.4 Repetitions, confidence intervals and minimum detectable effect

- **Georges, Buytaert & Eeckhout (OOPSLA 2007)** ([PDF](https://dri.es/files/oopsla07-georges.pdf)):
  - "Prevalent" methods (best-of-N, single run, etc.) were misleading in **up to 16%** of comparisons (startup) and >3% outright *incorrect* (wrong direction).
  - For steady state they were misleading in **>20% of cases at θ = 1%, >10% at θ = 2%, >5% at θ = 3%**.
  - They advocate the mean with a 95% CI across **multiple VM invocations**, using z for n ≥ 30 and t otherwise.
  - Their JavaStats tool repeats until the CI half-width is within **1-2% of the mean** or **30 runs**.
- **Kalibera & Jones, "Rigorous Benchmarking in Reasonable Time" (ISMM 2013)** ([PDF](http://petertsehsun.github.io/soen691/current/papers/reasonable_benchmarking.pdf)):
  - In a survey of 122 papers (90 measuring time), **71 reported no measure of variation** and only **3** gave a CI for a speedup ratio.
  - They recommend: "Always provide effect size confidence intervals". They use a Fieller interval for the ratio of means.
  - Repetition counts at each level (process executions vs iterations) should come from a one-off variance-components experiment. Spend repetitions at the highest-variance level (usually process executions).
  - The ratio CI is about √2 wider than a single system's CI.
  - Their companion tech report ("Quantifying performance changes with effect size confidence intervals", 2012) covers bootstrap as well as parametric intervals **(not re-read here)**.
- **Bootstrap vs t-test.** Timing data are right-skewed, often multimodal (P/E cores, GC) and have outliers. The t-test (pyperf `compare_to`, hyperfine's Welch script) assumes approximately normal means, which is fine for large n and fragile for n ≈ 5-10. Non-parametric choices:
  - Mann-Whitney U / Wilcoxon rank-sum (asv uses it at p under  0.002; Laaber et al. found it detects smaller slowdowns in clouds).
  - Percentile/BCa bootstrap CI on the **ratio of medians** (Laaber et al. also used overlapping bootstrapped CIs).
  - Mann-Whitney tests stochastic ordering, not "median changed by X%", so pair it with an effect-size CI.
- **Runs needed / MDE (worked formula).** Assume two independent groups, relative noise CV, two-sided α and power 1-β:
  - n per arm ≈ 2 · (z₁₋α/₂ + z₁₋β)² · (CV / δ)²
  - MDE δ ≈ (z₁₋α/₂ + z₁₋β) · CV · √(2/n)
  - With α = 0.05 and power 0.8, (1.96+0.84)² · 2 ≈ **15.7**. So:
    - CV 2.66% (GitHub runner, CodSpeed figure), δ = 2%: **n ≈ 28 per arm**. With n = 10 the MDE is **≈ 3.3%**; with n = 30 it is **≈ 1.9%**.
    - CV 0.56% (bare metal), δ = 1%: n ≈ 5. With n = 10 the MDE is ≈ 0.7%.
    - CV 5% (noisy laptop / startup), δ = 5%: n ≈ 16. Detecting 2% needs ≈ 98 per arm.
  - Paired/interleaved designs (A and B alternate on the same machine) cancel slow drift, so effective CV drops. Estimate CV from the *differences*.
  - Laaber et al. found that with test and control on the same instance, in randomized order, slowdowns of **≤10%** are detectable with high confidence even where CVs range **0.03% to >100%** ([EMSE 2019](https://www.ifi.uzh.ch/dam/jcr:326f9543-d719-4e8c-a27e-d5a5cace1abf/emse_smb_cloud.pdf)).

### B.5 Regression detection on noisy shared CI runners

- **Same-runner A/B beats history.**
  - **Laaber, Scheuner & Leitner (EMSE 2019)**: >4.5 M data points (Java/Go) across AWS, GCE, Azure, IBM and bare metal. CV varied **0.03% to >100%**. Running test and control **on the same instance in randomized interleaved order** made **≤10%** slowdowns detectable with Wilcoxon rank-sum or bootstrap CIs.
  - **Duet benchmarking** (Bulej et al., ICPE 2020) runs A and B *concurrently* on the same VM and compares them pairwise. Accuracy improved **2.3-12.5x (avg 5.03x)** for ScalaBench/DaCapo and **23.8-82.4x (avg 37.4x)** for SPEC CPU 2017 ([paper page](http://aleksandar-prokopec.com/publications/duet-benchmarking-icpe/)).
  - Historical-baseline tools (pytest-benchmark `--benchmark-compare`, github-action-benchmark) compare across *different* machines and need much looser thresholds.
- **Relative vs absolute thresholds.**
  - MongoDB first used static 10% thresholds. Run-to-run variation was "less than 10%" in most tests but "as much as 20% or more" in sensitive ones, so a common threshold either spams or misses. The old system raised **2,393 tickets in 5 months that boiled down to 24 useful ones (~1 in 100)**.
  - Relative (%) thresholds should be calibrated per benchmark from its own CV. Absolute budgets (ms, MB, bytes, query counts) suit SLO-style gates and deterministic metrics.
  - CodSpeed's data: on GitHub runners a 2% gate gives **45% false positives**, and you need a **7%** gate for under 1% FP. On macro runners **1.5%** suffices ([CodSpeed](https://codspeed.io/blog/benchmarks-in-ci-without-noise)).
- **Change-point detection on history.**
  - **Daly, Brown, Ingo, O'Leary & Bradford, ICPE 2020** (the user's "Change Point Detection in Software Performance Testing"; actual title "*The Use of Change Point Detection to Identify Software Performance Regressions in a Continuous Integration System*") ([PDF](https://research.spec.org/icpe_proceedings/2020/proceedings/p67.pdf)). They used a modified **E-Divisive means** with permutation significance testing. It found all regressions tracked in Jira. A sampled false-positive rate was **40-80%** (10 sampled points: 2 real, 4 noise, 4 ambiguous), which is still a large improvement over 99:1. It struggles with *correlated* noise.
  - **Hunter** (DataStax, Fleming et al., ICPE 2023) replaced the Monte-Carlo permutation test with **Student's t-test** and split the series into windows. This made results deterministic and more sensitive to short-lived regressions. It is now **Apache Otava (incubating)**: 0.8.0-incubating (2026-05-08), Apache-2.0.
  - Otava CLI defaults: **`--pvalue 0.001`, `--magnitude 0.0`, `--window 50`** ([main.py](https://github.com/apache/otava/blob/main/otava/main.py)).
  - Ingo (2025): practical E-Divisive implementations used only **100 permutations**, so the smallest p is 0.01 and "a single shuffle may determine" significance. Otava is now **18,000-300,000x** faster, with incremental O(W²) recompute ([arXiv 2505.06758](https://arxiv.org/abs/2505.06758)).
  - **Nyrkiö** is the hosted service built on it (v2.0.0, 2026-02-23, Apache-2.0).
- **CodSpeed CPU simulation.**
  - Runs the benchmark once under Valgrind-style instrumentation. It estimates cycles = instruction cost (latency-weighted) + L1 misses × 10-40 + LL misses × 100+, and **excludes syscalls** ([docs](https://codspeed.io/docs/instruments/cpu)).
  - Marketing claim: **under 1% variance**.
  - Default project regression threshold **10%**, adjustable 0-50% ([docs](https://docs.codspeed.io/features/understanding-the-metrics)).
  - Blind spots: I/O, syscalls, lock contention and real cache/branch-predictor behaviour on actual hardware. Use the walltime instrument plus macro runners for those.
  - Python ≥ 3.12 with pytest-codspeed ≥ 2; vitest/tinybench plugins for JS.
- **Bencher thresholds.**
  - Test types: static, percentage, z-score (≥30 samples recommended), **t-test**, log-normal, IQR and delta-IQR. Optional window and min/max sample size ([thresholds](https://bencher.dev/docs/explanation/thresholds/)).
  - No implicit default. The documented example is `--threshold-test t_test --threshold-upper-boundary 0.99 --threshold-max-sample-size 64`, with `--error-on-alert` to fail CI ([track-benchmarks](https://bencher.dev/docs/how-to/track-benchmarks/)).
  - Licence MIT OR Apache-2.0 (plus a proprietary "plus" directory). v0.6.13 (2026-09-28).
- **Other defaults for comparison:**
  - github-action-benchmark: `alert-threshold` **200%**, `fail-on-alert` false (v1.22.2).
  - asv: **10%** factor plus MWU p under  0.002.
  - pyperf: t-test at 95%, `--min-speed` 0%.
  - pytest-benchmark: no default fail (you set e.g. `mean:5%`).
- **Recommended defaults (synthesis of the sources above, not from any single paper):**
  1. Build base and head on the **same runner job**. Run them **interleaved** (ABAB… or randomized blocks), at least **10 rounds** for a smoke gate and **≥30** for a merge gate. Use multiple processes per round for JIT runtimes.
  2. Statistic: the **median ratio head/base** with a **bootstrap 95% CI** (≥2,000 resamples), plus a Mann-Whitney U test at **α = 0.05**. Use Holm or Benjamini-Hochberg across many benchmarks, since 20 benchmarks at α = 0.05 give about one false alarm per PR.
  3. Fail only if the CI lower bound exceeds 1 **and** the point estimate exceeds max(practical threshold, ≈ 2.5 × measured CV). Sensible thresholds:
     - **5%** for wall-clock on GitHub-hosted runners (CodSpeed suggests 7% for under 1% FP on single comparisons).
     - **1-2%** for bare metal or instruction-count simulation.
     - Absolute budgets for memory, size and counts.
  4. On main-branch history, run change-point detection (Otava defaults: p = 0.001, window 30-50) to catch slow drifts that per-PR gates miss.
  5. Re-measure CV quarterly with an **A/A run** (same commit twice). If the A/A run "detects" a change, the gate is miscalibrated.

### B.6 Flame graphs vs icicle graphs vs sandwich views; differential flame graphs

- **Flame graph** (Gregg): the x-axis is the stack population **sorted alphabetically, not time**. Width is the inclusive sample share, and colours are random unless a palette is applied ([flamegraphs](https://www.brendangregg.com/flamegraphs.html)). **Icicle graph**: the same data inverted, root at the top. It suits deep stacks because "the starting point is always on screen". The choice is purely presentational. **Flame chart** (Chrome DevTools, speedscope "Time Order"): the x-axis *is* time. It is good for phases, spikes and event-loop gaps, and bad for aggregation. Note that the FlameGraph scripts are **CDDL-1.0** (last commit 2024-10-20). speedscope is MIT (1.25.0, 2025-12-03).
- **Sandwich view** (speedscope): a table of functions by self/total time. Selecting one shows a merged **callers** graph above and a **callees** graph below ([speedscope](https://github.com/jlfwong/speedscope), [Mozilla Hacks](https://hacks.mozilla.org/2018/11/cross-language-performance-profile-exploration-with-speedscope/)). It is the right tool when a hot function (e.g., `JSON.stringify`, `dict.__getitem__`, a regex) is called from many sites. In a normal flame graph its cost is fragmented into many narrow towers, and every one looks small. "Left heavy" merges identical stacks and sorts the widest left, which is a flame graph with deterministic ordering.
- **Differential flame graphs** ([Gregg 2014](https://www.brendangregg.com/blog/2014-11-09/differential-flame-graphs.html)): the shape is drawn from the **"after" profile**. Red means the frame grew and blue means it shrank, with saturation ∝ delta. Pitfalls:
  1. **Code paths that vanished are invisible** ("nothing to color blue"). Use the *negated* variant, which draws the "before" shape, or view both.
  2. Without normalization (`difffolded.pl -n`), different load or durations make "everything red/blue".
  3. Users report negated delta percentages that look wrong, e.g., −0.8% for a removed function ([FlameGraph #44](https://github.com/brendangregg/FlameGraph/issues/44)).
  4. Sampling noise. Per B.1, a ±0.7 pp SE for a 5% frame at 1,000 samples means small coloured deltas are often noise. Diff only profiles with ≥10k samples, or repeat and check consistency.
  5. Renamed or inlined functions show up as one removal plus one addition.
- **When any of these mislead:**
  - **Wall vs CPU mode mismatch.** CPU flame graphs omit off-CPU/blocked time entirely. Wall-mode graphs mix in idle time, and Bun currently bills idle time to JS (#44077).
  - **JIT inlining.** Inlined callees are attributed to callers, so the profile shows the optimized shape, not the source structure.
  - **Broken native stacks.** Missing frame pointers truncate native frames, collapsing them under `[unknown]`. CPython 3.15 now builds with frame pointers (PEP 831).
  - **Recursion.** It inflates inclusive time in some aggregations.
  - **Self vs total.** Flame graphs emphasize *total*, while the optimization target is usually *self* time (use sandwich or a table).
  - **Profiler bias.** The deterministic-profiler function bias from B.1 is drawn faithfully, so it is wrong in a convincing way.
  - **Amdahl.** Width shows where time *is*, not what speeding something up would *save* in concurrent programs. Use Coz-style causal experiments or critical-path analysis for that.

---

### Gaps / unverified items

- No independent overhead measurements for Python 3.15 `profiling.sampling`, 3.12+ `sys.monitoring`-based cProfile/line_profiler, 0x, `node --cpu-prof`, or Bun's profiler. The Node/Bun numbers above are a small local experiment.
- No published quantitative data on variance reduction from macOS tuning (Low Power Mode, QoS, thermal), or on P/E-core bimodality.
- Whether CPython 3.15's JIT is on by default; the 3.15.0 final release date (rc3 is the latest tag).
- Bun JUnit `time` attributes; the @platformatic/flame licence (MIT on npm vs Apache-2.0 on GitHub); the moreutils licence; line_profiler JSON output; clinic `--collect-only`.


## Addendum: measurements on this machine (2026-10-05)

Apple M4, macOS 27.0, Bun 1.3.14, Node 24.20, background load average 6–10 from other fleet work.
- **Instruction counters without root:** `/usr/bin/time -l` reports `instructions retired` and `cycles elapsed`.
  Over 12 runs, the CV of instructions was 0.05% (Python), 0.28% (Node) and 1.06% (bash, parent process only),
  against 5–13% for wall time. Basis for ADR-0005's corroborating counter.
- **Bun:** `--cpu-prof` writes a Chrome `.cpuprofile` that perfkit reads. `--cpu-prof-md` writes an LLM-oriented
  Markdown table that separates native frames (e.g. `includes` at `[native code]`). `--heap-prof` writes a V8-format
  `.heapsnapshot`; `--heap-prof-md` writes Markdown. File names carry a non-wall-clock timestamp. `bun test` runs
  `node:test`-style suites unchanged. The TypeScript resolver fixture produced byte-identical output on Node and
  Bun, but ran 3× slower on Bun (17 s vs 5.6 s).
- **Claude Code shell:** in the agent's interactive zsh, `grep` and `find` are shell functions that dispatch to the
  embedded ugrep/bfs. Scripts run with bash get `/usr/bin/grep` and `/usr/bin/find`. Time shell code by executing the
  script, never by pasting its commands into the agent's shell.
- **macOS has no perf.** `dtrace`/`dtruss` exist but SIP blocks them for system binaries; `sample`, `spindump` and
  `powermetrics` are present; `xctrace` needs full Xcode (absent here). `/bin/bash` is 3.2 (no `EPOCHREALTIME`,
  no `BASH_XTRACEFD`). zsh's `%D{%s.%6.}` PS4 timestamps work (verified).
