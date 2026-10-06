# nightly access-log summary

`./nightly.sh data/access.log > summary.csv` — runs nightly on the ops box (stock macOS, /bin/bash 3.2, `LANG=en_US.UTF-8`)
and in a Linux container. Production logs are ~2M lines/day; the job now takes far too long.
Output feeds the dashboard importer, so it must not change. `make_log.py` generates synthetic logs.

Tests: `tests/run_tests.sh`
