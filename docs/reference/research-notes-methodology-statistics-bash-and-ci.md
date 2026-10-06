---
# yaml-language-server: $schema=../../.lore/schemas/reference.schema.json
type: Reference
title: "Research notes: methodology, statistics, Bash and CI"
tags:
  - research
summary: Performance methodology (USE/RED, active benchmarking, Amdahl), benchmark statistics, native profilers, Bash/zsh profiling, CI gating and agent-optimization research, as of Oct 2026.
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:00:48.601Z
---

# Research notes: methodology, statistics, Bash and CI

Raw research notes gathered 2026-10-05 by three parallel research passes (web sources cited inline; items not confirmed against a primary source are marked unverified). The distilled design input is [the state-of-the-art summary](state-of-the-art-in-performance-profiling-and-agent-driven-optimization.md).

### A command-level field guide for an AI coding agent (Claude Code) on macOS (Apple Silicon) and Linux CI

Research date: 2026-10-05. Versions below were checked against GitHub/PyPI/crates.io on that date where noted
("verified"). Anything not checked against a primary source is marked **unverified**.

---

## 0. TL;DR for an agent

1. **Never optimize without a number.** Define the metric and the workload first, measure a baseline with
   repetition, *then* profile to find where time goes, *then* change one thing, *then* re-measure with the same
   harness and compare statistically.
2. **Profile before you hypothesize.** The best-documented failure of LLM agents on performance work is mis-localizing
   the bottleneck (SWE-Perf, GSO, SWE-fficiency). Profiler evidence in the loop roughly doubles success (PerfAgent, 2026).
3. **Use Amdahl's law to pick targets**: a function at 5% of runtime can give at most a 5% win.
4. **Report median + spread (IQR or bootstrap CI), never a single run or a bare mean.** Interleave A/B runs on the
   same machine. Treat under ~2-5% wall-clock differences on a laptop or shared CI runner as noise unless proven otherwise.
5. **Use instruction counts (callgrind/cachegrind, `perf stat -e instructions`, CodSpeed simulation) for low-noise
   CI gates**, and wall-clock (hyperfine, bare-metal walltime) for the real user-facing claim.
6. **Correctness tests are the guard; the benchmark is not the spec.** Reject "wins" from caching benchmark inputs,
   special-casing harness data, skipping work, or changing output.
7. **Log every experiment** (hypothesis, change, metric, before/after with CI, verdict, commit) and keep only
   statistically-supported wins.

---

## 1. Methodology

### 1.1 Terminology: profiling vs benchmarking vs tracing vs observability

| Activity | Question it answers | Output | Typical tools |
|---|---|---|---|
| **Benchmarking** | *How fast is it?* (a number, for comparison) | time/throughput distribution | hyperfine, pyperf, criterion, Google Benchmark, CodSpeed, wrk2, k6 |
| **Profiling** | *Where does the time/memory go?* (attribution) | sampled stacks, flame graphs, line costs | perf, samply, Instruments/xctrace, py-spy, Scalene, pprof, callgrind |
| **Tracing** | *What happened, in what order, how long each step?* (events with timestamps) | timelines, spans, syscalls | strace/dtruss, bpftrace, Perfetto, OpenTelemetry traces, `set -x` + timestamps |
| **Observability / monitoring** | *Is production healthy, and what changed?* | metrics/logs/traces/profiles over time | Prometheus+Grafana, Pyroscope, Parca, OTel |

Benchmarking tells you *whether* something changed; profiling tells you *why*. An agent needs both: a benchmark to
score a change, a profiler to choose the change.

### 1.2 Brendan Gregg's USE method (resource-oriented)
Source: https://www.brendangregg.com/usemethod.html

"For every resource, check **U**tilization, **S**aturation, and **E**rrors." Resources = CPUs, memory, disks, network
interfaces, controllers, interconnects, plus software resources (locks, thread pools, file descriptors).
- Utilization: fraction of time the resource was busy.
- Saturation: queued work it cannot service yet (run-queue length, swap/paging, disk queue depth).
- Errors: error event counts (often cheapest to check first).

Quick Linux checklist (Gregg's "60-second analysis"):
```bash
uptime; dmesg -T | tail; vmstat 1 5; mpstat -P ALL 1 3; pidstat 1 3
iostat -xz 1 3; free -m; sar -n DEV 1 3; sar -n TCP,ETCP 1 3; top -b -n1 | head -30
```
macOS equivalents: `top -l 2 -o cpu`, `vm_stat 1`, `iostat -w 1`, `nettop -P -L 1`, `powermetrics --samplers cpu_power`
(sudo; also shows P/E-cluster frequency and residency), `fs_usage` (sudo), Activity Monitor.

### 1.3 RED method (request-oriented)
Tom Wilkie (2015, Weaveworks), derived from Google's Four Golden Signals: for every service, track **R**ate
(req/s), **E**rrors (failed req/s), **D**uration (latency *distribution*, i.e. histograms, not averages).
Sources: https://thenewstack.io/monitoring-microservices-red-method/ , https://clickhouse.com/resources/engineering/red-use-methods
Rule: RED for services (what users feel), USE for the resources underneath (why).

### 1.4 Active benchmarking (Gregg)
Source: https://www.brendangregg.com/activebenchmarking.html
"Casual benchmarking: you benchmark A, but actually measure B, and conclude you've measured C." Active benchmarking =
while the benchmark runs, use observability tools (top, `perf top`, iostat, `vmstat`, `powermetrics`) to confirm
**what the limiter actually is**. Checklist of things it catches: other processes disrupting the run,
software-imposed throttles, client/network as bottleneck, single-threaded benchmark on multi-core, version mismatch
between A and B, benchmarking the page cache instead of the disk, unrealistic workloads.
Agent translation: when you report "X is 30% faster", also report what the profile/`perf stat` says is the limiter
(CPU-bound? syscalls? I/O wait? lock contention?). If you cannot explain *why* it got faster, treat it as suspect.

### 1.5 Drill-down analysis
Start at the top (end-to-end latency, whole-program time), decompose into components, pick the largest, decompose
again (process -> thread -> function -> line -> instruction/syscall). Stop when the cause is actionable. In practice:
`hyperfine` (whole command) -> `samply`/`perf record` (functions) -> line profiler / annotate (`perf annotate`,
Scalene, `line_profiler`) -> `perf stat` counters (IPC, cache misses, branch misses) to explain *why* a hot loop is slow.
Other Gregg methods worth knowing (https://www.brendangregg.com/methodology.html): Workload Characterization
(who/what/why/how much load), Off-CPU analysis (time blocked: I/O, locks, sleep), "Streetlight anti-method" and
"Random change anti-method" (what to avoid), and Thread State Analysis.

### 1.6 The core loop: measure -> hypothesize -> change one thing -> re-measure
```
0. Define: metric (wall time p50? p99 latency? peak RSS? instructions?), workload, target/budget, guard tests.
1. Baseline: N runs of the benchmark on the unmodified code, record median/IQR + environment.
2. Profile: find the dominant cost (flame graph / top-N self time). Apply Amdahl to bound the possible win.
3. Hypothesis: "X takes 40% because of Y; doing Z should cut X by half -> ~20% total."  (write the prediction down)
4. Change ONE thing. Run correctness tests first (fail -> discard).
5. Re-measure with identical harness, interleaved with baseline; compare statistically.
6. Verdict: keep (significant win, tests pass), discard (no effect/noise/regression), or investigate (surprise).
7. Log it. Re-profile: the bottleneck has moved. Repeat until budget met or remaining hot spots < threshold.
```
The written prediction is important: if measured gain <under predicted gain, your model of the system is wrong;
re-profile rather than piling on more changes.

### 1.7 Amdahl's law for target selection
Overall speedup S = 1 / ((1 - p) + p / s), where p = fraction of time in the part you speed up, s = local speedup.
- p = 0.05, s = infinity -> S = 1.053 (max 5% win). Do not spend effort here.
- p = 0.6, s = 2 -> S = 1.43. p = 0.6, s = 10 -> S = 2.17.
Corollary for agents: sort profile by *inclusive* time of things you can change, compute the ceiling, and only
attack items whose ceiling exceeds your noise floor *and* the budget gap. Gustafson's law is the scaled-workload
counterpart for parallel speedups.

### 1.8 Latency: percentiles vs means, and coordinated omission
- Latency distributions are skewed/multi-modal; the mean hides tails. Report p50/p90/p99/p99.9 and max, ideally
  with HdrHistogram-style recording. Don't average percentiles across hosts/windows (merge histograms instead).
- **Coordinated omission** (Gil Tene, ~2013): closed-loop load generators wait for a response before sending the next
  request, so when the server stalls, the generator stops sending and fails to record the latency the
  would-have-been-queued requests experienced. Result: wildly optimistic tail percentiles (wrk2's README shows a p99
  ~200x under-reported). Fix: open-loop/constant-throughput load (wrk2 `-R`, k6 `constant-arrival-rate` executor,
  Gatling open model, vegeta `-rate`), and measure latency from the *intended* send time; HdrHistogram's
  `recordValueWithExpectedInterval` back-fills missing samples.
  Sources: https://github.com/giltene/wrk2 , https://groups.google.com/g/mechanical-sympathy/c/icNZJejUHfE/m/BfDekfBEs_sJ
- For CLI tools and scripts, "latency" is just run time; hyperfine's min/median/max/stddev plus exported per-run times
  are enough.

### 1.9 Performance budgets and SLOs
- SLO form: "p99 of `/search` under 300 ms over 28 days, 99.9% of windows" or for CLIs "`tool build` on fixture X under 2.0 s
  median on the reference runner; peak RSS under 500 MB".
- Budgets as tests: assert on a *robust* statistic with headroom (e.g., median of 10 runs under budget x 1.0; fail CI
  only at > budget x 1.1 to absorb noise), or assert on deterministic proxies (instruction count, allocations, bytes
  shipped, number of SQL queries, number of subprocess spawns). Deterministic-count budgets are much less flaky than
  time budgets. Examples: `size-limit` / bundle-size budgets, Lighthouse CI budgets (web), Django
  `assertNumQueries`, allocation-count tests (Gungraun/iai, `pytest-codspeed --mode memory`).

### 1.10 Where performance fits in the SDLC
| Phase | Activity | Agent-relevant practice |
|---|---|---|
| Design | Complexity analysis (big-O on expected n), back-of-envelope latency numbers, choose data structures/IO patterns, define SLO/budget | Write down n, expected sizes, and the budget in the design doc/task before coding |
| Implementation | Micro-benchmarks for hot paths; avoid known anti-patterns | Add a benchmark next to the code you optimize; keep it in-repo |
| PR time | Regression gates: CodSpeed / Bencher / github-action-benchmark; deterministic counters; diff flame graphs | Compare PR vs base on the same runner; gate on instruction counts or relative thresholds |
| Release | Load/soak tests (k6, Gatling, wrk2, Locust) against SLOs; capacity tests | Open-loop load; percentiles; run long enough to reach steady state |
| Production | Continuous profiling (Pyroscope, Parca/Polar Signals, Datadog, OTel profiles), RED dashboards, fleet-wide regression detection | Use production profiles to choose what to optimize (this is how Google ECO localizes work) |

Prior art at scale: Meta's **ServiceLab** (pre-production A/B, OSDI 2024) and **FBDetect** (in-production, SOSP 2024)
detect regressions as small as **0.005%** via careful variance analysis of machine factors and statistics; combined
TOCS paper "Detecting Tiny Performance Regressions at Hyperscale" (https://dl.acm.org/doi/10.1145/3785504 ;
https://www.usenix.org/conference/osdi24/presentation/chow). Google-Wide Profiling (GWP, 2010) is the ancestor of
fleet continuous profiling and feeds Google's ECO system (section 6).

---

## 2. Statistical rigor for benchmarks

### 2.1 Noise sources and mitigations
| Source | Effect | Mitigation (Linux) | Mitigation (macOS / Apple Silicon) |
|---|---|---|---|
| CPU frequency scaling / turbo | Multi-% run-to-run drift; first runs faster than later (thermal) | `pyperf system tune` (performance governor, min freq = max, disable Intel turbo), or `cpupower frequency-set -g performance` | Cannot pin frequency. Keep plugged in, Low Power Mode off, let machine idle/cool, prefer longer runs and interleaving |
| Thermal throttling | Slow degradation across a long session | Short bursts, cooldown between batches; monitor with `turbostat` | Watch `sudo powermetrics --samplers smc,cpu_power -i 1000`; laptops throttle sooner than desktops |
| Heterogeneous cores (P/E, big.LITTLE) | Bimodal timing depending on which cluster runs the process | `taskset -c 2 cmd` / isolated cores | **No user-space core pinning on macOS.** Scheduling is QoS-driven: `taskpolicy -b` demotes to E cores, `taskpolicy -B` re-allows P cores; default-QoS foreground CLI processes mostly land on P cores. Expect occasional E-core outliers; use median, not mean. (https://eclecticlight.co/2024/12/17/tune-for-performance-core-types/) |
| Background processes | Random spikes | Quiet machine, `isolcpus`, `nohz_full`, stop irqbalance (pyperf does) | Quit apps; Spotlight (`mdworker`), Time Machine, iCloud sync, browser tabs; check `top -o cpu` before running |
| ASLR / memory layout / env size / link order | Systematic bias of several %; can flip conclusions | `setarch -R` to disable ASLR for analysis; randomize layout to *average out* bias (Stabilizer idea) | Run with consistent environment; compare multiple builds/layouts if the effect is small |
| Environment size, cwd, user name | Shifts stack alignment -> systematic bias | Fix env (`env -i`) for both A and B | same |
| Caches (page cache, CPU caches, JIT, disk) | First run differs ("cold") | `--warmup`, or explicitly flush (`--prepare 'sync; echo 3 \| sudo tee /proc/sys/vm/drop_caches'`) when measuring cold | `sudo purge` to drop file cache for cold-start tests |
| Shared CI runners | +-10-20% amplitude typical; heterogeneous CPUs behind the same label | Relative (same-job) comparison, instruction counts, bare-metal/dedicated runners | GitHub macOS runners are VMs; avoid wall-clock gates there |

Key references:
- Mytkowicz et al., "Producing Wrong Data Without Doing Anything Obviously Wrong!" (ASPLOS 2009): UNIX environment
  size and link order alone create measurement bias big enough to reverse "-O3 beats -O2" conclusions.
  https://users.cs.northwestern.edu/~robby/courses/322-2013-spring/mytkowicz-wrong-data.pdf
- CodSpeed, "Why glibc is faster on some GitHub Actions runners": `ubuntu-24.04` jobs landed on Intel Xeon 8370C
  vs AMD EPYC 7763; glibc picks different memcpy/malloc paths by CPU/cache size, so *even instruction counts* changed
  (20,577 vs 20,901) with byte-identical binaries. Log `lscpu`/CPU model with every result.
  https://codspeed.io/blog/unrelated-benchmark-regression
- Laaber, Scheuner, Leitner, "Software Microbenchmarking in the Cloud. How Bad is it Really?" (EMSE 2019): CoV ranged
  from 0.03% to >100% by benchmark/instance; running A and B **on the same instance in randomized interleaved order**
  detects slowdowns of 10% or less with high confidence. https://www.ifi.uzh.ch/dam/jcr:326f9543-d719-4e8c-a27e-d5a5cace1abf/emse_smb_cloud.pdf
- Laurence Tratt, "What Metric to Use When Benchmarking?" (2022): instructions are stable but can mislead (a threaded
  change had +5% instructions but -7% wall time). Use instructions for small fragments, wall-clock for whole programs.
  https://tratt.net/laurie/blog/2022/what_metric_to_use_when_benchmarking.html
- Kalibera & Jones, "Rigorous Benchmarking in Reasonable Time" (ISMM 2013): variation exists at multiple levels
  (iteration, process execution, build); repeat at the level with the most variance (often *process* re-launch, not
  more in-process iterations).

### 2.2 Warmups, run counts, and what to report
- **Warmup**: discard the first 1-3 runs for disk/page cache and CPU frequency ramp (`hyperfine --warmup 3`). For JIT
  runtimes (JVM, V8, PyPy) use the language harness (JMH, pyperf) which handles warmup within process.
- **Runs**: hyperfine's default is at least 10 runs and at least 3 seconds. For an A/B decision on a noisy laptop aim
  for 20-30 runs per variant; for p99 claims you need hundreds-thousands of samples.
- **Report**: median, IQR (or MAD), min, max, N, and a 95% CI of the *difference/ratio*. Show the environment (CPU
  model, OS, power state, tool versions, commit SHAs). The mean+stddev is fine only for well-behaved unimodal data;
  hyperfine reports mean +- sigma, so also export JSON and compute medians.
- **Use `min` with care**: the minimum is a robust estimate of "intrinsic" cost for CPU-bound deterministic code
  (it filters interference), but hides real variability for I/O or concurrent code.
- **Aggregate across benchmarks with the geometric mean of ratios** (never the arithmetic mean of raw times or of
  ratios). Heiser lists arithmetic-mean averaging as a crime.

### 2.3 A/B comparison tests
- **Interleave** A and B (ABABAB... or randomized order), not AAAA then BBBB, so drift (thermal, background load)
  hits both equally. hyperfine runs commands sequentially (all runs of A, then all of B), so for small effects wrap
  it: alternate several short hyperfine invocations, or write a small driver (see 2.6).
- **Mann-Whitney U** (rank-based, no normality assumption) for "is B shifted relative to A?"; report effect size as
  ratio of medians or Hodges-Lehmann shift. `scipy.stats.mannwhitneyu(a, b, alternative='two-sided')`.
- **Bootstrap CI** of the ratio of medians: resample each group with replacement 10,000 times, compute
  median(B)/median(A), take the 2.5/97.5 percentiles. If the CI excludes 1.0 *and* its bound clears your
  practical threshold, it is a win. `scipy.stats.bootstrap` supports this directly.
- **Welch's t-test** is what hyperfine's `scripts/welch_ttest.py` and pyperf's `compare_to` use (pyperf marks
  results "not significant" otherwise). Note hyperfine v1.21.0 fixed the interpretation in that script.
- **Minimum detectable effect (MDE)**: roughly, with n runs per arm and coefficient of variation CV, the smallest
  reliably detectable relative difference at ~80% power is about 2.8 x CV x sqrt(2/n). Example: CV 3%, n = 20 ->
  MDE ~ 2.7%. If your expected win is smaller than the MDE, either increase n, reduce noise, or switch to a
  deterministic counter. (Normal-approximation rule of thumb; heavy tails make it worse.)
- **Thresholds**: use *relative* thresholds for time (e.g., flag >5% on dedicated hardware, >10-25% on shared
  runners) and tight thresholds (0.5-2%) for instruction counts. Absolute thresholds only make sense for budgets
  ("under 200 ms").
- **Multiple comparisons**: with 100 benchmarks at alpha = 0.05 you will get ~5 false "regressions" per run. Use
  stricter alpha, require confirmation on rerun, or control FDR (Benjamini-Hochberg).

### 2.4 Gernot Heiser's "Systems Benchmarking Crimes" (checklist)
Source: https://gernot-heiser.org/benchmarking-crimes.html
1. *Selective benchmarking*: not evaluating potential degradations; benchmark sub-setting without justification;
   selective data sets that hide deficiencies.
2. *Improper handling of results*: micro-benchmarks presented as overall performance; throughput degradation
   reported as overhead; downplaying overheads (percent vs percentage points, wrong base); **no indication of
   significance** (no variance/CI); arithmetic mean for averaging scores.
3. *Wrong benchmarks*: simplified simulated systems; inappropriate/misleading benchmarks; same dataset for
   calibration and validation (directly relevant to agents tuning on the benchmark they're scored on).
4. *Improper comparison*: no proper baseline; only evaluating against yourself; unfair benchmarking of competitors.
5. *Missing information*: platform spec; sub-benchmark results; relative numbers only (no absolute values).

### 2.5 hyperfine (v1.21.0, released 2026-10-05, verified)
Repo: https://github.com/sharkdp/hyperfine . Install: `brew install hyperfine` / `cargo install hyperfine` / apt.
```bash
# Basic A/B with warmup, fixed runs, JSON for later stats
hyperfine --warmup 3 --runs 30 --export-json ab.json --export-markdown ab.md \
  -n old './old.sh input.txt' -n new './new.sh input.txt'

# Fast commands (<~5 ms): bypass the intermediate shell to avoid its startup cost/noise
hyperfine -N --warmup 10 'mytool --version'          # -N == --shell=none

# Cold-cache measurement: run a prepare step before EACH timing run
hyperfine --prepare 'sync; echo 3 | sudo tee /proc/sys/vm/drop_caches' 'grep -r foo .'   # Linux
hyperfine --prepare 'sudo purge' 'grep -r foo .'                                          # macOS
# --conclude runs after each timing run; $HYPERFINE_ITERATION is exposed to prepare/conclude (v1.21)

# Parameter scan (scaling behavior; check complexity empirically)
hyperfine -P n 1000 100000 -D 33000 'seq {n} | ./slow.sh' --export-json scan.json
hyperfine -L impl awk,bash './count.{impl}.sh big.txt'      # list scan

# Compare against a named reference; relative speeds printed
hyperfine --reference './old.sh' --reference-name baseline './new.sh'

# Compare two git revisions of the same script
hyperfine --prepare 'git checkout -q {rev}' -L rev main,feature './build.sh'
# (Better: build both into separate dirs first so checkout cost/caches don't interfere.)

# Robustness / IO
hyperfine --input big.txt './filter.sh'          # feed stdin from file
hyperfine --output=pipe 'cmd'                     # or null|inherit|<file>; output to a TTY skews results
hyperfine -i 'cmd-that-exits-nonzero'             # --ignore-failure (accepts list of exit codes since v1.20)
hyperfine --time-unit ms ...                      # v1.21 adds min/hours and aliases
```
Gotchas:
- Default shell spawning adds ~1-5 ms; hyperfine subtracts a calibrated shell overhead, but use `-N` for sub-10 ms
  commands (then you can't use shell syntax like pipes; wrap in `bash -c` if needed and benchmark that consistently).
- Statistical outlier warnings ("first run significantly slower") mean add `--warmup` or `--prepare`.
- The JSON export contains every run's `times` (and `user`, `system`, `exit_codes`; peak memory since recent
  versions, now per-command on Unix as of v1.21). Bundled scripts in `scripts/`: `advanced_statistics.py`,
  `welch_ttest.py`, `plot_whisker.py`, `plot_histogram.py`, `plot_parametrized.py`, `plot_benchmark_comparison.py`.
- hyperfine runs all runs of command 1, then all of command 2. For small-effect A/B, interleave yourself.

### 2.6 A minimal interleaved A/B + bootstrap harness (agent-ready)
```bash
# ab.sh: interleave 10 rounds of 3 runs each, export JSON per round
for i in $(seq 1 10); do
  hyperfine -N --warmup 1 --runs 3 --export-json "r_${i}_a.json" "./a $ARGS" >/dev/null
  hyperfine -N --warmup 1 --runs 3 --export-json "r_${i}_b.json" "./b $ARGS" >/dev/null
done
```
```python
# compare.py
import glob, json, numpy as np
from scipy import stats
ld = lambda pat: np.concatenate([json.load(open(f))["results"][0]["times"] for f in sorted(glob.glob(pat))])
a, b = ld("r_*_a.json"), ld("r_*_b.json")
ratio = lambda x, y: np.median(y) / np.median(x)
ci = stats.bootstrap((a, b), ratio, paired=False, vectorized=False, n_resamples=10000, method="percentile")
u = stats.mannwhitneyu(a, b, alternative="two-sided")
print(f"A med={np.median(a)*1e3:.2f}ms IQR={np.subtract(*np.percentile(a,[75,25]))*1e3:.2f}  "
      f"B med={np.median(b)*1e3:.2f}ms  B/A={ratio(a,b):.3f} "
      f"95%CI=[{ci.confidence_interval.low:.3f},{ci.confidence_interval.high:.3f}] MWU p={u.pvalue:.2g}")
```
Verdict rule: **win** if CI upper bound under 1 - (practical threshold, e.g. 0.02) and tests pass; **regression** if CI
lower bound > 1 + threshold; otherwise **no detectable change**.

### 2.7 Language harnesses with good statistics
- Python: `pyperf` 2.10.0 (verified): `python -m pyperf timeit -o new.json '...'`, `python -m pyperf compare_to
  old.json new.json --table` (significance-aware), `python -m pyperf system tune` (Linux). Spawns worker processes
  (process-level repetition, per Kalibera & Jones).
- Rust: criterion / divan; `critcmp` (BurntSushi) to compare saved criterion baselines (`cargo bench -- --save-baseline
  main`; `critcmp main pr`). Gungraun (formerly iai-callgrind, renamed in 0.17; v0.20.0 2026-09-26, verified) for
  Valgrind-based instruction/cache/allocation counts.
- Go: `go test -bench . -count 10 > new.txt; benchstat old.txt new.txt` (Mann-Whitney + CI built in).
- C++: Google Benchmark `--benchmark_repetitions=20 --benchmark_report_aggregates_only=true`, `compare.py`.
- JVM: JMH (forks, warmup iterations, blackhole).
- JS: tinybench / mitata; `node --cpu-prof`.

### 2.8 Instruction counts as low-noise proxies
```bash
# Linux: hardware counters (needs perf_event_paranoid <= 1 or CAP_PERFMON)
perf stat -r 10 -e instructions,cycles,task-clock,context-switches,cpu-migrations,page-faults,branch-misses,cache-misses ./prog
# instructions:u = user-space only, more stable
perf stat -e instructions:u -x, -o counts.csv ./prog

# Valgrind (deterministic, ~20-100x slower; Linux x86_64/arm64; NOT supported on macOS Apple Silicon)
valgrind --tool=cachegrind --cache-sim=no ./prog    # Ir = instructions executed (Valgrind >= 3.21 defaults cache-sim off)
valgrind --tool=callgrind --dump-instr=yes ./prog && callgrind_annotate callgrind.out.<pid> | head -40
#  kcachegrind / qcachegrind for GUI
```
Reported stability: one study found instruction count RSD ~0.003-0.005% vs ~2-5% for wall time with near-1.0
correlation on CPU-bound benchmarks (**unverified**: source surfaced via search, paper not identified). Caveats:
instruction counts ignore memory-latency, parallelism, I/O, syscalls in kernel (unless counted), SIMD width changes,
and CPU-dispatch differences (glibc example above). Use as a *gate* and as a *signal*, then confirm user-facing wins
with wall-clock.
On macOS there is no `perf stat`; options: Instruments "CPU Counters" template (`xcrun xctrace record --template 'CPU
Counters'`), or run counters in a Linux container/VM (note: Docker on macOS is a Linux VM; Valgrind works there but
emulation/virtualization changes absolute numbers, so compare only within the same environment).

---

## 3. Generic/native profilers and visualization

### 3.1 Linux `perf`
```bash
sudo sysctl kernel.perf_event_paranoid=1      # or -1; kernel.kptr_restrict=0 for kernel symbols
perf record -F 999 -g -- ./prog args          # frame-pointer stacks (needs -fno-omit-frame-pointer builds)
perf record -F 999 --call-graph dwarf -- ./prog   # DWARF unwinding when FPs are missing (big files)
perf record -F 999 -a -g -- sleep 10          # whole system
perf report --stdio --no-children --sort comm,dso,symbol | head -60
perf annotate --stdio -s hot_function
perf script > out.perf                        # loads in Firefox Profiler / speedscope / FlameGraph
perf trace -s ./prog                          # strace-like syscall summary, lower overhead
perf stat -d ./prog                           # detailed counters
```
Gotchas: missing frame pointers produce broken stacks (Fedora/Ubuntu 24.04+ build distro packages with frame
pointers; your own code may not); JIT runtimes need perf maps (`node --perf-basic-prof`, Python 3.12+
`-X perf` / `PYTHONPERFSUPPORT=1`, JVM `-XX:+PreserveFramePointer` + perf-map-agent/async-profiler).
Unavailable in most containers/CI without privileges; GitHub-hosted Ubuntu runners allow `sudo sysctl`.

### 3.2 eBPF / bpftrace (Linux)
```bash
sudo bpftrace -e 'profile:hz:99 /pid == 1234/ { @[ustack] = count(); }'          # on-CPU sampling
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_execve { printf("%s -> %s\n", comm, str(args->filename)); }'  # every exec (great for shell scripts)
sudo bpftrace -e 'tracepoint:raw_syscalls:sys_enter /comm == "bash"/ { @[ksym(args->id)] = count(); }'  # (id->name mapping varies; unverified one-liner)
sudo execsnoop-bpfcc   # bcc tools: execsnoop, opensnoop, biolatency, offcputime, profile
sudo offcputime-bpfcc -df -p PID 10 > offcpu.folded   # off-CPU flame graph input
```
Rule: use eBPF for production-safe, low-overhead tracing and off-CPU analysis; use perf for most on-CPU work.

### 3.3 samply (macOS + Linux + Windows; Firefox Profiler UI)
Repo: https://github.com/mstange/samply . Latest tagged release **0.13.1** (2025-02-01; crates.io latest 0.13.1,
verified 2026-10-05; repo still active as of 2026-09-30. A "0.13.2" mentioned by one search summary is **unverified**).
```bash
cargo install --locked samply        # or brew install samply
samply record ./prog args            # spawns, samples at 1 kHz, opens profiler.firefox.com with local symbol server
samply record --save-only -o prof.json.gz ./prog args   # agent-friendly: no browser
samply record --rate 4000 ./prog     # higher sampling frequency
samply record -p 1234                # attach (macOS: run `samply setup` once to self-sign; Linux: perf_event_paranoid)
samply load prof.json.gz             # later: serve + open
samply import perf.data              # import Linux perf recordings
```
macOS notes: profiles on-CPU *and* off-CPU samples; cannot attach to SIP-protected system binaries; works on
Apple Silicon without disabling SIP. Linux: on-CPU only; needs `perf_event_paranoid` at most  1 (or CAP_PERFMON).
Agent tip: the saved `.json.gz` is the Firefox Profiler "processed" format; symbolication is done by the samply
server at load time, so for headless analysis either keep `samply load` running or export collapsed stacks via
another route (e.g. on Linux use `perf script | inferno-collapse-perf`). Newer samply builds have presymbolication
flags (`--unstable-presymbolicate`; **unverified** in 0.13.1 help text) to embed symbols.

### 3.4 macOS Instruments / xctrace / sample / dtrace
```bash
# xctrace (Xcode CLT/Xcode required)
xcrun xctrace list templates
xcrun xctrace record --template 'Time Profiler' --time-limit 30s --output run.trace --launch -- ./prog args
xcrun xctrace record --template 'Time Profiler' --attach <pid|name> --time-limit 10s --output run.trace
xcrun xctrace export --input run.trace --toc                              # see tables
xcrun xctrace export --input run.trace \
  --xpath '/trace-toc/run[@number="1"]/data/table[@schema="time-profile"]' --output tp.xml   # big XML; parse backtraces
open run.trace                                                            # Instruments GUI
# Other templates: 'Allocations', 'Leaks', 'System Trace', 'CPU Counters', 'File Activity'

# sample: quick stack sampling of a running process, no Xcode needed
sample <pid|name> 5 1 -file /tmp/sample.txt     # 5 s, 1 ms interval; text call tree with counts
# spindump for hangs: sudo spindump <pid> 5 -file out.txt
```
dtrace/dtruss on macOS: SIP blocks dtrace on protected/system binaries ("dtrace cannot control executables signed
with restricted entitlements"); full use needs `csrutil enable --without dtrace` from Recovery (not acceptable on most
dev machines/CI). Workaround: copy the binary out of `/bin` (e.g., `cp /bin/bash /tmp/bash && sudo dtruss -c
/tmp/bash script.sh`) - the copy loses Apple's signature restrictions. Apple Silicon/macOS 26+ further restrict dtrace
(**unverified** for specifics). Prefer samply / xctrace for CPU profiling, `fs_usage -w -f filesys <pid>` (sudo) for
file I/O, and `sudo eslogger exec` (Endpoint Security, macOS 13+) for counting process execs.

### 3.5 Flame graphs, collapsed stacks, speedscope, Firefox Profiler
- **Collapsed ("folded") stack format** (Gregg): one line per unique stack, frames root->leaf separated by `;`,
  then a space and a count: `main;parse;read_line 42`. Universal interchange format for flame graphs.
- FlameGraph scripts (https://github.com/brendangregg/FlameGraph; maintenance-mode):
  ```bash
  perf script | ./stackcollapse-perf.pl > out.folded
  ./flamegraph.pl out.folded > flame.svg
  ./difffolded.pl before.folded after.folded | ./flamegraph.pl > diff.svg   # red = grew, blue = shrank
  ./flamegraph.pl --reverse --inverted out.folded > icicle.svg             # bottom-up / "callers of hot leaf"
  ```
  Collapse scripts exist for perf, dtrace, sample (`stackcollapse-sample.awk`), instruments, gdb, jstack, etc.
- **inferno** (Rust port, faster): `cargo install inferno`; `perf script | inferno-collapse-perf | inferno-flamegraph > f.svg`;
  `inferno-diff-folded a.folded b.folded | inferno-flamegraph > diff.svg`. Also collapses `sample` and dtrace output.
- **Differential flame graphs** (https://www.brendangregg.com/blog/2014-11-09/differential-flame-graphs.html): drawn
  with the *after* profile's widths, colored by after-minus-before. Normalize sample counts (`difffolded.pl -n`) when
  runs have different total samples. Ideal artifact to attach to a perf PR.
- **speedscope** (v1.25.0, verified; https://github.com/jlfwong/speedscope): `npm i -g speedscope; speedscope
  profile.file` opens browser. Imports: its own JSON schema, collapsed stacks, Chrome trace-event / `.cpuprofile`,
  Firefox profiles, `perf script` output, Instruments deep-copy text, pprof, `stackprof`, `rbspy`, `py-spy
  --format speedscope`, Go pprof (**partially unverified**; wiki confirms speedscope JSON, collapsed stacks, trace-event).
  Views: Time Order, Left Heavy (aggregated), Sandwich (callers/callees of a function, best for "where is X called").
- **Firefox Profiler** (https://profiler.firefox.com): imports Gecko/processed profiles, `perf script` text
  (`perf script -F +pid > x.perf`), Chrome trace-event format, Android simpleperf/ART, Valgrind DHAT. Has call tree,
  flame graph, stack chart, per-thread tracks, and *profile comparison* (`/compare/` view). Data stays local unless
  uploaded.
- **Perfetto UI** (https://ui.perfetto.dev) for timeline traces (Chrome JSON, systrace, ftrace, perf).

### 3.6 Continuous profiling (production)
- **Grafana Pyroscope** v2.3.1 (2026-09-08, verified). Collect with Grafana Alloy (`pyroscope.ebpf` component for
  whole-host eBPF CPU profiles on Linux >= 4.9; `pyroscope.scrape` for pprof endpoints) or language SDKs; supports
  diff views between time ranges/labels. https://grafana.com/docs/pyroscope/latest/configure-client/grafana-alloy/
- **Parca** v0.29.1 (2026-09-28, verified): storage + UI; the Parca Agent's development merged into the
  OpenTelemetry eBPF profiler. **Polar Signals** (Parca's company) joined **Dash0** (announced 2026-08-17); Polar
  Signals Cloud continues and Parca remains open source. https://www.polarsignals.com/blog/posts/2026/08/17/polar-signals-is-joining-dash0
- **OpenTelemetry Profiles** (the "fourth signal") entered **public alpha in March 2026**: OTLP profiles support,
  Collector pipelines from v0.148.0 (pprof receiver, k8sattributes, OTTL), whole-system eBPF profiler
  (`open-telemetry/opentelemetry-ebpf-profiler`, donated by Elastic). Not for critical production: data model may
  change, no language SDK APIs yet, limited backends. https://opentelemetry.io/blog/2026/profiles-alpha/
- Others: Datadog Continuous Profiler, Google Cloud Profiler, Elastic Universal Profiling, Pyroscope-in-Grafana Cloud.
  Production profiles are the best input for choosing *what* an agent should optimize (Amdahl at fleet scale).

---

## 4. Bash/shell script profiling

### 4.1 First, know which bash you have
macOS ships **bash 3.2.57** at `/bin/bash` (verified on this machine, Darwin 27). It lacks `$EPOCHREALTIME`
(bash 5.0+), `${var@Q}`, associative arrays (4.0+), `mapfile` (4.0+), `wait -n`, etc. Install a modern bash with
`brew install bash` (`/opt/homebrew/bin/bash`) and invoke scripts explicitly with it when profiling. Bash **5.3**
(released July 2025) adds **non-forking command substitution** `${ cmd; }` (runs in the current shell, captures
stdout) and `${| cmd; }` (result taken from `$REPLY`), directly removing the most common per-iteration fork.
https://lwn.net/Articles/1029079/ . Linux CI images typically have bash 5.1-5.2 (Ubuntu 22.04: 5.1; 24.04: 5.2).

### 4.2 Whole-script timing
```bash
time ./script.sh                         # real vs user+sys; real >> user+sys => waiting (I/O, sleep, network, locks)
/usr/bin/time -v ./script.sh             # GNU (Linux): max RSS, context switches, page faults
/usr/bin/time -l ./script.sh             # macOS/BSD: max RSS, page faults, "instructions retired" and "cycles elapsed"
hyperfine --warmup 2 './script.sh fixture' 'bash ./script_v2.sh fixture'
```
User+sys >> real indicates parallelism; sys large relative to user indicates fork/exec/syscall overhead (typical of
shell scripts that spawn many processes).

### 4.3 Per-line timing with xtrace (`set -x`) + PS4
```bash
#!/usr/bin/env bash   # must be bash >= 5.0 for EPOCHREALTIME
exec {XFD}>"/tmp/trace.$$.log"           # dedicated FD (bash 4.1+ syntax), keeps stderr clean
BASH_XTRACEFD=$XFD
PS4='+ ${EPOCHREALTIME} ${BASH_SOURCE}:${LINENO} ${FUNCNAME[0]:-main} '
set -x
# ... script body ...
set +x
```
Or without editing the script: `PS4='+ ${EPOCHREALTIME} ${BASH_SOURCE}:${LINENO} ' bash -x ./script.sh 2>trace.log`
(PS4 is inherited from the environment only if exported; bash 4.4+ ignores an imported PS4 when running as root? -
**unverified**; passing via `env PS4=... bash -x` works for normal users).

Notes:
- `$EPOCHREALTIME` is a builtin variable (no fork, microsecond resolution). **Do not** use `$(date +%s.%N)` in PS4 on
  real measurements: it forks `date` for every traced command, which dominates and distorts timings (in a test here a
  50-iteration arithmetic loop was attributed 165 ms, almost all of it the `date` forks). BSD `date` on older macOS
  doesn't support `%N` (recent macOS prints nanoseconds; observed on Darwin 27).
- The number of leading `+` characters encodes subshell/command-substitution nesting depth (the first char of PS4
  is repeated). Lines inside `$(...)` show up as `++`.
- Time between trace line *i* and line *i+1* is attributed to command *i*; xtrace prints a command *before* running
  it. Commands that run in the background or in subshells interleave.
- xtrace overhead is substantial (string formatting on every command); use it to find *where* time goes, not for
  absolute numbers. Confirm improvements with hyperfine with tracing off.
- zsh equivalent: `zmodload zsh/datetime; PS4='+%D{%s.%6.} %N:%i> '; setopt xtrace` (`%D{...}` strftime with `%6.`
  microseconds, `%N` script/function name, `%i` line). (**Partially unverified**: `%.`/`%6.` fractional-second syntax
  per zsh docs.)

Summarizer (tested here on a sample script; works on macOS awk and gawk):
```awk
# xtrace-summary.awk  usage: awk -f xtrace-summary.awk trace.log | sort -rn | head -20
# input lines: "+ <epoch.frac> <file>:<line> <cmd...>"
$1 ~ /^\++$/ && $2 ~ /^[0-9]+\.[0-9]+$/ {
  if (prev != "") { d = $2 - pt; tot[prev] += d; cnt[prev]++ }
  prev = $3; pt = $2
}
END { for (k in tot) printf "%10.6f %6d %s\n", tot[k], cnt[k], k }
```
Output columns: total seconds attributed, number of executions, `file:line`. High-count lines with modest per-call
cost are the loop bodies to fix. Off-the-shelf alternatives: `bashprof`-style scripts, and the trap-based approach
`trap 'echo "$EPOCHREALTIME $LINENO" >&3' DEBUG` (similar overhead, finer control).

### 4.4 Counting forks/execs and syscalls
The dominant cost in slow shell scripts is almost always **process creation** (fork+exec ~0.5-2 ms each on Linux,
often more on macOS), not the shell's own interpretation.
```bash
# Linux
strace -f -c -o summary.txt ./script.sh                 # syscall counts/time across children
strace -f -e trace=execve -o execs.txt ./script.sh; grep -c execve execs.txt       # number of exec'd programs
strace -f -e trace=execve ./script.sh 2>&1 | grep -o 'execve("[^"]*"' | sort | uniq -c | sort -rn | head   # which tools
strace -f -e trace=clone,clone3,fork,vfork -c ./script.sh   # number of forks (subshells + externals)
perf stat -e task-clock,context-switches,cpu-migrations,page-faults ./script.sh
sudo bpftrace -e 'tracepoint:sched:sched_process_fork { @forks[comm] = count(); }'   # system-wide fork counts by parent comm
sudo execsnoop-bpfcc -t      # live list of every exec with timestamps

# macOS
sudo dtruss -f -c /tmp/bash ./script.sh                  # copy of bash outside /bin (SIP); counts syscalls incl. children
sudo eslogger exec > execs.json & ./script.sh; kill %1   # Endpoint Security exec events (macOS 13+), JSON
/usr/bin/time -l ./script.sh                             # rough: "involuntary context switches", RSS
```
Cheap in-script fork counter (bash 5): compare `$BASHPID` changes, or wrap with
`strace -f -qq -e trace=execve` in CI. A good per-script KPI to put in a budget test: "number of execve calls on
fixture X at most  N" (deterministic, platform-stable on Linux).

### 4.5 Shell performance anti-patterns (and fixes)
| Anti-pattern | Why slow | Fix |
|---|---|---|
| `$(...)` / backticks inside a loop body (`x=$(echo "$line" \| cut -d, -f2)`) | fork (+exec) per iteration | Parameter expansion: `${line#*,}`, `${line%%,*}`, `${var//a/b}`, `${#var}`, `${var:off:len}`; `IFS=, read -r a b c <<< "$line"`; bash 5.3 `${ cmd; }` for functions |
| `while read` loop over a large file calling sed/awk/grep/jq/cut per line | N processes | One pass of `awk`/`sed`/`jq` over the whole file; `jq -c '.[]'` once instead of `jq` per item; `grep -F -f patterns.txt` instead of a grep per pattern |
| `while read line` itself on large files (>~100k lines) | bash reads byte-by-byte from pipes; interpreted loop | `awk`, `mapfile -t arr < file` (bash 4+) then loop, or rewrite in Python/Go |
| `cat file \| grep x` ("useless cat") | extra process + pipe copy | `grep x file` / `< file grep x` (small cost per call; matters in loops) |
| `cmd \| wc -l` to test existence | runs to completion | `grep -q`, `[[ -n $(...) ]]` -> `grep -q` short-circuits |
| Pipes into `while read` that set variables | loop runs in a subshell (vars lost) and adds forks | `while ...; done < <(cmd)` or `shopt -s lastpipe` (non-interactive) |
| `find ... -exec cmd {} \;` | one exec per file | `find ... -exec cmd {} +` (batched) or `find -print0 \| xargs -0 cmd` |
| Serial work on many files | single core | `xargs -0 -P "$(nproc)" -n 50 cmd` (macOS: `sysctl -n hw.ncpu`), GNU `parallel -j+0`, `make -j` |
| `for f in $(ls *.txt)` / unquoted `$var` | word-splitting + globbing per expansion, correctness bugs, extra `ls` process | `for f in *.txt` with `shopt -s nullglob`; quote expansions |
| `expr`, `bc`, `basename`, `dirname`, `seq` in loops | external process each | `$(( ))`, `${path##*/}`, `${path%/*}`, `for ((i=0;i<n;i++))`, `{1..100}` |
| `echo "$x" \| tr a-z A-Z` | fork | `${x^^}` / `${x,,}` (bash 4+) |
| `date` called per log line | fork | `printf '%(%F %T)T' -1` (bash 4.2+), `$EPOCHSECONDS`/`$EPOCHREALTIME` (bash 5) |
| `source`-ing big files repeatedly, or re-running `command -v`/`which` | repeated parsing/PATH search | cache results in variables; `hash` |
| Slow external tools by default (GNU vs BSD differences; `grep` with locale) | UTF-8 locale regex is slower | `LC_ALL=C grep ...` for byte-wise matching when safe; `rg` for big trees |
| `sleep`-based polling | wall time | event-driven waits (`wait`, `inotifywait`, `fswatch`) |
| Running the shell with `-x` or `set -o functrace` in prod | overhead | ensure tracing off |

Example rewrite (and how to prove it):
```bash
# slow: 3 processes per line
while IFS= read -r line; do
  user=$(echo "$line" | cut -d: -f1); shell=$(echo "$line" | awk -F: '{print $7}')
  [ "$shell" = /bin/bash ] && echo "$user"
done < passwd.big
# fast: 1 process total
awk -F: '$7=="/bin/bash"{print $1}' passwd.big
# prove: hyperfine --warmup 2 -n loop 'bash slow.sh' -n awk 'bash fast.sh'; and diff outputs for equality first
```

### 4.6 Shell startup time (interactive zsh/bash)
```bash
hyperfine --warmup 3 'zsh -i -c exit' 'zsh -f -i -c exit'      # rc files vs no rc (-f): shows rc cost
hyperfine --warmup 3 'bash -i -c exit' 'bash --norc -i -c exit'
# zsh function-level profile:
#   first line of ~/.zshrc:  zmodload zsh/zprof
#   last line of ~/.zshrc:   zprof          (prints calls, self/total time per function)
zsh -i -c 'zprof' 2>/dev/null | head -30   # if zprof loaded in .zshrc
# zsh line-level trace with timestamps:
zsh -i -x -c exit 2>&1 | head    # or set PS4 with %D{%s.%6.} as in 4.3; `zsh -xv` adds verbose source echo
# bash:
PS4='+ $EPOCHREALTIME ${BASH_SOURCE}:${LINENO} ' bash -i -x -c exit 2> bash-startup.trace
```
- `zsh -i -c exit` measures total init time; it does **not** equal perceived prompt latency (prompt themes,
  deferred/async plugin loading, instant-prompt). `romkatv/zsh-bench` measures first-prompt lag, first-command lag,
  command lag, input lag through a virtual TTY and gives baseline thresholds (e.g., first prompt lag ~50 ms as the
  perception threshold). https://github.com/romkatv/zsh-bench
- Usual culprits: `compinit` without `-C`/dump caching, `nvm`/`pyenv`/`rbenv`/`conda` init (use lazy loading),
  `brew shellenv`/`$(brew --prefix)` subshells (hardcode paths), oh-my-zsh plugin count, `eval "$(tool init zsh)"`
  per startup (cache output to a file).

### 4.7 When to rewrite shell in Python/Go
Rewrite (or move the hot part into a single awk/jq/Python invocation) when any of these hold:
- A loop over data runs >~1k iterations and calls external tools per iteration (process creation dominates).
- You need real data structures (nested maps, JSON manipulation beyond a single `jq` pass), floating point, or
  concurrency with error handling.
- The script exceeds ~100-200 lines of logic, has tricky quoting, or needs unit tests (Google's Shell Style Guide
  recommends a real language beyond ~100 lines or complex control flow:
  https://google.github.io/styleguide/shellguide.html).
- Measured: `strace -f -c` shows execve/clone counts in the thousands, or `sys` time comparable to `user`.
Keep shell when it's orchestration of a handful of long-running tools (where the tools dominate run time).
Python startup (~15-40 ms) is itself a cost for tiny scripts invoked thousands of times; Go/Rust binaries start in ~1 ms.

---

## 5. Continuous benchmarking and regression gates in CI (GitHub Actions)

### 5.1 Tool landscape (status checked 2026-10-05)
| Tool | Model | Noise strategy | Status |
|---|---|---|---|
| **CodSpeed** (https://codspeed.io) | SaaS + OSS runner/CLI; integrations pytest-codspeed (5.0.3), codspeed-rust, codspeed-node, Go, C++; generic `codspeed exec` (Jan 2026) | **CPU simulation** (Valgrind-based instruction/cache simulation, single run, under 1% variance, hardware-independent), **walltime** on CodSpeed-managed bare-metal "macro runners" (now also collects HW counters), **memory** (heap allocations) | Active; CLI v5.4.0 (2026-10-02) |
| **Bencher** (https://bencher.dev) | OSS (self-host or cloud) `bencher run` wrapper + many adapters (hyperfine JSON, criterion, pytest-benchmark, Go, Google Benchmark, JMH, Gungraun, ...) | Statistical thresholds over history (t-test, z-score, log-normal, IQR, delta-IQR, percentage, static) or **relative** same-job comparison | Active; v0.6.13 (2026-09-28) |
| **github-action-benchmark** (https://github.com/benchmark-action/github-action-benchmark) | Stores history in `gh-pages` JSON, plots charts, alerts on ratio threshold | Simple ratio (`alert-threshold: '150%'` default) | Active; v1.22.2 (2026-09-15) |
| **Conbench** (https://github.com/conbench/conbench) | Self-hosted server (Apache Arrow's CB) | History + z-score-like detection | Low activity; not archived (a search summary claiming archival was wrong) |
| **Nyrkiö** | Change-point detection (E-divisive / Hunter) SaaS | Change points over history instead of pairwise thresholds | Active (2025 MooBench study: https://arxiv.org/pdf/2510.11310) |
| Language-native | `benchstat`, `critcmp`, `pyperf compare_to`, asv (airspeed velocity; `asv continuous base HEAD`) | Paired comparisons | Active |

### 5.2 Patterns
1. **Deterministic gate on every PR** (cheap, low flake): instruction counts via CodSpeed simulation, Gungraun, or
   `perf stat -e instructions:u` / `valgrind --tool=cachegrind`; threshold 1-3%.
2. **Relative same-runner comparison** for wall time: in one job, build base and PR, run both interleaved, compare
   statistically; fail only on large regressions (10-25% on shared runners). Bencher's "relative continuous
   benchmarking" formalizes this (`--start-point main --start-point-reset --threshold-test percentage
   --threshold-upper-boundary 0.25`).
3. **Historical statistical baselines on main** for trend detection (Bencher t-test with
   `--threshold-max-sample-size 64 --threshold-upper-boundary 0.99`, CodSpeed, github-action-benchmark, Nyrkiö
   change points). Store CPU model/runner metadata with each data point.
4. **Dedicated hardware** for anything wall-clock that must be tight: self-hosted bare-metal runner, CodSpeed macro
   runners, or a quiet machine with `pyperf system tune`.
5. **Budgets as tests** for user-facing numbers (startup time, bundle size, RSS) with headroom and a retry-once policy.
6. **Flaky perf test mitigation**: retry on failure and require the regression to reproduce; widen thresholds per
   benchmark based on its measured CoV; quarantine high-variance benchmarks; record environment and pin runner image;
   prefer counts over times; never gate on a single run.

### 5.3 GitHub Actions snippets
```yaml
# CodSpeed (CPU simulation) for Python
- uses: CodSpeedHQ/action@v5        # latest v5.4.0 (2026-10-02, verified)
  with:
    mode: simulation                # or walltime (requires CodSpeed macro runner labels)
    run: pytest tests/ --codspeed
    token: ${{ secrets.CODSPEED_TOKEN }}   # OIDC supported for public repos (unverified detail)
```
```yaml
# hyperfine -> github-action-benchmark (custom JSON)
- run: |
    hyperfine --warmup 3 --runs 20 --export-json h.json './bin/tool fixture'
    jq '[.results[] | {name: .command, unit: "s", value: .median}]' h.json > bench.json
- uses: benchmark-action/github-action-benchmark@v1
  with:
    tool: customSmallerIsBetter
    output-file-path: bench.json
    github-token: ${{ secrets.GITHUB_TOKEN }}
    auto-push: ${{ github.ref == 'refs/heads/main' }}
    alert-threshold: '120%'
    comment-on-alert: true
    fail-on-alert: true
```
```bash
# Bencher with hyperfine adapter (relative mode, same job)
bencher run --project my-proj --branch "$GITHUB_HEAD_REF" --start-point "$GITHUB_BASE_REF" --start-point-reset \
  --testbed ubuntu-latest --adapter shell_hyperfine --file h.json \
  --threshold-measure latency --threshold-test percentage --threshold-upper-boundary 0.15 --thresholds-reset \
  --error-on-alert --github-actions "$GITHUB_TOKEN" \
  "hyperfine --warmup 3 --runs 20 --export-json h.json './bin/tool fixture'"
```
(Adapter name `shell_hyperfine` verified in Bencher adapter docs; flag spellings verified against Bencher docs for
`--threshold-*`, `--start-point*`, `--error-on-alert`.)

---

## 6. LLM / AI-agent-driven performance optimization (2024-2026)

### 6.1 Benchmarks: what the evidence says
| Work | Setting | Headline finding |
|---|---|---|
| **PIE** - Learning Performance-Improving Code Edits (Shypula et al., ICLR 2024) https://pie4perf.com | 77k C++ competitive-programming pairs; timing in **gem5 simulator** for determinism | Best: mean 6.86x speedup with 8 samples (humans avg 3.66x); best-of-8 + correctness filter + performance-conditioned fine-tuning reaches 9.56x. Lesson: deterministic measurement, sample-many-then-filter-by-correctness-and-speed. |
| **Supersonic / SBLLM** - Search-Based LLMs for Code Optimization (Gao et al., ICSE 2025, award) https://arxiv.org/abs/2408.12159 | Iterative search: select representative candidates, retrieve optimization patterns, genetic-operator prompting | Iterative refinement with execution feedback beats one-shot; +8.7-28% top-5 speedup rate (Python). |
| **ECCO** (Waghjale et al., EMNLP 2024) https://arxiv.org/abs/2407.14044 | Python efficiency, NL-to-code and history-based editing | "No existing method can improve efficiency without sacrificing functional correctness"; execution feedback helps preserve correctness, NL feedback gives bigger speedups. |
| **EffiBench** (NeurIPS 2024 D&B), **Mercury** (NeurIPS 2024 D&B; Beyond@K metric) | LeetCode-style efficiency | LLM code passes but is less efficient than human canonical solutions (Mercury: ~65% Pass vs under 50% Beyond). |
| **Rethinking Code Performance Benchmarks for LLMs** (Le et al., 2026-07) https://arxiv.org/abs/2607.07619 | Re-audit of EffiBench/Enamel/EvalPerf/Mercury | With rigorous measurement only **6.11%** of "performant" solutions are significantly faster than canonical; tests lack inputs that expose complexity differences. Lesson: performance tests must exercise large/adversarial inputs. |
| **SWE-Perf** (2025) https://arxiv.org/abs/2507.12415 | 140 repo-level instances from perf PRs | Expert 10.85% gain vs best agent (OpenHands + Claude 3.7) 2.26%; agents often optimize irrelevant code. |
| **GSO** (Shetty et al., 2025) https://gso-bench.github.io | 102 tasks, 10 codebases, multiple languages; Opt@1 = >=95% of expert speedup + passes tests | Initial leading agents under 5%; failures: low-level languages, "lazy" optimizations, bottleneck mis-localization. Leaderboard now has a **Hack Detector** penalizing memoization and harness hijacking; "Hack-Adjusted" column. |
| **SWE-fficiency** (2025) https://arxiv.org/abs/2511.06090 | 498 tasks, 9 data-science/ML/HPC repos; Speedup Ratio vs gold patch | Agents average under 0.15x expert speedup; "convenience bias" toward small input-specific edits. |
| **FormulaCode** (Sehgal et al., 2026-03) https://arxiv.org/abs/2603.16011 | 957 perf issues from scientific Python repos, ~265 community perf tests per task (asv-style), multi-objective | Repo-scale multi-objective optimization remains a major challenge for frontier agents. |
| **SWE-Pro (perf)** (Sarikayak et al., 2026-06) https://arxiv.org/abs/2606.25530 | 102 expert optimizations; runtime and memory | Experts: 15.5x aggregate speedup, 171x peak-memory reduction; current LLMs: negligible runtime gains, almost no memory optimizations. |
| **Audit: Are Performance-Optimization Benchmarks Reliably Measuring Coding Agents?** (Chen et al., 2026-07) https://arxiv.org/abs/2607.01211 | Replays reference patches of SWE-Perf/GSO/SWE-fficiency on 4 cloud machine types | Only 39/102 GSO, 11/140 SWE-Perf, 411/498 SWE-fficiency reference patches stayed valid across machines; rankings disagree on 9/28 pairs; harmonic-mean scoring lets the worst 10 tasks carry 58-83% of score weight. Lesson: **cross-machine noise invalidates many "speedups"**. |
| **PerfAgent** (Deng et al., 2026-07) https://arxiv.org/abs/2607.19653 | Profiler-guided iterative refinement | Uses *profiler evidence rather than timing alone* to choose next target: GSO expert-matching 19.6% -> 39.2%, SWE-fficiency-Lite 26% -> 74%, >2x over OpenHands baseline. Strongest direct evidence for "profile in the loop". |
| **Performance-Aligned LLMs** (Nichols et al., LLNL/UMD; TPDS 2026) https://arxiv.org/abs/2404.18864 | RL with performance feedback (RLPF) + DPO for HPC code | Expected speedup 0.9 -> 1.6 (serial), 1.9 -> 4.5 (OpenMP). |
| **Scalene AI optimization** (Berger et al.; v2.3.0 2026-05) https://github.com/plasma-umass/scalene | Line-level CPU/GPU/memory profiler that proposes LLM optimizations per hot line/region; MCP server variants exist | Profiler-localized prompting; open models (DeepSeek-R1) produce comparable proposals (arXiv 2502.10299). |
| **Google ECO** (OSDI 2026 operational systems) https://arxiv.org/abs/2503.15669 | Fleet continuous profiling + embedding search for anti-patterns + fine-tuned LLM refactors + multi-stage verification (tests, LLM self-review, post-deploy monitoring) | >6,400 commits, >25,000 lines, >99.5% production success; ~500k normalized CPU cores saved per quarter. Lesson: localization from production profiles + anti-pattern dictionary + heavy verification. |
| **AlphaEvolve** (Google DeepMind, May 2025) https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/ | Evolutionary search: Gemini Flash+Pro generate diffs, automated evaluators score, program database keeps best/diverse | 23% speedup on a Gemini matmul kernel (~1% training time), up to 32.5% FlashAttention kernel speedup; months of tuning -> days. |
| **OpenEvolve** (OSS AlphaEvolve-style; v0.4.0 2026-09-28) https://github.com/algorithmicsuperintelligence/openevolve | Configurable evaluator + MAP-Elites style database | Practical open implementation of evolve-with-evaluator loops. |
| **"Simple Baselines are Competitive with Code Evolution"** (Gideoni, Risi, Gal; ICLR 2026 workshop) https://openreview.net/forum?id=QSWFqDcveB | Compares evolution pipelines vs simple baselines | Simple baselines match/exceed sophisticated evolution in 3 domains. Lesson: the evaluator and budget matter more than the search scaffolding. |
| **Meta KernelEvolve** (ISCA 2026) https://engineering.fb.com/2026/04/02/developer-tools/kernelevolve-how-metas-ranking-engineer-agent-optimizes-ai-infrastructure/ | Production agent generating Triton kernels; job harness evaluates each candidate and feeds diagnostics back; search over hundreds of candidates | 1.25-17x kernel speedups; >60% inference throughput (Andromeda ads, NVIDIA), >25% training throughput (MTIA). |
| **Karpathy autoresearch** (March 2026) https://github.com/karpathy/autoresearch | Minimal agent loop: edit -> time-boxed run -> metric -> keep (advance branch) or `git reset` -> log to `results.tsv` | Popularized git-as-memory keep/discard loops; many Claude Code "autoresearch" skills derive from it. |
| Self-Refine (Madaan et al., 2023) https://arxiv.org/abs/2303.17651 | Generic iterate-with-self-feedback | Included code-optimization tasks; self-feedback alone is weaker than execution/profiler feedback for perf. |

### 6.2 What made agent loops succeed
1. **Profiler-guided localization** (PerfAgent, ECO, Scalene): choose the edit target from measured hot spots, not
   from code reading. Mis-localization is the #1 documented failure.
2. **A trustworthy, cheap evaluator** in the loop: deterministic simulators (PIE/gem5), instruction counts, or a
   dedicated harness with repeated measurements (KernelEvolve, AlphaEvolve). Evaluator quality dominates scaffolding
   sophistication ("Simple Baselines...").
3. **Correctness as a hard gate before any timing**: run tests first; reject on any behavior change (ECO, GSO Opt@1,
   ECCO's correctness-efficiency tradeoff).
4. **Iterate with measured feedback** (SBLLM, PerfAgent, KernelEvolve): feed back numbers *and* diagnostics
   (profile diff, counters, failing test output), not just "faster/slower".
5. **Sample several candidates, keep the best that passes** (PIE best-of-8; AlphaEvolve program database;
   autoresearch keep/discard with git reset). Always retain the incumbent; never "accumulate" unverified changes.
6. **Anti-pattern knowledge** (ECO mined dictionary; PIE retrieval few-shot): retrieval of known optimization
   patterns improves hit rate.
7. **Post-change monitoring** (ECO): verify the win in the real environment, roll back if not.

### 6.3 Failure modes to guard against
- **Bottleneck mis-localization / premature optimization**: editing code that is not hot (SWE-Perf, GSO).
  Guard: require a profile excerpt and Amdahl ceiling in every hypothesis.
- **Micro-optimizations with no measurable effect / "lazy" or convenience edits** (GSO, SWE-fficiency): small local
  tweaks below the noise floor. Guard: MDE check; reject changes whose CI includes 0 effect.
- **Breaking semantics**: changed output, precision, ordering, error handling, thread-safety (ECCO). Guard: full test
  suite + output diff on representative inputs + property tests for edge cases.
- **Noise mistaken for wins**: single runs, non-interleaved runs, different machines (the 2026 audit shows many
  benchmark "speedups" do not survive machine changes). Guard: interleaved repeated runs, CI on ratio, re-run to
  confirm, same machine for A/B.
- **Reward hacking / benchmark gaming**: memoizing or caching benchmark inputs across runs, detecting the harness,
  special-casing fixture data, hijacking the timing harness, skipping work whose results aren't checked, warming
  caches in `--prepare`, reducing workload size, disabling tests (GSO Hack Detector; Heiser "same dataset for
  calibration and validation"). Guard: hold-out workloads the agent never sees, randomized inputs/seeds, check that
  the benchmark file and harness are unchanged in the diff, review diffs for caches keyed on inputs.
- **Overfitting to one platform**: e.g., AVX-512-only paths, macOS-only gains. Guard: confirm on the CI/production
  platform.
- **Regressing other metrics**: memory, startup, tail latency, readability. Guard: multi-metric gates (FormulaCode's
  multi-objective framing).

### 6.4 Recommended agent loop (synthesized)
```
setup:   pin metric + workload + budget; write/locate correctness tests; record environment; build harness
baseline:N>=10 interleaved runs -> median/IQR; noise floor = CoV; compute MDE
loop:
  profile current best (samply/perf/xctrace/py-spy/xtrace-summary) -> top hot spots with % inclusive
  pick target with largest Amdahl ceiling above MDE; write hypothesis + predicted gain
  implement ONE change on a scratch branch/commit
  run tests -> fail => discard (git reset), log
  measure interleaved vs incumbent -> bootstrap CI of ratio
  keep iff CI excludes practical threshold and no other gated metric regresses; else discard
  log experiment row; stop when budget met, ceilings < MDE, or N consecutive discards
finish:  confirm on target platform / CI; attach before/after numbers + diff flame graph to the PR
```

---

## 7. Perf experiment log format

### 7.1 Prior art
- **Karpathy autoresearch `results.tsv`**: `commit  metric  memory_gb  status(keep|discard|crash)  description`;
  untracked by git; git branch history is the memory of kept changes. https://github.com/karpathy/autoresearch/blob/master/program.md
- **Meta ServiceLab**: every code change is an A/B experiment with control and treatment on reserved, matched
  servers; statistical tests account for machine-factor variance; results tie to diffs. (OSDI 2024)
- **Google**: perf work driven by GWP fleet profiles; ECO changes go through test + self-review + post-deploy
  monitoring. Internal "perflab"/benchmark-experiment tooling exists but public detail is limited (**unverified** naming).
- **Mozilla Perfherder/Talos**, **Chromium Pinpoint** (bisects perf regressions with repeated A/B runs on lab devices),
  **asv** (airspeed velocity; per-commit history and `asv compare`) are open prior art for regression
  bookkeeping (descriptions from general knowledge; **unverified** in this session).
- Scientific lab-notebook style: pre-registered hypothesis and prediction before measuring (guards against HARKing).

### 7.2 Recommended format (one row per experiment, plus optional detail block)
TSV/JSONL (machine-readable, append-only, outside of tracked source or in `perf/experiments.jsonl`):
```json
{"id":"E07","date":"2026-10-05T14:02Z","base":"a1b2c3d","candidate":"e4f5a6b",
 "hypothesis":"parse_line forks cut+awk per line (62% inclusive in xtrace-summary); single awk pass removes ~60%",
 "predicted":"-55% wall","change":"replace while-read loop (lines 40-58) with one awk program",
 "metric":"wall_s median","workload":"fixtures/big.log (200k lines)","harness":"hyperfine -N, 10x3 interleaved",
 "env":"M3 Pro, macOS 27.0, AC power, bash 5.3.3; hyperfine 1.21.0",
 "before":{"median":4.812,"iqr":0.091,"n":30},"after":{"median":0.214,"iqr":0.006,"n":30},
 "ratio":0.0445,"ci95":[0.0439,0.0452],"p_mwu":1e-11,
 "secondary":{"execve_count":{"before":600412,"after":3},"max_rss_mb":{"before":9,"after":11}},
 "tests":"pass (bats 48/48; output diff identical)","verdict":"keep",
 "notes":"bottleneck moved to sort (71%); next: E08 LC_ALL=C sort"}
```
Human-readable PR/commit summary template:
```
Perf: <short title>
Hypothesis: <cause> -> <change> should improve <metric> by ~X% (profile: <hot spot, % inclusive>)
Result:  <metric> <before median (IQR)> -> <after median (IQR)>, ratio 0.xx [95% CI a-b], n=.., MWU p=..
Env:     <CPU, OS, power, tool versions>, interleaved runs, warmup k
Guards:  tests pass; outputs identical on <inputs>; memory <before -> after>; no harness/benchmark files changed
Verdict: keep | discard | inconclusive (below MDE ~x%)
Artifacts: diff flame graph, hyperfine JSON, raw logs
```
Rules: log discards and inconclusive results too (they prevent re-trying dead ends); never edit past rows; include
the predicted effect so model errors are visible; record environment every time.

---

## 8. Quick reference: default tool choices for an agent

| Need | macOS (Apple Silicon) | Linux / CI |
|---|---|---|
| Time a command / A/B | `hyperfine` (+ interleave script, bootstrap) | same; `perf stat -r` |
| CPU profile any native/Rust/C/C++/Go binary | `samply record --save-only`; `xcrun xctrace record --template 'Time Profiler'`; `sample` | `perf record -g` / `samply`; flame graph via inferno |
| Deterministic counts | Instruments CPU Counters; Linux VM/container for Valgrind | `perf stat -e instructions:u`, `valgrind --tool=cachegrind/callgrind`, CodSpeed simulation, Gungraun |
| Syscalls / forks | `/tmp/bash` copy + `sudo dtruss -c -f`; `sudo eslogger exec`; `fs_usage` | `strace -f -c`, `strace -f -e trace=execve`, `bpftrace`, `execsnoop` |
| Shell per-line cost | bash 5 (Homebrew) + PS4 `$EPOCHREALTIME` + xtrace-summary.awk; zsh `zprof` | same |
| Shell startup | `hyperfine 'zsh -i -c exit'`, `zprof`, `zsh-bench` | same |
| Visualize | Firefox Profiler, speedscope, Instruments | Firefox Profiler, speedscope, FlameGraph/inferno, Perfetto |
| Diff two profiles | `difffolded.pl`/`inferno-diff-folded`; Firefox Profiler compare | same; Pyroscope diff view |
| CI regression gate | (avoid wall-clock on macOS runners) | CodSpeed, Bencher, github-action-benchmark, benchstat/critcmp/pyperf |
| Production | - | Pyroscope / Parca / OTel eBPF profiler (alpha) |

---

## Sources (selected, beyond inline links)
- hyperfine releases: https://github.com/sharkdp/hyperfine/releases (v1.21.0, 2026-10-05)
- CodSpeed docs/CLI: https://codspeed.io/docs/instruments , https://codspeed.io/changelog/2026-01-23-introducing-codspeed-cli
- Bencher thresholds and relative benchmarking: https://bencher.dev/docs/explanation/thresholds/ , https://bencher.dev/docs/how-to/track-benchmarks/
- pyperf system tuning: https://pyperf.readthedocs.io/en/latest/system.html
- Gungraun (ex iai-callgrind): https://github.com/gungraun/gungraun
- speedscope formats: https://github.com/jlfwong/speedscope/wiki/Importing-from-custom-sources
- Firefox Profiler perf guide: https://github.com/firefox-devtools/profiler/blob/main/docs-user/guide-perf-profiling.md
- xctrace man page: https://keith.github.io/xcode-man-pages/xctrace.1.html
- OTel profiles alpha: https://opentelemetry.io/blog/2026/profiles-alpha/ ; Polar Signals: https://www.polarsignals.com/blog/posts/2026/03/26/opentelemetry-profiling-goes-alpha
- Apple Silicon QoS/core types: https://eclecticlight.co/2024/12/17/tune-for-performance-core-types/
- SIP and dtrace: https://8thlight.com/insights/a-few-dtrace-gotchas-and-workarounds-on-os-x
- Bash 5.3: https://lwn.net/Articles/1029079/
- zsh-bench: https://github.com/romkatv/zsh-bench
- GSO: https://arxiv.org/abs/2505.23671 ; SWE-Perf: https://arxiv.org/abs/2507.12415 ; PIE: https://arxiv.org/abs/2302.07867
- Mercury: https://proceedings.neurips.cc/paper_files/paper/2024/file/1df1df43b58845650b8dada00fca9772-Paper-Datasets_and_Benchmarks_Track.pdf ; EffiBench: https://papers.nips.cc/paper_files/paper/2024/file/15807b6e09d691fe5e96cdecde6d7b80-Paper-Datasets_and_Benchmarks_Track.pdf
- KernelEvolve paper: https://arxiv.org/abs/2512.23236
