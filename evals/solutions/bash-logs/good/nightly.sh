#!/bin/bash
# nightly.sh <access.log> : per-day, per-endpoint traffic summary for the ops dashboard.
# Log format (one request per line):
#   <client_ip> - <user> [<dd/Mon/yyyy:HH:MM:SS +0000>] "<METHOD> <path> HTTP/1.1" <status> <bytes> <ms>
# Output (sorted): day,endpoint,requests,errors,bytes,p_slow   (p_slow = % of requests over 500 ms)
# Endpoint = path with query string removed and numeric ids replaced by :id.
# Lines that don't parse are counted and reported on stderr; the exit code is 0 unless the file is missing.
#
# One awk pass replaces the per-line pipelines (2-3 processes per field per line). The field
# rules mirror the previous cut/awk/bc implementation exactly, including its quirks:
#   - cut prints a line unchanged when it lacks the delimiter;
#   - p_slow is bc `scale=1` output: truncated (not rounded), "0" for zero, no leading zero below 1.
set -u
log="${1:?usage: nightly.sh <access.log>}"
[ -f "$log" ] || { echo "no such file: $log" >&2; exit 1; }

badfile=$(mktemp)
awk -v badfile="$badfile" '
function cutf(s, d, n,    parts, k) {          # cut -d"d" -fn semantics
  if (index(s, d) == 0) return s
  k = split(s, parts, d)
  return (n <= k) ? parts[n] : ""
}
function word(s, n,    w, k) { k = split(s, w, /[ \t]+/); if (w[1] == "") { return (n + 1 <= k) ? w[n + 1] : "" } return (n <= k) ? w[n] : "" }
function bcpct(slow, n,    t, ip) {               # bc: scale=1; 100 * slow / n
  t = int((1000 * slow) / n)
  if (t == 0) return "0"
  ip = int(t / 10)
  return (ip == 0 ? "" : ip) "." (t % 10)
}
{
  line = $0
  ip = word(line, 1)
  if (ip == "") { bad++; next }
  stamp = cutf(cutf(line, "[", 2), "]", 1)
  day = cutf(stamp, ":", 1)
  req = cutf(line, "\"", 2)
  path = word(req, 2)
  if (path == "") { bad++; next }
  endpoint = path
  sub(/\?.*/, "", endpoint)
  gsub(/\/[0-9][0-9]*/, "/:id", endpoint)
  rest = cutf(line, "\"", 3)
  status = word(rest, 1); bytes = word(rest, 2); ms = word(rest, 3)
  if ((status bytes ms) == "" || (status bytes ms) ~ /[^0-9]/) { bad++; next }
  key = day "," endpoint
  n[key]++
  if (status + 0 >= 500) err[key]++
  sum[key] += bytes
  if (ms + 0 > 500) slow[key]++
}
END {
  for (k in n) printf "%s,%d,%d,%d,%s\n", k, n[k], err[k] + 0, sum[k], bcpct(slow[k] + 0, n[k])
  print bad + 0 > badfile
}' "$log" | sort

bad=$(cat "$badfile"); rm -f "$badfile"
if [ "$bad" -gt 0 ]; then echo "skipped $bad unparseable lines" >&2; fi
exit 0
