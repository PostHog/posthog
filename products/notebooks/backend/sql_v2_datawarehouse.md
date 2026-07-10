# SQLV2 and the Data Warehouse

How a notebook reads a customer's connected Data Warehouse (Stripe, Postgres, S3, BigQuery, ...) through the SQLV2 data plane, why it already works on the inline path, and the two access-control seams that need care as the frame store lands.

Companion to `sql_v2_kernel_architecture.md`, `sql_v2_result_delivery.md`, and `sql_v2_frame_store.md`.

## TL;DR

- A connected warehouse is not a separate query engine. Each source syncs to S3 (Delta/Parquet), producing a `DataWarehouseTable` row that registers into the per-team HogQL `Database` as a table. `SELECT * FROM stripe_customers` resolves there and prints to a ClickHouse `s3()` / `s3Cluster()` / `deltaLake()` table function.
- The SQLV2 data plane already reaches warehouse data. It enqueues on the same async query manager the SQL editor and insights use, and it already passes the querying user, so per-user warehouse access control is preserved identically to the SQL editor on the inline path.
- What is left is not "make DW work". It is two seams: threading the real user through the frame-store materialize activity, and deciding the run-as principal for agent/MCP notebooks (which currently mint a null user).

## How DW querying works

**Physical layout.** A connected source is an `ExternalDataSource`; each syncable stream is an `ExternalDataSchema` that writes into S3 as Delta Lake / Parquet, producing a `DataWarehouseTable` (`products/warehouse_sources/backend/models/table.py`) recording `url_pattern`, `format` (`Delta` / `DeltaS3Wrapper` / `Parquet` / ...), `credential`, and ClickHouse column types. Direct-query sources (`AccessMethod.DIRECT`: Postgres/MySQL/Snowflake) instead read the customer's live DB.

**HogQL resolution.** When the per-team `Database` is built, `Database.create_for(...)` iterates warehouse tables and calls `DataWarehouseTable.hogql_definition()`, registering each as a `TableNode` (`posthog/hogql/database/database.py`, `_build_from_sources`). The resolver then sees warehouse tables next to `events` and `persons`.

**Physical read.** The ClickHouse printer calls `S3Table.to_printed_clickhouse()` -> `build_function_call()` (`posthog/hogql/database/s3_table.py`), emitting `s3(url, key, secret, format, structure)`, or `s3Cluster('posthog', ...)` past 1 GiB, or `deltaLake(...)`. Credentials are bound as sensitive params, never string-interpolated. ClickHouse reads Parquet/Delta straight from S3.

**Shared spine.** Every warehouse surface funnels into one path: build a `HogQLQuery` -> `process_query_model` -> `HogQLQueryRunner` compiles against the `Database` -> heavy queries go async via `enqueue_process_query_task` -> `process_query_task` on the `ANALYTICS_QUERIES` Celery queue. The SQL editor, insights (`DataWarehouseNode`), saved views (`DataWarehouseSavedQuery`), and the SQLV2 data plane are all producers into this one spine.

**DuckLake.** Real and actively developed (`posthog/ducklake/`, per-org duckgres servers, copy workflows) but currently a shadow / rollout path validated against ClickHouse, not the serving path. A warehouse HogQL node executes on ClickHouse `s3()` today. Because DW tables live in the same HogQL `Database`, if/when DuckLake becomes the serving path the data plane inherits it for free. We do not build against it now.

## Access control is preserved on the async path

The Celery worker re-hydrates the user from the serialized id and rebuilds the access-control context from `User` + `Team`:

- Worker re-loads the user outside the request cycle: `posthog/clickhouse/client/execute_async.py` (`execute_process_query`) does `User.objects.get(pk=user_id)`, then passes it into `process_query_dict`, same as the sync API path.
- `UserAccessControl(user, team)` is derived from that user and threaded into `Database.create_for`.
- Warehouse tables are stripped at Database-build time by `_is_warehouse_table_denied` (`posthog/hogql/database/database.py`): allowed only if `is_organization_admin or check_access_level_for_object(table, "viewer")`. Views have `_is_warehouse_view_denied`. Even if `user_access_control` is passed as `None`, it is reconstructed from `user` + `team`, so passing the `User` alone is sufficient.

**The data plane already passes the user.** `products/notebooks/backend/sql_v2_data_plane.py` sends `user_id=user.id if user else None` into `enqueue_process_query_task`. A warehouse `SELECT` through the data plane gets the same per-user table filtering the SQL editor gets. Nothing to change on the inline path.

### Three load-bearing rules

1. **Fail closed on `user=None`.** A null `user_id` makes `_is_warehouse_table_denied` deny every warehouse table. Events and persons still work (system tables are not warehouse-denied), so the symptom is a warehouse-only "table not found".
2. **Never wrap the principal as `SyntheticUser` / project secret key.** That sets `bypass_warehouse_access_control=True` and skips DW access control entirely. Pass a real `User`.
3. **The physical strip is flag-gated** by `hogql-warehouse-access-control` per team. Off means tables are not filtered at build time on any path, so the data plane matches the SQL editor either way.

## Seam 1: the frame-store materialize activity must thread the user

The frame-store materialize activity (`sql_v2_frame_store.md`) is the path a Python/DuckDB node takes to pull a full frame, including a warehouse table. It prints HogQL to ClickHouse SQL through `HogQLQueryExecutor` and streams the result to object storage.

`HogQLQueryExecutor` (`posthog/hogql/query.py`) applies team scoping and property access control from `team` alone, but warehouse table access control needs the real `User`. The executor takes `user: Optional[User]` and threads it into `Database.create_for(user=...)`. `generate_clickhouse_sql()` then returns the compiled CH SQL + context with warehouse tables already filtered.

The requirement: reconstruct `User.objects.filter(id=user_id).first()` from the data-plane token's `user_id` and pass `user=` into `HogQLQueryExecutor`. Do not set `bypass_warehouse_access_control`. Do not pass a synthetic principal. Fail closed and loud if `user_id` is null. Without this, every DW-backed frame materialization fails closed exactly where DW matters most, and the failure is silent (a Stripe query looks like a missing table).

## Seam 2: the run-as principal for agent/MCP notebooks

The data-plane token mint sets `user_id = user.id if isinstance(user, User) else None`, so token-user / MCP-created notebooks currently mint a null `user_id`. Combined with the fail-closed rule above, that makes warehouse tables invisible to agent-run notebooks by construction. Resolving this means baking a real run-as `User` id into the data-plane token at dispatch. An org-admin service user would see all DW tables, which is almost certainly too broad, so the notebook creator or an explicit run-as user is the safer default.

## Browsing DW schemas

Schema browsing (listing events, persons, warehouse tables, and saved views for a notebook) should reuse the `DatabaseSchemaQuery` query runner that powers the SQL editor sidebar. It serializes the full HogQL `Database` with the same `UserAccessControl` filtering, so the browse view shows only tables the user can actually query. A hand-rolled catalog risks showing tables that then fail closed at query time; the browse view and the query path must share one access snapshot.

## Scale notes for DW

- `s3()` / `s3Cluster()` reads are the cost. Past 1 GiB the read escalates to `s3Cluster` across the whole cluster. For materialization, size `max_bytes_to_read` as the real governor, not just row count. A 2M-row events cap and a 2M-row full-parquet-scan cap are very different byte volumes.
- Direct-query sources hit the customer's live DB. Latency and reliability are theirs, and some CH SETTINGS do not pass through. Give `max_execution_time` and the kernel poll budget headroom, and surface a clean timeout rather than a hung cell.
- The shared concurrency limiter holds slots longer for DW (WAN + S3), so effective throughput per slot is lower than for events. Model this before raising the row tier.
