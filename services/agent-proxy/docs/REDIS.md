# Redis connection model

**Status:** Accepted (2026-06-06)
**Scope:** the SSE read path in `src/hono/sse-handler.ts` and `src/lib/redis-stream.ts`

## Decision

Each SSE stream opens its own dedicated Redis connection (`redis.duplicate()`) for its blocking `XREAD` read loop, and closes it when the stream ends.
The single shared client is kept for everything else: ingest writes (`XADD`, `WATCH`/`MULTI`) and non-blocking control reads.

We chose this over two alternatives:

1. one shared connection for everything (what the first cut did): correct-looking but broken under load, see below
2. a bounded pool of multiplexed blocking-read connections: the right answer at large scale, but premature complexity for our current workload

We are accepting one extra Redis connection per active SSE stream as the cost, with monitoring and a documented migration path instead of building the pool now.

## What the connection actually does

agent-proxy talks to Redis on two very different access patterns:

| Path                              | Commands                          | Holds the connection?              |
| --------------------------------- | --------------------------------- | ---------------------------------- |
| SSE read (tail a task-run stream) | `XREAD ... BLOCK 100` in a loop   | **Yes**, up to `BLOCK_MS` per call |
| Ingest write (sandbox to Node)    | `XADD`, `WATCH`/`MULTI`, `EXPIRE` | No (returns immediately)           |
| Control / lifecycle               | `GET`, `SET`, `EXISTS`, `EXPIRE`  | No                                 |

The read path is the only one that blocks the connection. Everything else is a short request/response.

## Why not one shared connection

ioredis sends every command for a client over a single TCP socket in FIFO order.
A blocking `XREAD ... BLOCK 100` occupies that socket for up to 100 ms waiting for data.
With N concurrent SSE streams sharing one client, the blocking reads serialize:

- worst-case event-delivery latency for any one stream is about N x `BLOCK_MS`
- ingest `XADD` writes queue behind the blocking reads, so reads starve writes

This degrades at trivial concurrency (tens of streams already give multi-second delays plus ingest backpressure). It is not an optimization to skip. The fix is mandatory. The only open question is which fix.

## Why per-stream over a pool, for our workload

Our streams are task-run watchers: relatively few at a time, long-lived (minutes up to the 6h sandbox TTL), low churn. For that shape a connection per stream is simple and obviously correct:

- the connection's lifetime is the stream's lifetime (created right before the read loop, closed in the generator's `finally` on completion, error or client disconnect)
- no shared state, no head-of-line blocking between streams, nothing to rebalance

A bounded pool would block-read many streams per connection using multi-key `XREAD`. It bounds connection count, but it is a real subsystem:

- you cannot add or remove a stream from an in-flight blocking `XREAD`; every connect/disconnect makes you let the current block return then reissue with a new key set
- you own per-stream cursors (each stream advances independently), demultiplexing returned entries to the right consumer, per-consumer backpressure (one slow client must not stall the shared reader for others on that connection) and shard rebalancing

That is worth building when connection count is the binding constraint. It is not worth building speculatively.

## The cost we are accepting (read this part)

agent-proxy connects to `REDIS_URL`, which in production is **the main shared Redis**. That instance also backs the Celery broker and result backend, general caching, rate limiting and today the Python proxy's stream plane (`products/tasks/backend/stream/redis_stream.py`, which uses `settings.REDIS_URL` and shares the exact same stream with us during the cutover).

So every active SSE stream consumes one connection on a resource that almost every PostHog service hits. Two failure modes follow, and neither is local to agent-proxy:

- **Connection count.** Active dedicated connections grow linearly with concurrent streams, summed across every agent-proxy pod. If that fleet-wide total competes for the shared instance's `maxclients` budget (Redis default 10,000, but the real ceiling is whatever the managed instance is set to), exhaustion surfaces as errors in _other_ services, not just here.
- **Idle-poll load (bandwidth and ops).** With `BLOCK_MS = 100`, an idle stream issues about 10 `XREAD` round-trips per second. N idle streams is roughly 10N ops/sec of command traffic on the shared instance even when nothing is happening. The event payload itself would transfer under any design, but the idle-poll round-trip rate is pure overhead that scales with stream count.

The Python proxy already runs this same blocking-read pattern against the same Redis, so the load shape is not new. The Node rewrite makes the connection count explicit, which is precisely why we are writing it down and governing it rather than leaving it implicit.

This is the open risk. We are accepting it at current scale. We are not claiming it is free.

## What makes it safe enough today

- **It is observable.** `agent_proxy_sse_open_streams` (gauge) tracks active streams, which is an upper bound on dedicated read connections. `posthog_tasks_task_run_stream_connections_opened_total` / `_closed_total` give the same view from counters.
- **It fails soft.** If a dedicated connection cannot be established (for example the instance is at `maxclients`), the read path emits an SSE `error` event and ends that one stream instead of crashing the process (`stream:redis_dup_connect_failed`). Ingest uses the separate shared client, so a read-side connection ceiling does not directly kill writes.
- **It is conservative per connection.** Duplicated connections inherit the shared client's options: `commandTimeout`, bounded `maxRetriesPerRequest`, `enableOfflineQueue: false`. A stuck or unreachable Redis surfaces fast rather than piling up queued work.

## Cheap levers, available without re-architecting

These reduce shared-Redis load while keeping the simple per-stream model. None change the wire protocol (same keys, same `XREAD` args, same SSE bytes):

- **Raise `BLOCK_MS`.** `XREAD ... BLOCK` returns _immediately_ when data arrives, so a larger block timeout cuts the idle-poll rate with no added latency on real events. Going from 100 ms to 1000 ms drops idle traffic roughly 10x. The only thing a longer block delays is the loop's periodic wake to check the 20s keepalive timer, which is fine. Client disconnect is still immediate because `disconnect()` aborts the in-flight call.
- **Add a per-pod cap.** A max-concurrent-streams limit that returns `503` on new SSE connections past the cap turns a silent `maxclients` cliff into predictable load shedding. Roughly 15 lines, can be added at any time.

## Migration path, in order of preference

1. **Dedicated Redis for the task-run stream plane.** This removes the blast-radius concern entirely by isolating both the connection count and the idle-poll load off the shared instance, and it lets the simple per-stream model stay. PostHog already isolates hot workloads this way: `FLAGS_REDIS_URL`, `AI_GATEWAY_REDIS_URL`, `SESSION_RECORDING_REDIS_URL`, `QUERY_CACHE_REDIS_CLUSTER_URL`. Add an equivalent (for example `TASKS_STREAM_REDIS_URL`) and point it at its own cluster.
   - **Constraint:** the stream is shared with the Python proxy during the cutover. Both sides (the Python stream plane and agent-proxy) must move to the same dedicated instance together, or this waits until the Python proxy is retired. Moving one side alone splits the stream and breaks live runs.
2. **Bounded connection pool (multiplexed `XREAD`).** If even a dedicated instance's connection count or idle-poll rate is the binding constraint, replace per-stream `duplicate()` with a small fixed pool (for example 10 to 20 connections), each block-reading a shard of streams via multi-key `XREAD`. This is the subsystem described above. The wire protocol is unaffected.

The order is deliberate. A dedicated Redis is operationally cheap and solves the actual concern (shared blast radius). The pool only becomes worthwhile once the workload is already isolated and still too large for one connection per stream.

## When to revisit

Pull the migration path when any of these fire:

- fleet-wide `agent_proxy_sse_open_streams` (pods x streams per pod) approaches the connection headroom you are willing to allocate this workload out of the shared `maxclients` budget (suggest alerting around 50 to 60%)
- `stream:redis_dup_connect_failed` starts logging, which means streams are already hitting the connection ceiling
- connection-establishment latency, or shared-Redis CPU and network, climbs in step with stream count
