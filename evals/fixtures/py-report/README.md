# reportgen

Nightly event report. `python -m reportgen data/events.csv > report.csv`

Events arrive from an at-least-once queue, so duplicates (same `event_id`) happen and are counted once.
Production files are ~250k rows and will double next quarter. The job runs in a container with a
**256 MB memory limit**. `make_data.py` generates synthetic input.

Tests: `python -m pytest -q`
