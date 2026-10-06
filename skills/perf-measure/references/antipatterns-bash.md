# Bash / shell performance anti-patterns

Process creation dominates. Count forks per iteration × iterations.

| Cue | Forks | Fix (bash 3.2-safe unless noted) | Risk |
|---|---|---|---|
| `x=$(echo "$line" \| cut -d, -f2)` / `awk` / `sed` per line inside `while read` | 2–3 per line | `IFS=, read -r a b c <<< "$line"`; `${line#*,}`, `${line%%,*}`; or one `awk -F,` pass over the file | field edge cases (empty fields, quotes in CSV) |
| `while read …; do grep/jq/sed …; done < file` | N | single `awk`/`jq -c`/`sed` invocation; `grep -F -f patterns` | ordering, error handling |
| `cat file \| grep x` | 1 extra | `grep x file` | none |
| `$(date +…)` per line/iteration | 1 per call | `printf '%(%F %T)T' -1` (bash ≥4.2); `$EPOCHSECONDS` (bash 5); compute once if constant | bash version |
| `basename`/`dirname`/`expr`/`bc`/`seq` in loops | 1 per call | `${p##*/}`, `${p%/*}`, `$(( ))`, `for ((i=0;i<n;i++))` | `basename` suffix stripping semantics |
| `echo "$x" \| tr a-z A-Z` | 2 | `${x^^}` (bash ≥4) or keep `tr` once over the stream | bash version |
| `for f in $(ls *.txt)` / `for l in $(cat file)` | 1 + word splitting bugs | `for f in *.txt` (+ `nullglob`); `while IFS= read -r l` or `mapfile` (bash ≥4) | whitespace handling (fixes bugs) |
| `find … -exec cmd {} \;` | 1 per file | `-exec cmd {} +`; `find -print0 \| xargs -0 cmd` | arg list limits |
| serial loop over independent heavy commands | — | `xargs -0 -P "$(getconf _NPROCESSORS_ONLN)" -n K`; GNU `parallel` | output interleaving, error propagation |
| `cmd \| wc -l` just to test existence | runs to completion | `grep -q` / `[ -n "$(cmd \| head -1)" ]` | — |
| piping into `while` to set variables | subshell + lost vars | `done < <(cmd)` | — |
| `sort \| uniq -c \| sort` on huge inputs with UTF-8 locale | slow collation | `LC_ALL=C sort` **only if byte order is acceptable** | collation/case semantics change |
| `sleep`-based polling loops | wall time | `wait`, event tools (`inotifywait`, `fswatch`) | — |
| sourcing large files or running `$(tool init)` on each invocation | startup | cache output in a file | staleness |

Verify:
- **Output equivalence**: diff the output and exit codes on the fixtures and on edge inputs
  (empty file, spaces in names, missing file).
- **Speed**: `perfkit abtest --require-same-output`.
- **Fork count**: xtrace or `strace -c`.

Check the shebang. A `#!/bin/bash` script that must run on stock macOS has to stay on bash
3.2: no `mapfile`, no `${x^^}`, no associative arrays, no `$EPOCHREALTIME`.
