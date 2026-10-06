#!/bin/bash
# Golden-output tests: tests/run_tests.sh   (must pass with /bin/bash 3.2 on macOS and bash 5 on Linux)
cd "$(dirname "$0")/.." || exit 1
fail=0
check() { # name input expected_stdout expected_stderr_substring
  out=$(./nightly.sh "$2" 2>/tmp/nightly.err); err=$(cat /tmp/nightly.err)
  if [ "$out" != "$3" ]; then echo "FAIL $1: stdout"; echo "--- got"; echo "$out"; echo "--- want"; echo "$3"; fail=1; fi
  case "$err" in *"$4"*) ;; *) echo "FAIL $1: stderr '$err' lacks '$4'"; fail=1 ;; esac
}
f=$(mktemp)
cat > "$f" <<'LOG'
10.0.0.1 - - [03/Oct/2026:10:00:00 +0000] "GET /api/orders/123?x=1 HTTP/1.1" 200 100 20
10.0.0.2 - bob [03/Oct/2026:10:00:01 +0000] "GET /api/orders/9 HTTP/1.1" 503 50 900
10.0.0.3 - - [04/Oct/2026:10:00:01 +0000] "POST /api/orders/7/items/8 HTTP/1.1" 201 10 600
not a log line
10.0.0.4 - - [04/Oct/2026:11:00:00 +0000] "GET /health HTTP/1.1" 200 2 1
LOG
check basic "$f" "03/Oct/2026,/api/orders/:id,2,1,150,50.0
04/Oct/2026,/api/orders/:id/items/:id,1,0,10,100.0
04/Oct/2026,/health,1,0,2,0" "skipped 1 unparseable lines"
: > "$f"
check empty "$f" "" ""
./nightly.sh /nonexistent >/dev/null 2>&1; [ $? -eq 1 ] || { echo "FAIL missing file exit code"; fail=1; }
rm -f "$f"
[ $fail -eq 0 ] && echo "all tests passed"
exit $fail
