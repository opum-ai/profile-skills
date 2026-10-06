# Services, databases, and production

## Tracing vs profiling vs benchmarking

- **Tracing** (spans) says *which* request step is slow.
- **Profiling** says *why* the code in that step is slow.
- **Benchmarking** says *whether* a change helped.

For a slow endpoint, find the span first (OpenTelemetry, or framework timing), then profile
the code under that span.

Use RED for services and USE for the resources under them:
- **RED:** request rate, errors, and the duration distribution (p50/p95/p99, never the
  mean).
- **USE:** utilization, saturation and errors for CPU, memory, disk, network, connection
  pools and locks.

## Load testing without lying to yourself

```bash
oha -z 30s -c 50 http://localhost:8000/api/items            # native client; latency histogram
npx autocannon -c 50 -d 30 http://localhost:8000/api/items   # Node client (can saturate before the server)
k6 run --vus 50 --duration 30s load.js                       # scenarios, thresholds (k6 2.x runs TS)
```
- **Coordinated omission.** A closed-loop client waits for each response, so a server
  stall silences the client and hides the tail. For latency SLOs use open-loop load at a
  fixed rate:
  - k6 `constant-arrival-rate`;
  - `wrk2 -R`;
  - `vegeta -rate`.
- **Run the load generator on other cores or another machine,** and check that it isn't
  the bottleneck: its own CPU should stay under about 70%.
- **Warm up first** (JIT, connection pools, caches). Run at least 30–60 s, and report
  p50, p99 and max together with the request rate.
- **Profile the server under load:**
  - Python: py-spy `--pid`, or pyinstrument middleware;
  - Node: `--cpu-prof` with a SIGINT handler, or the inspector API;
  - also watch event-loop delay, the ELU, and pool wait times.

## Databases and N+1

Count queries rather than timing them. The count is deterministic, so it makes a good test
and gate.

- **Django:** `assertNumQueries(n)`, `CaptureQueriesContext(connection)`, and pytest-django
  `django_assert_max_num_queries(n)`. Fix with `select_related` (FK/one-to-one),
  `prefetch_related` (M2M/reverse), `.only()`, and `bulk_create`.
- **SQLAlchemy 2.x:**
  ```python
  from sqlalchemy import event
  n = 0
  @event.listens_for(engine, "before_cursor_execute")
  def _count(*a):
      global n; n += 1
  ```
  Use `options(raiseload("*"))` in tests to turn lazy loads into errors. Fix with
  `selectinload` / `joinedload`.
- **sqlite3 / DB-API:** wrap the connection, or call `conn.set_trace_callback(print)` and
  count the lines.
- **Node:** Prisma `log: ['query']`, Knex/TypeORM query events, or count with
  `diagnostics_channel` for undici.
- **A slow single query:** `EXPLAIN ANALYZE` / `EXPLAIN QUERY PLAN`, then check for missing
  indexes, sequential scans, and sorts that spill to disk.
- **Per-row commits** and **a connection opened per request** often cost more than any
  single query.

nplusone (Python) has been unmaintained since 2018. Use query-count assertions instead.

## External calls

Common causes:
- sequential HTTP calls in loops;
- no keep-alive (a new TLS handshake per call);
- missing timeouts;
- retries that multiply latency.

Measure the number of calls per request. Fix by batching, bounded concurrency, connection
reuse (`httpx.Client` / `AsyncClient`, undici's `Agent`), and caching *with* production
access patterns in mind.

## Production continuous profiling

When production profiles exist, choose targets from them; that is how Google's ECO picks
its work.
- **Pyroscope** (Grafana Alloy eBPF, or the `pyroscope-io` SDK, configured after fork in
  gunicorn).
- **Parca.**
- **Datadog / Cloud Profiler.**
- **OpenTelemetry Profiles** (public alpha since March 2026; not for critical
  production yet).

Compare time ranges or labels before and after a deploy to confirm a win in the real
environment.
