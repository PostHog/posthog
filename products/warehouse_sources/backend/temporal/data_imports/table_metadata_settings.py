"""Workflows/activities for the dedicated table-metadata worker.

Post-sync, best-effort enrichment + profiling of synced tables — semantic descriptions and per-column
statistics. They run on their own worker (DATA_WAREHOUSE_METADATA_TASK_QUEUE) so they can't contend with
the import pipeline. The import workflow starts them as fire-and-forget children on this queue.
"""

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.compute_table_statistics import (
    ComputeTableStatisticsWorkflow,
    compute_table_statistics_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.enrich_table_semantics import (
    EnrichTableSemanticsWorkflow,
    enrich_table_semantics_activity,
)

WORKFLOWS = [
    EnrichTableSemanticsWorkflow,
    ComputeTableStatisticsWorkflow,
]

ACTIVITIES = [
    enrich_table_semantics_activity,
    compute_table_statistics_activity,
]
