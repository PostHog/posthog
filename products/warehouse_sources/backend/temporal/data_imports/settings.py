from products.warehouse_sources.backend.temporal.data_imports.cdc.activities import (
    cdc_extract_activity,
    cleanup_orphan_slots_activity,
    validate_cdc_prerequisites_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.workflows import (
    CDCExtractionWorkflow,
    CDCSlotCleanupWorkflow,
)
from products.warehouse_sources.backend.temporal.data_imports.cdp_producer_job import (
    CDPProducerJobWorkflow,
    produce_to_cdp_kafka_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.discover_schemas_workflow import DiscoverSchemasWorkflow
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    ExternalDataJobWorkflow,
    calculate_table_size_activity,
    check_billing_limits_activity,
    create_external_data_job_model_activity,
    create_source_templates,
    import_data_activity_sync,
    trigger_schedule_buffer_one_activity,
    update_external_data_job_model,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    acquire_v3_pipeline_lock_activity,
    check_pipeline_version_activity,
    release_v3_pipeline_lock_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table import (
    maybe_repartition_table_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.sync_new_schemas import (
    sync_new_schemas_activity,
)

# NOTE: post-sync table-metadata workflows (semantic enrichment, column statistics) intentionally live on
# their own worker — see table_metadata_settings.py / DATA_WAREHOUSE_METADATA_TASK_QUEUE — not here.
WORKFLOWS = [
    ExternalDataJobWorkflow,
    CDPProducerJobWorkflow,
    CDCExtractionWorkflow,
    CDCSlotCleanupWorkflow,
    DiscoverSchemasWorkflow,
]

ACTIVITIES = [
    create_external_data_job_model_activity,
    update_external_data_job_model,
    import_data_activity_sync,
    create_source_templates,
    check_billing_limits_activity,
    sync_new_schemas_activity,
    calculate_table_size_activity,
    trigger_schedule_buffer_one_activity,
    produce_to_cdp_kafka_activity,
    cdc_extract_activity,
    validate_cdc_prerequisites_activity,
    cleanup_orphan_slots_activity,
    check_pipeline_version_activity,
    acquire_v3_pipeline_lock_activity,
    release_v3_pipeline_lock_activity,
    maybe_repartition_table_activity,
]
