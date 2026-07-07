# SQLV2 result delivery

How a SQLV2 node learns that its run finished and gets the result envelope.

## Current approach: FE short-poll (implemented)

The run result is written durably to `NotebookNodeRun` (Postgres) by the sandbox
callback. The frontend node polls a cheap read endpoint until the run reaches a
terminal state.

- **Backend:** `GET .../sql_v2/runs/<run_id>` returns `{status, result, error}`
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

1. **Callback handler** (`sql_v2_callback.py`)
   - Keep the DB write (envelope → `NotebookNodeRun`) as the authoritative source.
   - After the write, best-effort `PUBLISH notebook:sql_v2:run:<run_id>` with a
     tiny signal (e.g. `{"status": "done"}`). Payload stays small — the SSE handler
     re-reads the authoritative envelope from Postgres. A failed publish never loses
     data; the connect-time read (below) covers it.

2. **SSE stream handler** — replace the busy-poll with **subscribe-then-check**:
   1. **Subscribe first** to `notebook:sql_v2:run:<run_id>` (before the DB read —
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
(`Last-Event-ID` cursor over a trimmed stream). SQLV2 delivers one terminal
result, so pub/sub + a durable row is sufficient and much simpler. Revisit the
Stream approach only if SQLV2 starts streaming incremental output (stdout,
rows-as-they-arrive, progress).

---

# Result storage & paging (design, not yet implemented)

## Three layers — don't conflate them

| Layer                       | Where it lives                                       | Size                                             |
| --------------------------- | ---------------------------------------------------- | ------------------------------------------------ |
| `NotebookNodeRun.envelope`  | Postgres JSONField on the run                        | small — metadata + `first_page` **preview** only |
| Full result (all pages)     | a **result store** the sandbox populates at run time | can be large                                     |
| `NotebookNodeRun.result_id` | Postgres (UUID column, from the envelope)            | tiny — a **handle** into the store               |

The envelope carries `{columns, row_count, first_page, result_id}` — a bounded
preview plus a pointer. **It never holds more than the first page.** The full
dataset lives in the result store, referenced by `result_id`. This is the
"pass large data by reference, not by value" rule (same reason Temporal payloads
are capped) — a multi-MB dataframe must never land in the JSONField or the
callback body.

## One run = one row (not one row per page)

`NotebookNodeRun` is one row per **execution** (per Run click). It produces one
`result_id` and one stored result set. **A page fetch is not a run** — it's a
read of an already-materialized result, so it creates **no new `NotebookNodeRun`,
no Temporal workflow, no DB write**. Runs stay the audit/history record; page
reads stay stateless.

```text
1 Run click → 1 NotebookNodeRun → 1 result_id → 1 stored result set
                                                     ↑
        page 1, 2, 3, "download all" ──read-only────┘   (0 new runs)
```

## Where the full result lives

**Now: a capped in-memory cache in the kernel-server (hogql runs).** A run fetches up to
`RESULT_CACHE_ROWS` (300) rows in one ClickHouse query; the kernel-server keeps
them per run (LRU over the last 20 runs). `/page` requests within the cache are
local slices — no ClickHouse work, no held backend workers. Paging beyond the
cache, or after a kernel restart emptied it, falls back to a LIMIT/OFFSET
re-query through the data plane.

**Kernel runs (python/duckdb) page from the on-sandbox result store.** The kernel
writes each produced frame to `/data/results/<result_id>.arrow`; `/page` requests
carrying a `result_id` slice that file in the server process (`kernel/result_store.py`,
pyarrow mmap). There is no data-plane fallback — the run's code is not a HogQL query —
so a lost frame (sandbox death) means re-run, per the alive-only trade-off below.

**Later: durable store** (object storage / Parquet / a results table). The
sandbox materializes the full result at run time; `result_id` is the storage key.
Removes the alive-only limitation below. Switch to this when results must survive
kernel teardown/reloads.

## Page fetch with a kernel-resident store

The data is _in_ the sandbox, so a page fetch **must round-trip to the sandbox** —
but it must **not** use the run's async callback. The callback exists because a
run has unbounded latency; slicing rows out of an in-memory frame is fast and
bounded, so paging is a plain **synchronous request/response**:

```text
Run (unbounded):   FE → POST /sql_v2/run → Temporal → kernel-server POST /run → 202
                                              (later) → POST /callback → DB → FE polls
Page (bounded):    FE → GET /sql_v2/results/<result_id>?page=2&page_size=100
                        → backend finds the running kernel
                        → HTTP POST kernel-server /page {result_id, page, page_size}
                        → kernel-server slices resident frame, returns rows in the 200 response
                        → backend returns rows to FE
```

- **No docker control plane needed.** The run goes through Temporal partly because
  `ensure_sql_v2_server` bootstraps the server via `write_file`/`execute` (docker
  socket). By page-fetch time the kernel-server is already up, so paging is just a
  **network HTTP call** to it — allowed even under the dev Seatbelt sandbox (only
  the docker _socket_ is denied, not network egress). Hence a synchronous
  web→kernel-server call is fine and low-latency.
- **To build:** add a synchronous `/page` route to the kernel-server
  (`kernel/server.py`) + a thin backend read endpoint that proxies to it.

## Kernel-resident tradeoff: alive-only

The `result_id` slice exists only while that kernel is up. If the kernel
idle-times-out, is restarted, or the notebook reloads onto a fresh kernel,
`result_id` is stale → `/page` returns not-found → the UI must **re-run** to get a
fresh `result_id`. Durable storage is what removes this later.

## Related model notes

- **`KernelRuntime.server_url` / `server_connect_token`** are stored **plaintext**
  (`TextField`). This matches PostHog Code, which keeps `sandbox_url` /
  `sandbox_connect_token` plaintext in `TaskRun.state` (a plain JSONField). The
  connect token is an ephemeral Modal tunnel token, not a durable account secret
  (those, e.g. env vars, tasks _does_ encrypt via `EncryptedJSONStringField`). If
  we ever want defense-in-depth, an encrypted field is the established pattern.
- **`NotebookNodeRun` has no FK to `KernelRuntime`** and doesn't need one: dispatch
  targets the currently-running kernel and the result returns by `run_id`; a later
  run just creates a new row against whatever kernel is up then. If we want
  run→sandbox traceability for debugging, prefer storing the **`sandbox_id` string**
  on the run over a hard FK — `KernelRuntime` rows are transient
  (starting/stopped/discarded/error), so a FK would couple run history to a churny
  row.
