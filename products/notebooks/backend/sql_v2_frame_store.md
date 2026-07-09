# SQLV2 frame materialization via object storage

Design notes for moving python-node frame materialization off the Redis JSON transport and onto an object-storage handoff.
Status: **phase 1 shipped** (env-gated by `NOTEBOOKS_FRAME_STORE_ENABLED`, default off) — object delivery at a 500k row tier-1 ceiling (`MAX_SELECT_NOTEBOOK_MATERIALIZE_LIMIT`); the inline path remains as the degraded fallback, still clamped at 50k. Phases 2+ not started.

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
One correction to the sketch below: the kernel's client is `urllib`, not `requests` — urllib re-sends
`Authorization` on redirects, so the client intercepts the 302 and fetches the presigned URL with a fresh,
credential-free request instead of auto-following.
The Redis path stays as fallback when the frame store is disabled or unconfigured (dev parity, degraded mode).

**Phase 2 — let ClickHouse do the writing.**
Replace the worker-streamed upload with `INSERT INTO FUNCTION s3(...'ArrowStream')` (batch-exports recipe):
the worker's job shrinks to issuing one statement; zero result bytes transit PostHog Python.
Add partitioned files + a manifest for very large frames, and Range-based resume in the executor.

**Phase 3 — reuse and convergence.**
Serve repeat materializations of an unchanged upstream query straight from the existing object
(`query_hash` in the key makes this a HEAD check), tighten lifecycle (delete on supersede),
and align the format with the local-DuckDB engine direction so materialized frames double as DuckDB-readable
tables without re-encoding.

## Open questions

- ~~Bucket choice~~ — resolved in phase 1: `OBJECT_STORAGE_BUCKET` under the `notebooks/frames/` prefix
  (a dedicated bucket stays an option if lifecycle/IAM scoping demands it). The lifecycle TTL (~24h) on
  the frames prefix is an infra ticket — a bucket rule, not app code.
- Does cloud CH's instance role already permit writes to the chosen bucket, or does that need infra work
  (batch exports suggests the pattern is established)?
- Presign from SeaweedFS in local dev: verify the presigned host is reachable from the locally-run kernel.
- Whether phase 1 should also carry SQLV2 (hogql-node) first pages, or stay materialization-only
  (recommendation: materialization-only — envelopes are small and the current path serves them well).
