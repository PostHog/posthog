# DuckLake copy workflow configuration

## DuckgresServer retirement telemetry

ORM access to `DuckgresServer` emits the counter
`warehouse.duckgres.server.model.access`. It has five bounded attributes: `operation`
(`read`, `create`, `update`, or `delete`), the immediate `accessor_module` and
`accessor_function`, and the meaningful outer `caller_module` and `caller_function`.
The outer caller skips shared managed-warehouse configuration gateways so the result
identifies the business workflow that still depends on the model. Caller names are
limited to 160 characters. The metric deliberately excludes model fields,
organization identifiers, connection details, and other customer data.

Use the PostHog Metrics SQL editor to find active callers over a representative
period:

```sql
SELECT
    attributes['operation'] AS operation,
    attributes['accessor_module'] AS accessor_module,
    attributes['accessor_function'] AS accessor_function,
    attributes['caller_module'] AS caller_module,
    attributes['caller_function'] AS caller_function,
    sum(value) AS accesses
FROM posthog.metrics
WHERE metric_name = 'warehouse.duckgres.server.model.access'
    AND metric_type = 'counter'
    AND aggregation_temporality = 'delta'
    AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY operation, accessor_module, accessor_function, caller_module, caller_function
ORDER BY accesses DESC
```

Reads are recorded through the model's default `objects` manager when a normal
queryset is evaluated, or when `get`, `count`, `exists`, or `iterator` executes.
Re-evaluating the same cached queryset does not emit another access. Normal model
saves and deletes and queryset updates and deletes are also recorded once per ORM
operation. Normal `async for` queryset evaluation uses `_fetch_all` and is recorded,
although attribution may become `unknown` across its thread boundary.

This is deliberately a probe of the default manager rather than proof of all model
use. It does not observe reads through `_base_manager`, reverse one-to-one access,
`select_related` or `prefetch_related` hydration, raw SQL, `raw()`/`RawQuerySet`, or
`.aiterator()`. `bulk_create` bypasses the save signals. These paths can construct or
write `DuckgresServer` instances without incrementing the counter.

Before using an empty result as retirement evidence, confirm that another known
metric from every relevant service is reaching the same Metrics project. Observe
for at least one complete schedule window, remove the remaining callers, then
repeat the query. An empty result cannot prove that the model is unused: a final
static search for the model, its table, and reverse relation is mandatory before
removal because telemetry cannot discover dormant or uninstrumented code paths.

The DuckLake copy and registration workflows write data into a DuckLake-managed S3 bucket. There are three workflows:

1. **Data Modeling** (`ducklake-copy.data-modeling`) - copies materialized saved query outputs
2. **Data Imports** (`ducklake-copy.data-imports`) - copies external data source imports (Stripe, Hubspot, etc.)
3. **Data Import Registration** (`ducklake-register.data-imports`) - copies and registers prepared Parquet files from completed imports

The workflows share the same infrastructure and configuration. Workers running these workflows must be configured explicitly; otherwise copies will fail before they even reach the first activity.

## Environment variables

The workflow obtains its DuckLake configuration from the following environment variables:

- `DUCKLAKE_RDS_HOST` - Postgres catalog host
- `DUCKLAKE_RDS_PORT` - Postgres catalog port
- `DUCKLAKE_RDS_DATABASE` - Postgres catalog database name
- `DUCKLAKE_RDS_USERNAME` - Postgres catalog username
- `DUCKLAKE_RDS_PASSWORD` - Postgres catalog password
- `DUCKLAKE_BUCKET` - S3 bucket for DuckLake data
- `DUCKLAKE_BUCKET_REGION` - AWS region for the S3 bucket
- `DUCKLAKE_S3_ACCESS_KEY` - S3 access key (optional, for local dev; production uses IRSA)
- `DUCKLAKE_S3_SECRET_KEY` - S3 secret key (optional, for local dev; production uses IRSA)

`bin/start` exports sensible defaults for local development, so you usually get a working DuckLake setup just by running the dev script. Temporal workers in staging/production must set these variables directly in their process environment (or via Helm/k8s secrets). If you need to run the workflow against a bespoke DuckLake deployment, override the environment variables before starting the worker—no code changes are required.

For local dev the defaults are:

- `DUCKLAKE_RDS_HOST=localhost`
- `DUCKLAKE_RDS_PORT=5432`
- `DUCKLAKE_RDS_DATABASE=ducklake`
- `DUCKLAKE_RDS_USERNAME=posthog`
- `DUCKLAKE_RDS_PASSWORD=posthog`
- `DUCKLAKE_BUCKET=ducklake-dev`
- `DUCKLAKE_BUCKET_REGION=us-east-1`
- `DUCKLAKE_S3_ACCESS_KEY=object_storage_root_user`
- `DUCKLAKE_S3_SECRET_KEY=object_storage_root_password`
- `DUCKGRES_HOST=localhost`
- `DUCKGRES_PORT=15432`
- `DUCKGRES_DATABASE=ducklake`
- `DUCKGRES_USERNAME=posthog`
- `DUCKGRES_PASSWORD=posthog`

## Self-managed object storage reads

The DuckLake query path can read credentialed self-managed Parquet tables directly from S3-compatible object storage. HogQL compiles these tables to DuckDB's `read_parquet` function. Before each query, the Duckgres client creates a temporary secret from the table's `DataWarehouseCredential`. Secrets cover only the tables the compiled query's schema still exposes after warehouse access control, so a query cannot borrow credentials from a table it may not read. Each secret is scoped to the table's object path and disappears when the connection closes. Credentials use query parameters and never appear in the compiled SQL.

Supported URL forms include AWS S3, Google Cloud Storage with HMAC credentials, Cloudflare R2, and other path-style S3-compatible HTTPS endpoints. Local HTTP endpoints such as SeaweedFS are also supported. AWS regions are inferred from regional endpoints. Other providers use `us-east-1` for S3 request signing.

This path currently supports Parquet only. Support for Azure Blob Storage, CSV, JSON, and Delta will follow. Until then, these sources continue to use the existing non-DuckLake query path.

## Feature flag gating

Each workflow evaluates a feature flag through `feature_enabled`. Create or update the appropriate flag locally. The copy flags target the project, while `data-warehouse-scene` targets the organization. Otherwise, the workflow will be skipped even if the rest of the configuration is correct.

| Workflow                 | Feature Flag                           |
| ------------------------ | -------------------------------------- |
| Data Modeling            | `ducklake-data-modeling-copy-workflow` |
| Data Imports             | `ducklake-data-imports-copy-workflow`  |
| Data Import Registration | `data-warehouse-scene`                 |

The data-import copy and registration paths target the same stable DuckLake table. An organization with `data-warehouse-scene` enabled runs registration. Disable `ducklake-data-imports-copy-workflow` for its projects to avoid both paths applying the same import. If both run, the last atomic table swap wins.

## Data Ops workflow status

The copy and registration workflows both write their lifecycle to `ManagedWarehouseSourceJob`. Each row identifies the project, source schema, external data job, workflow type, and workflow attempt. The supported states are running, completed, failed, skipped, and stale.

The Data Ops overview reads the latest workflow attempt for each source schema from this shared model. It also reads the most recent completed attempt separately, so a later failed or stale attempt does not erase when data was last applied successfully. The Duckgres consumer sink state is not used for source readiness.

## Target bucket layout

Every copy is written to a deterministic schema inside DuckLake. Each workflow namespaces its data under a workflow-specific schema:

### Data Modeling

- **Schema**: `posthog_data_modeling_team_<team_id>`
- **Table**: `<model_label>` (derived from saved query name)
- **Example**: `ducklake.posthog_data_modeling_team_123.my_saved_query`

### Data Imports and Data Import Registration

- **Schema**: `posthog_data_imports_team_<team_id>`
- **Table**: a physical name derived from the organization's naming version
- **Example**: `ducklake.posthog_data_imports_team_123.stripe_prod_invoices`
- **Registered files**: `s3://<ducklake-bucket>/<ducklake-schema>/<ducklake-table>/_imports/<source-schema-id>/<job-id>/<generation-token>/<prepared-relative-path>`

Duckgres stores a table-naming version on the organization. Organizations that existed when versioning was introduced keep the batch sink's snake-case format, such as `tik_tok_ads_ad_report`. New organizations use the copy workflow format, such as `tiktokads_ad_report`. Copy, registration, the batch sink, and query binding derive the same physical name from that organization-level policy. Do not change the policy after an organization has written data unless the underlying tables are migrated at the same time.

Each completed import creates a timestamped prepared Parquet snapshot in the data warehouse bucket. The registration workflow copies those objects directly into the DuckLake bucket, preserving Hive partition directories. Schema creation still uses one recursive Parquet glob. File registration calls `ducklake_add_data_files` in batches of copied object paths so each catalog transaction stays short. The workflow verifies the shadow table's row count, then swaps it into the stable table name through the Duckgres PostgreSQL connection. Publication uses one short transaction that renames the current table to an attempt-owned backup and the verified shadow to the stable name. A mismatch never enters the publication transaction, so the previous table remains live. The backup is dropped after publication. Each prepared generation gets its own object prefix. The workflow id is one per schema, so a later start is skipped while a run is in flight. The next import after that run finishes can start.

A run that is no longer the latest prepared snapshot still publishes after a successful verify, so a long registration can land instead of losing the race to the next snapshot. A later run replaces it. Publication is skipped only when a newer snapshot has already been published, so the live table does not move backward. Prepare still skips a snapshot that is already obsolete before any copy or catalog work starts.

The registered objects are permanent DuckLake data files, not staging files. Old generations remain reachable through DuckLake snapshots until snapshot expiration and old-file cleanup make them eligible for object deletion. Choose the bucket lifecycle policy with that retention behavior in mind.

## Required permissions

Temporal workers must be able to:

1. Read from the existing PostHog object storage bucket where Delta tables live (already required for the modeling pipeline).
2. Read/write/delete within the DuckLake data bucket referenced by `DUCKLAKE_BUCKET`.

For AWS S3, grant the worker role at least `s3:ListBucket`, `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on the DuckLake bucket/prefix (plus `s3:CreateBucket` for local auto-creation). Local development uses the configured SeaweedFS object store and the `DUCKLAKE_*` access keys.

## Local testing (dev)

Follow these checklists to exercise the DuckLake copy workflows on a local checkout.

### Testing Data Modeling workflow

1. **Start the dev stack**
   Run `hogli start` (or `bin/start`) so Postgres, SeaweedFS, Temporal, and all DuckLake defaults are up. Make sure the `ducklake-data-modeling-copy-workflow` feature flag is enabled for the team you plan to use.

2. **Trigger a model materialization from the app**
   In the PostHog UI, open Data Warehouse → Views, pick (or create) a view, open the Materialization section, enable it if needed, and click **Sync now**. This schedules the `data-modeling-run` workflow for that team/view.

3. **Observe the data-modeling workflow**
   Visit the Temporal UI at `http://localhost:8081/namespaces/default/workflows` and confirm a `data-modeling-run` execution appears. Wait for it to finish successfully.

4. **Verify the DuckLake copy workflow runs**
   Once the modeling workflow completes it automatically starts `ducklake-copy.data-modeling` as a child run. You should see it listed in the same Temporal UI; wait for the run to complete.

5. **Query the new DuckLake table**
   The copy activity creates a table at `ducklake.posthog_data_modeling_team_<team_id>.<model_label>`. From any DuckDB shell you can inspect it, for example:

   ```sql
   duckdb -c "
     INSTALL ducklake;
     LOAD ducklake;
     SET s3_endpoint='localhost:19000';
     SET s3_use_ssl=false;
     SET s3_access_key_id='object_storage_root_user';
     SET s3_secret_access_key='object_storage_root_password';
     SET s3_url_style='path';

     ATTACH 'ducklake:postgres:dbname=ducklake host=localhost user=posthog password=posthog'
       AS ducklake (DATA_PATH 's3://ducklake-dev/');

     -- Discover available schemas
     SELECT * FROM information_schema.schemata WHERE catalog_name = 'ducklake';

     -- List tables in the ducklake catalog
     SELECT table_schema, table_name FROM information_schema.tables WHERE table_catalog = 'ducklake';

     -- Query a specific table
     SELECT * FROM ducklake.posthog_data_modeling_team_${TEAM_ID}.${MODEL_LABEL} LIMIT 10;
   "
   ```

### Testing Data Imports workflows

1. **Start the dev stack**
   Run `hogli start` (or `bin/start`) so Postgres, Duckgres, SeaweedFS, Temporal, and all DuckLake defaults are up. Enable `data-warehouse-scene` for the prepared-Parquet path. Enable `ducklake-data-imports-copy-workflow` only when testing the existing Delta-copy path; both paths run when both flags are enabled.

2. **Trigger a data import sync from the app**
   In the PostHog UI, open Data Warehouse → Sources, connect a source (e.g., Stripe, Hubspot), select the schemas to sync, and click **Sync**. This schedules the `external-data-job` workflow.

3. **Observe the external-data-job workflow**
   Visit the Temporal UI at `http://localhost:8081/namespaces/default/workflows` and confirm an `external-data-job` execution appears. Wait for it to finish successfully.

4. **Verify the selected DuckLake workflow runs**
   Once the import workflow completes it starts both independently gated child workflows. The enabled path appears as either `ducklake-copy.data-imports` or `ducklake-register.data-imports`; the disabled path exits after its gate activity.

5. **Query the new DuckLake table**
   The copy activity creates a table at `ducklake.posthog_data_imports_team_<team_id>.<source_type>_<prefix>_<table_name>`. From any DuckDB shell you can inspect it:

   ```sql
   duckdb -c "
     INSTALL ducklake;
     LOAD ducklake;
     SET s3_endpoint='localhost:19000';
     SET s3_use_ssl=false;
     SET s3_access_key_id='object_storage_root_user';
     SET s3_secret_access_key='object_storage_root_password';
     SET s3_url_style='path';

     ATTACH 'ducklake:postgres:dbname=ducklake host=localhost user=posthog password=posthog'
       AS ducklake (DATA_PATH 's3://ducklake-dev/');

     -- Discover available schemas
     SELECT * FROM information_schema.schemata WHERE catalog_name = 'ducklake';

     -- List tables in the ducklake catalog
     SELECT table_schema, table_name FROM information_schema.tables WHERE table_catalog = 'ducklake';

     -- Query a specific table
     SELECT * FROM ducklake.posthog_data_imports_team_${TEAM_ID}.${SOURCE_TYPE}_${PREFIX}_${TABLE_NAME} LIMIT 10;
   "
   ```
