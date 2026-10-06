# Benchmarking crimes: checklist

Adapted from Gernot Heiser's "Systems Benchmarking Crimes", and from the ways agent
optimizations fail in GSO, SWE-fficiency and PERFOPT-Bench. Go through it before you report
a number.

## Selective benchmarking
- [ ] Measured the workload the user cares about, not a convenient toy.
- [ ] Checked for degradations elsewhere: secondary metrics (memory, p99, startup, bundle
      size) and other workloads, especially the hold-out.
- [ ] Did not drop benchmarks or inputs that looked bad.

## Improper handling of results
- [ ] Repeated runs, with spread (IQR) and an uncertainty (CI) reported. No single runs.
- [ ] Medians or geometric means. No arithmetic mean of ratios.
- [ ] Relative changes stated with their base: "−40% time" is a 1.67× speedup, not 1.4×.
- [ ] A microbenchmark win confirmed on the real workload before claiming an application
      speedup.
- [ ] "No significant change" reported as such, not rounded into a win.

## Wrong benchmarks
- [ ] The benchmark does the real work: its result is consumed or asserted, there is no DCE,
      and inputs are not constant-folded.
- [ ] The inputs differ from the ones used to develop or tune the change (hold-out),
      especially when caches are involved.
- [ ] Not measuring the harness: process spawn, shell, TTY output, setup inside the timing.
- [ ] Warm/cold state matches the claim.

## Improper comparison
- [ ] Both arms on the same machine, at the same time (interleaved), with the same input
      bytes, environment and flags.
- [ ] A real baseline: the incumbent, or the original. Not a strawman.
- [ ] Both arms produce the same output (`--require-same-output`, a diff, or an assert).
- [ ] No changes to the benchmark, harness, workload or guard between the baseline and the
      candidate (`git diff --stat`).

## Missing information
- [ ] Platform: CPU model, OS, power state, runtime and tool versions.
- [ ] n per arm, warmup, interleaving, the exact commands.
- [ ] Absolute numbers as well as ratios.
- [ ] Environment caveats from `perfkit doctor`.
