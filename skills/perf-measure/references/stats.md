# Statistics for benchmark comparisons (ADR-0005)

**The rule (owner decision 2026-10-05).** Wall-clock, or the user's own metric, is primary, measured interleaved in
fresh processes. A change counts as **improved** or **regressed** only if:
- the 95% CI on the median ratio excludes 1.0;
- the point estimate is past the minimum effect;
- p < 0.05 (0.01 at R4+).

Instruction counts are recorded alongside as corroboration and never decide. Tool-native statistics (pyperf t-tests,
hyperfine Welch, mitata summaries) are reported but never decide (ADR-0006 follow-up).

## Paired analysis of interleaved runs

`abtest` runs every arm once per block, in shuffled order, so sample *i* of A and sample *i* of B ran seconds apart
under the same conditions. perfkit therefore analyses **per-block log ratios**:
- the point estimate is exp(median log(bᵢ/aᵢ)), with a bootstrap CI over blocks;
- the test is Wilcoxon signed-rank.

Pairing cancels drift that both arms share, such as thermal throttling or a background job starting. On a busy
machine it can shrink the CI several-fold compared with pooling the samples. Duet benchmarking reports 5–37×
accuracy gains from the same idea. The unpaired path (Mann-Whitney U plus a bootstrap on the ratio of medians) is
used for samples that weren't interleaved, such as two pyperf files or mitata's in-process samples, or when
`--unpaired` is given.

## What perfkit computes and why

- **Median and IQR, not mean ± stdev.** Benchmark timings are right-skewed (GC, scheduling,
  cache misses, and on Apple Silicon the occasional E-core run) and often bimodal. The median
  is robust to the tail, and IQR/median is the noise level.
- **The ratio of medians, B/A, with a 95% percentile-bootstrap CI** (4,000 resamples,
  seeded). The ratio is unit-free and reads directly as "B takes 0.55× the time". The CI
  says how sure we are.
- **Mann-Whitney U** (two-sided, tie-corrected normal approximation): is B's distribution
  shifted relative to A's? It assumes no normality. Its p-value is a sanity check alongside
  the CI.
- **Cliff's delta**, from −1 (every B faster than every A) to +1 (every B slower). It is an
  effect size that ignores magnitudes.

## Verdict rule (lower is better; mirrored for `--higher-is-better`)

With minimum effect `m` (default 2%) and significance level α (default 0.05):

| Verdict | Condition |
|---|---|
| improved | CI upper < 1, ratio ≤ 1 − m, p < α |
| regressed | CI lower > 1, ratio ≥ 1 + m, p < α |
| equivalent | the whole CI inside [1 − m, 1 + m] |
| below-threshold | CI excludes 1 and p < α, but the ratio is inside ±m (real, but too small to matter) |
| inconclusive | everything else; `runs_needed` estimates the runs per arm that would narrow the CI below m |

**Choose `m` before measuring.** It should reflect what matters to the user and the noise
floor of the environment:
- 2–5% on a quiet machine;
- 10–25% for wall time on shared CI runners;
- 0.5–2% for instruction counts.

## Noise and the minimum detectable effect (MDE)

Rule of thumb for ~80% power: **MDE ≈ 2.8 × CV × √(2/n)**, equivalently **n ≈ 15.7 × (CV/δ)²** runs per arm to
detect a relative change δ (α = 0.05). CV is the relative spread per arm (`iqr_rel` ≈ 1.35 × CV for normal-ish data);
with pairing, use the CV of the per-block ratios, which is usually much smaller.

Measured references:
- GitHub-hosted runners have CV ≈ 2.66%: a 2% gate gives about 45% false positives, and about 7% is needed to get
  under 1% (CodSpeed).
- CodSpeed's bare-metal runners have CV 0.56%.
- On this M4 under load average ~10, unpaired wall CV was 5–13%, while instructions retired had CV 0.05–1%.
- CV 3%, n = 20 → MDE ≈ 2.7%
- CV 10%, n = 20 → MDE ≈ 9%. You can't see a 5% win there. Reduce the noise, or switch to a
  counter.

To reduce noise, most effective first:
1. A longer workload per run, so each run takes at least 100 ms.
2. Interleaving (abtest).
3. A quiet machine: AC power, no Low Power Mode, nothing heavy in the background.
4. `pyperf system tune` (Linux).
5. Pinning or isolating cores (Linux `taskset`). macOS has no user-space core pinning.
6. Deterministic counters: `perf stat -e instructions:u`, Valgrind/cachegrind, or CodSpeed
   simulation. These are Linux-only and blind to I/O and syscalls.

## Interleaving and repetition levels

- **Drift is the enemy.** Thermal throttling, background jobs and frequency changes make
  "all of A, then all of B" biased. Shuffle within blocks (abtest does), or alternate
  ABAB…
- **Repeat at the level with the most variance** (Kalibera & Jones). Variance between
  processes (ASLR, hash seeds, memory layout) is often larger than between iterations in
  one process. Multiple processes (abtest, pyperf) beat a long loop in one process.
- The **environment size, the cwd and the link order** can bias results by several percent
  (Mytkowicz et al. 2009). Keep them identical for both arms. Worktrees at equal path
  depth help.

## Many benchmarks at once

- At α = 0.05, 100 benchmarks produce about 5 false alarms per run. Before calling any
  single benchmark regressed: rerun the flagged ones, use α = 0.01 (R4+), or require a
  regression to reproduce.
- **Summarize a suite with the geometric mean of the ratios**, never the arithmetic mean of
  ratios or of raw times.

## Percentiles

- For latency claims, report p50, p95, p99 and max, with the number of samples.
- A p99 needs hundreds of samples or more; with n = 20, p95 is basically the maximum.
- Don't average percentiles across hosts or time windows. Merge the histograms instead.

## min vs median

- The **minimum** estimates the intrinsic cost of deterministic CPU-bound code (timeit and
  pytest-benchmark gates use `min`). It hides real variability for I/O-bound or concurrent
  code.
- perfkit uses medians. When you report `min`, say so.
