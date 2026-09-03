"""
Temporal registration wiring for warehouse_sources.

Re-exports the workflow/activity registration the temporal worker bootstrap loads,
plus the queryable-table prep helper and person-property row sink the data-modeling
temporal workflow calls.

This module imports the data-import ``settings`` (which pull temporalio, dlt, pandas,
...), so it must only be imported **off** the ``django.setup()`` path — i.e. from the
temporal worker bootstrap and temporal activity modules, never from an AppConfig or a
model. The light external-product hooks live in ``facade.hooks`` for setup-time
consumers.

The worker bootstrap also registers the dedicated table-metadata worker's workflows and
activities (semantic enrichment + column statistics) and loads every source module so it
self-registers with ``SourceRegistry`` — both re-exported here as the registration surface,
so the bootstrap never reaches into the source/settings internals directly.
"""

from products.warehouse_sources.backend.temporal.data_imports.person_property_backfill_job import (
    PERSON_PROPERTY_BACKFILL_ACTIVITIES,
    PERSON_PROPERTY_BACKFILL_WORKFLOWS,
)
from products.warehouse_sources.backend.temporal.data_imports.person_property_sync_job import (
    PERSON_PROPERTY_SYNC_ACTIVITIES,
    PERSON_PROPERTY_SYNC_WORKFLOWS,
)
from products.warehouse_sources.backend.temporal.data_imports.person_property_triggers import (
    ExternalDataSchemaSyncPausedError,
    SavedQueryNotFoundError,
    SavedQueryNotOnV2ScheduleError,
    WarehouseBindingMissingError,
    start_person_property_backfill,
    trigger_saved_query_materialization,
    trigger_schema_sync,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.account_property_paths import (
    completion_prefix as account_property_completion_prefix,
    job_staged_prefix as account_property_job_staged_prefix,
    snapshot_prefix as account_property_snapshot_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.account_property_row_sink import (
    AccountPropertyRowSink,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_paths import (
    job_staged_prefix as person_property_job_staged_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_row_sink import (
    PersonPropertyRowSink,
)
from products.warehouse_sources.backend.temporal.data_imports.settings import ACTIVITIES, WORKFLOWS
from products.warehouse_sources.backend.temporal.data_imports.sources import load_all_sources
from products.warehouse_sources.backend.temporal.data_imports.table_metadata_settings import (
    ACTIVITIES as METADATA_ACTIVITIES,
    WORKFLOWS as METADATA_WORKFLOWS,
)
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying

__all__ = [
    "ACTIVITIES",
    "METADATA_ACTIVITIES",
    "METADATA_WORKFLOWS",
    "PERSON_PROPERTY_BACKFILL_ACTIVITIES",
    "PERSON_PROPERTY_BACKFILL_WORKFLOWS",
    "PERSON_PROPERTY_SYNC_ACTIVITIES",
    "PERSON_PROPERTY_SYNC_WORKFLOWS",
    "WORKFLOWS",
    "ExternalDataSchemaSyncPausedError",
    "AccountPropertyRowSink",
    "account_property_completion_prefix",
    "account_property_job_staged_prefix",
    "account_property_snapshot_prefix",
    "PersonPropertyRowSink",
    "person_property_job_staged_prefix",
    "SavedQueryNotFoundError",
    "SavedQueryNotOnV2ScheduleError",
    "WarehouseBindingMissingError",
    "load_all_sources",
    "prepare_s3_files_for_querying",
    "start_person_property_backfill",
    "trigger_saved_query_materialization",
    "trigger_schema_sync",
]
