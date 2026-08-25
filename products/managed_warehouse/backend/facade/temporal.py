"""
Temporal registration wiring for managed_warehouse.

Re-exports the workflow/activity registration the temporal worker bootstrap loads, the
workflow classes callers start as children, and the input types they construct.

Imports temporalio (and, through the workflow modules, duckdb), so it must only be
imported off the ``django.setup()`` path — the worker bootstrap, schedule setup, and
temporal activity modules.
"""

from products.managed_warehouse.backend.temporal import ACTIVITIES, WORKFLOWS
from products.managed_warehouse.backend.temporal.compaction_types import DucklakeCompactionInput
from products.managed_warehouse.backend.temporal.ducklake_copy_data_imports_workflow import (
    DataImportsDuckLakeCopyInputs,
    DuckLakeCopyDataImportsWorkflow,
)
from products.managed_warehouse.backend.temporal.ducklake_copy_data_modeling_workflow import (
    DuckLakeCopyDataModelingWorkflow,
)
from products.managed_warehouse.backend.temporal.ducklake_register_data_imports_workflow import (
    DuckLakeRegisterDataImportsInputs,
    DuckLakeRegisterDataImportsWorkflow,
    build_register_data_imports_workflow_id,
)
from products.managed_warehouse.backend.temporal.publish_table_workflow import (
    DuckgresPrunePublishedSnapshotWorkflow,
    DuckgresPublishTableWorkflow,
    PrunePublishedSnapshotInputs,
    PublishTableInputs,
    build_publish_table_workflow_id,
)
from products.managed_warehouse.backend.temporal.types import DataModelingDuckLakeCopyInputs, DuckLakeCopyModelInput

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "DataImportsDuckLakeCopyInputs",
    "DataModelingDuckLakeCopyInputs",
    "DuckLakeCopyDataImportsWorkflow",
    "DuckLakeCopyDataModelingWorkflow",
    "DuckLakeCopyModelInput",
    "DuckLakeRegisterDataImportsInputs",
    "DuckLakeRegisterDataImportsWorkflow",
    "DuckgresPrunePublishedSnapshotWorkflow",
    "DuckgresPublishTableWorkflow",
    "DucklakeCompactionInput",
    "PrunePublishedSnapshotInputs",
    "PublishTableInputs",
    "build_register_data_imports_workflow_id",
    "build_publish_table_workflow_id",
]
