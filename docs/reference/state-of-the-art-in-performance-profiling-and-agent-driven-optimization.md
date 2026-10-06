---
# yaml-language-server: $schema=../../.lore/schemas/reference.schema.json
type: Reference
title: State of the art in performance profiling and agent-driven optimization
tags:
  - research
  - performance
summary: Tools, methodology and research (2024-2026) for profiling, benchmarking and agent-driven optimization of Python, JS/TS, browser and Bash code, and how each finding shapes profile-skills.
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:00:48.124Z
---

# State of the art in performance profiling and agent-driven optimization

Snapshot: 2026-10-05. Scope: Python, JavaScript/TypeScript (Node, Bun, Deno, browser) and Bash, on
macOS (Apple Silicon) development machines and Linux CI. This is the distilled design input for
profile-skills. The raw, fully-cited notes are:
- [Python](research-notes-python-profiling-and-benchmarking.md)
- [JS/TS and browser](research-notes-javascript-typescript-and-browser-performance.md)
- [methodology, statistics, Bash and CI](research-notes-methodology-statistics-bash-and-ci.md)

## 1. What the research on agents says (and why the skills look the way they do)

| Finding | Source | Design consequence |
|---|---|---|
| Agents reach under 0.15–0.23× of expert speedups; > 68% of expert gains sit in functions the agent never edits (~71% wrong-target rate); 15–45% of patches break tests; agents stop after the first small gain ("satisficing") and prefer convenience edits (memoization, early exits, input-specific hacks) | SWE-fficiency (ICML 2026), SWE-Perf (2025), GSO (2025) | **No profile, no change** (perf-optimize): every hypothesis names a frame from a saved profile with its Amdahl ceiling; re-profile after each win; explicit stop rules instead of stopping at the first win; the optimization ladder ranks structural fixes above micro-tuning |
| Profiler-guided, verifier-in-the-loop agents double expert-matching rates (GSO 19.6% → 39.2%; SWE-fficiency-Lite 26% → 74%), beating best-of-5 sampling at lower cost | PerfAgent (Jul 2026) | perf-profile is a first-class skill, and `perfkit hotspots` turns every profiler's output into one table the agent reasons from |
| No method improved efficiency without sacrificing correctness | ECCO (EMNLP 2024) | The guard comes before the baseline: tests + output equivalence (`abtest --require-same-output`) + differential harness at R4; semantics checklist (order, floats, errors, laziness, concurrency) |
| Agents game evaluators (caching benchmark inputs, harness hijacking, specializing to visible workloads); GSO added a Hack Detector | GSO, PERFOPT-Bench (Jul 2026) | Anti-gaming rules: never touch the measuring stick (`git diff --stat`), no caches keyed on benchmark inputs, a **hold-out workload** never profiled or tuned on, policy read from the base ref in CI |
| Many reported speedups don't survive a change of machine (only 39/102 GSO and 11/140 SWE-Perf reference patches stayed valid); under rigorous measurement only 6.11% of "performant" LLM solutions are significantly faster | Chen et al. 2026 audit; Le et al. 2026 | perf-bench: interleaved runs, medians + bootstrap CI on the ratio, Mann-Whitney U, a minimum effect fixed in advance, explicit `inconclusive` verdict with runs-needed estimate |
| LLMs make almost no memory optimizations (experts: 171× peak-memory reduction) | SWE-Pro perf (Jun 2026) | `abtest --all-metrics` records peak RSS on every experiment; secondary metrics must not regress; memory reference in perf-profile |
| Restarting from an externalized optimization summary recovers 1.0–2.5× more speedup in long campaigns | PERFOPT-Bench | Experiment ledger (`experiments.jsonl`) + `NOTES.md` handoff state |
| Sampling candidates and keeping the best that passes works (PIE best-of-8, AlphaEvolve, KernelEvolve); but evaluator quality matters more than search sophistication | PIE (ICLR 2024), AlphaEvolve (2025), KernelEvolve (2026), "Simple baselines are competitive with code evolution" (2026) | Candidate fan-out in worktrees, measured in one multi-arm interleaved A/B, only after guard and baseline are solid |
| Fleet-profile localization + anti-pattern dictionary + multi-stage verification ships thousands of safe optimizations | Google ECO (OSDI 2026) | perf-review's anti-pattern catalogs; production continuous profiles (Pyroscope, Parca, OTel Profiles alpha) as the preferred target source |
| LLM DOM "performance" fixes often introduce layout shift | LLMs for DOM-level web perf (Jan 2026) | CLS is a gated secondary metric for frontend changes |

## 2. Methodology the skills encode

- **The loop**: scope (metric, workload, hold-out, target) → guard → baseline → profile → hypothesis with a
  predicted gain → change one thing → guard → interleaved A/B against the incumbent → keep/revert + ledger →
  re-profile. Written predictions expose a wrong mental model when the measured gain is far off.
- **Amdahl's law** picks targets: a frame at 5% self time can never give more than ×1.05.
- **USE** (utilization, saturation, errors) for resources, **RED** (rate, errors, duration distribution) for services,
  **active benchmarking** (confirm the limiter while the benchmark runs), drill-down from command → function → line.
- **Latency**: percentiles, never means; open-loop load to avoid coordinated omission (k6 constant-arrival-rate,
  wrk2 `-R`, oha `--latency-correction`).
- **Statistics**: median and IQR; ratio of medians with a 95% bootstrap CI; Mann-Whitney U; geometric mean across
  benchmarks; MDE ≈ 2.8 × CV × √(2/n); α tightened or reruns required when many benchmarks are compared.
- **Noise**: interleave A/B (Laaber et al.: same-instance randomized interleaving detects ≤10% slowdowns on cloud VMs);
  repeat at the process level (Kalibera & Jones); keep environment size/cwd identical (Mytkowicz et al.); Apple Silicon
  has no user-space core pinning and P/E cores differ 2–3×; shared CI runners drift 10–20% and even instruction counts
  change with the CPU model (CodSpeed's glibc finding).
- **Benchmarking crimes** (Heiser): selective benchmarking, no significance, arithmetic means of ratios, micro→macro
  extrapolation, calibrating and validating on the same data.

## 3. Tool landscape (October 2026)

| Area | Default | Notes |
|---|---|---|
| Python CPU | pyinstrument (macOS, no sudo), py-spy 0.4 (Linux), `python -m profiling.sampling` (3.15, PEP 799) | py-spy needs sudo on macOS, can't profile `/usr/bin/python3`, no `--native` on macOS; Tachyon needs matching minor version |
| Python exact counts / lines | cProfile (`profiling.tracing`), line_profiler 5, Scalene 2.3 (Python/native split, copy volume) | deterministic overhead distorts shares |
| Python memory | memray 1.20, tracemalloc, pytest-memray | `PYTHONMALLOC=malloc` for leaks; 3.14.0–3.14.4 GC regression |
| Python benchmarks | pyperf 2.10, pytest-benchmark 5.3 (`--benchmark-save-data`), pytest-codspeed 5, asv 0.6 | timeit reports min and disables GC |
| Node CPU | `node --cpu-prof` (stable), inspector `Profiler.*` | file only on normal exit; clinic.js unmaintained, 0x stale, `@platformatic/flame` active |
| Bun / Deno | `--cpu-prof`, `--cpu-prof-md` (LLM-ready Markdown), `--heap-prof-md` | JSC ≠ V8 |
| JS benchmarks | mitata, tinybench 6, Vitest bench (**v5 rewrote the API**), `deno bench` | benchmark.js archived |
| TypeScript | TS 7 (Go) GA 2026-07: `--extendedDiagnostics`, `--singleThreaded`; TS ≤6: `--generateTrace` + analyze-trace | `node --cpu-prof` useless on TS 7 |
| Browser | Playwright/Puppeteer CDP traces with CPU/network emulation; Chrome DevTools MCP (stable, Chrome 149); Lighthouse 13 / LHCI; web-vitals v6 | Playwright `context.tracing` is not a perf trace; Lighthouse 13 renamed audits; DevTools MCP sends URLs to CrUX unless `--no-performance-crux` |
| Bash | bash 5 `$EPOCHREALTIME` xtrace, fork/exec counts (`strace -f`, `eslogger`), hyperfine 1.21 | macOS `/bin/bash` is 3.2; `$(date)` in PS4 swamps measurements; bash 5.3 adds non-forking `${ cmd; }` |
| Native | samply 0.13 (macOS+Linux), perf, xctrace, flame graphs / differential flame graphs, speedscope, Firefox Profiler | |
| CI | same-runner interleaved A/B, CodSpeed simulation (instruction counts; no I/O), Bencher 0.6, github-action-benchmark 1.22, size-limit, LHCI | |
| Production | Pyroscope 2.3, Parca 0.29, OpenTelemetry Profiles (public alpha, Mar 2026) | |

## 4. How it maps to profile-skills

| Skill | Grounded in |
|---|---|
| perf-optimize | §1 agent findings; the loop, Amdahl, ladder; guards and anti-gaming; ledger and handoff; fan-out |
| perf-profile | §3 tool landscape per runtime; profile-in-the-loop evidence; one normalized hotspot table |
| perf-bench | §2 statistics and noise; benchmarking crimes; harness choice; empirical complexity |
| perf-ci | same-runner interleaving, instruction-count proxies, deterministic budgets, policy integrity (mirrors test-skills' gate reading policy from base) |
| perf-review | ECO-style anti-pattern catalogs + frequency arguments + measured confirmation; verifying claimed speedups symmetrically |

Shared with the sibling plugins: test-skills' rigor profiles R1–R5 (evidence strength, not effort) and its
test-economy rules for any test a perf change adds; proof-skills' formal-verify for concurrency changes made for
speed and proof-simplify for proving a lock or guard redundant before deleting it.
