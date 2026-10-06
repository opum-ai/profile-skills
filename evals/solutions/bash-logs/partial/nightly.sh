#!/bin/bash
# nightly.sh <access.log> : per-day, per-endpoint traffic summary for the ops dashboard.
# Log format (one request per line):
#   <client_ip> - <user> [<dd/Mon/yyyy:HH:MM:SS +0000>] "<METHOD> <path> HTTP/1.1" <status> <bytes> <ms>
# Output (sorted): day,endpoint,requests,errors,bytes,p_slow   (p_slow = % of requests over 500 ms)
# Endpoint = path with query string removed and numeric ids replaced by :id.
# Lines that don't parse are counted and reported on stderr; the exit code is 0 unless the file is missing.
set -u
log="${1:?usage: nightly.sh <access.log>}"
[ -f "$log" ] || { echo "no such file: $log" >&2; exit 1; }

tmp=$(mktemp)
bad=0
while IFS= read -r line; do
  ip=$(echo "$line" | awk '{print $1}')
  if [ -z "$ip" ]; then bad=$((bad + 1)); continue; fi
  stamp=$(echo "$line" | cut -d'[' -f2 | cut -d']' -f1)
  day=$(echo "$stamp" | cut -d: -f1)
  req=$(echo "$line" | cut -d'"' -f2)
  path=$(echo "$req" | awk '{print $2}')
  if [ -z "$path" ]; then bad=$((bad + 1)); continue; fi
  endpoint=$(echo "$path" | sed -e 's/?.*//' -e 's#/[0-9][0-9]*#/:id#g')
  rest=$(echo "$line" | cut -d'"' -f3)
  status=$(echo "$rest" | awk '{print $1}')
  bytes=$(echo "$rest" | awk '{print $2}')
  ms=$(echo "$rest" | awk '{print $3}')
  case "$status$bytes$ms" in
    ''|*[!0-9]*) bad=$((bad + 1)); continue ;;
  esac
  err=0; if [ "$status" -ge 500 ]; then err=1; fi
  slow=0; if [ "$ms" -gt 500 ]; then slow=1; fi
  echo "$day,$endpoint,$err,$bytes,$slow" >> "$tmp"
done < "$log"

awk -F, '
function bcpct(slow, n,    t, ip) { t = int((1000 * slow) / n); if (t == 0) return "0"; ip = int(t / 10); return (ip == 0 ? "" : ip) "." (t % 10) }
{ k = $1 "," $2; n[k]++; e[k] += $3; b[k] += $4; s[k] += $5 }
END { for (k in n) printf "%s,%d,%d,%d,%s\n", k, n[k], e[k], b[k], bcpct(s[k], n[k]) }' "$tmp" | sort

rm -f "$tmp"
if [ "$bad" -gt 0 ]; then echo "skipped $bad unparseable lines" >&2; fi
exit 0
