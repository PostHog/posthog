"""View translation jobs that staff start by hand from PostHog Admin."""

from functools import partial
from uuid import UUID

from django.db import IntegrityError, transaction

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.contracts import StaffActionOutcome, ViewTranslationSummary
from products.managed_warehouse.backend.models import (
    DuckgresServer,
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)

ACTIVE_STATUSES = [ManagedWarehouseViewTranslationJob.Status.PENDING, ManagedWarehouseViewTranslationJob.Status.RUNNING]
RETRYABLE_STATUSES = [
    ManagedWarehouseViewTranslationResult.Status.FAILED,
    ManagedWarehouseViewTranslationResult.Status.STALE,
]
ACTIVE_JOB_CONSTRAINT = "unique_active_mw_view_translation_job"
ALREADY_RUNNING = "This organization already has a pending or running translation job. Wait for it to finish."


def _start_translation_job(job_id: UUID, organization_id: UUID) -> None:
    from products.managed_warehouse.backend.view_translation import (  # noqa: PLC0415 - keeps the Temporal client off Django startup paths
        start_managed_warehouse_view_translation,
    )

    start_managed_warehouse_view_translation(job_id, organization_id)


class ViewTranslationStaff:
    @staticmethod
    def summary(organization_id: UUID) -> ViewTranslationSummary | None:
        jobs = ManagedWarehouseViewTranslationJob.objects.filter(organization_id=organization_id).order_by(
            "-created_at"
        )
        latest = jobs.first()
        if latest is None:
            return None
        has_retryable_results = ManagedWarehouseViewTranslationResult.all_teams.filter(
            job=latest, status__in=RETRYABLE_STATUSES
        ).exists()
        return ViewTranslationSummary(
            latest_status=latest.get_status_display(),
            total_count=latest.total_count,
            compiled_count=latest.compiled_count,
            failed_count=latest.failed_count,
            stale_count=latest.stale_count,
            active=latest.status in ACTIVE_STATUSES,
            retry_job_id=latest.id if has_retryable_results else None,
        )

    @staticmethod
    def _create_and_start(organization_id: UUID, **fields: object) -> ManagedWarehouseViewTranslationJob | None:
        try:
            with transaction.atomic():
                job = ManagedWarehouseViewTranslationJob.objects.create(
                    organization_id=organization_id,
                    status=ManagedWarehouseViewTranslationJob.Status.PENDING,
                    **fields,
                )
                transaction.on_commit(partial(_start_translation_job, job.id, organization_id))
        except IntegrityError as error:
            # The unique constraint on active jobs settles a race between two staff starting a job at once.
            if ACTIVE_JOB_CONSTRAINT not in str(error):
                raise
            return None
        return job

    @classmethod
    def start(cls, organization_id: UUID, saved_query_ids: list[UUID], actor_user_id: int) -> StaffActionOutcome:
        if not DuckgresServer.objects.filter(organization_id=organization_id).exists():
            return StaffActionOutcome(
                ok=False, status_code=400, message="This organization does not have a provisioned managed warehouse."
            )
        selected_ids = [str(saved_query_id) for saved_query_id in dict.fromkeys(saved_query_ids)]
        if selected_ids:
            eligible_ids = {
                str(saved_query_id)
                # Staff-only PostHog Admin operation scoped to one organization's warehouse, so it spans its teams.
                for saved_query_id in DataWarehouseSavedQuery.objects.filter(  # nosemgrep: idor-lookup-without-team
                    id__in=selected_ids, team__organization_id=organization_id, deleted=False
                )
                .exclude(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)
                .values_list("id", flat=True)
            }
            if eligible_ids != set(selected_ids):
                return StaffActionOutcome(
                    ok=False,
                    status_code=400,
                    message="One or more IDs do not identify an active view in this organization. Check the IDs and try again.",
                )
        scope = (
            ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS
            if selected_ids
            else ManagedWarehouseViewTranslationJob.Scope.ENTIRE_ORGANIZATION
        )
        job = cls._create_and_start(
            organization_id,
            created_by_id=actor_user_id,
            trigger_source=ManagedWarehouseViewTranslationJob.TriggerSource.ADMIN,
            scope=scope,
            selected_saved_query_ids=selected_ids,
        )
        if job is None:
            return StaffActionOutcome(ok=False, status_code=409, message=ALREADY_RUNNING)
        views = f"{len(selected_ids)} selected views" if selected_ids else "every view in the organization"
        return StaffActionOutcome(ok=True, status_code=201, message=f"Started translation job {job.id} for {views}.")

    @classmethod
    def retry(
        cls, organization_id: UUID, job_id: UUID, saved_query_ids: list[UUID], actor_user_id: int
    ) -> StaffActionOutcome:
        source_job = ManagedWarehouseViewTranslationJob.objects.filter(
            id=job_id, organization_id=organization_id
        ).first()
        if source_job is None:
            return StaffActionOutcome(
                ok=False, status_code=404, message=f"No translation job {job_id} in this organization."
            )
        results = ManagedWarehouseViewTranslationResult.all_teams.filter(job=source_job, status__in=RETRYABLE_STATUSES)
        if saved_query_ids:
            results = results.filter(saved_query_id__in=saved_query_ids)
        selected_ids = sorted(
            {str(saved_query_id) for saved_query_id in results.values_list("saved_query_id", flat=True)}
        )
        if not selected_ids:
            return StaffActionOutcome(
                ok=False, status_code=400, message="This job has no failed or stale views to retry."
            )
        if saved_query_ids and len(selected_ids) != len(set(saved_query_ids)):
            return StaffActionOutcome(
                ok=False,
                status_code=400,
                message="One or more IDs are not failed or stale views of this job. Check the IDs and try again.",
            )
        job = cls._create_and_start(
            organization_id,
            created_by_id=actor_user_id,
            trigger_source=ManagedWarehouseViewTranslationJob.TriggerSource.RETRY,
            scope=ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS,
            selected_saved_query_ids=selected_ids,
            retry_of=source_job,
        )
        if job is None:
            return StaffActionOutcome(ok=False, status_code=409, message=ALREADY_RUNNING)
        return StaffActionOutcome(
            ok=True, status_code=201, message=f"Started retry job {job.id}. Selected views: {len(selected_ids)}."
        )
