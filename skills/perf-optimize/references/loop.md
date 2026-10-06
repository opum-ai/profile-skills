# The loop in practice

## Contents
1. Incumbent vs candidate with git worktrees
2. Measuring library functions (not commands)
3. The ledger
4. Stop rules
5. Candidate fan-out
6. Long campaigns and handoff

## 1. Incumbent vs candidate with git worktrees

Measure the candidate against the last *kept* state, with both checkouts on disk, so the two
arms run interleaved in one process tree under identical conditions:

```bash
git stash -u || true                      # or commit your WIP on a scratch branch first
git worktree add -f .perf/wt-incumbent HEAD   # incumbent = last kept commit
git stash pop || true                     # candidate = working tree
python3 $PK abtest --names incumbent,candidate \
  --a "python -m app.report data/big.csv" --cwd-a .perf/wt-incumbent \
  --b "python -m app.report data/big.csv" --cwd-b . \
  --runs 20 --warmup 2 --require-same-output -o .perf/<c>/E4-ab.json
```

- Commit each kept experiment (`perf(<concern>): E4 <change>`), then move the incumbent with
  `git -C .perf/wt-incumbent checkout --detach <sha>`. Reverted experiments leave no commit, only
  a ledger line.
- If the project must be built (TS, bundlers), build both trees *before* measuring, and
  measure the built artifact. The build must not be inside the timed command unless build time
  is the metric.
- Inputs and outputs: both arms must read the same input and write nowhere shared. Send
  output to stdout, or to per-arm temp paths with `--prepare` cleaning them.
- Remove worktrees at the end: `git worktree remove .perf/wt-incumbent`. `.perf/` must be git-ignored. Git refuses to add a worktree inside a tracked path.
- No git? Copy the incumbent tree to `../incumbent/`. The method is the same.

## 2. Measuring library functions (not commands)

When the hot code is a function, wrap it in a tiny driver per arm so `abtest` can still
interleave processes:

```python
# .perf/<c>/bench_driver.py — run from each worktree: python .perf/<c>/bench_driver.py
import sys, time, json, pathlib
sys.path.insert(0, ".")
from app.report import build_report            # resolves to the arm's checkout
data = pathlib.Path("data/big.csv").read_text()
build_report(data)                              # warm up imports and caches like production would
t = time.perf_counter(); out = build_report(data); dt = time.perf_counter() - t
print(json.dumps({"digest": hash(repr(out)) & 0xffffffff}))  # stable stdout lets abtest check equivalence
print(dt, file=sys.stderr)
```

Process-level repetition is the right default, because variance between processes is often
larger than variance between iterations (Kalibera & Jones). Use in-process harnesses
(pyperf, mitata, pytest-benchmark) when per-call time is under ~10 ms. Then compare their JSON
outputs with `python3 $PK compare base.json cand.json` (see perf-measure bench mode).

`hash()` of a str is salted per process. Use `hashlib.sha256(repr(out).encode())` or
`PYTHONHASHSEED=0` if you print digests.

## 3. The ledger

`.perf/<concern>/experiments.jsonl`, one JSON object per attempt, appended by
`perfkit ledger add`. It records:
- id, hotspot, hypothesis, change;
- verdict, speedup, ratio CI, p-value, n;
- the guard result, the decision, the commit, and notes.

`perfkit ledger show .perf/<c>` prints the table and the cumulative speedup of the kept
experiments. It also lints suspicious records: "kept" without an `improved` verdict, or
without a guard.

Decisions:

| decision | when |
|---|---|
| `baseline` | the first row: the reference measurement |
| `kept` | guard green, verdict `improved`, no gated secondary metric regressed |
| `kept-simplification` | verdict `equivalent` (or `below-threshold`) and the code is simpler. Name the simplification |
| `reverted` | guard red, or the verdict is not `improved` |
| `abandoned` | started, but not measurable or not finished. Say why |

Write the predicted gain into `--hypothesis` ("expect ~2×"). When the measured result
disagrees with the prediction, the notes column is where you explain why. Never edit past rows.

## 4. Stop rules

Stop when any of these holds, and say which one in the report:
1. **Target met.** For a budget, confirm it on the hold-out workload too.
2. **Ceiling below noise.** Every remaining project frame has an Amdahl `max×` below
   1 + MDE. The MDE is roughly `2.8 × noise × sqrt(2/n)`; with 3% noise and 20 runs it is
   about 2.7%.
3. **Diminishing returns.** Three consecutive experiments were not kept.
4. **Budget spent** (experiments or time).
5. **Needs a decision.** API or behavior change, new dependency, native extension, infra
   change (more cores, a cache server), or a trade-off on a gated metric. Present the
   options with the evidence.

Before stopping on rule 2, check that the profile is the right kind:
- A CPU profile of an I/O-bound program shows nothing hot. Use wall-clock mode
  (py-spy `--idle`, pyinstrument, or Node's event-loop delay).
- An in-process profile misses subprocess cost (Bash, `subprocess.run`). Count
  forks/execs instead.

## 5. Candidate fan-out

Use fan-out when one hotspot dominates and the first idea did not pay. AlphaEvolve,
KernelEvolve and PIE's best-of-k show the value of sampling several candidates and
**keeping the best that passes**. "Simple baselines are competitive with code evolution"
shows the evaluator matters more than the search.

1. Write 2–4 *different* approaches in the ledger as hypotheses, e.g. "index by key with a
   dict", "sort and merge", "push it into one SQL query", "vectorize with numpy".
2. Put each in its own worktree (`git worktree add ../wt-cand-a HEAD`). With subagents,
   give each one the SCOPE, the guard command, and its single approach. Don't let them
   edit the harness.
3. Run each candidate through the guard. Then run one multi-arm interleaved `abtest`:
   `--a incumbent --b cand-a --extra "<cand-b cmd>" ...`, so every candidate is measured
   under the same conditions.
4. Keep the best `improved` candidate. Log every candidate, the losers as `reverted`, with
   their numbers. A loser's idea sometimes combines with the winner in the next pass. That
   combination is a new experiment, measured against the new incumbent.

## 6. Long campaigns and handoff

PERFOPT-Bench found that agents that restart from an externalized optimization summary
recover 1.0–2.5× more speedup than agents that push on in a degraded context. For campaigns
longer than a few experiments, keep the Quest task notes and `.perf/<concern>/NOTES.md` current with:
- the incumbent commit;
- the current hotspot table, top 5;
- what was tried and why it failed;
- the next 3 hypotheses with their ceilings.

A fresh session, or a handoff skill, can resume from it and the ledger.
