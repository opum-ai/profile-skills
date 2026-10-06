---
# yaml-language-server: $schema=../../.lore/schemas/reference.schema.json
type: Reference
title: "Perf report: perfkit hotspots on large Chrome traces"
tags:
  - perf
  - engine
summary: perfkit hotspots on a 134 MB browser trace went from 1.23 s to 0.53 s (x2.34) and 785 to 162 MB peak RSS, with identical output; x1.43 on a 527 MB hold-out.
generated:
  by: lore/0.12.0
  at: 2026-10-05T20:32:28.042Z
---

# Perf report: perfkit hotspots on large Chrome traces

**Result:** `perfkit hotspots` on a 134 MB Playwright trace takes 0.53 s instead of 1.23 s (×2.34), and peak RSS falls
from 785 MB to 162 MB. Output is identical. On the 527 MB hold-out trace it is ×1.43 faster and RSS falls from
3.08 GB to 1.0 GB.

**Rigor:** R3 (no `test-policy.toml` in this repository) · **Quest:** PSKI-15 · **Skill:** perf-optimize, the real
example for PSKI-12 · **Environment:** Apple M4, macOS 27.0, Python 3.9.6 (system), load average 3–4, AC power.

## Scope

| | |
|---|---|
| Primary metric | wall median of `perfkit hotspots <trace> --top 15` (stdout hashed) |
| Secondary | peak RSS; stdout identical; the full hotspot JSON identical (equivalence harness) |
| Workload | `main.trace.json`: 134 MB, 358k lines, sha256 `03271c82…` (Playwright trace of the web-dashboard fixture at 700 rows) |
| Hold-out (not tuned on) | `holdout.trace.json`: 527 MB, 1.69M lines, sha256 `fb6fe80a…` (the same page at 3,000 rows) |
| Budget | 4 experiments. Raised once to 5, with the reason recorded in Quest before E5 was measured |

## Behaviour pinned before any change

- `load()` for Chrome traces was only 77% covered (`profiles.py`); the file-reading branch had no test. A pinning test
  now runs `load()` on all three layouts Chrome/Playwright/Puppeteer write (one event per line, single-line JSON,
  bare array) and requires the same table as the in-memory loader.
- The equivalence harness (`.perf/hotspots-trace/equiv.sh`) diffs stdout and the full hotspot JSON between incumbent
  and candidate on both traces after every change.
- **Harness fix before measuring (not a perf experiment):** the harness showed two runs of *identical* code printing
  tied frames in different orders, because ties followed `set()` order, which changes with `PYTHONHASHSEED`. Fixed with
  a deterministic tie-break, plus a regression test.

## Baseline

A/A (incumbent against itself, 10 interleaved runs): median 1.181 s, IQR 10 ms (0.9%), ratio CI [0.999, 1.157] →
inconclusive, as it should be. RSS 785 MB.

The profile (cProfile, shares inflated for call-heavy code): `json` `raw_decode` held **74.7% of self time**, an
Amdahl ceiling of ×3.95.

## Experiments (kept and rejected)

| id | hotspot | hypothesis | change | verdict | change (ratio CI) | decision |
|---|---|---|---|---|---|---|
| E0 |  | A/A baseline: incumbent vs itself | none | inconclusive | +0.8% (0.999–1.157) | baseline |
| E1 | json raw_decode 74.7% self (max x3.95) | decode only trace lines load_chrome_trace uses (ProfileChunk, thread_name, X events); expect ~2.5x and <50% RSS | profiles.load: streaming one-event-per-line pass with full-parse fallback | improved | -33.1% (0.664–0.673) | kept |
| E2 | line-filter genexpr+any ~33% (cProfile, inflated) | one compiled bytes-regex search per line instead of 4 Python substring tests; expect ~1.2x | _TRACE_KEEP as compiled regex | improved | -20.2% (0.790–0.805) | kept |
| E3 | json.loads wrappers (decode+loads+detect_encoding ~13%) | module-level JSONDecoder.raw_decode on decoded text skips loads() per-call overhead; expect ~1.08x | _JSON.raw_decode(line.decode()) | improved | -12.2% (0.859–0.891) | kept |
| E4 | file iteration (line reads across a 134 MB file) | 1 MiB read buffer cuts read syscalls; expect ~3% | open(path, 'rb', buffering=1<<20) | improved | -5.7% (0.937–0.961) | kept |
| E5 | regex search per line 20.3% self | check the commonest kept marker with a bytes 'in' before the regex; expect ~1-2% (likely below threshold) | b'"ph":"X"' in line or _TRACE_KEEP.search(line) | regressed | +9.3% (1.076–1.097) | reverted |

Kept: E1, E2, E3, E4 — cumulative speedup ×2.26 over 6 experiments (1 reverted).


Each row is also a note on PSKI-15. All rows were measured incumbent-vs-candidate, interleaved and paired (n = 10–15
per arm), with ADR-0005's rule.

## Final confirmation (original vs final, interleaved, paired)

| Workload | original | final | ratio (95% CI) | verdict | peak RSS |
|---|---|---|---|---|---|
| main (134 MB) | 1.226 s | 0.528 s | 0.428 [0.427, 0.434] | improved, ×2.34 | 785 → 162 MB |
| hold-out (527 MB) | 5.52 s | 3.94 s | 0.700 [0.677, 0.759] | improved, ×1.43 (n = 8, noisy) | 3084 → 1007 MB |

**Why the hold-out gains less:** the gain depends on how much of the trace the loader needs. The main trace keeps 23%
of its lines (15% of its bytes); the hold-out keeps 34% of its lines (27% of its bytes), because the 3,000-row page
emits thousands of `Layout` events. That is a property of the workload, not overfitting: nothing in the change refers
to the main trace.

## Where the time goes now

After E4: the regex scan per line (about 20%), JSON decoding of kept lines (about 18%), the streaming loop itself
(about 19%), then `load_chrome_trace` aggregation. Further gains would need a different scan, for example `mmap`
plus `re.finditer` over the whole buffer to find event starts. That is a larger rewrite. E5 showed that adding a
Python-level test per line costs more than it saves.

## Stop rule

The experiment budget was reached (rule 3), after 5 experiments with E5 rejected.

## Caveats

- Measured on macOS arm64 with system Python 3.9; absolute times differ on Linux CI.
- The hold-out confirmation used n = 8, with 10% noise on the candidate arm.
- The streaming path assumes one event per line. Any decode failure falls back to the full parse, which is pinned by
  the layout test.
- Raw artefacts were in `.perf/hotspots-trace/` (git-ignored, disposable). Every number cited is in this report.
