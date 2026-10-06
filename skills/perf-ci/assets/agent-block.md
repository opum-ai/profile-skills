<!-- profile-skills:perf-rules:begin -->
## Performance rules (perf-policy.toml, enforced by `perfkit gate`)

When a change is meant to make something faster or leaner, or touches a path in a perf tier:
1. **Measure before and after.** Use an interleaved A/B with ≥10 runs per arm
   (`perfkit abtest` / `compare`). Report the ratio with its 95% CI, not a single timing.
   Changes inside the noise floor are "no change".
2. **Profile before optimizing.** Name the hotspot and its share from a saved profile. Don't
   optimize code that the profile doesn't show as hot.
3. **Correctness first.** Tests must stay green and outputs identical. A faster wrong answer
   is a bug.
4. **Never touch the measuring stick to get green.** Don't edit benchmarks, workloads,
   fixtures, timing harnesses or `perf-policy.toml` in the same change as the code they
   judge. No caches keyed on benchmark inputs. No special-casing fixtures.
5. **Check memory and tails.** A speedup that regresses peak memory, p99 or bundle size is
   a trade-off to surface, not a silent win.
6. **Concurrency is a correctness change.** New parallelism, caching, batching or lock
   removal needs a race test or formal verification (proof-skills).
7. **Work at the effective rigor.** That is the highest of the project default, the tiers you
   touch, and any `Rigor:` trailer. At R4/R5, an inconclusive result is a failed gate, not a
   footnote.
<!-- profile-skills:perf-rules:end -->
