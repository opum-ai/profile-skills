#!/usr/bin/env bash
# xtrace.sh: per-line wall-clock profile of a bash script, then a hotspot table.
#
#   xtrace.sh [-o trace.log] [--top N] [--no-report] [--allow-fork-clock] script.sh [args...]
#
# Runs the script under a bash that has $EPOCHREALTIME (bash >= 5), with
# PS4='+ ${EPOCHREALTIME} ${BASH_SOURCE}:${LINENO} ' and xtrace sent to its own file descriptor
# so the script's stderr stays clean. An EXIT trap stamps the end so the last line gets its time.
# Then it runs `perfkit hotspots` on the log. The time between two trace lines is charged to
# the earlier line, which includes any external program it ran.
#
# zsh scripts (zsh shebang or .zsh) are traced with zsh and its $EPOCHREALTIME (zsh/datetime).
#
# macOS ships bash 3.2 (no $EPOCHREALTIME). Install bash 5 (`brew install bash`), or pass
# --allow-fork-clock to timestamp with an external `date` / `perl` per line. That fallback forks
# on every traced command, so it inflates cheap lines badly: use it for WHERE, never HOW MUCH.
set -u
out="" top=15 report=1 allow_fork=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    --top) top="$2"; shift 2 ;;
    --no-report) report=0; shift ;;
    --allow-fork-clock) allow_fork=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
[ $# -ge 1 ] || { echo "usage: xtrace.sh [-o trace.log] script.sh [args...]" >&2; exit 2; }
script="$1"; shift
[ -f "$script" ] || { echo "no such script: $script" >&2; exit 2; }
[ -n "$out" ] || out="$(basename "$script").xtrace.log"

# zsh scripts (shebang mentions zsh, or *.zsh): trace with zsh's own microsecond clock, no forks.
first=$(head -n1 "$script" 2>/dev/null)
case "$first$script" in
  *zsh*)
    Z=$(command -v zsh) || { echo "zsh not found" >&2; exit 2; }
    PERF_XTRACE_OUT="$out" "$Z" -c '
      exec 9>"$PERF_XTRACE_OUT"; exec 2>&9
      PS4="+%D{%s.%6.} %x:%I> "
      trap ": perfkit-end" EXIT
      setopt xtrace
      source "$0" "$@"
    ' "$script" "$@"
    status=$?
    echo "trace: $out (zsh: $Z, exit $status; note: script stderr is mixed into the trace)" >&2
    if [ "$report" -eq 1 ]; then
      here="$(cd "$(dirname "$0")" && pwd)"
      python3 "$here/perfkit.py" hotspots "$out" --by self --top "$top" >&2 || true
    fi
    exit $status ;;
esac

pick_bash() {
  for b in "${PERF_BASH:-}" /opt/homebrew/bin/bash /usr/local/bin/bash "$(command -v bash)" /bin/bash; do
    [ -n "$b" ] && [ -x "$b" ] || continue
    v=$("$b" -c 'echo ${BASH_VERSINFO[0]}' 2>/dev/null) || continue
    if [ "${v:-0}" -ge 5 ]; then echo "$b"; return 0; fi
  done
  return 1
}

if B=$(pick_bash); then
  clock='${EPOCHREALTIME}'
else
  B=$(command -v bash)
  if [ "$allow_fork" -ne 1 ]; then
    echo "No bash >= 5 found (this is $("$B" -c 'echo $BASH_VERSION')). Install it: brew install bash" >&2
    echo "or re-run with --allow-fork-clock (forks a clock per line; inflates cheap lines)." >&2
    exit 3
  fi
  if date +%s.%N | grep -q N; then
    clock='$(perl -MTime::HiRes=time -e "printf q(%.6f), time")'
  else
    clock='$(date +%s.%N)'
  fi
  echo "warning: fork-per-line clock in use; per-line costs are inflated" >&2
fi

runner='
  PS4=$PERF_PS4
  trap ": perfkit-end" EXIT
  set -x
  . "$0" "$@"
'
major=$("$B" -c 'echo $((BASH_VERSINFO[0]*10 + BASH_VERSINFO[1]))')
if [ "$major" -ge 41 ]; then   # BASH_XTRACEFD keeps the script's own stderr clean
  PERF_XTRACE_OUT="$out" PERF_PS4="+ $clock \${BASH_SOURCE}:\${LINENO} " \
    "$B" -c 'exec 9>"$PERF_XTRACE_OUT"; BASH_XTRACEFD=9;'"$runner" "$script" "$@"
else                           # bash < 4.1: trace shares stderr with the script
  PERF_PS4="+ $clock \${BASH_SOURCE}:\${LINENO} " "$B" -c "$runner" "$script" "$@" 2>"$out"
fi
status=$?
echo "trace: $out (bash: $B, exit $status)" >&2

if [ "$report" -eq 1 ]; then
  here="$(cd "$(dirname "$0")" && pwd)"
  python3 "$here/perfkit.py" hotspots "$out" --by self --top "$top" >&2 || true
fi
exit $status
