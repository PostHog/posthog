from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

JOB_ATTEMPTS = "job_attempts"
JOB_METRICS = "job_metrics"
ARTIFACTS = "artifacts"
FAILURE_DIAGNOSES = "failure_diagnoses"

ENDPOINTS = (JOB_ATTEMPTS, JOB_METRICS, ARTIFACTS, FAILURE_DIAGNOSES)

PRIMARY_KEYS: dict[str, list[str]] = {
    JOB_ATTEMPTS: ["attempt_id"],
    JOB_METRICS: ["attempt_id"],
    ARTIFACTS: ["artifact_id"],
    # Depot computes the fingerprint per run, so the same failure in two runs has two rows.
    FAILURE_DIAGNOSES: ["run_id", "fingerprint"],
}

# Creation time is stable for partitioning. The source replays runs to pick up late retries.
RUN_CREATED_AT = "run_created_at"

# Failure diagnoses sync as a full refresh: a retry that passes removes a run's failure groups, and a
# merge never deletes the rows it no longer receives.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: [
        {
            "label": RUN_CREATED_AT,
            "type": IncrementalFieldType.DateTime,
            "field": RUN_CREATED_AT,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]
    for endpoint in (JOB_ATTEMPTS, JOB_METRICS, ARTIFACTS)
}
