"""
Temporal registration wiring for warehouse_sources.

Re-exports the workflow/activity registration the temporal worker bootstrap loads,
plus the queryable-table prep helper the data-modeling temporal workflow calls.

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
    "WORKFLOWS",
    "load_all_sources",
    "prepare_s3_files_for_querying",
]
