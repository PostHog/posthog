"""Re-mask already-synced warehouse data in place, without re-fetching from the source.

When a user *adds* a column to `ExternalDataSchema.masked_columns`, the rows already in the Delta
table still hold the column in plaintext, and (because masking rewrites the column to a string
digest) its stored type no longer matches what future incremental writes will produce. This job
reads the existing Delta table, HMACs the newly-masked columns, overwrites the table, and refreshes
the queryable files + column metadata — cheaper than a full source resync for large tables.

NOT DISPATCHED YET: the API currently routes every mask change (adds included) through the tested
full-resync path instead. Before wiring this job back up it needs hardening — mutual exclusion with
running syncs, retry idempotency (a retry after the overwrite would double-hash), a queue/signal for
concurrent mask-adds, immediate purge of pre-mask Delta versions and superseded queryable folders
(the current `use_timestamped_folders=False` finalize deletes its own destination on a second run),
resolving primary keys the way the pipeline does (schema PKs are unset for API sources), deleted
schema/source checks, a table-size guard, and failure surfacing — plus a live-stack integration run.
"""

import json
import uuid
import asyncio
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.utils import REMASK_COLUMNS_WORKFLOW_NAME, RemaskColumnsInputs

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    DeltaTableHelper,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.hogql_schema import HogQLSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.masking import mask_table_columns
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
    validate_schema_and_update_table,
)
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying


def _latest_job(team_id: int, schema_id: uuid.UUID) -> ExternalDataJob | None:
    return ExternalDataJob.objects.filter(team_id=team_id, schema_id=schema_id).order_by("-created_at").first()


@activity.defn
async def remask_columns_activity(inputs: RemaskColumnsInputs) -> None:
    async with Heartbeater():
        logger = get_logger(__name__)

        schema = await database_sync_to_async(ExternalDataSchema.objects.select_related("source").get)(
            id=inputs.schema_id, team_id=inputs.team_id
        )
        job = await database_sync_to_async(_latest_job)(inputs.team_id, inputs.schema_id)
        if job is None:
            await logger.ainfo("remask: no job yet, nothing synced to re-mask", schema_id=str(inputs.schema_id))
            return

        # `s3_folder_name` pins the actual Delta subdir (including migrated/legacy rows); fall back to the
        # schema name for rows written before that column existed. DeltaTableHelper normalizes it again,
        # which is idempotent for an already-normalized folder name.
        resource_name = schema.s3_folder_name or schema.name
        delta_helper = DeltaTableHelper(resource_name, job, logger)

        delta_table = await delta_helper.get_delta_table()
        if delta_table is None:
            await logger.ainfo("remask: delta table missing, nothing to re-mask", schema_id=str(inputs.schema_id))
            return

        primary_keys = schema.primary_key_columns
        # v1 loads the whole table to keep the overwrite a single atomic operation; batched streaming is a
        # follow-up if this proves memory-heavy on large tables.
        pa_table = await asyncio.to_thread(delta_table.to_pyarrow_table)
        masked = await asyncio.to_thread(
            mask_table_columns,
            pa_table,
            inputs.columns,
            team_id=inputs.team_id,
            primary_keys=primary_keys,
            incremental_field=schema.incremental_field,
        )

        previous_file_uris = await delta_helper.get_file_uris()
        await delta_helper.write_to_deltalake(
            masked, write_type="full_refresh", should_overwrite_table=True, primary_keys=primary_keys
        )

        # Refresh the query-facing S3 files + the warehouse table's column metadata so the masked columns
        # read back as strings immediately (mirrors the pipeline's post-write finalize).
        file_uris = await delta_helper.get_file_uris()
        new_file_uris = list(set(file_uris) - set(previous_file_uris))
        folder_path = await database_sync_to_async(job.folder_path)()
        queryable_folder = await prepare_s3_files_for_querying(
            folder_path=folder_path,
            table_name=resource_name,
            file_uris=new_file_uris,
            delete_existing=True,
            use_timestamped_folders=False,
            logger=logger,
        )

        internal_schema = HogQLSchema()
        internal_schema.add_pyarrow_table(masked)
        await validate_schema_and_update_table(
            run_id=str(job.id),
            team_id=inputs.team_id,
            schema_id=schema.id,
            table_schema_dict=internal_schema.to_hogql_types(),
            row_count=masked.num_rows,
            queryable_folder=queryable_folder,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )

        await delta_helper.compact_table()
        await logger.ainfo("remask: complete", schema_id=str(inputs.schema_id), rows=masked.num_rows)


@workflow.defn(name=REMASK_COLUMNS_WORKFLOW_NAME)
class RemaskColumnsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RemaskColumnsInputs:
        loaded = json.loads(inputs[0])
        return RemaskColumnsInputs(
            team_id=loaded["team_id"], schema_id=uuid.UUID(loaded["schema_id"]), columns=loaded["columns"]
        )

    @workflow.run
    async def run(self, inputs: RemaskColumnsInputs) -> None:
        await workflow.execute_activity(
            remask_columns_activity,
            inputs,
            start_to_close_timeout=timedelta(hours=1),
            # Without a heartbeat timeout the heartbeats enforce nothing — a dead worker would hold
            # the stable workflow id for the full hour while further mask-adds bounce off it.
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
