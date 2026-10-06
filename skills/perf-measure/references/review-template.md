# Performance review template

```markdown
# Performance review: <PR / branch / commit range>

**Verdict:** block | changes requested | approve with notes | approve
**Rigor:** R3 (tiers touched: …) · **Measured on:** <machine, power, runtime versions>

## Findings
### [blocker] <one-line title> — `path/file.py:123`
- **Pattern:** quadratic membership test (`if x not in seen_list`) inside the per-row loop
- **Frequency:** runs once per input row; production inputs are ~200k rows (nightly export)
- **Evidence (measured):** base vs head on 20k generated rows, 15 runs/arm interleaved:
  ratio 6.8 [6.5, 7.1], outputs identical; scaling tail exponent 1.02 → 1.97
  (.perf/review-123/ab.json, scaling-*.json)
- **Fix:** `seen = set()`; preserves order because output is built from the iteration, not the set
- **Expected effect:** back to base (linear); ~7× at 20k, ~70× at 200k

### [major] <title> — `...` (suspected, not measured: requires production DB)
- **Pattern / Frequency / Reasoning / Fix**

### [minor] ...

## Claims in the PR description
| Claim | Measured | Verdict |
|---|---|---|
| "parse is 3× faster" | ratio 0.71 [0.69, 0.73] → 1.4× | partially supported |

## Checked and fine
- `load_config()` change: startup path, once per process; no effect measured (equivalent, ±2%)
- New `lru_cache(maxsize=1024)` on `tz_lookup`: bounded, pure, keys repeat in production (timezones)

## Measuring-stick check
No changes to benchmarks / fixtures / perf-policy.toml. ✓
```

Keep it short. Group notes on cold paths into one line, or omit them. When nothing
significant is found, say so. Give the evidence you gathered and the remaining risks you
could not measure.
