# SQLV2 frame materialization via object storage

Design notes for moving python-node frame materialization off the Redis JSON transport and onto an object-storage handoff.
Status: **proposal** — not started; materialization is deliberately clamped at 50k rows until phase 1 lands.

## Problem

When a python node reads an upstream SQLV2 frame, the sandbox kernel fetches the whole frame through the data plane
(`sql_v2_data_plane.py`), which rides the generic async query manager:

1. A Celery worker executes the HogQL and holds the full result as Python tuples.
2. The worker JSON-renders the entire result into **one Redis string value** (`QueryStatusManager.store_query_status`).
3. On poll, a web worker reads the blob back, parses the JSON, and re-encodes it as an Arrow stream for the sandbox.

The frame is fully copied ~5 times, and the middle copy sits in Redis — the shared cache for the whole deployment.
This transport is implicitly sized by the 50k row ceiling (`MAX_SELECT_RETURNED_ROWS` under the async limit context),
so materialized frames are silently clipped at 50k rows today.
A `LimitContext.NOTEBOOK_MATERIALIZE` context raising the ceiling to 2M (`_MATERIALIZE_ROW_CAP`) was built and then
**deliberately reverted**: without a better payload transport, wide multi-hundred-thousand-row frames stress Redis
(single-threaded, 512MB per-value hard cap, eviction pressure) and the workers that render/parse the JSON.
The clamp is pinned by `test_materialization_request_is_accepted_and_clipped_at_the_row_ceiling` and comes off as
part of phase 1, when the transport can carry what the limit allows.

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
- **Reuse.** Frames are keyed by `query_hash`; an object serves retries, kernel restarts, and unchanged upstream
  queries without re-executing CH. Push has no reuse story — every delivery is a fresh execution.
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
That cache exists to reuse identical insight queries within a TTL; the notebook flow already gets its reuse from
`query_hash`-keyed frames, so we are not duplicating (or blocked on) any platform facility.

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
- **Write-side auth.** CH writes via its instance role (keyless, batch-exports pattern), write-scoped to the
  notebooks prefix. If tighter isolation is wanted later: STS prefix-scoped credentials per run
  (file-download-export pattern).
- **Egress.** The sandbox already makes outbound HTTPS calls to the PostHog API; fetching a presigned S3 URL adds
  one more allowed destination. If Modal egress policy must stay single-destination, the fallback is proxying the
  object through the data-plane endpoint as a bounded stream — bytes transit Django once, but never Redis and
  never as JSON. Keep this as a config switch, not the default.
- **Data at rest is a conscious change.** Query results currently live ≤20 min in Redis; parking them in object
  storage for hours is a retention-policy decision. Bound it with a bucket lifecycle TTL (e.g. 24h) plus
  delete-prefix-on-supersede, and document it.

## Resource governance — not hammering ClickHouse

Materialization is **user-facing** — someone is waiting on their cell — so it belongs on the ONLINE pool with
interactive queries (OFFLINE is where batch exports, usage reports, and cohort calculations run, with
explicitly accepted latency variance and failure rates; a user-waiting query must not queue behind those).
The risk is different: a single materialization can be far more expensive than an insight query, an
**uncapped whale in a pool tuned for bounded queries**. The governance goal is therefore not relocation but
making the whale impossible. Note the cap that matters is not the row count — an insight query with
`LIMIT 50000` can still scan billions of rows; cost is bounded by execution time, bytes read, memory,
and threads.

Layered levers:

- **Per-query SETTINGS (batch-exports recipe).** The staging query carries hard caps, as `internal_stage.py`
  does: `max_execution_time` (modestly above the insight ceiling — frame pulls are legitimately heavier),
  `max_bytes_to_read` (refuse oversized scans up front), `max_memory_usage`,
  `max_bytes_before_external_sort/group_by` (spill to disk), `max_threads`, `min_insert_block_size_bytes`
  (64MiB there). `max_network_bandwidth` can throttle the S3 write rate if needed.
- **Scheduler priority, not pool exile.** CH's `priority` setting lets materialization run ONLINE while
  yielding CPU to interactive queries under genuine contention — dashboards get right-of-way without
  sending notebooks to a worse pool.
- **Tiered row ceiling.** Don't jump 50k → 2M in one step: raise to ~500k with the phase-1 transport,
  watch the footprint, then raise toward `_MATERIALIZE_ROW_CAP`.
- **Admission control above CH.** One operation per notebook is already enforced by the operations logic;
  add a per-team concurrency cap (one concurrent materialization per team initially) and a small dedicated
  Celery queue so global concurrency equals worker count. The refs resolver already minimizes demand —
  only frames the code actually reads are materialized.
- **Dedicated ClickHouse user as the backstop.** The repo already splits traffic across CH users
  (`ClickHouseUser.APP` / `API`), each governed by a server-side settings profile. A materialization user gets
  profile limits, QUOTAs, and `max_concurrent_queries_for_user` — a hard server-enforced ceiling no
  application bug can exceed.
- **Demand elimination.** Phase 3's `query_hash` reuse means an unchanged upstream query never re-executes;
  long-term this is the strongest lever.
- **Escalation path.** If notebooks' share of online capacity becomes meaningful, the router already supports
  product-specific pools (`Workload.ENDPOINTS` is precedent) — a dedicated notebooks pool with online-grade
  latency is the growth answer, decided with data rather than up front.

The flow is already measurable: the data plane tags queries with `Product.NOTEBOOKS`, and the Dagster
query-log exports make its CH footprint analyzable, so the knobs can be tightened with data.

## Phased plan — start basic, improve later

**Phase 0 (current state).** Materialization runs over the existing Redis transport, clipped at 50k rows.
Fine for the current flag-gated audience and frames up to low hundreds of thousands of rows.

**Phase 1 — swap the payload path, minimal moving parts.**
Reintroduce `LimitContext.NOTEBOOK_MATERIALIZE` together with the new transport (tiered ceiling — see
resource governance — landing eventually at `_MATERIALIZE_ROW_CAP`).
When the data-plane task runs under it, the worker streams the CH result
(`output_format="ArrowStream"`, bounded batches — data-modeling pattern) into one object,
stores the **object key** in `QueryStatus` instead of rows, and the status endpoint answers the poll with a
**302 redirect to a presigned URL**.
The kernel's `requests` client follows redirects by default and drops the `Authorization` header on cross-host
redirects, so the existing executor works nearly unchanged and the presigned URL needs no auth.
Keep the Redis path as fallback when object storage is unconfigured (dev parity, degraded mode).

Two decisions locked in for this phase:

- **Format: one plain Arrow IPC stream object per frame — not Delta, not Parquet.** Delta earns its machinery
  when ClickHouse re-reads a versioned, overwritten _table_ (data modeling's case). A frame is an immutable
  write-once blob keyed by `query_hash`, read by pandas — an "update" is a different hash, i.e. a different
  key. The executor already consumes ArrowStream from the data plane, so the sandbox-side change is just
  "read the same bytes from a different host". If size matters, Arrow IPC supports LZ4/ZSTD buffer
  compression without a format change; multi-file partitioning waits for phase 2, if ever.
- **The queue is the throttle.** Under worker streaming, one active task = one running CH query = one upload,
  so the dedicated queue's concurrency directly bounds CH concurrency, worker memory (~100MB × concurrency),
  and S3 parallelism with a single knob — no dedicated CH user needed for v1 (that stays as hardening).
  Throttling moves load in time (backlog), never above the cap; the real amplification risk is impatient
  re-runs, and the async manager's existing `cache_key` dedup (`get_running_query_by_cache_key`) closes it:
  enqueue with `cache_key = query_hash` and duplicate in-flight materializations join the running query
  instead of stacking new ones.

**Phase 2 — let ClickHouse do the writing (only if the data says so).**
Replace the worker-streamed upload with `INSERT INTO FUNCTION s3(...'ArrowStream')` (batch-exports recipe):
the worker's job shrinks to issuing one statement; zero result bytes transit PostHog Python.
Add partitioned files + a manifest for very large frames, and Range-based resume in the executor.

Why phase 1 streams from the worker instead of starting here:

- **Security path.** Phase 1 keeps the whole HogQL runner path (team scoping, property access controls applied
  at print time) untouched — new code only handles the result. The CH-side write must print the guarded SQL
  and splice it into a raw `INSERT ... SELECT` executed outside the runner; batch exports does this safely,
  but over its own known tables, not arbitrary user HogQL. That seam deserves its own review, not a ride-along.
- **Credentials.** Workers already hold object-storage credentials; the CH-side write needs the cluster's IAM
  role extended to the notebooks prefix (see open questions) and local CH → SeaweedFS config.
- **Load placement.** Worker streaming actually puts _less_ work on ClickHouse — CH only executes and streams
  blocks, while Arrow encoding and S3 PUTs burn worker CPU/NIC instead of CH-node resources. The worker's
  drain pace is set by an in-region worker→S3 leg, so CH's result-hold time is near-identical either way.
- **What A buys.** Worker economics at scale (a slot held seconds instead of the stream duration) and no
  double transfer for very large frames. With per-team concurrency ~1 and frames in the tens-to-hundreds of
  MB, neither matters yet — escalate on query-log evidence, and phase 2 may never be needed.

**Phase 3 — reuse and convergence.**
Serve repeat materializations of an unchanged upstream query straight from the existing object
(`query_hash` in the key makes this a HEAD check), tighten lifecycle (delete on supersede),
and align the format with the local-DuckDB engine direction so materialized frames double as DuckDB-readable
tables without re-encoding.

## Open questions

- Bucket choice: reuse `OBJECT_STORAGE_BUCKET` under a `notebooks/` prefix vs a dedicated bucket
  (dedicated is cleaner for lifecycle rules and IAM scoping; more infra to provision).
- Does cloud CH's instance role already permit writes to the chosen bucket, or does that need infra work
  (batch exports suggests the pattern is established)?
- Presign from SeaweedFS in local dev: verify the presigned host is reachable from the locally-run kernel.
- Whether phase 1 should also carry SQLV2 (hogql-node) first pages, or stay materialization-only
  (recommendation: materialization-only — envelopes are small and the current path serves them well).
