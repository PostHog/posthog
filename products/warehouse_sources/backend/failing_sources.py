from collections import defaultdict
from datetime import datetime
from uuid import UUID

from django.db.models import OuterRef, Subquery

from products.warehouse_sources.backend.facade import contracts
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


def list_failing_sources(
    team_id: int, created_by_id: int, *, since: datetime, limit: int
) -> list[contracts.FailingSource]:
    from products.warehouse_sources.backend.presentation.views.external_data_source.helpers import (  # noqa: PLC0415 -- the redaction helpers sit under presentation, which imports the facades
        get_error_redaction_values,
        redact_error_message,
    )
    from products.warehouse_sources.backend.temporal.data_imports.cdc.companion_jobs import (  # noqa: PLC0415 -- the cdc package imports pyarrow, which the facade path does not load
        COMPANION_JOB_IDS_KEY,
    )
    from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (  # noqa: PLC0415 -- the import workflow module loads pyarrow, which the facade path does not load
        CANCELLED_RUN_MESSAGE,
        WORKER_RESTART_ERROR_MESSAGE,
    )

    sources = {
        source.id: source
        for source in ExternalDataSource.objects.filter(team_id=team_id, created_by_id=created_by_id).exclude(
            deleted=True
        )
    }
    if not sources:
        return []
    failed_jobs = list(
        ExternalDataJob.objects.filter(
            team_id=team_id,
            pipeline_id__in=list(sources),
            schema__isnull=False,
            status=ExternalDataJob.Status.FAILED,
            finished_at__gte=since,
        )
        .exclude(schema__deleted=True)
        .exclude(schema__should_sync=False, schema__auto_disabled_at__isnull=True)
        .exclude(
            latest_error__in=[ExternalDataJob.USER_CANCELLED_ERROR, CANCELLED_RUN_MESSAGE, WORKER_RESTART_ERROR_MESSAGE]
        )
        .values_list("id", "schema_id", "latest_error", "schema_snapshot__companion_of")
    )
    current_companions = {
        str(companion_id)
        for snapshot in ExternalDataJob.objects.filter(
            team_id=team_id, id__in={parent_id for *_, parent_id in failed_jobs if parent_id}
        ).values_list("schema_snapshot", flat=True)
        for companion_id in (snapshot or {}).get(COMPANION_JOB_IDS_KEY) or []
    }
    schema_runs: defaultdict[UUID, set[str]] = defaultdict(set)
    run_errors: dict[str, str | None] = {}
    for job_id, schema_id, error, parent_id in failed_jobs:
        if parent_id and str(job_id) not in current_companions:
            continue
        run_id = parent_id or str(job_id)
        schema_runs[schema_id].add(run_id)
        if not parent_id or run_id not in run_errors:
            run_errors[run_id] = error
    if not schema_runs:
        return []
    newest_run = ExternalDataJob.objects.filter(
        team_id=team_id,
        pipeline_id=OuterRef("source_id"),
        schema_id=OuterRef("id"),
        schema_snapshot__companion_of__isnull=True,
    ).order_by("-created_at")
    schemas = (
        ExternalDataSchema.objects.filter(team_id=team_id, id__in=list(schema_runs))
        .annotate(
            newest_run_id=Subquery(newest_run.values("id")[:1]),
            newest_run_at=Subquery(newest_run.values("created_at")[:1]),
        )
        .order_by("-newest_run_at")
    )
    failures: defaultdict[UUID, int] = defaultdict(int)
    errors: dict[UUID, str | None] = {}
    for schema in schemas:
        newest_run_id = str(schema.newest_run_id)  # type: ignore[attr-defined]
        if newest_run_id in run_errors or schema.cdc_halted:
            failures[schema.source_id] += len(schema_runs[schema.id])
            errors.setdefault(schema.source_id, run_errors.get(newest_run_id, schema.latest_error))
    return [
        contracts.FailingSource(
            source_id=source_id,
            source_type=sources[source_id].source_type,
            source_label=sources[source_id].description or sources[source_id].prefix or None,
            failures=failures[source_id],
            latest_error=redact_error_message(errors[source_id], get_error_redaction_values(sources[source_id])),
        )
        for source_id in sorted(failures, key=failures.__getitem__, reverse=True)[:limit]
    ]
