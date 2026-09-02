from products.managed_warehouse.backend.temporal.compaction_workflow import (
    DucklakeCompactionWorkflow,
    run_ducklake_compaction,
)
from products.managed_warehouse.backend.temporal.ducklake_copy_data_imports_workflow import (
    DuckLakeCopyDataImportsWorkflow,
    cleanup_data_imports_staging_activity,
    copy_data_imports_to_ducklake_activity,
    ducklake_copy_data_imports_gate_activity,
    prepare_data_imports_ducklake_metadata_activity,
    verify_data_imports_ducklake_copy_activity,
)
from products.managed_warehouse.backend.temporal.ducklake_copy_data_modeling_workflow import (
    DuckLakeCopyDataModelingWorkflow,
    cleanup_data_modeling_staging_activity,
    copy_data_modeling_model_to_ducklake_activity,
    ducklake_copy_workflow_gate_activity,
    prepare_data_modeling_ducklake_metadata_activity,
    verify_ducklake_copy_activity,
)
from products.managed_warehouse.backend.temporal.ducklake_register_data_imports_workflow import (
    DuckLakeRegisterDataImportsWorkflow,
    cleanup_ducklake_registration_tables_activity,
    copy_and_register_ducklake_data_imports_activity,
    ducklake_register_data_imports_gate_activity,
    prepare_ducklake_data_imports_registration_activity,
)
from products.managed_warehouse.backend.temporal.source_job_state import record_managed_warehouse_source_job_activity

WORKFLOWS = [
    DucklakeCompactionWorkflow,
    DuckLakeCopyDataImportsWorkflow,
    DuckLakeCopyDataModelingWorkflow,
    DuckLakeRegisterDataImportsWorkflow,
]
ACTIVITIES = [
    cleanup_data_imports_staging_activity,
    cleanup_data_modeling_staging_activity,
    cleanup_ducklake_registration_tables_activity,
    copy_data_imports_to_ducklake_activity,
    copy_data_modeling_model_to_ducklake_activity,
    copy_and_register_ducklake_data_imports_activity,
    ducklake_copy_data_imports_gate_activity,
    ducklake_copy_workflow_gate_activity,
    ducklake_register_data_imports_gate_activity,
    prepare_data_imports_ducklake_metadata_activity,
    prepare_data_modeling_ducklake_metadata_activity,
    prepare_ducklake_data_imports_registration_activity,
    record_managed_warehouse_source_job_activity,
    run_ducklake_compaction,
    verify_data_imports_ducklake_copy_activity,
    verify_ducklake_copy_activity,
]
