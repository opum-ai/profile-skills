# fastparse

Parses structured log lines (`ts level msg | k=v k="quoted"`). It sits on the ingest hot path
(~50k lines/s per worker), so `parse` / `parse_many` speed matters. CI: GitHub-hosted runners.

    uv run pytest -q
