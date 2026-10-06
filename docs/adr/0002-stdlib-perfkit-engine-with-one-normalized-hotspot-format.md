---
# yaml-language-server: $schema=../../.lore/schemas/adr.schema.json
type: ADR
title: Stdlib perfkit engine with one normalized hotspot format
summary: One stdlib-only Python engine (perfkit) for statistics, A/B runs, profile normalization, ledger and gate, vendorable into any repo.
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:14.017Z
---
# Stdlib perfkit engine with one normalized hotspot format

## Status

Proposed (awaiting the owner's decision; drafted before the release-quality review)

## Context

Every profiler emits a different format (pstats, V8 .cpuprofile, Chrome traces, speedscope, folded stacks, xtrace logs),
and agents reason far better from a compact table than from flame graphs. Benchmark comparisons need robust statistics
that most harnesses don't provide (hyperfine reports mean ± σ; pytest-benchmark compares to one saved run without a
significance test). test-skills' `tmx` showed that a stdlib engine is easy to vendor into CI.

## Decision

`skills/perf-bench/scripts/perfkit.py` (Python 3.9+, no dependencies) provides `doctor`, `abtest` (interleaved,
output-checked), `compare` (median ratio + bootstrap CI + Mann-Whitney + verdict at a minimum effect), `hotspots`
(every format above → self/total/Amdahl table, folding of library frames, diffs), `scaling` (log-log exponent),
`ledger`, `suite` and `gate`. Helpers that need other runtimes live in perf-profile's scripts (`browser_trace.mjs`
for Playwright traces, `xtrace.sh` for bash/zsh).

## Consequences

- One mental model across languages: every profile becomes the same table; every comparison has the same verdicts.
- The engine is tested in `tests/` (Python 3.9 and 3.12) and vendored by `perf-ci/scripts/vendor_perfkit.sh`.
- We do not re-implement full profilers or harnesses; perfkit reads their output.
