from products.warehouse_sources.backend.facade import contracts
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def build_sync_alert_context(
    team_id: int, schema_id: str, job_id: str | None, *, include_error: bool
) -> contracts.SyncAlertContext | None:
    schema = ExternalDataSchema.objects.select_related("source").filter(id=schema_id, team_id=team_id).first()
    if schema is None:
        return None

    job = ExternalDataJob.objects.filter(id=job_id, team_id=team_id).first() if job_id else None
    source = schema.source

    latest_error = None
    if include_error and schema.latest_error:
        # Deferred: the redaction helpers live under presentation, which imports the facades.
        from products.warehouse_sources.backend.presentation.views.external_data_source.helpers import (  # noqa: PLC0415
            get_error_redaction_values,
            redact_error_message,
        )

        latest_error = redact_error_message(schema.latest_error, get_error_redaction_values(source))

    return contracts.SyncAlertContext(
        source_id=source.id,
        source_type=source.source_type,
        source_prefix=source.prefix,
        schema_id=schema.id,
        schema_name=schema.name,
        schema_label=schema.label,
        status=schema.status,
        latest_error=latest_error,
        sync_halted=schema.sync_halted,
        failed_runs_in_a_row=schema.failed_runs_in_a_row,
        job_id=job.id if job else None,
        rows_synced=job.rows_synced if job else None,
        finished_at=job.finished_at if job else None,
    )
