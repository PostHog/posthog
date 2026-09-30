"""Delivering a run's batches to BigQuery.

BigQuery loads Arrow natively, so batches are loaded as parquet rather than turned into INSERT
statements. The shape is otherwise the same as the other SQL destinations:

- A full refresh loads into a per-run staging table and copies it over the live table on the
  final batch. `WRITE_TRUNCATE` on a copy job is atomic, so readers never see a partial run.
- An incremental run loads the batch into a temporary table and runs `MERGE` on the schema's
  primary keys, which is what makes re-applying a batch harmless.
"""

from __future__ import annotations

import io
import hashlib
from collections.abc import AsyncIterator
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import async_to_sync, sync_to_async
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from posthog.models.integration.google_cloud import GoogleCloudServiceAccountIntegration

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryClient,
    verify_impersonated_service_account_ownership,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.merge_dedup import (
    dedupe_merge_source,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.run_markers import (
    BATCH_INDEX_COLUMN,
    run_scope,
    stamp_batch_index,
)

# Proof this writer created a table, so a sync never truncates, merges into or appends to one
# the customer already had. `table_name` comes from the source's resource name, which a custom
# source manifest controls, so without a marker any table sharing that name is fair game.
#
# Stored as a BigQuery label rather than a comment: labels survive `copy_table`'s WRITE_TRUNCATE
# (the destination table's own metadata is left alone, only its data is replaced), which is what
# lets `finalize_run` check the live table's label after the swap that publishes it.
_OWNERSHIP_LABEL_KEY = "posthog_sync_schema"

# The run that last published this table, carried beside the ownership label. A redelivered
# final batch reads it to tell "this run already published" from "this run never started";
# without it the replay rebuilds a staging table out of that one batch and copies it over the
# complete table.
_PUBLISHED_RUN_LABEL_KEY = "posthog_sync_run"


class BigQueryDestinationConfigurationError(ValueError):
    """The destination's config cannot produce a valid BigQuery write."""


class UnrelatedTableExistsError(RuntimeError):
    """A sync would have overwritten, merged into or appended to a table it never created."""


def staging_table_name(ctx: DestinationRunContext) -> str:
    return f"{ctx.table_name}__ph_stage_{run_scope(ctx.run_uuid)}"


def _backtick(name: str) -> str:
    # BigQuery quoted identifiers cannot contain a backtick at all (there is no escape
    # sequence for one inside backticks), so a name carrying one is rejected rather than
    # silently stripped, which could otherwise let two differently-named source columns
    # collide on the same destination column.
    if "`" in name:
        raise ValueError(f"BigQuery identifier {name!r} cannot contain a backtick")
    return f"`{name}`"


class BigQueryDestinationWriter:
    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        config = ctx.config or {}
        self._dataset = config.get("dataset") or config.get("dataset_id") or ""
        self._client: bigquery.Client | None = None
        self._project: str = config.get("project") or config.get("project_id") or ""

        self._validate_config()

    def _validate_config(self) -> None:
        """Reject a config that cannot write, before a batch is read.

        Left to fail later, a missing dataset fails inside a load job, hundreds of MiB into the
        batch, and reports itself as a table-reference error rather than as missing config.
        """
        if not self._dataset:
            raise BigQueryDestinationConfigurationError(
                f"Destination {self._ctx.destination_name} has no dataset. Add a dataset to the destination, "
                "then run the sync again."
            )

    def _get_client(self) -> bigquery.Client:
        """The underlying BigQuery client, resolved the way the batch export resolves it.

        `from_service_account_integration` also covers the case where the integration holds no
        key and PostHog impersonates the service account instead, which hand-building the
        credentials from `sensitive_config` does not.
        """
        if self._client is not None:
            return self._client

        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        from posthog.models.integration import Integration  # noqa: PLC0415 — avoids a model import cycle

        integration = Integration.objects.get(id=self._ctx.integration_id, team_id=self._ctx.team_id)
        google_cloud_integration = GoogleCloudServiceAccountIntegration(integration)
        if not google_cloud_integration.has_key():
            # Keyless means PostHog impersonates the team's service account instead of holding
            # its credentials. Confirm the team actually owns that account first — otherwise a
            # team that merely knows another org's service account email could have PostHog
            # impersonate it, the confused-deputy problem batch exports guards against at the
            # same call site.
            async_to_sync(verify_impersonated_service_account_ownership)(
                google_cloud_integration.service_account_email, self._ctx.team_id
            )
        client = BigQueryClient.from_service_account_integration(google_cloud_integration)

        self._client = client.sync_client
        self._project = self._project or self._client.project or ""
        return self._client

    def _table_ref(self, table: str) -> str:
        return f"{self._project}.{self._dataset}.{table}"

    def _quoted_table(self, table: str) -> str:
        return _backtick(self._table_ref(table))

    def _schema_label(self) -> str:
        # BigQuery labels only allow lowercase letters, digits, underscores and dashes, at most
        # 63 bytes, and `schema_id` carries no such guarantee. Hashing sidesteps that validation
        # entirely while staying specific to the schema that owns the table. A hex digest is
        # already within the allowed character set, but a sha256 one is 64 characters long — one
        # over the limit — so it is truncated; 63 hex characters carries far more than enough
        # entropy left to stay collision-free for this many schemas.
        return hashlib.sha256(self._ctx.schema_id.encode()).hexdigest()[:63]

    def _run_label(self) -> str:
        # Hashed for the same reason as `_schema_label`: `run_uuid` carries no guarantee that it
        # only holds characters a BigQuery label value accepts.
        return hashlib.sha256(self._ctx.run_uuid.encode()).hexdigest()[:63]

    def _check_owned_or_absent(self, client: bigquery.Client, table_ref: str, action: str) -> bool:
        """Whether `table_ref` does not exist yet.

        Raises if it exists and was not created by this schema's sync, rather than silently
        truncating, merging into or appending to a table that predates this sync and merely
        happens to share the generated name.
        """
        try:
            existing = client.get_table(table_ref)
        except NotFound:
            return True
        if (existing.labels or {}).get(_OWNERSHIP_LABEL_KEY) != self._schema_label():
            raise UnrelatedTableExistsError(
                f"{table_ref} already exists and was not created by this sync; refusing to {action}."
            )
        return False

    def _set_labels(self, client: bigquery.Client, table_ref: str, labels: dict[str, str]) -> None:
        existing = client.get_table(table_ref)
        existing.labels = {**(existing.labels or {}), **labels}
        client.update_table(existing, ["labels"])

    def _mark_owned(self, client: bigquery.Client, table_ref: str) -> None:
        self._set_labels(client, table_ref, {_OWNERSHIP_LABEL_KEY: self._schema_label()})

    def _mark_published(self, client: bigquery.Client, table_ref: str) -> None:
        self._set_labels(
            client,
            table_ref,
            {_OWNERSHIP_LABEL_KEY: self._schema_label(), _PUBLISHED_RUN_LABEL_KEY: self._run_label()},
        )

    def _already_published(self, ctx: DestinationRunContext) -> bool:
        """Whether this run already copied its staging table over the live table."""
        client = self._get_client()
        try:
            client.get_table(self._table_ref(staging_table_name(ctx)))
        except NotFound:
            pass
        else:
            return False

        try:
            live = client.get_table(self._table_ref(ctx.table_name))
        except NotFound:
            return False
        return (live.labels or {}).get(_PUBLISHED_RUN_LABEL_KEY) == self._run_label()

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        def ensure_dataset() -> None:
            client = self._get_client()
            client.create_dataset(f"{self._project}.{self._dataset}", exists_ok=True)

        await sync_to_async(ensure_dataset, thread_sensitive=False)()

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        if ctx.run.is_full_refresh and await sync_to_async(self._already_published, thread_sensitive=False)(ctx.run):
            # This run's staging table is gone and the live table carries this run's publish
            # label, so the run finished. Rebuilding a staging table from this one batch and
            # copying it over the live table would replace the whole table with it.
            return BatchWriteOutcome(rows_written=0)

        rows_written = 0
        chunk = 0

        async for record_batch in batches:
            if record_batch.num_rows == 0:
                continue
            # One load job per record batch. Collecting the whole staged batch first would hold
            # ~200 MiB of Arrow plus its parquet copy in memory, per destination.
            rows_written += await self._write_one(record_batch, ctx, chunk)
            chunk += 1

        return BatchWriteOutcome(rows_written=rows_written)

    async def _write_one(self, record_batch: pa.RecordBatch, ctx: DestinationBatchContext, chunk: int) -> int:
        run = ctx.run
        full_refresh = run.is_full_refresh
        is_first_chunk = chunk == 0

        def write() -> int:
            client = self._get_client()

            if full_refresh:
                return self._write_full_refresh_chunk(client, record_batch, ctx, first_chunk=is_first_chunk)

            if run.is_incremental and run.primary_keys:
                return self._merge_chunk(client, record_batch, ctx, chunk)

            # pq.write_table needs a Table, and one record batch is one load job.
            table = pa.Table.from_batches([record_batch])
            target_ref = self._table_ref(run.table_name)
            target_absent = self._check_owned_or_absent(client, target_ref, "append to it")
            self._load(client, run.table_name, table, bigquery.WriteDisposition.WRITE_APPEND)
            if target_absent:
                self._mark_owned(client, target_ref)
            return table.num_rows

        return await sync_to_async(write, thread_sensitive=False)()

    def _write_full_refresh_chunk(
        self, client: bigquery.Client, record_batch: pa.RecordBatch, ctx: DestinationBatchContext, *, first_chunk: bool
    ) -> int:
        """Append one chunk to the run's staging table, having cleared this batch's own rows.

        Every staged row carries the batch that wrote it, and the first chunk of a batch deletes
        the rows its previous attempt left. Without that, a re-applied batch appends a second
        copy of its rows: the consumer re-claims any batch whose outcome it could not confirm,
        and the staging table lives for the whole run, so nothing else removes them.
        """
        staging = staging_table_name(ctx.run)
        staging_ref = self._table_ref(staging)
        table = pa.Table.from_batches([stamp_batch_index(record_batch, ctx.batch_index)])

        if first_chunk:
            # The staging name is unique to this run, so a genuine collision is remote, but
            # refusing to reuse an unrelated table costs one read and closes the gap.
            staging_absent = self._check_owned_or_absent(client, staging_ref, "reuse it as a staging table")
            if not staging_absent:
                self._delete_batch_rows(client, staging, ctx.batch_index)

            self._load(client, staging, table, bigquery.WriteDisposition.WRITE_APPEND)
            if staging_absent:
                self._mark_owned(client, staging_ref)
            return table.num_rows

        self._load(client, staging, table, bigquery.WriteDisposition.WRITE_APPEND)
        return table.num_rows

    def _delete_batch_rows(self, client: bigquery.Client, table: str, batch_index: int) -> None:
        client.query(
            f"DELETE FROM {self._quoted_table(table)} WHERE {_backtick(BATCH_INDEX_COLUMN)} = {int(batch_index)}"
        ).result()

    def _merge_chunk(
        self, client: bigquery.Client, record_batch: pa.RecordBatch, ctx: DestinationBatchContext, chunk: int
    ) -> int:
        """Upsert one chunk on the primary keys, staging it in a scratch table first."""
        run = ctx.run
        primary_keys = list(run.primary_keys)
        # BigQuery rejects a `MERGE` whose source matches one target row more than once, and it
        # rejects it again on every retry.
        table = pa.Table.from_batches([dedupe_merge_source(record_batch, primary_keys)])

        temp = f"{run.table_name}__ph_tmp_{run_scope(run.run_uuid, 8)}_{ctx.batch_index}_{chunk}"
        target_ref = self._table_ref(run.table_name)
        target_absent = self._check_owned_or_absent(client, target_ref, "merge into it")

        self._load(client, temp, table, bigquery.WriteDisposition.WRITE_TRUNCATE)
        try:
            if target_absent:
                # `MERGE` fails outright against a target that does not exist, and an
                # incremental schema is on `sync_type` "incremental" from its very first run,
                # so nothing else ever creates it. Take the schema BigQuery just derived for the
                # scratch table rather than mapping Arrow types a second time.
                self._create_like(client, target_ref, temp)
                self._mark_owned(client, target_ref)
            self._merge(client, run.table_name, temp, list(table.schema.names), primary_keys)
        finally:
            client.delete_table(self._table_ref(temp), not_found_ok=True)
        return table.num_rows

    def _create_like(self, client: bigquery.Client, table_ref: str, model: str) -> None:
        """Create an empty table carrying another table's schema."""
        client.create_table(bigquery.Table(table_ref, schema=client.get_table(self._table_ref(model)).schema))

    def _load(self, client: bigquery.Client, table: str, data: pa.Table, disposition: str) -> None:
        """Load an Arrow table as parquet, letting BigQuery derive and evolve the schema."""
        buffer = io.BytesIO()
        pq.write_table(data, buffer)
        buffer.seek(0)
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=disposition,
            autodetect=True,
        )
        if disposition == bigquery.WriteDisposition.WRITE_APPEND:
            # Additive evolution: a column the source grew is added rather than rejected.
            # BigQuery rejects this option on a truncating load, which replaces the schema
            # outright and so has nothing to evolve.
            job_config.schema_update_options = [bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]
        client.load_table_from_file(buffer, self._table_ref(table), job_config=job_config).result()

    def _merge(
        self, client: bigquery.Client, target: str, source: str, column_names: list[str], primary_keys: list[str]
    ) -> None:
        on_clause = " AND ".join(f"T.{_backtick(k)} = S.{_backtick(k)}" for k in primary_keys)
        updates = ", ".join(f"T.{_backtick(c)} = S.{_backtick(c)}" for c in column_names if c not in primary_keys)
        columns = ", ".join(_backtick(c) for c in column_names)
        values = ", ".join(f"S.{_backtick(c)}" for c in column_names)
        update_clause = f"WHEN MATCHED THEN UPDATE SET {updates} " if updates else ""
        client.query(
            f"MERGE {self._quoted_table(target)} T USING {self._quoted_table(source)} S ON {on_clause} "
            f"{update_clause}"
            f"WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({values})"
        ).result()

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Copy a completed full refresh over the live table. Idempotent: no staging table means done."""
        if not ctx.is_full_refresh:
            return

        def publish() -> None:
            client = self._get_client()
            staging = staging_table_name(ctx)
            try:
                client.get_table(self._table_ref(staging))
            except NotFound:
                # No staging table means an earlier attempt already published. Anything else
                # has to propagate: swallowing it would leave the live table on stale data
                # and complete the run anyway.
                return
            target_ref = self._table_ref(ctx.table_name)
            # The live table predates this run when it exists at all, so this is the one check
            # that cannot be skipped on the strength of `write_batch`'s: a table sharing the
            # generated name could have appeared, or lost its label, between the two calls.
            self._check_owned_or_absent(client, target_ref, "replace it with the full refresh's staging table")
            # The batch-index column belongs to the staging table's own bookkeeping, so it is
            # dropped before the copy rather than published as part of the synced table.
            client.query(
                f"ALTER TABLE {self._quoted_table(staging)} DROP COLUMN IF EXISTS {_backtick(BATCH_INDEX_COLUMN)}"
            ).result()
            client.copy_table(
                self._table_ref(staging),
                target_ref,
                job_config=bigquery.CopyJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE),
            ).result()
            # Stamp the run that published, so a redelivery of the final batch can tell "already
            # published" from "never started" and refuse to rebuild the table.
            self._mark_published(client, target_ref)
            client.delete_table(self._table_ref(staging), not_found_ok=True)

        await sync_to_async(publish, thread_sensitive=False)()

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        # No `self._client is None` guard: `abort_destinations` builds a fresh writer for this
        # call, so the client is always unset here and the cleanup would never run.
        if not ctx.is_full_refresh:
            return

        def drop() -> None:
            try:
                self._get_client().delete_table(self._table_ref(staging_table_name(ctx)), not_found_ok=True)
            except Exception:
                pass

        await sync_to_async(drop, thread_sensitive=False)()
