# SQLV2 rollout observability

What you can watch today while rolling out the notebooks SQLV2 frame store, where each signal lives, and what is missing.
Companion to [`sql_v2_frame_store.md`](./sql_v2_frame_store.md) — that doc decides the mechanism, this one decides whether the rollout is going well.

Artifacts:

- [`observability/notebooks-rollout.grafana.json`](../observability/notebooks-rollout.grafana.json) — export of the live Grafana dashboard `notebooks-sqlv2-rollout` (Prometheus/VictoriaMetrics). Its "Transport A/B" row is the flag-on vs flag-off comparison. Its "Temporal queue" row shows the health of the worker queue that every notebook workflow shares with other products. Its "Notebook sandboxes" row counts kernel sandboxes and shows their lifetime from Modal's own metrics.
- [`observability/notebooks-query-log.sql`](../observability/notebooks-query-log.sql) — `query_log_archive` query pack (ClickHouse per-query cost). SQL 9 is the same comparison on the ClickHouse side.
- Notebook `Vs0Gjpqb` in project 2 ("SQLV2 transport benchmark") — the graduated workload to run under each arm.

## The split: two surfaces, and why

Nothing gives you all of this in one place, because the two halves have incompatible storage.

**Prometheus (Grafana)** holds the rollout mechanics: attempt/outcome rates, materialize latency, object size, throttling, HTTP.
It cannot hold per-query ClickHouse cost — scanned bytes per query is unbounded-cardinality data that only makes sense per row, not per series.

**ClickHouse `query_log_archive`** holds the per-query cost: `read_bytes`, `result_bytes`, `result_rows`, `query_duration_ms`, `memory_usage`, `peak_threads_usage`, exception codes.
It is not in Grafana — production ClickHouse holds customer data and there is deliberately no ClickHouse datasource there.
The sanctioned path is the internal Metabase under your own SSO session (the `querying-production-databases-via-metabase` skill).

Grafana dashboards are **not code-managed** in this repo — they are edited in the UI, reachable over Tailscale at `grafana-prod-us` / `grafana-prod-eu` (see `tools/infra-scripts/mcp/README.md`).
The JSON here is an export of the live dashboard, not a provisioned source of truth.
Edit the dashboard in the UI, then export its JSON back here in the same change, so that the copy stays current.

### Attribution is already wired

Both data-plane paths wrap their enqueue in `tags_context(product=Product.NOTEBOOKS, feature=Feature.QUERY, ...)` (`sql_v2_data_plane.py:161,185`), and the tags survive the process hop:
the inline path snapshots them into the Celery task argument (`execute_async.py:343` → `tasks.py:381-383`), and the materialize activity re-establishes them itself (`frame_materialize.py:665`).
So **`lc_product = 'notebooks'` is the single filter that scopes every ClickHouse query**, and `lc_temporal__workflow_type` / `lc_temporal__attempt` come along for free on the materialize path — retries are attributable in ClickHouse.

One caveat: this covers the **SQLV2 data plane**, which is what is being rolled out.
Queries from the classic notebook scene's embedded insights are not covered — `SCENE_TO_TAGS` deliberately maps `Notebook`/`Notebooks` to `None` (`query_tagging.py:168`), letting the inner query kind decide, so those land under `product_analytics` and similar.

### A naming trap

`prometheus_client` appends `_total` to counter sample names.
`Counter("posthog_notebooks_frame_materializations_started")` is scraped as **`posthog_notebooks_frame_materializations_started_total`**.
The dashboard uses the `_total` names; the source code does not have them.

## Coverage against what you asked for

| Want                              | Where                                                                                                  | State                                                           |
| --------------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| Notebook request E2E latency      | `posthog_notebooks_node_run_seconds{node_type,outcome,delivery}` + `notebook node run completed` event | Covered — see "Node-run instrumentation" below                  |
| CH latency for notebook queries   | `query_log_archive.query_duration_ms` (SQL 1)                                                          | Covered                                                         |
| CH scanned bytes                  | `query_log_archive.read_bytes` (SQL 1, 6)                                                              | Covered                                                         |
| CH bytes returned                 | `result_bytes` / `WriteBufferFromS3Bytes` (SQL 4)                                                      | Covered, but mode-dependent — see below                         |
| CH rows returned                  | `result_rows` / `written_rows` (SQL 4)                                                                 | Covered, mode-dependent                                         |
| Overall CH health                 | Existing shared CH Grafana dashboards + SQL 8                                                          | Covered by platform; SQL 8 gives notebooks' share of offline    |
| Throttled queries                 | `posthog_clickhouse_query_concurrency_limit_exceeded_total{limit_name=~"notebooks_materialize_.*"}`    | Covered (rejections only)                                       |
| Parallel queries per team         | Reconstructed from `query_log_archive` (SQL 5)                                                         | Covered by SQL; **no live gauge** — gap 3                       |
| Parallel queries per user         | Same, group by `lc_user_id`                                                                            | Same                                                            |
| Per-notebook / per-node breakdown | `NotebookNodeRun` in Postgres (gap 4)                                                                  | Available in Postgres — runs, node type, status, rough duration |
| E2E latency per transport         | `posthog_notebooks_node_run_seconds{delivery}` + the event's `delivery` property                       | Covered — see "The `delivery` dimension" below                  |
| CH cost per transport             | `query_log_archive` split on `query_kind` (SQL 9)                                                      | Covered                                                         |

"Bytes/rows returned" is mode-dependent and averaging the modes together is wrong:
the streaming path returns a result set (`result_bytes`, `result_rows`), while the CH-writes path is an `INSERT` whose result set is empty and whose delivered bytes show up as `ProfileEvents['WriteBufferFromS3Bytes']` and `written_rows`.
`query_kind` (`Select` vs `Insert`) is what separates them.
The Prometheus `posthog_notebooks_frame_object_bytes` histogram is the mode-independent view of the same thing, but only on the success path.

## Kernel sandbox usage events

Modal's own metrics count notebook sandboxes, but they carry no team, no size, and no price.
Two events from `kernel_sandbox_usage.py` carry those, so product analytics can show sandbox starts, sandbox-hours, and an estimated price per team.

| Event                             | Fires when                                                                                           | Main properties                                                                                                |
| --------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `notebook kernel sandbox started` | The provider returns a new sandbox, before the kernel starts inside it                               | `backend`, `cpu_cores`, `memory_gb`, `compute_preset`, `hourly_price_usd`, `ttl_seconds`, `provision_seconds`  |
| `notebook kernel sandbox ended`   | PostHog stops tracking the sandbox: a stop, a failure, a discard, or the status poll finding it gone | `ended_reason`, `sandbox_still_running`, `tracked_seconds`, `estimated_runtime_seconds`, `estimated_price_usd` |

`KernelRuntime` stores `ttl_expires_at`, the time the provider kills the sandbox at the latest, and `ended_at`.
Several paths can notice the same end, and a conditional update on `ended_at` lets only the first one report it.

Read the estimates with these rules:

- **The price is the rate card, not Modal's charge.** `hourly_price_usd` and `estimated_price_usd` use the rates in `compute_pricing.py`, which set the price shown to users. Docker sandboxes have no price.
- **A sandbox that nothing destroyed costs its full lifetime.** A discard, a kernel that does not answer, or a failed destroy leaves the sandbox running. The event then sets `sandbox_still_running` and runs the estimate to `ttl_expires_at`.
- **A sandbox found gone ends when PostHog finds it, but never after its TTL.** A sandbox that crashed early and was found late counts longer than it ran.
- **A sandbox that dies while nobody watches has no end event** until a later stop, reuse, or status poll notices it.
- **Rows from before these columns existed** have no `ttl_expires_at`, so they report no end event.

## Node-run instrumentation (closes gap 1)

Every terminal transition of a `NotebookNodeRun` — the sandbox callback, the direct-lane finish, dispatch failures, and interrupts — reports once through `sql_v2_metrics.record_node_run_terminal`, emitting three sinks:

- **`posthog_notebooks_node_run_seconds{node_type,outcome,delivery}`** — end-to-end duration, run-row `created_at` to the terminal transition. `outcome` is `done` / `failed` / `interrupted` / `timed_out`; the direct lane's grace-expiry watchdog reports `timed_out`, so an expired query is a bucket, not a user error.
- **`posthog_notebooks_node_run_phase_seconds{phase,node_type}`** — the decomposition, from the run envelope's `timings` dict. Sandbox-reported: `input_wait` (data-plane wait for referenced frames or the display fetch), `download` (presigned frame downloads), `exec` (ipykernel cell), `sandbox_total`. Direct lane, from `QueryStatus`: `queued` (enqueue → Celery pickup), `clickhouse` (pickup → completion).
- **`notebook node run completed`** PostHog event with `duration_seconds`, the phase seconds, `row_count`, `outcome`, `delivery`, `notebook_short_id` — the per-notebook/per-team view Prometheus label cardinality can't hold.

Both histograms also stream into the PostHog Metrics product via their OTLP twins (`posthog/otel_metrics.py`).

### The `delivery` dimension

`delivery` names the transport that actually served a run's rows, and it is what a transport A/B splits on:

| Value              | Meaning                                                                            |
| ------------------ | ---------------------------------------------------------------------------------- |
| `direct`           | Direct lane: ClickHouse to Redis to the UI. The sandbox is never involved.         |
| `inline`           | Sandbox fetch over the inline (Redis) transport, clamped at the async row ceiling. |
| `object_relay`     | Phase 1: a Temporal worker streams ClickHouse rows to object storage.              |
| `object_ch_writes` | Phase 2: ClickHouse writes the object itself via `INSERT INTO FUNCTION s3`.        |
| `none`             | Kernel run that read no ClickHouse-backed frame, so no transport applied.          |
| `mixed`            | One run materialized several inputs and they did not agree on a transport.         |

The data plane resolves the value where it picks a transport (`sql_v2_data_plane.py`) and reports it in the 202 accept body; the sandbox echoes it into the envelope without interpreting it.
That ordering matters: an object request that falls through either gate is labeled `inline`, so a silent fallback lands in the bucket it really used rather than the one the flags asked for.

The value crosses the sandbox boundary, where user code can forge an envelope, so `sql_v2_metrics.DELIVERY_LABEL_VALUES` is the allowlist bounding label cardinality.
Anything outside it collapses to `none`.
Adding a transport means adding it in both `sql_v2.DELIVERY_*` and that allowlist.

Two caveats when reading a comparison:

- `direct` and `none` runs have no transport choice, so including them dilutes the split. The dashboard's A/B panels select `delivery=~"object_relay|object_ch_writes|inline"`.
- The label describes delivery, not the ClickHouse write mode behind it. `query_log_archive.query_kind` (`Select` vs `Insert`) is the authoritative server-side split, and SQL 9 in the query pack uses it.

One deliberate hole: the callback is best-effort, so a kernel-lane run whose sandbox dies without delivering stays RUNNING and contributes **no** sample — the row remains visible in Postgres and the node can be re-run. A periodic reaper that would fail such rows (and record them as `timed_out`) was built and dropped as more complexity than the case warrants; revisit if stranded rows become common.

Still open from the original gap: lost-callback kernel runs (above), the frontend's own poll-to-render latency, and the kernel's presigned _download failure_ modes, which remain observable only as an `input_wait`-heavy failed run (see gap 5).

## Temporal queue health

Every notebook workflow runs on `general-purpose-task-queue`: `notebook-sandbox-cmd-run`, `notebook-frame-materialize`, and `notebook-widget-generate` (`temporal/client.py`).
Other products share that queue and its workers, so their load can delay notebook runs while the notebooks code is healthy.
The dashboard's "Temporal queue" row, under "Node runs", shows that shared health.

| Panel                                        | Metric                                                                                            | Scope       |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------- | ----------- |
| Queue backlog by task type                   | `temporal_cloud_v1_approximate_backlog_count`                                                     | Whole queue |
| Tasks that wait over 1s and 10s for a worker | `temporal_activity_schedule_to_start_latency`, `temporal_workflow_task_schedule_to_start_latency` | Whole queue |
| Sync match ratio                             | `temporal_cloud_v1_poll_success_sync_count` / `temporal_cloud_v1_poll_success_count`              | Whole queue |
| Worker slot usage                            | `temporal_worker_task_slots_used`, `temporal_worker_task_slots_available`                         | Whole queue |
| Notebook activity attempt failures           | `temporal_activity_execution_failed{activity_type=~"notebook-.*"}`                                | Notebooks   |
| Notebook workflow outcomes                   | `temporal_workflow_completed`, `temporal_workflow_failed`                                         | Notebooks   |
| Workflow task failures on the queue          | `temporal_workflow_task_execution_failed`                                                         | Whole queue |

The queue wait matters most for materializations.
`notebook-frame-materialize` has a 10-minute `schedule_to_close_timeout` that includes the wait (`temporal/frame_materialize.py`), so a backlog uses up the materialize deadline.
The worker fleet has a fixed pod count, so a backlog does not add workers.

Three traps when you read or extend the row:

- **Temporal Cloud series are not counters.** Temporal Cloud samples each `temporal_cloud_v1_*` series once a minute as a per-second rate or a gauge. Sum or divide the series directly. `rate()` over them returns wrong values.
- **SDK histograms use milliseconds and coarse buckets.** The worker sets `durations_as_seconds=False` (`posthog/temporal/common/worker.py`). The schedule-to-start buckets are 100, 500, 1000, 5000, 10000, and 100000 ms, so a percentile over them is a guess. The panel shows the share of tasks over a bucket edge instead.
- **No metric measures the queue wait for notebooks only.** The schedule-to-start and workflow task failure series carry `task_queue` but no workflow or activity label. Temporal Cloud has series labeled `temporal_workflow_type`, but it emits them only in minutes with events and has no activity latency per type. Its workflow latency for `notebook-sandbox-cmd-run` also includes the result grace sleep.

## Notebook sandboxes from Modal

Modal exports metrics for each sandbox it runs, and notebook kernels appear there as `app_name="posthog-sandbox-notebook"`, one `container_id` per sandbox.
The dashboard's "Notebook sandboxes" row, under "Temporal queue", reads those series.
They include every notebook sandbox, whatever code path started it, because Modal reports them and not the notebooks code.

| Panel                       | Query                                                                  | Shows                               |
| --------------------------- | ---------------------------------------------------------------------- | ----------------------------------- |
| Notebook sandboxes alive    | `count(modal_container_running_ratio{...})`                            | Sandboxes that run now              |
| Sandboxes in time range     | `count(count_over_time(modal_container_running_ratio{...}[$__range]))` | Distinct sandboxes in the range     |
| Sandbox-hours in time range | `sum(lifetime(modal_container_running_ratio{...}[$__range])) / 3600`   | Total sandbox run time in the range |
| Sandbox lifetime            | `quantile(0.5, lifetime(...))`, `max(lifetime(...))`                   | Median and longest lifetime         |
| Sandbox CPU use             | `modal_cpu_utilization_ratio`                                          | Average and busiest sandbox         |
| Sandbox memory use          | `modal_memory_usage_bytes`                                             | Average and busiest sandbox         |

Four limits when you read or extend the row:

- **`lifetime()` is a MetricsQL function.** It returns the seconds between the first and the last sample of a series, and plain Prometheus does not have it. Modal is scraped once a minute, so each lifetime is up to a minute short.
- **A kernel has a fixed lifetime.** `NOTEBOOK_KERNEL_TTL_SECONDS`, or the notebook's `kernel_idle_timeout_seconds`, becomes the Modal sandbox `timeout`, and use of the kernel does not extend it. Lifetimes that cluster at that limit mean that idle sandboxes wait for the limit.
- **No team, size, or price.** The Modal labels name the app and the container only. The price of a sandbox is its size multiplied by the rates in `compute_pricing.py`.
- **No memory limit.** Memory use divided by `modal_memory_utilization_ratio` does not give a usable limit, so the row does not chart that series.

## Gaps — suggested follow-ups

Ordered by how much they'd hurt during a rollout.

### 1. ~~No E2E latency for a notebook query~~ — closed by the node-run instrumentation above

Shipped — see "Node-run instrumentation" above for the metric names; the lost-callback caveat there is the one remaining sliver.

### 2. Success-only histograms → add an `outcome` label

The existing `frame_materialize_seconds`, `frame_object_bytes`, and `frame_clickhouse_seconds` are observed only on the success path (`frame_materialize.py:877-883`).
A materialization that dies at the 10-minute deadline contributes **no** sample, so the histograms are survivorship-biased exactly when things are going worst.

Suggested: observe duration (and partial size) on the failure branches too, carrying the same `outcome` label as gap 1. One-line change per exit path.
Partially mitigated: the node-run histogram sees every outcome, so a dying materialization now shows up as a slow `failed`/`timed_out` _run_ — but the frame-level histograms themselves are still success-only.

### 3. No in-flight gauge for the concurrency slots

The Redis sorted set holds current occupancy (`ZCARD`), but nothing samples it.
You can see **rejections** after the fact and nothing else, so "are we near the global 10?" is unanswerable until you're already over.
SQL 5 reconstructs true concurrency from `query_log_archive`, but that's forensics, not a dashboard.

Suggested: a periodically-sampled gauge `posthog_notebooks_materialize_slots_in_use{scope}` from the limiter keys.

### 4. Node- and notebook-level breakdowns — from Postgres, not CH tags

Per-notebook and per-node breakdowns (runs per notebook, busiest notebooks, failure rate by node type, nodes per notebook) come from **`NotebookNodeRun`** (`posthog_notebooknoderun`), not from a ClickHouse tag.
Tagging queries with `notebook_short_id` was considered and rejected — it is unbounded-cardinality label data, and it would miss the `python`/`duckdb` runs that never touch ClickHouse.

The table already has everything: `notebook_id`, `node_id`, `node_type` (`hogql`/`python`/`duckdb`), `user_id`, `status` (`running`/`done`/`failed`/`interrupted`), and `created_at`/`updated_at` (so `updated_at - created_at` is a rough per-run duration).
It is indexed on `(team, notebook, node_id)`, so these are plain ORM aggregations.
This is the source for a PostHog/Metabase notebook-usage view; ClickHouse `query_log_archive` stays the source for per-query _cost_, joined on `lc_client_query_id` when a row-level correlation is needed.

### 5. `frame_store.py` is entirely uninstrumented

No counter or timer on any object-store operation. Suggested instrumentation, each failure counter split by a `reason` label because the causes map to different infra problems:

- **`write_stream`** — upload-duration histogram + failure counter (`ObjectStorageError`). The phase-1 worker→S3 leg; today only inferred indirectly from the relay split, and a failed upload has no signal.
- **`stat_frame`** — failure counter split `reason="not_stored"` (HEAD is None — a silent no-op write by an `UnavailableStorage` client, i.e. object storage misconfigured) vs `reason="predates_write"` (the CH-writes freshness guard firing — endpoint/bucket skew, CH wrote where the app can't read). "Storage down" vs "storage misrouted" — worth telling apart at a glance.
- **`presign_get`** — mint counter + failure counter split `reason="prefix_mismatch"` (a key outside the team prefix — the tenant-isolation backstop firing, so any nonzero is security-relevant) vs `reason="presign_failed"` (empty URL — storage/config).
- **`delete_frame`** — a counter. A rising delete rate is a leading indicator that corrupt objects are being produced upstream (mid-stream tears, or oversize objects failing the post-write cap).

What this **cannot** see, and it's the riskiest leg: the kernel's actual _download_ of the presigned URL.
The server mints the URL and never learns whether the fetch succeeded — and that fetch is the documented rollout hazard (`OBJECT_STORAGE_PUBLIC_ENDPOINT` must resolve _from the sandbox's network_).
Observing it needs a kernel-side signal reported back, or the proxy-through-Django fallback (which would put the bytes on a meterable path) — track that as its own follow-up rather than pretending server-side metrics close it.

### 6. HogQL timings are computed and thrown away

`kernel_runtime.py:566-567` deletes the `timings` key from the HogQL response before returning it to the sandbox.
Per-stage HogQL timings exist and are discarded — cheap to log or record.
Partially closed: the direct lane now records `queued`/`clickhouse` phases from `QueryStatus` (see the node-run instrumentation); the HogQL executor's own per-stage breakdown is still discarded.

### 7. No tracing

No OpenTelemetry/Sentry spans anywhere in the product.
Nothing links API request → Temporal workflow → ClickHouse → object store → kernel poll → callback.
`client_query_id` is the only correlation id and it does not reach the frontend or the callback.
Not a rollout blocker, but it is why gap 1 is awkward to close cleanly.

## Before you trust the dashboard

- **Verify the `view` label values** on the two HTTP panels with `list_prometheus_label_values`. The data-plane paths have no `name=` in `urls.py`, so Django derives the view name and the regex in the panel is a guess.
- **Confirm the notebooks metrics are being scraped at all.** They are defined in the Temporal worker process (`frame_materialize.py`); the general-purpose worker fleet's `/metrics` endpoint must be scraped by vmagent for any of the frame panels to have data.
- The dashboard is import-only. Grafana here is not provisioned from git, so re-importing overwrites UI edits. Export the live dashboard and compare it with the JSON here before you import.
