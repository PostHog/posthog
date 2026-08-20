import uuid
import typing
import datetime as dt

from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.logger import get_logger

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema, process_incremental_value
from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    validate_and_coerce_row_filters,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.types import ExternalDataSourceType

LOGGER = get_logger(__name__)


@frozen
class ProbeSourceChangesActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    run_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "schema_id": str(self.schema_id),
            "source_id": str(self.source_id),
            "run_id": self.run_id,
        }


@activity.defn
def probe_source_changes_activity(inputs: ProbeSourceChangesActivityInputs) -> bool:
    """Whether the source has anything past this schema's watermark.

    True keeps the normal sync running and is the answer for every uncertainty: a source with no
    probe, a config that will not parse, a probe that raises. Only a source answering False —
    proving it has nothing new — lets the caller complete the run without extracting, and this
    stamps `last_synced_at` for that case so the schema still reads as checked.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    close_old_connections()

    try:
        schema = ExternalDataSchema.objects.select_related("source").get(id=inputs.schema_id, team_id=inputs.team_id)
        source_type = ExternalDataSourceType(schema.source.source_type)
        if not SourceRegistry.is_registered(source_type):
            return True

        source = SourceRegistry.get_source(source_type)
        config = source.parse_config(schema.source.job_inputs)
        source_inputs = SourceInputs(
            schema_name=schema.name,
            schema_id=str(schema.id),
            source_id=str(inputs.source_id),
            team_id=inputs.team_id,
            should_use_incremental_field=schema.should_use_incremental_field,
            incremental_field=schema.incremental_field,
            incremental_field_type=schema.incremental_field_type,
            db_incremental_field_last_value=process_incremental_value(
                schema.incremental_field_last_value, schema.incremental_field_type
            ),
            db_incremental_field_earliest_value=process_incremental_value(
                schema.incremental_field_earliest_value, schema.incremental_field_type
            ),
            row_filters=validate_and_coerce_row_filters(schema.row_filters, schema.schema_metadata),
            job_id=inputs.run_id,
            logger=logger,
            reset_pipeline=False,
            schema_metadata=schema.schema_metadata,
            s3_folder_name=schema.resolved_s3_folder_name,
            api_version=source.resolve_api_version(schema.api_version or schema.source.api_version),
        )

        has_new_data = source.probe_new_data(config, source_inputs)
    except Exception as e:
        logger.debug(f"probe_source_changes: running the full sync: {e}", exc_info=e)
        return True

    if has_new_data is not False:
        return True

    # The run still counts as a check, so the schema must not read as stale. Mirrors
    # `update_last_synced_at`, which post-load calls on the extracting path.
    job = ExternalDataJob.objects.get(pk=inputs.run_id)
    ExternalDataSchema.objects.filter(id=schema.id, team_id=inputs.team_id).update(
        last_synced_at=job.created_at, updated_at=dt.datetime.now(dt.UTC)
    )
    logger.info("Source reports no new data, completing without extracting", schema_id=str(schema.id))
    return False
