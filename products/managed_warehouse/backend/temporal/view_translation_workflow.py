from __future__ import annotations

import datetime as dt
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.schema import HogQLQuery

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.temporal.common.base import PostHogWorkflow

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.client import compile_hogql_to_trino_sql
from products.managed_warehouse.backend.facade.contracts import TrinoExpansionMode
from products.managed_warehouse.backend.facade.cp_teams import list_org_team_memberships
from products.managed_warehouse.backend.models import (
    DuckgresServer,
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)
from products.managed_warehouse.backend.trino_compiler import get_ready_trino_catalog_name
from products.managed_warehouse.backend.view_translation_status import source_query_hash


@frozen
class ViewTranslationPreparation:
    team_ids: tuple[int, ...]


@activity.defn
def prepare_managed_warehouse_view_translation_activity(job_id: str) -> ViewTranslationPreparation:
    job = ManagedWarehouseViewTranslationJob.objects.select_related("organization").get(id=job_id)
    organization_id = str(job.organization_id)

    if job.started_at is not None:
        team_ids = tuple(
            ManagedWarehouseViewTranslationResult.all_teams.filter(job=job)
            .order_by("team_id")
            .values_list("team_id", flat=True)
            .distinct()
        )
        return ViewTranslationPreparation(team_ids=team_ids)

    if not DuckgresServer.objects.filter(organization_id=organization_id).exists():
        raise ApplicationError("The organization does not have a provisioned managed warehouse", non_retryable=True)
    if get_ready_trino_catalog_name(organization_id) is None:
        raise ApplicationError("The organization's Trino target is not ready", non_retryable=True)

    memberships = list_org_team_memberships(organization_id, use_cache=False)
    if memberships is None:
        raise RuntimeError("The managed warehouse team membership service is unavailable")

    enabled_team_ids = {membership.team_id for membership in memberships if membership.enabled}
    enabled_org_team_ids = tuple(
        Team.objects.filter(id__in=enabled_team_ids, organization_id=organization_id)
        .order_by("id")
        .values_list("id", flat=True)
    )
    saved_queries_query = (
        DataWarehouseSavedQuery.objects.filter(team_id__in=enabled_org_team_ids, deleted=False)
        .exclude(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)
        .only("id", "team_id", "name", "query", "is_materialized")
        .order_by("team_id", "id")
    )
    if job.scope == ManagedWarehouseViewTranslationJob.Scope.ENTIRE_ORGANIZATION:
        if job.selected_saved_query_ids:
            raise ApplicationError(
                "An organization-wide translation job cannot contain selected view IDs",
                non_retryable=True,
            )
        saved_queries = list(saved_queries_query)
        team_ids = enabled_org_team_ids
    elif job.scope == ManagedWarehouseViewTranslationJob.Scope.SELECTED_VIEWS:
        if not isinstance(job.selected_saved_query_ids, list) or not job.selected_saved_query_ids:
            raise ApplicationError("The translation job does not contain selected view IDs", non_retryable=True)
        try:
            selected_saved_query_ids = {UUID(str(value)) for value in job.selected_saved_query_ids}
        except (TypeError, ValueError) as error:
            raise ApplicationError(
                "The translation job contains an invalid selected view ID",
                non_retryable=True,
            ) from error
        saved_queries = list(saved_queries_query.filter(id__in=selected_saved_query_ids))
        if {saved_query.id for saved_query in saved_queries} != selected_saved_query_ids:
            raise ApplicationError(
                "One or more selected views are unavailable or are not enabled for this organization",
                non_retryable=True,
            )
        team_ids = tuple(sorted({saved_query.team_id for saved_query in saved_queries}))
    else:
        raise ApplicationError(f"Unsupported translation scope: {job.scope}", non_retryable=True)

    results = [
        ManagedWarehouseViewTranslationResult(
            job=job,
            team_id=saved_query.team_id,
            saved_query_id=saved_query.id,
            saved_query_name=saved_query.name,
            is_materialized=bool(saved_query.is_materialized),
            source_query_hash=source_query_hash(saved_query.query),
        )
        for saved_query in saved_queries
    ]

    activity_info = activity.info()
    with transaction.atomic():
        ManagedWarehouseViewTranslationResult.all_teams.bulk_create(results, ignore_conflicts=True)
        job.status = ManagedWarehouseViewTranslationJob.Status.RUNNING
        job.started_at = timezone.now()
        job.workflow_id = activity_info.workflow_id
        job.workflow_run_id = activity_info.workflow_run_id
        job.total_count = len(results)
        job.latest_error = None
        job.save(
            update_fields=[
                "status",
                "started_at",
                "workflow_id",
                "workflow_run_id",
                "total_count",
                "latest_error",
                "updated_at",
            ]
        )

    return ViewTranslationPreparation(team_ids=team_ids)


@activity.defn
def compile_managed_warehouse_team_views_activity(job_id: str, team_id: int) -> None:
    job = ManagedWarehouseViewTranslationJob.objects.get(id=job_id)
    team = Team.objects.get(id=team_id, organization_id=job.organization_id)
    results = list(
        ManagedWarehouseViewTranslationResult.all_teams.filter(
            job=job,
            team_id=team_id,
            status=ManagedWarehouseViewTranslationResult.Status.PENDING,
        ).order_by("saved_query_id")
    )
    saved_queries = DataWarehouseSavedQuery.objects.filter(
        id__in=[result.saved_query_id for result in results],
        team_id=team_id,
        deleted=False,
    ).exclude(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)
    saved_queries_by_id = {saved_query.id: saved_query for saved_query in saved_queries}

    for result in results:
        activity.heartbeat(str(result.saved_query_id))
        saved_query = saved_queries_by_id.get(result.saved_query_id)
        if saved_query is None or source_query_hash(saved_query.query) != result.source_query_hash:
            ManagedWarehouseViewTranslationResult.all_teams.filter(id=result.id).update(
                status=ManagedWarehouseViewTranslationResult.Status.STALE,
                error_type="SavedQueryChanged",
                error_message="The saved query changed or was removed after this translation job started",
                processed_at=timezone.now(),
            )
            continue

        try:
            query = HogQLQuery.model_validate(saved_query.query)
            # Views reference other saved queries and warehouse tables, which only the
            # Django-backed expansion can map to their DuckLake relations.
            compiled = compile_hogql_to_trino_sql(
                team_id,
                query,
                team=team,
                bypass_warehouse_access_control=True,
                include_hogql=True,
                expansion_mode=TrinoExpansionMode.DJANGO,
            )
        except Exception as error:
            ManagedWarehouseViewTranslationResult.all_teams.filter(id=result.id).update(
                status=ManagedWarehouseViewTranslationResult.Status.FAILED,
                error_type=type(error).__name__[:255],
                error_message=str(error)[:4000],
                processed_at=timezone.now(),
            )
            continue

        ManagedWarehouseViewTranslationResult.all_teams.filter(id=result.id).update(
            status=ManagedWarehouseViewTranslationResult.Status.COMPILED,
            trino_sql=compiled.sql,
            trino_values=compiled.values,
            normalized_hogql=compiled.hogql,
            error_type=None,
            error_message=None,
            processed_at=timezone.now(),
        )


@activity.defn
def finalize_managed_warehouse_view_translation_activity(job_id: str) -> None:
    job = ManagedWarehouseViewTranslationJob.objects.get(id=job_id)
    results = ManagedWarehouseViewTranslationResult.all_teams.filter(job=job)
    compiled_count = results.filter(status=ManagedWarehouseViewTranslationResult.Status.COMPILED).count()
    failed_count = results.filter(status=ManagedWarehouseViewTranslationResult.Status.FAILED).count()
    stale_count = results.filter(status=ManagedWarehouseViewTranslationResult.Status.STALE).count()
    pending_count = results.filter(status=ManagedWarehouseViewTranslationResult.Status.PENDING).count()

    if pending_count:
        raise RuntimeError(f"{pending_count} managed warehouse view translations remain pending")

    job.status = (
        ManagedWarehouseViewTranslationJob.Status.COMPLETED_WITH_ERRORS
        if failed_count or stale_count
        else ManagedWarehouseViewTranslationJob.Status.COMPLETED
    )
    job.compiled_count = compiled_count
    job.failed_count = failed_count
    job.stale_count = stale_count
    job.finished_at = timezone.now()
    job.latest_error = None
    job.save(
        update_fields=[
            "status",
            "compiled_count",
            "failed_count",
            "stale_count",
            "finished_at",
            "latest_error",
            "updated_at",
        ]
    )


@activity.defn
def fail_managed_warehouse_view_translation_activity(job_id: str, error_message: str) -> None:
    results = ManagedWarehouseViewTranslationResult.all_teams.filter(job_id=job_id)
    ManagedWarehouseViewTranslationJob.objects.filter(id=job_id).update(
        status=ManagedWarehouseViewTranslationJob.Status.FAILED,
        compiled_count=results.filter(status=ManagedWarehouseViewTranslationResult.Status.COMPILED).count(),
        failed_count=results.filter(status=ManagedWarehouseViewTranslationResult.Status.FAILED).count(),
        stale_count=results.filter(status=ManagedWarehouseViewTranslationResult.Status.STALE).count(),
        finished_at=timezone.now(),
        latest_error=error_message[:4000],
    )


@workflow.defn(name="managed-warehouse.translate-views")
class ManagedWarehouseViewTranslationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> str:
        return str(UUID(inputs[0]))

    @workflow.run
    async def run(self, job_id: str) -> None:
        try:
            preparation = await workflow.execute_activity(
                prepare_managed_warehouse_view_translation_activity,
                job_id,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            for team_id in preparation.team_ids:
                await workflow.execute_activity(
                    compile_managed_warehouse_team_views_activity,
                    args=[job_id, team_id],
                    start_to_close_timeout=dt.timedelta(hours=1),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            await workflow.execute_activity(
                finalize_managed_warehouse_view_translation_activity,
                job_id,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception as error:
            await workflow.execute_activity(
                fail_managed_warehouse_view_translation_activity,
                args=[job_id, str(error)],
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
