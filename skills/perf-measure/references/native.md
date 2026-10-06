# Native profilers and flame graphs

Use these when the time is in native code (C extensions, Rust or N-API addons, GC, the
kernel) or in a binary with no language profiler (TS 7's `tsc`, esbuild, ripgrep, compiled
CLIs).

## samply (macOS + Linux; opens in the Firefox Profiler)

```bash
brew install samply          # or cargo install --locked samply
samply record --save-only -o .perf/<c>/prof.json.gz -- ./prog args    # no browser; for later
samply record --rate 4000 -- ./prog args
samply load .perf/<c>/prof.json.gz                                     # view (symbolicates at load time)
```
- On macOS it records on-CPU *and* off-CPU samples, and works without disabling SIP. It
  can't attach to system binaries.
- On Linux it needs `perf_event_paranoid ≤ 1`.
- The saved file is symbolicated only when loaded in the viewer. For headless text, on Linux
  prefer `perf script | inferno-collapse-perf` → `perfkit hotspots`.

## Linux perf

```bash
perf stat -r 10 -e task-clock,instructions:u,cycles,context-switches,page-faults ./prog   # counters; instructions:u is low-noise
perf record -F 999 -g -- ./prog args            # needs frame pointers; else --call-graph dwarf
perf report --stdio --no-children | head -60
perf script | stackcollapse-perf.pl > .perf/<c>/p.folded     # or inferno-collapse-perf
python3 $PK hotspots .perf/<c>/p.folded
```
- JIT runtimes need perf maps: `node --perf-basic-prof`, or `python -X perf` (3.12+).
- Containers often block `perf_event_open`.
- GitHub-hosted Ubuntu runners allow `sudo sysctl kernel.perf_event_paranoid=1`.

## macOS Instruments / xctrace / sample

```bash
xcrun xctrace record --template 'Time Profiler' --time-limit 30s --output .perf/<c>/run.trace --launch -- ./prog args
xcrun xctrace export --input .perf/<c>/run.trace --toc        # then --xpath for the time-profile table (large XML)
sample <pid|name> 5 1 -file .perf/<c>/sample.txt              # quick text call tree of a running process, no Xcode needed
```
`xctrace` needs a full Xcode install; Command Line Tools are not enough. `sample` works
everywhere.

## Flame graphs

- **Folded stacks** (`a;b;c 42`) are the interchange format. Write them from any profile with
  `perfkit hotspots <profile> --collapsed .perf/<c>/p.folded`.
- `flamegraph.pl .perf/<c>/p.folded > flame.svg` (Brendan Gregg's FlameGraph). Or
  `inferno-flamegraph`, or `npx speedscope .perf/<c>/p.folded`.
- **Differential:**
  `difffolded.pl -n before.folded after.folded | flamegraph.pl > diff.svg`. Red means a frame
  grew; blue means it shrank. `-n` normalizes the total sample counts. Attach one to perf
  PRs.
- **Text diff for an agent:** `perfkit hotspots before.prof --diff after.prof` (absolute), or
  add `--relative` (shares).
- **Viewers:**
  - speedscope: its "Sandwich" view lists callers and callees of one function.
  - Firefox Profiler: the call tree, and a compare view.
  - Perfetto: timelines.

## Hardware counters (explain *why* a hot loop is slow)

`perf stat -e cycles,instructions,cache-misses,branch-misses`:
- **Low IPC** (under about 1) with many cache misses means a memory-bound loop. Fix the
  data layout: arrays of structs → structs of arrays, numpy/TypedArrays instead of object
  lists.
- **Many branch misses** means data-dependent branching. Sort the data first, or make the
  code branchless.

On macOS, use the Instruments "CPU Counters" template, or run in a Linux VM. Never compare
absolute numbers across environments.
