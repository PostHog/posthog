"""
Temporal registration wiring for warehouse_sources.

Re-exports the workflow/activity registration the temporal worker bootstrap loads,
plus the queryable-table prep helper the data-modeling temporal workflow calls.

This module imports the data-import ``settings`` (which pull temporalio, dlt, pandas,
...), so it must only be imported **off** the ``django.setup()`` path — i.e. from the
temporal worker bootstrap and temporal activity modules, never from an AppConfig or a
model. The light external-product hooks live in ``facade.hooks`` for setup-time
consumers.
"""

from products.warehouse_sources.backend.temporal.data_imports.settings import ACTIVITIES, WORKFLOWS
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "prepare_s3_files_for_querying",
]
