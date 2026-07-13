"""
Pipeline/metrics wiring for warehouse_sources.

Re-exports the data-import pipeline internals (v3 S3 helpers, health server, duckgres
enablement flag), the app-metric emitters, the CDC extraction input, and the pipeline-
version + schema-sync helpers that sibling products (data_warehouse, error_tracking) and
core (the ducklake copy workflow) reach into while orchestrating or observing imports.

These live deep under ``temporal.data_imports`` and pull heavy dependencies (temporalio,
dlt, boto3, ...), so — like ``facade.source_management`` — the module resolves names lazily
(PEP 562): they load on first access, keeping the module off the ``django.setup()`` path
and out of any import cycle.
"""

_B = "products.warehouse_sources.backend.temporal.data_imports."

_LAZY = {
    "LOCK_TAKEOVER_LATEST_ERROR": "metrics",
    "TERMINAL_JOB_STATUSES": "metrics",
    "emit_data_import_app_metrics": "metrics",
    "CDCExtractionInput": "cdc.workflows",
    "is_pipeline_v3_enabled": "workflow_activities.create_job_model",
    "SyncNewSchemasActivityInputs": "workflow_activities.sync_new_schemas",
    "DUCKGRES_BATCH_SINK_FLAG": "pipelines.pipeline_v3.duckgres.enablement",
    "is_duckgres_sink_team_member": "pipelines.pipeline_v3.duckgres.enablement",
    "HealthState": "pipelines.pipeline_v3.load.health",
    "start_health_server": "pipelines.pipeline_v3.load.health",
    "ensure_bucket": "pipelines.pipeline_v3.s3.common",
    "strip_s3_protocol": "pipelines.pipeline_v3.s3.common",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
