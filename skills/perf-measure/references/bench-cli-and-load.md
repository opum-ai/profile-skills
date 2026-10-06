# CLIs, scripts, git revisions, and HTTP load

## Whole commands

```bash
# interleaved, output-checked (preferred for decisions)
python3 $PK abtest --names old,new --a "./old.sh data.csv" --b "./new.sh data.csv" --runs 20 --require-same-output -o ab.json
# hyperfine bursts, interleaved and paired by perfkit (ADR-0006 default for CLIs)
python3 $PK abtest --engine hyperfine --hf-runs 3 --names old,new --a "./old.sh data.csv" --b "./new.sh data.csv" --runs 12 -o ab.json
# plain hyperfine (sequential A-then-B: exploration, parameter scans, very fast commands with -N)
hyperfine --warmup 3 --runs 20 --export-json h.json -n old './old.sh data.csv' -n new './new.sh data.csv'
hyperfine -N --warmup 10 'mytool --version'                # no intermediate shell for <10 ms commands
hyperfine -P n 1000 64000 -D 21000 'python gen.py {n} | ./process.sh'   # scan
hyperfine --prepare 'sync; sudo purge' 'cmd'               # cold file cache (macOS); Linux: drop_caches
python3 $PK compare h.json                                  # bootstrap-CI verdict on hyperfine's per-run times
```
- hyperfine reports mean ± σ and runs commands sequentially (all of A, then all of B).
  Export JSON so the per-run `times` can be compared with medians and a CI.
- Use `--output=pipe` or `null`. Printing to a TTY distorts the timing.
- For commands under about 5 ms, process spawn and shell startup dominate. Use `-N`, or
  move to an in-process harness.

## Two git revisions

Build both trees first, then measure. Never `git checkout` inside the timed loop.
```bash
git worktree add ../wt-base origin/main
(cd ../wt-base && npm ci && npm run build)      # or uv sync, etc.
npm run build
python3 $PK abtest --names main,pr --a "node dist/cli.js run fixtures/big" --cwd-a ../wt-base \
                                     --b "node dist/cli.js run fixtures/big" --runs 20 -o ab.json
git worktree remove ../wt-base
```

## Inputs and caches

- **Same bytes for both arms.** Record a checksum of the input.
- **Caches** (disk cache, `.pyc`, `NODE_COMPILE_CACHE`, a build cache): decide whether the
  claim is warm or cold, then make both arms equal. Use `--warmup` for warm, and
  `--prepare 'rm -rf .cache'` for cold.
- **Outputs.** Send them to stdout, or to per-arm temp paths. Shared output files cause
  interference.

## HTTP services

```bash
k6 run load.js            # scenarios + thresholds; constant-arrival-rate for latency SLOs
oha -z 30s -c 50 --latency-correction http://localhost:8000/x   # native client; corrects coordinated omission
npx autocannon -c 50 -d 30 http://localhost:8000/x
```
```js
// load.js: open-loop (fixed arrival rate) avoids coordinated omission
import http from 'k6/http';
export const options = { scenarios: { steady: { executor: 'constant-arrival-rate', rate: 200, timeUnit: '1s',
  duration: '60s', preAllocatedVUs: 100 } }, thresholds: { http_req_duration: ['p(99)<300'] } };
export default () => http.get('http://localhost:8000/x');
```
- **Coordinated omission.** Closed-loop clients stop sending while the server stalls, so
  the tail goes missing. For p99 claims use fixed-rate load.
- **Run the server and the generator on separate cores or machines,** confirm the
  generator isn't saturated, and warm up first. Report p50/p95/p99/max and the achieved
  rate.
- **To A/B two server builds,** run each on its own port, and alternate the load runs:
  A, B, A, B, at least 3 each. Then compare per-run p50 or p99 with `perfkit compare` on a
  text file of values per arm.

## Startup

- Python: `perfkit abtest --a "python -c 'import pkg'" ...`, plus `python -X importtime`.
- Node: `hyperfine -N 'node dist/cli.js --version'`, plus `NODE_COMPILE_CACHE`.
- Shell: `hyperfine 'zsh -i -c exit'`.

Startup is mostly fixed cost per process. Compare medians over ≥20 runs.
