from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

JOB_ATTEMPTS = "job_attempts"

ENDPOINTS = (JOB_ATTEMPTS,)

PRIMARY_KEY = "attempt_id"

# A run's creation time never changes, so it is a stable partition key and a monotonic cursor.
RUN_CREATED_AT = "run_created_at"

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    JOB_ATTEMPTS: [
        {
            "label": RUN_CREATED_AT,
            "type": IncrementalFieldType.DateTime,
            "field": RUN_CREATED_AT,
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
