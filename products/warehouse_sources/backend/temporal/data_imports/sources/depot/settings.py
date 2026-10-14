from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

JOB_ATTEMPTS = "job_attempts"

ENDPOINTS = (JOB_ATTEMPTS,)

PRIMARY_KEY = "attempt_id"

# Creation time is stable for partitioning. The source replays runs to pick up late retries.
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
