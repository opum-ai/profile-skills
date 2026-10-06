# Data access, I/O, network and caching anti-patterns

## Databases / ORMs
| Cue | Fix | How to confirm |
|---|---|---|
| query inside a loop over rows/objects (`for o in orders: o.customer.name` with lazy FK; `await db.get(id)` per item) — N+1 | eager loading (`select_related`/`prefetch_related`, `selectinload`/`joinedload`, Prisma `include`), or one `WHERE id IN (...)` | count queries for n=10 vs n=100: N+1 grows linearly |
| per-row `INSERT`/`UPDATE` + commit | bulk operations (`bulk_create`, `executemany`, `COPY`), one transaction | time + query count |
| `SELECT *` of wide rows to use two columns | `.only()` / `.values_list()` / explicit columns | bytes transferred |
| filtering/sorting/aggregating in application code after fetching everything | push into SQL (`WHERE`, `GROUP BY`, `ORDER BY ... LIMIT`) | rows fetched |
| `OFFSET` pagination deep into large tables | keyset (seek) pagination | `EXPLAIN` |
| new filter/order column without index | add index (separate migration; consider write cost) | `EXPLAIN (ANALYZE)` / `EXPLAIN QUERY PLAN` |
| connection opened per request/operation | pool | connection count |
| `COUNT(*)` to check existence | `EXISTS` / `LIMIT 1` | plan |

Count queries deterministically (`assertNumQueries`, a SQLAlchemy `before_cursor_execute`
counter, `sqlite3` `set_trace_callback`, a Prisma query log). An N+1 is confirmed when the
query count scales with n.

## Network
| Cue | Fix |
|---|---|
| sequential calls to the same service in a loop | batch endpoint; bounded concurrency |
| no keep-alive / new client per call | shared session/agent |
| no timeout; unbounded retries; retry without backoff | timeouts, capped exponential backoff with jitter |
| chatty protocol (many small requests) | aggregate; GraphQL/batch APIs; HTTP/2 multiplexing |

## Files
| Cue | Fix |
|---|---|
| reading the same file repeatedly | read once |
| many tiny writes unbuffered / flush per line | buffered writes |
| whole-file read of potentially huge inputs | stream |
| parsing big CSV/JSON in interpreted loops | native parsers (pyarrow/polars/orjson/msgspec; streaming JSON in Node) |

## Caching
| Cue | Question to ask |
|---|---|
| new cache/memo | Bounded? Eviction? Invalidation on writes? Thread/async-safe? Keyed on inputs production repeats — or only the benchmark? Memory cost at production cardinality? |
| cache wrapping a function with side effects | Correctness bug |
| per-process cache in a multi-process deployment | Hit rate per worker; consistency across workers |
