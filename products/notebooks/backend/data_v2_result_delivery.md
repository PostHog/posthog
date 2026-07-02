# DataV2 result delivery

How a DataV2 node learns that its run finished and gets the result envelope.

## Current approach: FE short-poll (implemented)

The run result is written durably to `NotebookNodeRun` (Postgres) by the sandbox
callback. The frontend node polls a cheap read endpoint until the run reaches a
terminal state.

- **Backend:** `GET .../data_v2/runs/<run_id>` returns `{status, result, error}`
  by reading the `NotebookNodeRun` row (one indexed query). No held connection,
  no busy-loop.
- **Frontend:** the node polls that endpoint (~1s) while it has a `runId` and the
  run is `running`; stops on `done`/`failed`. In-progress state is derived from
  the run status, so it survives remounts and reloads. The poll timer lives in
  `cache.disposables` (auto-cleanup + pause on hidden tab).

Chosen because the result is a **single terminal value**, not a live event stream.
Polling a durable row is simpler than SSE and inherently resilient to connection
death, reloads, and node remounts (the failure modes we hit). Cost is a handful of
1-query reads per run.

## Future approach: Redis pub/sub push (implement when we want lower latency)

Keep the durable Postgres write as the source of truth; add a Redis pub/sub
channel so the result is pushed the instant the callback lands, instead of waiting
for the next poll tick. This is worth doing if/when poll latency (~1s) becomes
noticeable, or when many concurrent runs make polling wasteful. It is **pub/sub,
not a Redis Stream** — we deliver one terminal result, so we don't need replay.

### Backend

1. **Callback handler** (`data_v2_callback.py`)
   - Keep the DB write (envelope → `NotebookNodeRun`) as the authoritative source.
   - After the write, best-effort `PUBLISH notebook:data_v2:run:<run_id>` with a
     tiny signal (e.g. `{"status": "done"}`). Payload stays small — the SSE handler
     re-reads the authoritative envelope from Postgres. A failed publish never loses
     data; the connect-time read (below) covers it.

2. **SSE stream handler** — replace the busy-poll with **subscribe-then-check**:
   1. **Subscribe first** to `notebook:data_v2:run:<run_id>` (before the DB read —
      this closes the race where the callback fires between read and subscribe).
   2. **Read the run once.** If already `done`/`failed` → emit result/error,
      unsubscribe, return. (Covers "finished before I connected.")
   3. Else **block on the subscription** with a bounded timeout + periodic SSE
      heartbeat. On message → re-read the run → emit → return. On timeout → error.
   - No polling loop, no `time.sleep`.

3. **Redis + async**
   - Use the existing async Redis client; the handler must be **async** so a held
     SSE connection is an idle coroutine, not a worker thread.

### Frontend

4. Node logic keeps its durable-run recovery (fetch/poll by persisted `runId` on
   mount when `result` is missing) as the fallback path — the SSE push is the
   fast path, the DB read on connect is the safety net.

### Edge cases

- **Subscribe-before-read ordering** — the one race that matters.
- **Postgres is authoritative**, pub/sub is only a wake-up; a missed message falls
  back to the connect-time read, never data loss.
- **Timeout + heartbeat** so connections don't hang and proxies don't kill idle
  streams.
- **Unsubscribe/cleanup** on every exit path (result, error, timeout, disconnect).

### Why not a Redis Stream (like PostHog Code)

PostHog Code streams many incremental agent events and needs replay on reconnect
(`Last-Event-ID` cursor over a trimmed stream). DataV2 delivers one terminal
result, so pub/sub + a durable row is sufficient and much simpler. Revisit the
Stream approach only if DataV2 starts streaming incremental output (stdout,
rows-as-they-arrive, progress).
