# The lore report and the PR description

The report is a lore Reference (`lore new reference "Perf report: <concern>"`) linked from the
Quest task. Put its summary in the final message. Every number names the `.perf/<concern>/`
file it came from. Because `.perf/` is disposable, the numbers themselves must be in the
report.

```markdown
# <concern>: <one-line result, e.g. "report generation 18.2 s → 1.6 s (×11.4)">

**Rigor:** R3 · **Workload:** … · **Environment:** … (doctor warnings: …)

## Result
| | baseline | final | ratio (95% CI) | verdict |
|---|---|---|---|---|
| wall median (main workload) | 18.21 s (IQR 0.22) | 1.60 s (IQR 0.03) | 0.088 [0.086, 0.090] | improved |
| wall median (hold-out, never tuned on) | 41.0 s | 3.4 s | 0.083 [0.081, 0.085] | improved |
| peak RSS | 212 MB | 190 MB | 0.90 [0.88, 0.91] | improved |
n = 20 per arm, interleaved and paired; source: .perf/<c>/final-ab.json, .perf/<c>/final-holdout-ab.json

## Guard
`pytest -q` 212 passed (baseline 212) · changed-line coverage 96% before and after · stdout identical on every run · equiv.py: 500/500 cases equal

## What changed (kept experiments)
| id | hotspot (share at the time) | change | speedup |
|---|---|---|---|
| E1 | dedupe (report.py:41), 62% self | list membership → dict.fromkeys (order-preserving) | ×2.4 |
| E3 | parse_row, 48% total | csv.reader once instead of split per field + int() per cell | ×2.9 |
| ... |

## Tried and reverted
| id | hypothesis | why reverted |
|---|---|---|
| E2 | precompile regex in normalize() | equivalent (−0.4%, CI includes 0): `re` already caches patterns |

## Where the time goes now
Top 5 frames from .perf/<c>/final-hotspots.json with self% and Amdahl ceilings; what it would take to go further
(e.g. "65% is now json.dumps of the output; orjson would need a new dependency — your call").

## Caveats
Noise level, platform specifics (measured on macOS arm64; CI is Linux x86), anything at a lower rigor than asked.
```

## PR description (short form)

```
perf(<concern>): <result>

Hypothesis → change: <the kept experiments, one line each, with the profile share that motivated them>
Result: <metric> <before median (IQR)> → <after median (IQR)>, ratio <r> [95% CI a–b], n=<n>/arm interleaved;
        hold-out: <ratio [CI]>
Guard: <tests> pass; outputs identical on <inputs>; RSS <before → after>; no benchmark/harness files changed
Env: <CPU, OS, power, runtime versions>
Records: Quest <task id> (N experiment notes, K kept); lore reference/perf-report-<concern>
Rigor: R<n>
```
