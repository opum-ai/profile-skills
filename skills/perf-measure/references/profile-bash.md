# Profiling Bash and shell scripts

A slow shell script is almost always slow because of **process creation**: fork+exec costs
roughly 0.5–2 ms on Linux and more on macOS. The shell's own interpretation is rarely the
problem. The profile you want has per-line wall time plus counts. The metric you can gate
on is the number of forks and execs.

## 1. Know your bash

- macOS `/bin/bash` is **3.2.57**. It has no `$EPOCHREALTIME`, no `BASH_XTRACEFD`, no
  associative arrays, no `mapfile`, and no `${x,,}`. Homebrew bash 5 is at
  `/opt/homebrew/bin/bash`. Linux CI usually has 5.1 or 5.2.
- Bash 5.3 adds non-forking command substitution: `${ cmd; }` and `${| cmd; }`.
- **The script's shebang decides the production shell.** If it says `#!/bin/bash` and must
  run on macOS, the optimized version must still run on 3.2. Don't introduce bash-4+ syntax
  unless the target allows it.

## 2. Whole-script timing

```bash
time ./script.sh args          # real vs user+sys: real ≫ user+sys means waiting (I/O, sleep, network)
/usr/bin/time -l ./script.sh   # macOS: max RSS, context switches, "instructions retired"
/usr/bin/time -v ./script.sh   # Linux GNU time
python3 $PK abtest --a './old.sh in.txt' --b './new.sh in.txt' --runs 15 --require-same-output
```
- If `sys` is comparable to `user`, the time is going to fork/exec and syscalls.

## 3. Per-line profile: the bundled wrapper

```bash
${CLAUDE_SKILL_DIR}/scripts/xtrace.sh -o .perf/<c>/baseline.xtrace.log ./script.sh args   # finds /opt/homebrew/bin/bash 5 if installed
python3 $PK hotspots .perf/<c>/baseline.xtrace.log --by both --top 20
```
What the wrapper does:
- Finds a bash ≥5 (`PERF_BASH=/path/to/bash` overrides).
- Sets `PS4='+ ${EPOCHREALTIME} ${BASH_SOURCE}:${LINENO} '` and sends the trace to its own
  fd, so the script's stderr is untouched.
- Sources the script, so `$0` and `$@` are preserved, and stamps the end with an EXIT trap.

How to read the table:
- **calls** is how many traced commands that line produced. A loop body shows the
  iteration count times the commands per iteration.
- **self** is the wall time charged to the line, including the external programs it ran.
- Lines inside `$(...)` appear one `+` deeper and are nested under their line, so the
  enclosing line's **total** includes them.
- **High calls with modest per-call cost** is a loop body that forks. That is the fix target.

Without bash 5, `--allow-fork-clock` timestamps each line with a forked `perl`/`date`. That
inflates every line by roughly the cost of a fork, so cheap lines look expensive. Use it to
find *where*, then confirm with whole-script timing.

**zsh: the wrapper detects a zsh shebang or a `.zsh` file and traces it with zsh's own fork-free
microsecond clock (`PS4='+%D{%s.%6.} %x:%I> '`). By hand:**
```bash
zmodload zsh/datetime
PS4='+%D{%s.%6.} %N:%i> ' zsh -x script.zsh 2> trace.log
```
For interactive startup, put `zmodload zsh/zprof` at the top of `.zshrc` and `zprof` at the
bottom.

**Don't put `$(date …)` in PS4 for real measurements.** It forks once per traced command and
dominates the profile.

## 4. Count forks and execs (the deterministic metric)

```bash
# Linux
strace -f -c -o .perf/<c>/strace-summary.txt ./script.sh args
strace -f -qq -e trace=execve -o .perf/<c>/execs.txt ./script.sh args; grep -c execve .perf/<c>/execs.txt
strace -f -e trace=execve ./script.sh args 2>&1 | grep -o 'execve("[^"]*"' | sort | uniq -c | sort -rn | head
# macOS (no strace): SIP blocks dtruss on /bin/bash; copy it, or count via eslogger
cp /bin/bash /tmp/bash && sudo dtruss -f -c /tmp/bash ./script.sh args
sudo eslogger exec > .perf/<c>/execs.json & ./script.sh args; kill %1
```
Without root on macOS, approximate from the xtrace log: lines whose command is an external
program (`grep`, `sed`, `awk`, `cut`, `tr`, `date`, `jq`, `basename`, …), multiplied by
their calls. The bundled hotspot table shows the command text for each line.

The exec count is a good **budget** for perf-ci, because it is the same on every run:
"≤ 20 execs on fixture X".

## 5. Patterns you will find (fix catalog: `antipatterns-bash.md`)

| Hot line looks like | Why | Typical fix |
|---|---|---|
| `x=$(echo "$line" \| cut -d, -f2)` in a loop | 2 forks per iteration | `IFS=, read -r a b c <<< "$line"`, or `${line#*,}` |
| `while read …; do grep/sed/awk/jq …; done < big` | N processes | one `awk`/`jq` pass over the whole file |
| `$(date …)` per line | fork | `printf '%(%F %T)T' -1` (bash 4.2+), `$EPOCHSECONDS` |
| `basename`/`dirname`/`expr`/`seq` in loops | fork | `${p##*/}`, `${p%/*}`, `$(( ))`, `for ((…))` |
| `find … -exec cmd {} \;` | exec per file | `-exec cmd {} +`, `xargs -0 -P` |
| `sleep` polling | wall time | event-driven waits, `wait` |
| serial independent work | one core | `xargs -P "$(getconf _NPROCESSORS_ONLN)"` |

## 6. Shell startup

```bash
hyperfine --warmup 3 'zsh -i -c exit' 'zsh -f -i -c exit'    # rc cost = difference
hyperfine --warmup 3 'bash -i -c exit' 'bash --norc -i -c exit'
```
Usual culprits:
- `compinit` without caching;
- `nvm`/`pyenv`/`conda` init (lazy-load them);
- `$(brew --prefix)` subshells;
- `eval "$(tool init zsh)"` on every start (cache the output to a file).

`romkatv/zsh-bench` measures the latency users actually perceive.

## 7. When to rewrite instead

Rewrite the hot part as a single awk/jq/Python program when any of these hold:
- a loop over more than about 1k items calls external tools per item;
- you need real data structures;
- the exec count is in the thousands after the obvious fixes.

Python startup (15–40 ms) matters if the script is itself invoked thousands of times.
