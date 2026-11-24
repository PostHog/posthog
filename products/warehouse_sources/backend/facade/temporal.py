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

from posthog.temporal.common.registration import HistogramSpec, QueueBinding, TemporalRegistration

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
from products.warehouse_sources.backend.temporal.sync_alert_evaluate import (
    WAREHOUSE_ALERT_EVALUATION_ACTIVITIES,
    WAREHOUSE_ALERT_EVALUATION_WORKFLOWS,
)

__all__ = [
    "ACTIVITIES",
    "METADATA_ACTIVITIES",
    "METADATA_WORKFLOWS",
    "PERSON_PROPERTY_BACKFILL_ACTIVITIES",
    "PERSON_PROPERTY_BACKFILL_WORKFLOWS",
    "PERSON_PROPERTY_SYNC_ACTIVITIES",
    "PERSON_PROPERTY_SYNC_WORKFLOWS",
    "WAREHOUSE_ALERT_EVALUATION_ACTIVITIES",
    "WAREHOUSE_ALERT_EVALUATION_WORKFLOWS",
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

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="DATA_WAREHOUSE_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
        QueueBinding(
            queue_setting="DATA_WAREHOUSE_CDP_PRODUCER_TASK_QUEUE",
            workflows=tuple(WORKFLOWS),
            activities=tuple(ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="DATA_WAREHOUSE_METADATA_TASK_QUEUE",
            workflows=(*METADATA_WORKFLOWS, *PERSON_PROPERTY_SYNC_WORKFLOWS, *PERSON_PROPERTY_BACKFILL_WORKFLOWS),
            activities=(*METADATA_ACTIVITIES, *PERSON_PROPERTY_SYNC_ACTIVITIES, *PERSON_PROPERTY_BACKFILL_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_EVALUATION_TASK_QUEUE",
            workflows=tuple(WAREHOUSE_ALERT_EVALUATION_WORKFLOWS),
            activities=tuple(WAREHOUSE_ALERT_EVALUATION_ACTIVITIES),
        ),
    ),
    histograms=(
        # Both metrics hold small counts. The default buckets are for latencies in milliseconds,
        # which puts every count into the first bucket.
        HistogramSpec(
            metric_name="warehouse_pipeline_run_attempt",
            buckets=(1.0, 2.0, 3.0, 5.0, 9.0, 20.0, 50.0, 100.0, 200.0),
            queue_setting="DATA_WAREHOUSE_TASK_QUEUE",
        ),
        HistogramSpec(
            metric_name="warehouse_import_handoffs_per_run",
            buckets=(0.0, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0),
            queue_setting="DATA_WAREHOUSE_TASK_QUEUE",
        ),
        # Recorded in seconds, from a hand-off at once to a run that holds the worker for hours.
        HistogramSpec(
            metric_name="warehouse_import_shutdown_handoff_delay_seconds",
            buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 90.0, 120.0, 300.0, 900.0, 1800.0, 3600.0, 7200.0, 21600.0),
            queue_setting="DATA_WAREHOUSE_TASK_QUEUE",
        ),
        HistogramSpec(
            metric_name="warehouse_import_attempt_duration_seconds",
            buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0, 7200.0, 21600.0),
            queue_setting="DATA_WAREHOUSE_TASK_QUEUE",
        ),
    ),
)
