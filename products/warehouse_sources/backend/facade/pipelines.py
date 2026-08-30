"""
Pipeline/metrics wiring for warehouse_sources.

Re-exports the data-import pipeline internals (v3 S3 helpers and health server),
the app-metric emitters, the CDC extraction input, and the pipeline-
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
    "BatchQueue": "products.warehouse_sources_queue.backend.core.jobs_db",
    "mark_job_failed_if_not_terminal": "pipelines.pipeline_v3.postgres_queue.consumer",
    "release_v3_pipeline_lock": "pipelines.pipeline_v3.sync_lock",
    "CDCExtractionInput": "cdc.workflows",
    "is_pipeline_v3_enabled": "workflow_activities.create_job_model",
    "SyncNewSchemasActivityInputs": "workflow_activities.sync_new_schemas",
    "finish_row_tracking": "row_tracking",
    "HealthState": "products.warehouse_sources_queue.backend.core.health",
    "start_health_server": "products.warehouse_sources_queue.backend.core.health",
    "ensure_bucket": "pipelines.pipeline_v3.s3.common",
    "strip_s3_protocol": "pipelines.pipeline_v3.s3.common",
    "CDPProducer": "pipelines.core.cdp_producer",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    # Queue-engine names live in the warehouse_sources_queue package and are
    # mapped by absolute path; everything else is relative to this product.
    target = module if module.startswith("products.") else _B + module
    return getattr(importlib.import_module(target), name)
