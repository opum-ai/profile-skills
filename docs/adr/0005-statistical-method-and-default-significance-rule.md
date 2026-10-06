---
# yaml-language-server: $schema=../../.lore/schemas/adr.schema.json
type: ADR
title: Statistical method and default significance rule
summary: "How profile-skills decides that a change is faster, slower or no different: the primary metric, the statistics and the default significance rule."
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:07:13.430Z
---

# Statistical method and default significance rule

## Status

Accepted (2026-10-05, owner's choice: Option A).

## Context

- Wall-clock timings are right-skewed and drift: thermal, background load, Apple Silicon P/E cores, shared CI runners
  (10–20% between jobs). Sources: Laaber et al. EMSE 2019; Kalibera & Jones ISMM 2013; Mytkowicz et al. ASPLOS 2009;
  see [research notes](../reference/research-notes-methodology-statistics-bash-and-ci.md) §2.
- Agents mistake noise for wins: many published agent "speedups" do not survive a change of machine (Chen et al. 2026
  audit), and only 6.11% of LLM "performant" solutions were significantly faster under rigorous measurement
  (Le et al. 2026).
- **Measured on this machine (M4, macOS 27, load average ~10 from other fleet work, 12 runs each):**

  | Workload | instructions retired CV | cycles CV | wall CV |
  |---|---|---|---|
  | Python quadratic dedupe | 0.05% | 2.5% | 13.3% |
  | Node quadratic dedupe | 0.28% | 2.3% | 7.4% |
  | bash fork loop (parent only) | 1.06% | 3.6% | 5.3% |

  macOS exposes these counters without root via `/usr/bin/time -l`; Linux via `perf stat -e instructions:u`.
  Instruction counts ignore I/O, waiting, parallelism and memory latency (Tratt 2022: a threaded change can add
  instructions and still cut wall time), and for shell scripts they cover only the parent process.

## Options

### Option A (recommended): wall-clock primary with robust statistics; instruction counts corroborate

- **Primary metric:** wall time (or the user's metric: latency percentile, RSS, …), interleaved A/B in fresh
  processes, ≥10 runs per arm at R3.
- **Statistics:** median ± IQR per arm; 95% percentile-bootstrap CI on median(B)/median(A); Mann-Whitney U.
- **Default significance rule — keep a change only if all hold:** the CI excludes 1.0; the point estimate is past the
  minimum effect (default 3% locally, 10% on shared CI runners, or the measured MDE ≈ 2.8·CV·√(2/n) if larger);
  p < 0.05 (0.01 at R4+). Otherwise the verdict is `equivalent`, `below-threshold` or `inconclusive` (with a runs-needed
  estimate), and the change is reverted unless it is a recorded simplification.
- **Instruction counts** are recorded alongside for CPU-bound work. They break ties when wall time is inconclusive under
  noise, and a large counter change with no wall change is flagged for investigation. They never establish a
  user-facing win alone.
- **Trade-offs:** honest about what users feel; works for I/O, async and parallel code. Costs more runs on noisy
  machines, and small (&lt;3%) effects are often undecidable on a laptop.

### Option B: instruction counts primary for CPU-bound code; wall-clock only for I/O-bound work and final confirmation

- **Primary metric:** instructions retired (CV ≤ 1% measured here), 5 runs per arm, threshold 1%.
- Wall-clock is used for I/O-bound, concurrent or browser work, and once at the end to confirm the cumulative result.
- **Trade-offs:** fast and nearly deterministic, so small wins are detectable even on a busy shared machine. But it can
  reward changes that cut instructions while adding memory stalls or losing parallelism, or punish ones that add
  instructions while reducing wall time. Counters are unavailable in many containers, so behaviour differs across
  platforms. It also differs from what the user experiences.

## Decision

Option A. Wall-clock (or the user's own metric) is primary, measured interleaved in fresh processes with robust
statistics. A change is kept only if the 95% bootstrap CI on the median ratio excludes 1.0, the point estimate is past
the minimum effect (3% locally, 10% on shared CI runners, or the measured MDE if larger), and Mann-Whitney p < 0.05
(0.01 at R4+). Instruction counts are recorded alongside CPU-bound measurements as corroborating evidence only.

## Consequences

- perfkit `compare` keeps its current verdict rule. `abtest` gains an instruction-count column where the platform
  exposes one (macOS `/usr/bin/time -l`, Linux `perf stat`). `compare` reports it, but never upgrades a verdict from it.
- Skills default to ≥10 interleaved runs per arm at R3 (20 at R4, 30 at R5), and say "inconclusive" instead of
  rounding noise into a win.
- Interleaved runs are analysed **paired by block**: the ratio of each block's head and base runs, a bootstrap CI on
  their median, and a Wilcoxon signed-rank test. This cancels drift both arms share. A no-skill eval run designed the
  same idea independently and kept same-code ratios within ±1% under heavy load. Unpaired Mann-Whitney remains for
  samples that weren't interleaved (`--unpaired`).
- On busy machines, small effects stay undecidable. The skills report the MDE and the runs needed rather than guess.
