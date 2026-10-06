---
# yaml-language-server: $schema=../../.lore/schemas/adr.schema.json
type: ADR
title: Default profiler and harness per stack
summary: "The profiler and benchmark harness the skills reach for first on each stack: Python, Node, Bun and Bash/CLIs."
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:07:13.550Z
---

# Default profiler and harness per stack

## Status

Accepted (2026-10-05, owner's choice: Option B, with the follow-up decision that the tools collect samples while ADR-0005's rule decides).

## Context

Evidence is in the [tool matrix](../reference/research-notes-tool-comparison-matrix-and-methodology-numbers.md) and
the [research notes](../reference/research-notes-python-profiling-and-benchmarking.md). Key facts:
- **Overhead** (Scalene OSDI'23): py-spy 1.02×, pyinstrument 1.69×, cProfile 1.73×, line_profiler 2.21×,
  memray 3.98×. Tracing profilers can report 80% for a function that really takes 25%.
- **py-spy on macOS:** needs root, can't profile `/usr/bin/python3`, and has no `--native`.
- **Python 3.15** `profiling.sampling` (Tachyon) is at rc3 and needs root to attach on macOS.
- **Node:** `--cpu-prof` is built in; measured overhead here is about +0.8% at 1 ms sampling.
- **Bun 1.3.14:**
  - `--cpu-prof` costs +27% (1 ms) to +74% (0.1 ms) here;
  - Bun issue #44077 says it counts event-loop idle time as JS self time;
  - `--cpu-prof-md` is the most LLM-ready output.
- **Node tool status:** clinic.js is unmaintained, 0x is stale, mitata has no commits in about 20 months, tinybench 6
  is active, and Vitest 5 rewrote bench.
- **Bash:** macOS bash 3.2 lacks `EPOCHREALTIME`. hyperfine is not installed by default (1.21 released 2026-10-05).
- **Decisions under ADR-0005** run through perfkit's interleaved, paired A/B whatever harness collects the samples.

## Options

### Option A (recommended): built-in and zero-sudo first; decisions always through perfkit's process-level A/B

| Stack | Find hotspots | Exact counts / lines | Memory | Decide (A/B) | Micro-benchmark |
|---|---|---|---|---|---|
| Python | **pyinstrument** on macOS (no root); **py-spy** on Linux CI (1.02×); Tachyon on 3.15+ | cProfile for call counts; line_profiler on ≤5 named functions | tracemalloc → memray | perfkit abtest (fresh processes) | pyperf (multi-process); pytest-benchmark only where the repo already uses it |
| Node | `node --cpu-prof` (built in) | `--prof` tick log; deopt traces when shape-bound | `--heap-prof`, heap snapshots + memlab | perfkit abtest | tinybench 6 (maintained, Node+Bun); mitata where installed |
| Bun | `bun --cpu-prof-md` / `--cpu-prof` **for localisation only** (overhead 27–74%, idle-time attribution bug); cross-check on Node when the code runs on both | — | `--heap-prof-md` | perfkit abtest | tinybench / mitata |
| Bash / CLIs | bundled `xtrace.sh` (bash 5 `EPOCHREALTIME`, zsh native; bash 3.2 fallback flagged as inflated) + fork/exec counts | `/usr/bin/time -l` (RSS, instructions) | `/usr/bin/time -l` | perfkit abtest (interleaved, paired, output-checked); hyperfine for exploration if present | — |

- **Trade-offs:**
  - Works on a fresh Mac and in CI with no sudo and no installs beyond `uv run --with` / `npx`.
  - Every decision uses the same statistics and output check.
  - Uses the lowest-overhead profiler available on each platform.
  - pyinstrument's 1.69× overhead skews shares on call-heavy code; mitigate by cross-checking with cProfile counts, or
    with py-spy on Linux.

### Option B: ecosystem best-of-breed, installed on demand

- **Tools:**
  - Python: py-spy everywhere (sudo on macOS), Scalene for line-level CPU, memory and copy volume, pyperf for every
    comparison.
  - Node and Bun: mitata for every comparison, @platformatic/flame for flame graphs.
  - CLIs: hyperfine for every comparison.
- Each tool's own statistics decide: pyperf's t-test, mitata's summary, hyperfine's Welch script.
- **Trade-offs:**
  - Familiar to practitioners, with richer per-tool views.
  - Needs installs and sudo on macOS, and mitata is stale.
  - Comparison rules differ per tool (t-tests on means, no pairing), which conflicts with the ADR-0005 rule unless
    every result is re-analysed in perfkit anyway.

## Decision

Option B: best-of-breed tools, installed on demand.

| Stack | Find hotspots | Line level / memory | Collect benchmark samples | Flame graphs |
|---|---|---|---|---|
| Python | **py-spy** (`record -f speedscope`, `--idle` for wall time) | **Scalene** (CPU/memory/copy volume per line); memray for allocations and leaks | **pyperf** (functions/snippets, multi-process); `pyperf command` / hyperfine for CLIs | py-spy SVG / speedscope |
| Node | `node --cpu-prof` (zero-install; agent-readable via perfkit hotspots) | `--heap-prof`, heap snapshots + memlab | **mitata** (functions) | **@platformatic/flame** |
| Bun | `bun --cpu-prof-md` for localisation (not timings) | `--heap-prof-md` | **mitata** | @platformatic/flame not applicable; speedscope from `.cpuprofile` |
| Bash / CLIs | bundled `xtrace.sh` (per line) + fork/exec counts | `/usr/bin/time -l` / GNU `time -v` | **hyperfine** | — |

**Follow-up decision (owner, 2026-10-05):** the tools *collect*; ADR-0005's rule *decides*.
- Every keep/revert verdict goes through `perfkit compare`, which reads pyperf and hyperfine JSON and mitata samples.
  The tool's own statistics are reported alongside, but never decide.
- hyperfine is driven in interleaved rounds (`perfkit abtest --engine hyperfine`), so A/B stays paired.

## Consequences

- **Installs:** tools are installed on demand. User-level installs come first: `uv tool install py-spy`,
  `uv run --with scalene`, `npm i -D mitata @platformatic/flame`. System-wide installs (`brew install hyperfine`) are
  proposed to the user before they run.
- **py-spy on macOS needs root.** When `sudo -n true` fails, the skill asks the user to run the exact py-spy command
  themselves (`! sudo py-spy record ...`). Otherwise it falls back to Scalene/pyinstrument in-process and says so in
  the report. Scalene's CPU-only mode has 1.02× overhead.
- **Bun profiles are for localisation only.** Bun's 27–74% profiler overhead and its idle-time attribution bug mean
  timing claims come from mitata or perfkit A/B, never from a profile.
- **mitata's maintenance** (no commits in about 20 months) is a watched risk. tinybench 6 is the documented fallback.
- **perfkit gains:** `abtest --engine hyperfine` and a mitata JSON loader.
