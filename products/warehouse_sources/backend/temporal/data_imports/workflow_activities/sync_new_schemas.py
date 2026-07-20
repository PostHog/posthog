import typing as t
import dataclasses

from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.temporal.common.logger import get_logger

from products.data_warehouse.backend.facade.api import delete_discover_schemas_schedule
from products.warehouse_sources.backend.models.external_data_schema import (
    auto_enable_new_schemas,
    sync_old_schemas_with_new_schemas,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class SyncNewSchemasActivityInputs:
    source_id: str
    team_id: int

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "source_id": self.source_id,
            "team_id": self.team_id,
        }


@activity.defn
def sync_new_schemas_activity(inputs: SyncNewSchemasActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    close_old_connections()

    logger.info("Syncing new -> old schemas")

    # Self-destruct: if the source has been deleted (or hard-removed) since the schedule
    # was created, drop the discovery schedule so we stop firing zombie workflows. Mirrors
    # the existing per-schema pattern in `create_external_data_job_model_activity`.
    source_exists = (
        ExternalDataSource.objects.filter(team_id=inputs.team_id, id=inputs.source_id).exclude(deleted=True).exists()
    )
    if not source_exists:
        delete_discover_schemas_schedule(str(inputs.source_id))
        raise Exception("Source no longer exists - deleted discover-schemas temporal schedule")

    source = ExternalDataSource.objects.get(team_id=inputs.team_id, id=inputs.source_id)

    source_type_enum = ExternalDataSourceType(source.source_type)
    if SourceRegistry.is_registered(source_type_enum):
        if not source.job_inputs:
            return

        new_source = SourceRegistry.get_source(source_type_enum)

        try:
            config = new_source.parse_config(source.job_inputs)
        except Exception:
            # Config parsing is deterministic over the stored `job_inputs`, so a corrupt or
            # double-encoded config fails identically on every discovery run - there is nothing
            # to retry. The per-schema sync path surfaces and disables the source on the same
            # config, so skip quietly here rather than spamming retries and error tracking.
            logger.warning("Skipping schema discovery: source config could not be parsed", exc_info=True)
            return

        try:
            schemas = new_source.get_schemas(config, inputs.team_id)
        except Exception as e:
            # Schema discovery is best-effort and runs on its own ~6h cadence. If the source's
            # credentials are broken (expired/revoked tokens, permission denied, deleted account,
            # etc.) discovery will keep failing until the user reconnects — there is nothing to
            # retry here, and the per-schema sync path surfaces and disables the source on the
            # same error. Skip quietly on known non-retryable source errors rather than spamming
            # retries and error tracking on every discovery run. Other errors still propagate.
            error_msg = str(e)
            non_retryable_errors = new_source.get_non_retryable_errors()
            if any(pattern in error_msg for pattern in non_retryable_errors):
                logger.warning(f"Skipping schema discovery due to non-retryable source error: {error_msg}")
                return
            raise

        schemas_to_sync = {s.name: s.label for s in schemas}
    else:
        raise ValueError(f"Source type missing from SourceRegistry: {source.source_type}")

    # TODO: this could cause a race condition where each schema worker creates the missing schema

    # GitHub keeps its legacy repo's rows bare alongside qualified rows for added repos, so
    # bare↔qualified tail matching would wrongly collapse them; match names exactly and seed
    # per-repo location metadata on newly created rows.
    is_github = source_type_enum == ExternalDataSourceType.GITHUB
    schemas_created, schemas_deleted = sync_old_schemas_with_new_schemas(
        schemas_to_sync,
        source_id=inputs.source_id,
        team_id=inputs.team_id,
        strict_name_match=is_github,
        schema_metadata_by_name={s.name: s.schema_metadata for s in schemas if s.schema_metadata}
        if is_github
        else None,
    )

    if len(schemas_created) > 0:
        logger.info(f"Added new schemas: {', '.join(schemas_created)}")

        auto_enabled = auto_enable_new_schemas(source, schemas_created, {s.name: s for s in schemas})
        if auto_enabled:
            logger.info(f"Auto-enabled sync for new schemas: {', '.join(auto_enabled)}")
    else:
        logger.info("No new schemas to create")

    if len(schemas_deleted) > 0:
        logger.info(f"Deleted schemas: {', '.join(schemas_deleted)}")
    else:
        logger.info("No schemas to delete")
