# SQLV2 sandbox kernel architecture

How the in-sandbox runtime is structured so it can:

1. accept HTTP requests to run commands (as it does today),
2. make HTTP requests to the PostHog backend to fetch ClickHouse data (the data plane),
3. load SQL responses as Python dataframes from locally stored files,
4. run DuckDB locally against those files and against kernel-made dataframes.

This extends the Journey 1 slice (`sql_v2.py`, the `kernel/` package) toward the full walkthrough design: push compute to CH, stream Arrow to local files, sandbox drives execution, results return via callback.

## Two processes, one owner

The sandbox runs **two cooperating processes**, both owned by the notebook runtime:

```text
Sandbox (Modal / Docker container)
├── kernel-server            ← long-lived HTTP server (today's exposed port)
│   ├── HTTP API: /health /run /page /interrupt /state
│   ├── run queue → executor (jupyter_client, one run at a time)
│   ├── data-plane client (streams Arrow from backend → local files)
│   └── result-store reader (pyarrow mmap / read-only DuckDB, serves /page)
├── ipykernel                ← child process, spawned and owned by kernel-server
│   └── user namespace + `_ph` bootstrap module
│       (persistent DuckDB connection, frame registry, node runner)
└── /data
    ├── frames/<query_hash>.arrow    materialized CH inputs (Arrow IPC files)
    ├── results/<result_id>.arrow    node outputs, for paging
    └── duck/                        DuckDB db file + temp spill directory
```

**Why not one process (exec user code inside the server)?** Interrupt requires SIGINT semantics (`KernelManager.interrupt_kernel()`), a segfaulting C extension must not take down the HTTP endpoint, and ipykernel gives stdout/stderr/`display_data` (matplotlib PNG) capture for free. All of that is already in the image.

**Why not keep the backend driving a bare ipykernel (V1)?** That is the stdout bridge we are replacing: every execution round-trips the docker/Modal control plane with a generated script. Here the control plane is used exactly once — to launch the kernel-server — and everything after is plain authed HTTP. The kernel-server becomes the single owner of the kernel process (spawn, health, interrupt, restart); the backend never touches the kernel directly.

### Division of labor (the important rule)

- **The kernel-server does all network I/O.** It receives commands, calls the data plane, sends the result callback. Credentials (command secret, callback token, data-plane token) live only in the server process.
- **The ipykernel does all compute and holds all data.** User Python, DuckDB queries, pandas frames, the persistent DuckDB connection.
- **They share data through files** (`/data`), never through sockets: the server streams Arrow onto disk; the kernel maps those files into DuckDB/pandas. This keeps backend credentials out of the process that runs user code — user code can read anything in its own process, so the less that process holds, the better. (Everything in the sandbox is scoped to this one notebook/team regardless; this is defense in depth, not the boundary.)

## The HTTP API (capability 1)

Same server, same port, same HMAC command-token auth as today (`sql_v2.mint_command_token` / `_verify_command_token`), extended:

| Route                  | Sync? | Purpose                                                                                                                                                                                                             |
| ---------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /health`          | sync  | liveness + `{version, kernel_alive}` — version drives the redeploy handshake                                                                                                                                        |
| `POST /run`            | 202   | enqueue a node run; result arrives via callback                                                                                                                                                                     |
| `POST /interrupt`      | sync  | `KernelManager.interrupt_kernel()` (SIGINT) for the active run                                                                                                                                                      |
| `POST /page`           | sync  | one result page — bounded, no callback. Today (pure-HogQL nodes) it re-queries the data plane with the run’s code + LIMIT/OFFSET; materialized results will slice from `/data/results` once the result store exists |
| `GET /state`           | sync  | list materialized frames, kernel variables, DuckDB tables (Journey 7)                                                                                                                                               |
| `POST /kernel/restart` | sync  | recycle the ipykernel child; frames on disk survive, namespace does not                                                                                                                                             |

The command token grows a **scope** claim: `run:<run_id>` (authorizes `/run`, `/interrupt` for that run) or `kernel:<runtime_id>` (authorizes `/page`, `/state`, `/kernel/restart`). Same HMAC scheme, signed payload becomes `{scope}.{exp}`.

`POST /run` body (superset of today's):

```json
{
  "run_id": "…",
  "node": { "type": "hogql | duckdb | python", "code": "…", "output_name": "df3" },
  "inputs": [
    { "name": "df1", "kind": "hogql", "query": "<CTE-resolved HogQL>", "query_hash": "sha256…" },
    { "name": "df2", "kind": "local" }
  ],
  "callback": { "url": "…", "token": "…" },
  "data_plane": { "url": "…", "token": "…" }
}
```

The backend resolves upstream HogQL references into `inputs` before dispatch (it owns the notebook document); the sandbox never parses HogQL. `kind: local` asserts the frame already exists in the kernel (made by an earlier Python/DuckDB node); the server fails the run cleanly if it doesn't.

Runs execute **one at a time** in arrival order (a kernel has one namespace; concurrent mutation is meaningless). The server keeps a small FIFO queue and per-run state so `/run` returns 202 immediately, and the watchdog/callback bookkeeping has one source of truth. `/page` and `/state` are served concurrently off the server's own read-only view of `/data` — they never wait behind a long run.

## The data plane (capability 2)

New backend endpoint, the counterpart of the callback:

```text
POST /internal/notebooks/<short_id>/data_plane/query
Authorization: Bearer <data-plane token>
{ "query": "<HogQL>", "limit"?, "offset"? }
→ 200, Content-Type: application/vnd.apache.arrow.stream (RecordBatch stream)
```

- **Auth**: a signed data-plane token, same `django.core.signing` pattern as the callback token, scoped `(notebook, team)`, minted per run and delivered inside the `/run` payload. TTL must exceed the run watchdog. Hardening later swaps both for RS256 JWTs (Code's `sandbox_event_ingest` pattern), unchanged wire shape.
- **Execution**: the endpoint runs the HogQL through the normal HogQL layer (access controls apply), against ClickHouse — or DuckLake for warehouse sources (Journey 6) — and writes Arrow record batches into the streaming HTTP response as they arrive. No object storage, no buffering the full result server-side.
- **Client side**: the kernel-server issues the request with `requests(..., stream=True)` and feeds `response.raw` into `pyarrow.ipc.open_stream`, writing batches straight into an Arrow IPC **file** under `/data/frames/<query_hash>.arrow`. Peak memory is one record batch, regardless of result size.

Two uses of the same endpoint:

1. **Display page for a pure-HogQL node** — the server requests the query with `LIMIT/OFFSET` for the capped page, builds the envelope from the small Arrow payload, and **never involves the kernel**. Paging/sorting a displayed HogQL node is a fresh CH query every time (accepted trade-off from the walkthrough).
2. **Materialization** — when a Python/DuckDB node needs a CH-resident input, the server fetches the **full** result to a frame file first, then hands the run to the kernel.

Frame files are keyed by `query_hash` (sha256 of the canonical resolved query): re-running a Python node whose inputs didn't change reuses the file; an edited upstream query changes the hash, so staleness falls out naturally (the UI's stale-flag flow, Journey 10, decides _when_ to re-run; the hash decides _whether_ a fetch is needed).

## Loading frames into Python (capability 3)

The kernel is bootstrapped once (at kernel start, by the kernel-server) with a small module, `_ph`, which holds:

- a **persistent DuckDB connection** (`duckdb.connect("/data/duck/duck.db")` with `temp_directory` set, so big operations spill to disk),
- a **frame registry**: `name → {query_hash, path, registered_view}`,
- the **node runner** the server invokes per run.

For each run, the server sends the kernel a single execute request — `_ph.run_node(<payload>)` — where the payload lists the node code and the (already fetched) input file paths. `run_node`:

1. **Registers inputs.** For each `hogql` input: `pyarrow.ipc.open_file(path)` (memory-mapped, zero-copy) and `duckdb.register(name, arrow_object)` — the frame is queryable in DuckDB without ever fully loading into RAM. For a **Python** node it additionally binds `name = <arrow>.to_pandas()` into the user namespace — this is the one step that materializes in RAM, matching the accepted trade-off ("pandas may need to materialize all in memory"); heavy reduction should happen in HogQL/DuckDB first.
2. **Runs the node** (below).
3. **Builds the envelope** — `{status, stdout, stderr, error?, result_id, columns, dtypes, row_count, first_page, media}` — and returns it as the execute result. The kernel-server, not the kernel, POSTs it to the callback URL.
4. **Writes the result frame** (if the node produced one) to `/data/results/<result_id>.arrow`, so `/page` can slice it later without touching the kernel.

Python node execution uses `get_ipython().run_cell(code)` inside a capture context: full IPython semantics (last-expression value, tracebacks), stdout/stderr capture, and matplotlib figures arrive as `display_data` PNG — straight into `envelope.media`.

## Local DuckDB (capability 4)

**DuckDB nodes always execute inside the kernel process.** This is forced by DuckDB's replacement scans: `duckdb.sql("select * from my_pandas_df")` only resolves `my_pandas_df` if the frame lives in the same process. Since DuckDB nodes exist precisely to query local frames (decision 3), they run where the frames are.

A DuckDB node is then just: register any not-yet-registered file-backed inputs, `_ph.duck.sql(code)`, bind the result relation to `output_name` (as a registered DuckDB view + lazily-materializable frame), envelope with a capped preview. The result stays lazy in DuckDB until a downstream Python node calls for pandas.

The routing rule the server applies per run (from the walkthrough, now concrete):

- `node.type == hogql` and **all** inputs are `hogql` → push to CH: data-plane page fetch only, kernel untouched.
- anything else (Python node, DuckDB node, or a HogQL node would go here if we ever allow HogQL over local frames — we don't; that's what DuckDB syntax is for) → materialize `hogql` inputs to frame files, run in the kernel.

## Result store and paging

`/page` reads `/data/results/<result_id>.arrow` in the **server** process (pyarrow mmap slice, or a read-only DuckDB connection for sorted/filtered pages). Consequences:

- paging a materialized result is sub-ms and never queues behind a running cell,
- `result_id` stays valid across a **kernel** restart (files survive; only the namespace dies) but not across a **sandbox** death — consistent with the documented alive-only trade-off in `sql_v2_result_delivery.md`,
- results above a size cap are written truncated with a `truncated: true` marker in the envelope; the UI offers re-run-with-filters rather than paging into a 10 GB frame.

## Packaging: from embedded string to a real package

`KERNEL_SERVER_SOURCE` (a stdlib-only string in Django) cannot carry this. Replace it with a real, dependency-using package that never imports Django:

```text
products/notebooks/kernel/          # or backend/kernel_src/ — sandbox-side code, no Django
├── server.py        # HTTP server (stdlib ThreadingHTTPServer stays fine — 202s and bounded reads)
├── auth.py          # command-token verification (mirror of sql_v2 HMAC, round-trip unit-tested)
├── executor.py      # run queue, jupyter_client KernelManager ownership, watchdog, callback POST
├── data_plane.py    # Arrow streaming fetch → /data/frames
├── result_store.py  # /page + /state reads
├── bootstrap.py     # the `_ph` module injected into the kernel (duck conn, frame registry, run_node)
└── envelope.py      # envelope construction shared by executor/bootstrap
```

Dependencies (`jupyter_client`, `pyarrow`, `duckdb`, `pandas`, `requests`) are already in `Dockerfile.sandbox-notebook`; no new image deps needed. Delivery:

- **Prod**: bake the package into the sandbox image (like Code's agent-server), launched as `python -m …kernel.server --port … --secret-file …`.
- **Dev / iteration**: keep the `write_file` bootstrap in `ensure_sql_v2_server`, but upload a tarball of the package keyed by content hash; `/health` reports the hash, and a mismatch triggers re-upload + restart. Editing kernel code then needs no image rebuild.

Because the package is plain Python with no Django imports, it gets normal unit tests in CI (auth round-trip, envelope building, run_node against a real in-process DuckDB, data-plane client against a stub Arrow server).

## Failure handling

- **Kernel dies mid-run** (OOM, segfault): the server's executor notices (execute reply timeout / `km.is_alive()` false), POSTs a `{status: "failed", error: "kernel_died"}` envelope to the callback, and can restart the kernel on the next run. The backend-side watchdog stays as the outer net for the case where the whole _sandbox_ dies and no callback can ever arrive.
- **Data-plane fetch fails** mid-stream: partial frame files are written to a temp name and renamed only on success, so the registry never sees a torn file; the run fails with the fetch error in the envelope.
- **Sandbox dies**: everything under `/data` is gone; recovery is the walkthrough's re-provision + mark-all-stale + re-run flow. Nothing here changes that.

## Build order

1. **Package extraction (pure refactor).** Move the current fabricated-result server into the package + tarball bootstrap + version handshake. E2E slice stays green; `KERNEL_SERVER_SOURCE` is deleted.
2. **Server owns an ipykernel.** `executor.py` spawns the kernel via `KernelManager`, injects `_ph`; `/run` with `node.type: python` executes real code and returns a real envelope (stdout, tracebacks, matplotlib media). `/interrupt` works.
3. **Backend data-plane endpoint** (HogQL → Arrow stream) + server-side fetch. Pure-HogQL display nodes return real ClickHouse data — Journey 1 is real end to end, Journey 2 paging via re-query.
4. **Materialization.** `inputs` in the run payload, frame files, `_ph` registration + pandas binding — Journeys 4/5.
5. **DuckDB node type** — Journey 3-alt/5/6 local joins.
6. **Result store `/page` + `/state`** — Journey 2 (materialized paging) and Journey 7.
