# SQLV2 frame materialization via object storage

Design notes for moving python-node frame materialization off the Redis JSON transport and onto an object-storage handoff.
Status: **phase 1 shipped** (env-gated by `NOTEBOOKS_FRAME_STORE_ENABLED`, default off) — object delivery at a 500k row tier-1 ceiling (`MAX_SELECT_NOTEBOOK_MATERIALIZE_LIMIT`); the inline path remains as the degraded fallback, still clamped at 50k. **Phase 2 implemented dark** (`NOTEBOOKS_FRAME_STORE_CH_WRITES`, default off — CH writes the object itself; see the phase-2 prerequisites before flipping). Phase 3 not started.

## Problem

When a python node reads an upstream SQLV2 frame, the sandbox kernel fetches the whole frame through the data plane
(`sql_v2_data_plane.py`), which rides the generic async query manager:

1. A Celery worker executes the HogQL and holds the full result as Python tuples.
2. The worker JSON-renders the entire result into **one Redis string value** (`QueryStatusManager.store_query_status`).
3. On poll, a web worker reads the blob back, parses the JSON, and re-encodes it as an Arrow stream for the sandbox.

The frame is fully copied ~5 times, and the middle copy sits in Redis — the shared cache for the whole deployment.
This transport is implicitly sized by the 50k row ceiling (`MAX_SELECT_RETURNED_ROWS` under the async limit context),
so inline materialized frames are silently clipped at 50k rows.
A `LimitContext.NOTEBOOK_MATERIALIZE` context raising the ceiling to 2M (`_MATERIALIZE_ROW_CAP`) was built and then
**deliberately reverted**: without a better payload transport, wide multi-hundred-thousand-row frames stress Redis
(single-threaded, 512MB per-value hard cap, eviction pressure) and the workers that render/parse the JSON.
With phase 1 the context is back, applied **only on the object path** and at a 500k tier-1 ceiling
(`MAX_SELECT_NOTEBOOK_MATERIALIZE_LIMIT`, raised toward 2M on query-log evidence); the inline path — now the
degraded fallback — keeps the 50k clamp, pinned by `test_inline_materialization_stays_clipped_at_the_row_ceiling`.

## Decision sketch: durable object handoff, not live push

Two async candidates were compared (web-tier streaming is ruled out — no design may pin a web worker on bulk bytes):

- **A — worker/CH writes Arrow to object storage; sandbox pulls a presigned URL.**
- **B — worker pushes the Arrow stream directly into the sandbox's kernel server.**

A wins on every axis that matters here except single-transfer latency:

- **Lifetime decoupling.** Push needs producer and consumer alive simultaneously; the sandbox is the most ephemeral
  component we have (Modal cold starts, idle teardown, kernel restarts wipe local disk). An object survives all of that:
  any sandbox instance — including one restarted mid-run — can fetch, resume with Range requests, and retry per leg.
- **ClickHouse resource-hold.** A `SELECT` counts as running until the client drains the last block.
  Draining into S3 happens at datacenter speed, so CH resources are held for ~pure execution time.
  Draining into a Modal container is paced by public-internet throughput and the kernel's ingest —
  backpressure propagates into CH (memory pinned, query slot held, execution-time clock ticking).
- **Reuse.** Frames are keyed by `query_hash`; an object serves download retries and kernel restarts without
  re-executing CH. Cross-run reuse of an unchanged query is phase 3 — and gated on a staleness policy,
  because the key has no freshness component (see the stale-read hazard there). Push has no reuse story —
  every delivery is a fresh execution.
- **Attack surface.** Pull keeps the sandbox ingress-free; push requires a new streamed-upload endpoint on the
  kernel server, exposed to the internet, plus a request/callback correlation protocol.

Making the sandbox "S3-shaped" is easy at the protocol level (accept a chunked PUT) but cannot provide S3's
semantics — durability, resume, producer/consumer decoupling — because the sandbox is ephemeral by design.
The hard part isn't accepting bytes; it's being a reliable place for bytes to live.

## Prior art in the repo

Every building block already runs in production. Inventory (per deep-dive, 2026-07):

### ClickHouse writes S3 directly (`INSERT INTO FUNCTION s3(...)`)

| Flow                                                                                                                    | User-facing?                                                                                                                                       | What it teaches us                                                                                                                                                                                                                                     |
| ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Batch exports internal stage** — `products/batch_exports/backend/pipeline/internal_stage.py:237`, `temporal/sql.py:8` | Yes, indirectly: users configure recurring batch exports (Data pipelines → Destinations); every run of every destination stages through this first | The core recipe: `INSERT INTO FUNCTION s3(...'ArrowStream') PARTITION BY rand() % N`, keyless IAM in cloud (CH instance role), partition sizing (~250k rows/file), 64MiB insert blocks, delete-prefix-before-write cleanup, bucket-lifecycle retention |
| File-download batch export — `destinations/file_download_batch_export.py:236`                                           | Yes: user requests an export file, downloads when ready                                                                                            | STS `assume_role` scoped to a single bucket prefix, 1h expiry — the tightest credential pattern in the repo                                                                                                                                            |
| Query-log exports (Dagster ×2) — `posthog/dags/export_query_logs_to_s3.py:98`                                           | No: internal ops, daily schedule                                                                                                                   | `s3_truncate_on_insert=1` for idempotent re-runs; per-host fan-out                                                                                                                                                                                     |
| Duckling backfill — `posthog/dags/events_backfill_to_duckling.py:1420`                                                  | No: operator-run migration tooling                                                                                                                 | Dynamic fan-out sizing (target rows/file), bounded CH writer memory via Parquet row-group settings                                                                                                                                                     |
| Identity matching — `products/growth/dags/identity_matching.py:485`                                                     | No: internal experiment                                                                                                                            | CH staging its own intermediate datasets in S3 and reading them back via `FROM s3(...)`                                                                                                                                                                |
| Web analytics Native export — `posthog/models/web_preaggregated/sql.py:835`                                             | No (write side appears dormant)                                                                                                                    | Native format preserves AggregateFunction states across the S3 round-trip                                                                                                                                                                              |

### Python/Temporal worker streams CH results and uploads

| Flow                                                                                                        | User-facing?                                                                                          | What it teaches us                                                                                                                                                                                                                                 |
| ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Data-modeling materialization** — `posthog/temporal/data_modeling/activities/materialize_view.py:346-598` | Yes: user creates a saved query / materialized view (Data warehouse), runs it manually or on schedule | HogQL → `astream_query_as_arrow` in bounded ~100MB batches → Delta/Parquet on S3 via delta-rs; **CH reads the result back** through `s3()`/`s3Cluster()`/`deltaLake()` table functions — proof that CH→S3→query round-trips are production reality |
| CSV/XLSX exports — `products/exports/backend/tasks/csv_exporter.py:480,641`, `models/exported_asset.py:315` | Yes: user clicks "Export" on an insight/table, gets notified, downloads                               | `LimitContext.EXPORT` + 10k-row pagination, single PUT to `OBJECT_STORAGE_BUCKET`, **7-day TTL with lazy expiry**, download via **presigned URL** — the asset-lifecycle pattern to copy                                                            |
| Usage reports v2 — `posthog/temporal/usage_report/activities.py:105`                                        | No: automated billing                                                                                 | Staging many small CH results as S3 objects with explicit best-effort cleanup                                                                                                                                                                      |

### Relevant negative

There is **no generic S3-backed query-result cache** — `query_cache_factory.py` only returns the Redis manager.
That cache exists to reuse identical insight queries within a TTL; the notebook flow gets its reuse from
`query_hash`-keyed frames (in-flight dedup and retry re-fetch today; cross-run reuse is phase 3), so we are
not duplicating (or blocked on) any platform facility.

## Security model for sandbox reads

Trust model today: the sandbox holds a signed, notebook+team-bound data-plane token and pulls from
`/internal/notebooks/data_plane/` over HTTPS. The frame store keeps that shape — the control plane stays
token-authed; only the bulk-bytes leg moves to object storage.

- **How the sandbox reads without AWS credentials.** The sandbox never assumes a role and never holds AWS
  credentials of any kind. The backend — which does hold the role — signs a GET for one specific object with an
  expiry and embeds that signature in the URL (a presigned URL); S3 verifies the signature server-side, so the
  fetch is a plain HTTPS GET with no SDK. This is the same position a user's browser is in when it downloads a
  CSV export (`ExportedAsset.get_content_response`) — an external reader given a narrow expiring capability, not
  an identity. STS temp credentials (file-download-export pattern) were considered and rejected for the read
  side: they would hand real, if scoped, AWS credentials to a container that executes arbitrary user code,
  where a presign is one object, one verb, minutes. Note a presign is only valid while the credentials that
  signed it are — fine for minutes-scale expiry, and the reason day-long URLs can't be minted from
  instance-role session credentials.
- **Bucket posture.** Private bucket (or dedicated prefix), public access blocked, SSE at rest.
  Per the repo's storage direction: SeaweedFS locally, S3 in cloud, standard S3 client, no hardcoded endpoints.
- **Tenant isolation lives at mint time, not in the URL.** Object keys are namespaced
  `notebooks/frames/team_{team_id}/{notebook_short_id}/{query_hash}.arrow`.
  The status endpoint verifies the data-plane token (which binds notebook + team) **before** presigning,
  and only ever presigns objects under that team's prefix. A sandbox can never request another team's key
  because it never names keys at all — it polls a query_id it was issued.
- **Presigned GET discipline.** Short expiry (minutes — long enough for a resume-with-Range retry loop, no more),
  HTTPS-only, never logged. A presigned URL is a bearer secret of the same class as the existing command tokens;
  its blast radius is one object for a few minutes.
- **Write-side auth.** Phase 1: the Temporal worker writes with the standard worker-held object-storage
  credentials (`OBJECT_STORAGE_*` — no new identity). Phase 2, if CH writes directly: CH's instance role
  (keyless, batch-exports pattern), write-scoped to the notebooks prefix. If tighter isolation is wanted
  later: STS prefix-scoped credentials per run (file-download-export pattern).
- **Egress.** The sandbox already makes outbound HTTPS calls to the PostHog API; fetching a presigned S3 URL adds
  one more allowed destination. If Modal egress policy must stay single-destination, the fallback is proxying the
  object through the data-plane endpoint as a bounded stream — bytes transit Django once, but never Redis and
  never as JSON. Keep this as a config switch, not the default.
- **Data at rest is a conscious change.** Query results currently live ≤20 min in Redis; parking them in object
  storage for hours is a retention-policy decision. Bound it with a bucket lifecycle TTL (e.g. 24h) plus
  delete-prefix-on-supersede, and document it.

## Resource governance — not hammering ClickHouse

Materialization runs on the **OFFLINE pool** (batch exports' home), as a **dedicated `notebooks` ClickHouse
user**. An earlier draft argued for ONLINE — someone is waiting on their cell — but the query itself is
batch-shaped: a 500k-row streaming pull with minutes-scale deadlines (the kernel's object-delivery poll
already tolerates 11 minutes), far closer to a batch export than to an insight query. The decisive risk runs
the other way: a single materialization can be far more expensive than an insight query, an **uncapped whale
in a pool tuned for bounded queries** — so it contends with batch work, whose latency variance the async flow
absorbs, instead of degrading interactive latency. Where no offline cluster exists (EU, self-hosted, dev/test)
the offline URL falls back to the online one, and the remaining levers below still bound the whale. Note the
cap that matters is not the row count — an insight query with `LIMIT 50000` can still scan billions of rows;
cost is bounded by execution time, bytes read, memory, and threads.

Layered levers:

- **Per-query SETTINGS (batch-exports recipe).** The staging query carries hard caps, as `internal_stage.py`
  does. Phase 1 ships `max_execution_time` 600s (via the `NOTEBOOK_MATERIALIZE` limit context — modestly
  above the insight ceiling, frame pulls are legitimately heavier), `max_bytes_to_read` 50GB (refuse
  oversized scans up front), `max_threads` 16, and `max_result_bytes` 2GB with `result_overflow_mode=throw`
  (row/scan caps don't bound the _output_ — `repeat('x', 10000)` over 500k rows would make a ~5GB object
  from a near-zero scan; the output cap bounds object size, storage abuse, and what the kernel later decodes
  into pandas, and it throws rather than silently truncating); memory stays on the cluster profile default
  for tier 1 (the typed `MEMORY_LIMIT_EXCEEDED` handling is the backstop). Further levers if data demands:
  `max_memory_usage`, `max_bytes_before_external_sort/group_by` (spill to disk), `max_network_bandwidth`
  to throttle the S3 write rate.
- **No scheduler priority.** CH's `priority` setting could make materialization yield CPU to other offline
  work under genuine contention. Phase 1 deliberately does not set it: everything else runs unprioritized
  (0), so a nonzero value would form a scheduling class of one — revisit if the cluster ever adopts
  priorities broadly.
- **Tiered row ceiling.** Don't jump 50k → 2M in one step: raise to ~500k with the phase-1 transport,
  watch the footprint, then raise toward `_MATERIALIZE_ROW_CAP`.
- **Admission control above CH.** One operation per notebook is already enforced by the operations logic;
  phase 1 adds the Redis-Lua concurrency slots (global 10, per-team 2) acquired at Temporal activity start.
  The refs resolver already minimizes demand — only frames the code actually reads are materialized.
- **Dedicated ClickHouse user as the backstop (shipped).** The repo already splits traffic across CH users
  (`ClickHouseUser.APP` / `API`), each governed by a server-side settings profile. Materializations run as
  `ClickHouseUser.NOTEBOOKS` (credentials from `CLICKHOUSE_NOTEBOOKS_USER`/`CLICKHOUSE_NOTEBOOKS_PASSWORD`,
  falling back to the default user where not provisioned), so the user gets profile limits, QUOTAs, and
  `max_concurrent_queries_for_user` — a hard server-enforced ceiling no application bug can exceed.
- **Demand elimination.** Phase 3's `query_hash` reuse means an unchanged upstream query never re-executes;
  long-term this is the strongest lever.
- **Escalation path.** If notebooks' share of offline capacity becomes meaningful (or batch-export contention
  starts hurting frame latency), the router already supports product-specific pools (`Workload.ENDPOINTS` is
  precedent) — a dedicated notebooks pool is the growth answer, decided with data rather than up front.

The flow is already measurable: the data plane tags queries with `Product.NOTEBOOKS`, and the Dagster
query-log exports make its CH footprint analyzable, so the knobs can be tightened with data.

## Phased plan — start basic, improve later

**Phase 0.** Materialization runs over the existing Redis transport, clipped at 50k rows.
Fine for the current flag-gated audience and frames up to low hundreds of thousands of rows.
Since phase 1 this path survives only as the degraded fallback (frame store disabled or unconfigured).

**Phase 1 — swap the payload path, minimal moving parts. (Shipped, env-gated by `NOTEBOOKS_FRAME_STORE_ENABLED`.)**
The kernel opts in per request with `delivery: "object"` (pages and envelope fetches stay `"inline"`).
The data plane registers a `notebook-frame:{team}:{query_hash}` dedup mapping and dispatches a Temporal
materialize workflow (`temporal/frame_materialize.py`, general-purpose queue, Redis-Lua concurrency slots
global 10 / per-team 2): the activity prints the HogQL through the guarded executor under
`LimitContext.NOTEBOOK_MATERIALIZE` (tier-1 ceiling 500k, not yet 2M), executes over the CH HTTP interface
with `FORMAT ArrowStream`, and relays the raw bytes into one multipart upload
(`frame_store.py`, key `notebooks/frames/team_{team}/{notebook}/{query_hash}.arrow`).
The **object key** lands in `QueryStatus` instead of rows, and the status endpoint answers the poll with a
**302 redirect to a presigned URL** (≤5 min, minted only after token verification, team-prefix-checked).
A frame key is a slot holding the query's current result, not an immutable blob: `query_hash` is
`sha256(user_id + wrapped query)` with no freshness component, and dedup only joins **in-flight**
materializations — a completed status is never served as a cache. Every re-run therefore re-executes against
ClickHouse and atomically overwrites the same key, so a re-run after new events lands returns fresh rows
modulo offline replica lag — materialization reads the OFFLINE pool, which can trail ingestion further than
the online nodes the inline path reads, so a frame can briefly miss rows an inline preview of the same query
just showed (batch exports accept the same window). A reader holding a presign across an overwrite gets one
complete object or the other, never torn bytes.
One correction to the sketch below: the kernel's client is `urllib`, not `requests` — urllib re-sends
`Authorization` on redirects, so the client intercepts the 302 and fetches the presigned URL with a fresh,
credential-free request instead of auto-following.
Stream integrity: ClickHouse sends `200 OK` before execution finishes, so a mid-stream failure can't change
the status code — current versions deliberately break the chunked encoding (the read tears, the multipart
upload aborts), but older versions/intermediaries can close the body cleanly with exception text appended.
The worker therefore refuses to finalize unless the streamed bytes end with the Arrow end-of-stream marker
(a corrupt object at the deterministic key is deleted), and on any stream failure it recovers the real
ClickHouse error from `system.query_log` — a confirmed query-side exception is terminal (no doomed
re-scans), an unconfirmed failure stays retryable.
The Redis path stays as fallback when the frame store is disabled or unconfigured (dev parity, degraded mode).

_Rollout prerequisites (per environment, before flipping the flag on):_

- Enable `NOTEBOOKS_FRAME_STORE_ENABLED` only **after** both the web and general-purpose Temporal worker
  fleets are on the new image. Temporal accepts a `start_workflow` for a workflow type no worker has
  registered yet — so flipping the flag early produces a bounded window of hung polls that the enqueue
  rollback (which only catches a dispatch _exception_) cannot recover.
- Confirm `OBJECT_STORAGE_PUBLIC_ENDPOINT` resolves and routes **from the sandbox kernel's network** — the
  kernel fetches the presigned URL directly. An internal-only host (or the local SeaweedFS docker name)
  makes every download fail (loud, not silent).
- Provision the `notebooks` ClickHouse user, **in this order**: create and verify the user server-side first
  (a `SELECT 1` as the user), then set `CLICKHOUSE_NOTEBOOKS_USER`/`CLICKHOUSE_NOTEBOOKS_PASSWORD` on the
  general-purpose Temporal worker fleet — env vars pointing at a not-yet-created user (or a rotated password;
  creds are cached per worker process, rotation needs a fleet restart) fail every materialization with a
  generic retried auth error, a hard outage rather than a fallback. The user spec, since HogQL fans out to
  distributed tables (remote legs authenticate as the initiating user via the interserver secret): exists on
  **every** node of the `posthog` cluster, SELECT grants mirroring the app user (including data-warehouse
  table functions), a profile with `readonly = 2` — `readonly = 1` rejects the per-query SETTINGS/HTTP params
  this path sends, and if the phase-2 CH-writes flag is enabled the phase-2 writer-identity spec (`readonly
= 0`, zero table-write grants) supersedes this — and no setting constraints below the app-side caps; prefer
  per-query `max_memory_usage`
  over `..._for_user` so a `MEMORY_LIMIT_EXCEEDED` stays attributable to the offending query, and leave QUOTA
  headroom since a shared-user quota breach reads as a (wrong) "narrow your query" message to whichever
  tenant trips it. Deliberately fail-open: until provisioned, the flow runs as the default CH user
  (dev/self-hosted parity) — the `ch_user` label on `posthog_notebooks_frame_materializations_started` is the
  signal that the dedicated user actually engaged.
- Confirm `CLICKHOUSE_OFFLINE_CLUSTER_HOST` is set on the **general-purpose** Temporal worker fleet (US) —
  batch exports prove offline routing on _their_ deployment, not this one, and an unset host silently
  falls back to the online URL, no-opping the pool isolation. The `pool` label on the started counter
  verifies routing from metrics.
- Provision the bucket lifecycle TTL (~24h) on the `notebooks/frames/` prefix **before** enabling.
  Successful objects are never deleted by app code, and query-text variations (even comment-only edits)
  mint new hashes, so without the lifecycle rule an authenticated user can accumulate unbounded durable
  objects. The rule is infra-owned; app-level cleanup would duplicate it poorly.
- Known degraded-mode caveat: with the flag off (the default) or object storage down, a `delivery: "object"`
  request falls back to the inline path clamped at 50k rows and the frame is silently truncated. Fine for
  frames under the clamp; a user-visible truncation signal is a follow-up before GA.

Two decisions locked in for this phase:

- **Format: one plain Arrow IPC stream object per frame — not Delta, not Parquet.** Delta earns its machinery
  when ClickHouse re-reads a versioned, overwritten _table_ (data modeling's case). A frame key is a slot
  holding one query's current result (see above — re-runs overwrite it atomically), read once by pandas;
  versioned re-read machinery buys nothing for that flow. The executor already consumes ArrowStream from the
  data plane, so the sandbox-side change is just "read the same bytes from a different host". If size matters,
  Arrow IPC supports LZ4/ZSTD buffer compression without a format change; multi-file partitioning waits for
  phase 2, if ever.
- **An explicit concurrency limiter is the throttle.** Under worker streaming, one active task = one running
  CH query = one upload — but the materialize workflow runs on the **shared** general-purpose Temporal queue,
  so queue slots alone don't cap notebooks. The shipped throttle is the Redis-Lua concurrency limiter
  (the `process_query_task` mechanism): slots acquired at activity start, global 10 / per-team 2, bounding CH
  concurrency, worker memory, and S3 parallelism with one knob — the dedicated `notebooks` CH user is the
  server-side backstop behind it, and a dedicated notebooks task queue stays a later infra option. Throttling moves load
  in time (retry backoff), never above the cap; the real amplification risk is impatient re-runs, and the
  async manager's `cache_key` dedup (`get_running_query_by_cache_key`) closes it: enqueue with
  `cache_key = notebook-frame:{team}:{sha256(user_id + query)}` (user-scoped, so differently-permissioned
  teammates never share a job or an object) and duplicate in-flight materializations join the running query
  instead of stacking new ones.

**Phase 2 — let ClickHouse do the writing (implemented, behind `NOTEBOOKS_FRAME_STORE_CH_WRITES`, default
off).**
The worker-streamed upload is replaced with `INSERT INTO FUNCTION s3(...'ArrowStream')` (batch-exports
recipe), issued through the pooled native clients (`sync_execute`, offline workload, `notebooks` user) with a
bounded socket timeout (the pooled clients' prod default is effectively infinite; a sync activity can't be
interrupted, so a half-open connection would pin the worker thread — the timeout mirrors the streaming path's
read-timeout defense). The worker's job shrinks to issuing one statement; zero result bytes transit PostHog
Python, and errors arrive in-band and typed — so the EOS-marker check and `system.query_log` recovery have no
role, but note the budget codes come back as `sync_execute`'s wrapped exception types (`ClickHouse*` for
241/159/160, `CHQueryError*`/`InternalCHQueryError` for 158/307/396), all mapped to terminal here. The s3()
endpoint/bucket/key/credentials are **bound as query parameters**, not spliced as literals: `sync_execute`'s
one `%`-substitution pass escapes them, so a `%` or quote in operator config can't corrupt the statement or
reach the credential zone (this is the real binding channel — client-side `escape_param`, the same all HogQL
`sync_execute` uses — not server-side binding). One object per frame, deliberately no `PARTITION BY`: the
poll/presign contract is a single object, and partitioned files + a manifest + Range-based resume stay future
work if frames outgrow it.

The output cap is enforced **post-write** (`max_result_bytes` bounds a result set returned to a client, not
an INSERT's sink). This is a real cost delta worth eyes-on: the in-flight bound is gone, so a pathological
wide-row query (`repeat('x', N)` over 500k rows) can have CH write tens of GB to the store — bounded only by
the 50GB scan budget, 600s time budget, and CH→S3 throughput — before the size check deletes it and fails the
run terminal (no retry). A post-write freshness check (LastModified vs the write start, 5-min skew margin)
also guards against a silent no-op write serving a stale prior-run object under endpoint skew.

_Prerequisites for flipping the flag (per environment, on top of the phase-1 list):_

- CH nodes must reach the object-store endpoint (`OBJECT_STORAGE_ENDPOINT` from the **CH node's** network —
  local dev works because compose puts CH and the store on one network).
- Credentials: keyless in cloud (the CH instance role, write-scoped to the `notebooks/frames/` prefix);
  where `OBJECT_STORAGE_ACCESS_KEY_ID`/`SECRET` are set they ride inline in the statement and land in
  `system.query_log` — acceptable for dev/self-hosted, not for cloud. Verify the deployed CH version masks
  `s3(url, key, secret, ...)` credential arguments as `[HIDDEN]` in `query_log` (masking is signature-based).
- The writer identity per the security notes above: `readonly = 0` with **zero** table-write grants,
  `GRANT S3` + `CREATE TEMPORARY TABLE`, `remote_url_allow_hosts` pinned to our storage endpoints. This
  supersedes the phase-1 `readonly = 2` spec for the `notebooks` user once the flag is on. Fail-safe: the code
  refuses to run the write-capable statement as the default user in a real deployment — if the flag is flipped
  before this identity is provisioned (creds still resolving to default), materialization degrades to the
  read-only streaming path with a warning rather than handing S3-egress to the broad account.
- Resource note (not a blocker, but size the profile for it): Arrow encoding and S3 upload buffering now burn
  CH initiator-node CPU/memory (the default S3 write buffers are ~hundreds of MiB per INSERT, counted against
  the query's `max_memory_usage`), the trade for freeing worker CPU/NIC. The `mode` label on the started /
  finished counters and the `clickhouse_seconds` histogram separates this path's footprint from the streaming
  path's for the flip decision.

Why the worker relay stays the default until then:

- **Security path.** Phase 1 keeps the whole HogQL runner path (team scoping, property access controls applied
  at print time) untouched — new code only handles the result. The CH-side write must print the guarded SQL
  and splice it into a raw `INSERT ... SELECT` executed outside the runner; batch exports does this safely,
  but over its own known tables, not arbitrary user HogQL. That seam deserves its own review, not a
  ride-along — the phase-2 security notes below break down what it entails.
- **Credentials.** Workers already hold object-storage credentials; the CH-side write needs the cluster's IAM
  role extended to the notebooks prefix (see open questions) and local CH → SeaweedFS config.
- **Load placement.** Worker streaming actually puts _less_ work on ClickHouse — CH only executes and streams
  blocks, while Arrow encoding and S3 PUTs burn worker CPU/NIC instead of CH-node resources. The worker's
  drain pace is set by an in-region worker→S3 leg, so CH's result-hold time is near-identical either way.
- **What A buys.** Worker economics at scale (a slot held seconds instead of the stream duration) and no
  double transfer for very large frames. With per-team concurrency ~1 and frames in the tens-to-hundreds of
  MB, neither matters yet — flip on query-log evidence (upload-half p95 dominating the split metrics, worker
  contention, or a byte-cap raise); the flag can stay off indefinitely if the data never asks.

_Phase-2 security notes (splice analysis, 2026-07) — read before building the CH-side write:_

This section is the pre-implementation analysis. As built (see the phase-2 block above), the s3() arguments
are **bound as query parameters** rather than literal-spliced — which resolves the injection and escaping
issue classes below by construction — and the interim-write bound became a post-write size check. The
privilege amplification analysis stands unchanged and is the load-bearing part.

The statement is `INSERT INTO FUNCTION s3('<url>/<key>', '<creds?>', 'ArrowStream') PARTITION BY rand() % N
<printed SELECT ... SETTINGS ...>` — three trust zones: the prefix (our code, our metadata), the printed
SELECT (user HogQL via the guarded printer), and the query parameters (client-side `escape_param` inlining —
the same channel all HogQL `sync_execute` uses; not literally server-side binding). Two facts
cap the risk: the printed SELECT is already the trusted-executable artifact (executed verbatim today, and
already spliced once into `DESCRIBE TABLE (...)`), and ClickHouse refuses multi-statement execution over both
HTTP and native protocols — realistic injection is clause-level corruption of the prefix, not stacked
statements. Issue classes, by zone:

- **The new injection surface is our own s3() arguments, not the user's query.** Today the object key is an
  inert boto3 API argument; in phase 2 it sits inside a SQL string literal in the most privileged statement
  we run. Key segments are safe today (int team id, hex digest, `[A-Za-z0-9_-]+`-validated short id), but
  that makes charset validation load-bearing forever — someone relaxing the short-id charset later turns a
  cosmetic change into SQL injection. Manual escaping is subtler than it looks: the batch-exports builder
  (`get_s3_function_call`) quote-doubles credentials but not the URL/folder, and quote-doubling alone
  mishandles a value ending in `\` — both fine there only because the inputs have known charsets.
- **Assembly-context grammar bugs.** The printer must run without `output_format` (a trailing
  `FORMAT ArrowStream` is invalid inside `INSERT ... SELECT`; the object format comes from the s3() arg);
  the printer's trailing `SETTINGS` must merge with INSERT-level settings (`s3_truncate_on_insert`) since two
  SETTINGS clauses are a syntax error; WITH-leading and UNION-set shapes interact with `PARTITION BY`
  placement, and the tempting `SELECT * FROM (<printed>)` wrap breaks the settings clause (invalid in a
  subquery), forcing settings-hoisting string surgery. Most failures are fail-safe syntax errors — but every
  workaround is string surgery on printer output, which is where the risk concentrates.
- **The parameter channel must survive.** The `%(hogql_val_N)s` placeholders resolve through `sync_execute`'s
  single `escape_param` substitution pass (client-side, the same as all HogQL) — and the s3() arguments now
  ride the same channel. An implementation that hand-inlines any of these values instead reintroduces classic
  injection for every user literal.
- **Privilege amplification is the deepest issue and is not about splicing — but it is narrower than it
  first looks, because `readonly` and GRANTs are independent layers.** An INSERT is a write statement even
  into a table function, so `readonly = 2` is off the table: the writer identity needs `readonly = 0`.
  That does NOT mean it can write ClickHouse: `INSERT` privileges are per-table and `s3()` is gated by its
  own source grant, so the right shape is `readonly = 0` with a grant set of SELECT on the HogQL-reachable
  tables, `GRANT S3 ON *.*`, `CREATE TEMPORARY TABLE`, and **zero** INSERT/ALTER/CREATE/DROP/TRUNCATE on
  any database or table — a user that physically cannot mutate CH state yet can run
  `INSERT INTO FUNCTION s3`. The `readonly` downgrade then costs only defense-in-depth redundancy, not
  authorization. What grants cannot close: `GRANT S3` is source-level, not resource-level — no per-user
  "only this bucket" exists, and a holder can call `s3('https://anywhere/...', key, secret)` with **inline
  attacker credentials**, bypassing our IAM entirely. That residual exfiltration channel is fenced
  server-side, not per-user: `remote_url_allow_hosts` pinned to our storage endpoints (verify it covers
  `s3()` on our CH version), plus confining the write-capable identity to the one materialize code path
  while everything else notebook-shaped stays on a read-only user. With allowlist + minimal grants, the
  blast radius of a hypothetical printer bug shrinks from "exfiltrate anywhere" to "write malformed objects
  into our own lifecycle-TTL'd frames prefix" — integrity, not confidentiality. One tempting dead end,
  preempted: an admin-created `ENGINE = S3` table (plain table-scoped INSERT grant, no S3 source grant, no
  URL in SQL at all) fails on schema — engine tables are fixed-schema and every frame carries its own
  arbitrary column set, which is exactly why `INSERT INTO FUNCTION s3` (per-statement schema inference) is
  the only shape that fits.

The playbook, if/when built: keep the URL out of the statement via a named collection pinned to bucket +
`notebooks/frames/` prefix (only a charset-validated **and** escaped `filename` override in SQL — validation
as policy, escaping as defense in depth; also keeps credentials out of `system.query_log` and error text);
build the INSERT wrapper as a printer-level construct rather than post-hoc string surgery, with a shape-matrix
test (plain / WITH / UNION / settings-suffix) asserting the output parses as exactly one INSERT; preserve
server-side param binding; give the writer identity the minimal-grant shape above (`readonly = 0`, no
table-write grants, S3 source grant) confined to the materialize path; pin `remote_url_allow_hosts` to our
storage endpoints; scope the CH-side credentials write-only to the notebooks prefix. Verdict: the splice is a
contained engineering problem with a known playbook and its own security review, and the table-mutation half
of the amplification is fully closable through grants; what is permanent is the S3-egress capability itself —
containable to our-own-bucket blast radius via the host allowlist, never eliminable — and that residual is
what must be consciously accepted.

**Phase 3 — reuse and convergence.**
Serve repeat materializations of an unchanged upstream query straight from the existing object
(`query_hash` in the key makes this a HEAD check), tighten lifecycle (delete on supersede),
and align the format with the local-DuckDB engine direction so materialized frames double as DuckDB-readable
tables without re-encoding.
**Stale-read hazard — must be solved before the HEAD check ships:** the key has no freshness dimension, so a
bare exists-check would serve a frame materialized before newer events landed. Phase 1 stays fresh only
because it always re-executes and overwrites; cross-run reuse needs an explicit staleness input first — an
age-based reuse rule (the insight cache's target-age precedent), a data watermark, or a time bucket folded
into the key.

## Open questions

- ~~Bucket choice~~ — resolved in phase 1: `OBJECT_STORAGE_BUCKET` under the `notebooks/frames/` prefix
  (a dedicated bucket stays an option if lifecycle/IAM scoping demands it). The lifecycle TTL (~24h) on
  the frames prefix is an infra ticket — a bucket rule, not app code.
- Does cloud CH's instance role already permit writes to the chosen bucket, or does that need infra work
  (batch exports suggests the pattern is established)?
- Presign from SeaweedFS in local dev: verify the presigned host is reachable from the locally-run kernel.
- Whether phase 1 should also carry SQLV2 (hogql-node) first pages, or stay materialization-only
  (recommendation: materialization-only — envelopes are small and the current path serves them well).
