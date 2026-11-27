import json
import hashlib
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.workload import Workload
from posthog.exceptions import Conflict
from posthog.models import Team, User

from products.authorization.backend.facade import api as authorization
from products.authorization.backend.facade.contracts import Resource, Subject
from products.authorization.backend.facade.enums import Action, ResourceType
from products.notebooks.backend.app_releases import read_release
from products.notebooks.backend.app_runtime_checks import (
    RuntimeCheckFailed,
    check_targets,
    reserve_check_capacity,
    run_checks,
    validate_checks,
)
from products.notebooks.backend.app_viewer import resolve_viewer_queries
from products.notebooks.backend.facade.contracts import AppRefreshedOutput, AppRefreshHistory, AppRefreshStatus
from products.notebooks.backend.models import Notebook, NotebookAppRefreshRun, NotebookAppSchedule
from products.notebooks.backend.presentation.app_serializers import notebook_app_builder_enabled
from products.notebooks.backend.sql_v2_direct import apply_page_bounds
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    SourceType,
    TargetType,
    create_notification,
)
from products.security.backend.facade.api import access_refused
from products.security.backend.facade.contracts import SubjectInput
from products.security.backend.facade.enums import Surface

logger = structlog.get_logger(__name__)
MAX_QUERIES = 20
MAX_ROWS = 1000
MAX_BYTES = 2 * 1024 * 1024
RUN_TIMEOUT = timedelta(minutes=15)
HISTORY_SIZE = 20
MAX_SCHEDULES_PER_TEAM = 50


def current_plans(notebook: Notebook, revision: int, checked_node_ids: list[str] | None = None):
    release = read_release(notebook.team_id, notebook.pk)
    if (
        release is None
        or release.revision != revision
        or notebook.app_revision != revision
        or release.published_at is None
    ):
        raise Conflict("A new release needs a new refresh schedule.")
    plans = resolve_viewer_queries(release, {})
    if checked_node_ids:
        validate_checks(release, checked_node_ids)
    if (not plans and not checked_node_ids) or len(plans) > MAX_QUERIES:
        raise ValidationError(
            f"Choose at least one SQL output or runtime check, with at most {MAX_QUERIES} native SQL outputs."
        )
    return plans


def check_query_access(notebook: Notebook, user: User, action: Action) -> None:
    subject = Subject(user_id=user.pk)
    resources = (
        (Resource.project(notebook.team_id), Action.VIEW),
        (
            Resource(
                type=ResourceType.NOTEBOOK,
                id=str(notebook.pk),
                project_id=notebook.team_id,
                created_by_id=notebook.created_by_id,
            ),
            action,
        ),
        (Resource(type=ResourceType.QUERY, project_id=notebook.team_id), Action.VIEW),
    )
    if (
        not user.is_active
        or access_refused(
            SubjectInput(email=user.email, user_uuid=str(user.uuid)), Surface.APP, call_site="notebook_app_refresh"
        )
        or any(
            not authorization.check(resource=resource, subject=subject, action=level) for resource, level in resources
        )
    ):
        raise PermissionDenied()


def configure(
    team_id: int,
    notebook_id: UUID,
    user_id: int,
    revision: int,
    interval: int,
    freshness: int,
    enabled: bool,
    checked_node_ids: list[str] | None = None,
) -> None:
    now = timezone.now()
    user = User.objects.get(pk=user_id)
    with transaction.atomic():
        locked = Notebook.objects.select_for_update().get(team_id=team_id, pk=notebook_id)
        check_query_access(locked, user, Action.EDIT)
        if not enabled:
            release = read_release(locked.team_id, locked.pk)
            if release is None or release.revision != revision:
                raise Conflict("A new release needs a new refresh schedule.")
            NotebookAppSchedule.objects.for_team(locked.team_id).filter(notebook=locked).update(enabled=False)
            return
        checks = sorted(checked_node_ids or [])
        current_plans(locked, revision, checks)
        reserve_check_capacity(locked, user, checks)
        Team.objects.select_for_update().only("pk").get(pk=team_id)
        active = NotebookAppSchedule.objects.for_team(team_id).filter(enabled=True)
        if active.exclude(notebook=locked).count() >= MAX_SCHEDULES_PER_TEAM:
            raise ValidationError(f"A project can have up to {MAX_SCHEDULES_PER_TEAM} active app schedules.")
        schedule, created = (
            NotebookAppSchedule.objects.for_team(locked.team_id)
            .select_for_update()
            .get_or_create(
                notebook=locked,
                defaults={
                    "team_id": locked.team_id,
                    "owner": user,
                    "revision": revision,
                    "interval_minutes": interval,
                    "freshness_minutes": freshness,
                    "next_due_at": now,
                },
            )
        )
        if (
            not created
            and schedule.enabled
            and schedule.checked_node_ids == checks
            and (schedule.owner_id, schedule.revision, schedule.interval_minutes, schedule.freshness_minutes)
            == (user.pk, revision, interval, freshness)
        ):
            return
        if not created and (
            schedule.revision != revision
            or schedule.owner_id != user.pk
            or (schedule.checked_node_ids and not checks and not schedule.outputs)
        ):
            schedule.last_success_at = None
            schedule.outputs = {}
        schedule.checked_node_ids = checks
        schedule.owner = user
        schedule.revision = revision
        schedule.interval_minutes = interval
        schedule.freshness_minutes = freshness
        schedule.configured_at = now
        if not created:
            schedule.next_due_at = max(schedule.next_due_at, now + timedelta(minutes=interval))
        schedule.stale_at = (schedule.last_success_at or now) + timedelta(minutes=freshness)
        schedule.enabled = True
        schedule.stale_notified = False
        schedule.save()


def refresh_status(team_id: int, notebook_id: UUID, reader_id: int | None = None) -> AppRefreshStatus:
    schedule = NotebookAppSchedule.objects.for_team(team_id).filter(notebook_id=notebook_id).defer("outputs").first()
    release = read_release(team_id, notebook_id)
    if release is None:
        raise Conflict("The app is no longer published.")
    published_revision = release.revision
    targets = check_targets(release)
    if not schedule:
        return AppRefreshStatus(published_revision=published_revision, enabled=False, history=[], check_targets=targets)
    if schedule.checked_node_ids and reader_id != schedule.owner_id:
        return AppRefreshStatus(
            published_revision=published_revision,
            enabled=schedule.enabled,
            history=[],
            check_targets=targets,
            revision=schedule.revision,
            interval_minutes=schedule.interval_minutes,
            freshness_minutes=schedule.freshness_minutes,
            next_due_at=schedule.next_due_at,
        )
    runs = (
        NotebookAppRefreshRun.objects.for_team(team_id)
        .filter(schedule=schedule, due_at__gte=schedule.configured_at)
        .order_by("-due_at")
    )
    if reader_id is not None:
        runs = runs.filter(owner_id=schedule.owner_id)
    threshold = (schedule.last_success_at or schedule.configured_at) + timedelta(minutes=schedule.freshness_minutes)
    return AppRefreshStatus(
        published_revision=published_revision,
        enabled=schedule.enabled,
        check_targets=targets,
        checked_node_ids=schedule.checked_node_ids,
        revision=schedule.revision,
        interval_minutes=schedule.interval_minutes,
        freshness_minutes=schedule.freshness_minutes,
        next_due_at=schedule.next_due_at,
        last_success_at=schedule.last_success_at,
        stale=schedule.enabled and timezone.now() >= threshold,
        history=[
            AppRefreshHistory(
                due_at=run.due_at,
                finished_at=run.finished_at,
                revision=run.revision,
                status=run.status,
                detail=run.detail,
                output_count=run.output_count,
                checked_count=run.checked_count,
                duration_seconds=(run.finished_at - run.started_at).total_seconds()
                if run.finished_at and run.started_at
                else None,
            )
            for run in runs[:HISTORY_SIZE]
        ],
    )


def read_outputs(team_id: int, notebook_id: UUID, user_id: int, revision: int) -> dict[str, AppRefreshedOutput]:
    schedule = (
        NotebookAppSchedule.objects.for_team(team_id)
        .select_related("notebook__team__organization")
        .filter(notebook_id=notebook_id, revision=revision, last_success_at__isnull=False)
        .first()
    )
    if not schedule or not schedule.outputs:
        return {}
    notebook, user = schedule.notebook, User.objects.get(pk=user_id)
    check_query_access(notebook, user, Action.VIEW)
    database = query_catalog(notebook, user)
    visible: dict[str, AppRefreshedOutput] = {}
    for plan in current_plans(notebook, revision):
        cached = schedule.outputs.get(plan.node_id)
        if not cached:
            continue
        executor = query_executor(plan.query, notebook, user, database)
        try:
            sql, context = executor.generate_clickhouse_sql()
        except ExposedHogQLError:
            continue
        if (
            not context.external_tables
            and executor.direct_sql is None
            and cached["scope"] == result_scope(sql, context)
        ):
            visible[plan.node_id] = AppRefreshedOutput(**cached["result"])
    return visible


def query_catalog(notebook: Notebook, user: User) -> Database:
    database = Database.create_for(team=notebook.team, user=user, build_postgres_foreign_keys=False)
    access = database.user_access_control
    if access is None or access.user.pk != user.pk:
        raise PermissionDenied()
    return database


def query_executor(query: str, notebook: Notebook, user: User, database: Database) -> HogQLQueryExecutor:
    return HogQLQueryExecutor(
        query=apply_page_bounds(query, MAX_ROWS + 1, 0),
        team=notebook.team,
        user=user,
        context=HogQLContext(
            database=database,
            team_id=notebook.team_id,
            team=notebook.team,
            user=user,
            user_access_control=database.user_access_control,
        ),
        user_access_control=database.user_access_control,
        workload=Workload.OFFLINE,
        limit_context=LimitContext.QUERY,
        query_type="notebook_app_refresh",
        returned_row_limit=MAX_ROWS + 1,
    )


def result_scope(sql: str, context: HogQLContext) -> str:
    # Row filters can bind different parameters even when two readers can access the same tables.
    if context.external_tables:
        raise ValidationError("This output uses temporary tables and cannot be cached.")
    restrictions = sorted(repr(prop) for prop in context.restricted_properties or ())
    return hashlib.sha256(
        json.dumps([sql, context.values, restrictions], default=str, sort_keys=True).encode()
    ).hexdigest()


def refresh_outputs(schedule: NotebookAppSchedule) -> dict[str, Any]:
    owner, notebook = schedule.owner, schedule.notebook
    check_query_access(notebook, owner, Action.EDIT)
    if not notebook_app_builder_enabled(owner, notebook.team):
        raise PermissionDenied()
    outputs: dict[str, Any] = {}
    plans = current_plans(notebook, schedule.revision, schedule.checked_node_ids)
    if not plans:
        return outputs
    database = query_catalog(notebook, owner)
    for plan in plans:
        executor = query_executor(plan.query, notebook, owner, database)
        sql, context = executor.generate_clickhouse_sql()
        if executor.direct_sql is not None or executor.clickhouse_sql is None:
            raise ValidationError("Scheduled refresh supports native SQL outputs.")
        scope = result_scope(sql, context)
        result = query_executor(plan.query, notebook, owner, database).execute()
        if result.error:
            raise ValidationError("A SQL output failed.")
        payload = result.model_dump(mode="json", include={"columns", "results", "types", "hasMore"})
        if len(payload["results"]) > MAX_ROWS:
            payload["results"] = payload["results"][:MAX_ROWS]
            payload["hasMore"] = True
        outputs[plan.node_id] = {
            "result": payload,
            "scope": scope,
        }
        if len(json.dumps(outputs, ensure_ascii=False, allow_nan=False).encode()) > MAX_BYTES:
            raise ValidationError("The refreshed results exceed the snapshot size limit.")
    return outputs


def notify_owner(schedule: NotebookAppSchedule, title: str, key: str, *, owner_id: int | None = None) -> None:
    create_notification(
        NotificationData(
            notification_type=NotificationType.NOTEBOOK_APP_REFRESH,
            title=title,
            body="Open the published notebook app to review its refresh history.",
            team_id=schedule.team_id,
            target_type=TargetType.USER,
            target_id=str(owner_id or schedule.owner_id),
            source_type=SourceType.NOTEBOOK,
            source_id=str(schedule.notebook_id),
            resource_type="notebook",
            resource_id=str(schedule.notebook_id),
            source_url=f"/project/{schedule.team_id}/notebooks/{schedule.notebook.short_id}?view=app",
            idempotency_key=key,
        )
    )


def store_sql_outputs(schedule: NotebookAppSchedule, outputs: dict[str, Any]) -> None:
    now = timezone.now()
    schedule.outputs = outputs
    schedule.last_success_at = now
    schedule.stale_at = now + timedelta(minutes=schedule.freshness_minutes)
    schedule.stale_notified = False
    schedule.save(update_fields=["outputs", "last_success_at", "stale_at", "stale_notified"])


def publish_sql_before_checks(run: NotebookAppRefreshRun, outputs: dict[str, Any]) -> bool:
    with transaction.atomic():
        schedule = (
            NotebookAppSchedule.objects.for_team(run.team_id)
            .select_for_update()
            .filter(
                pk=run.schedule_id,
                owner_id=run.owner_id,
                enabled=True,
                revision=run.revision,
                configured_at__lte=run.due_at,
            )
            .first()
        )
        if (
            schedule is None
            or not NotebookAppRefreshRun.objects.for_team(run.team_id)
            .filter(pk=run.pk, status=NotebookAppRefreshRun.Status.RUNNING)
            .exists()
        ):
            return False
        store_sql_outputs(schedule, outputs)
        return True


def finish_run(
    run: NotebookAppRefreshRun,
    outputs: dict[str, Any] | None,
    detail: str,
    *,
    obsolete: bool = False,
    checked_count: int = 0,
) -> None:
    now = timezone.now()
    with transaction.atomic():
        schedule = (
            NotebookAppSchedule.objects.for_team(run.team_id).select_for_update().filter(pk=run.schedule_id).first()
        )
        if not schedule:
            return
        runs = NotebookAppRefreshRun.objects.for_team(run.team_id).filter(schedule=schedule)
        if (
            not schedule.enabled
            or schedule.owner_id != run.owner_id
            or schedule.revision != run.revision
            or run.due_at < schedule.configured_at
        ):
            outputs, detail = None, "The schedule changed before this run finished."
        state = NotebookAppRefreshRun.Status
        updated = runs.filter(pk=run.pk, status=state.RUNNING).update(
            status=state.SUCCEEDED if outputs is not None and not detail else state.FAILED,
            finished_at=now,
            detail=detail,
            output_count=len(outputs or {}),
            checked_count=checked_count,
        )
        if not updated:
            return
        if outputs is not None and not detail and not (outputs and schedule.checked_node_ids):
            store_sql_outputs(schedule, outputs)
        if detail and schedule.enabled and run.due_at >= schedule.configured_at:
            previous = (
                runs.filter(due_at__gte=schedule.configured_at, due_at__lt=run.due_at)
                .order_by("-due_at")
                .values_list("status", flat=True)
                .first()
            )
            if obsolete and schedule.revision == run.revision:
                schedule.enabled = False
                schedule.save(update_fields=["enabled"])
            if previous != state.FAILED:
                runs.filter(pk=run.pk).update(failure_notification_pending=True)
                transaction.on_commit(lambda: deliver_failure(run.team_id, run.pk))
        runs.exclude(pk__in=runs.order_by("-due_at").values("pk")[:HISTORY_SIZE]).exclude(
            status__in=[state.RUNNING, state.QUEUED]
        ).exclude(failure_notification_pending=True).delete()


def deliver_failure(team_id: int, run_id: UUID) -> None:
    pending = NotebookAppRefreshRun.objects.for_team(team_id).filter(pk=run_id, failure_notification_pending=True)
    run = pending.select_related("schedule__notebook").first()
    if run is None or run.owner_id is None:
        return
    try:
        notify_owner(run.schedule, "Notebook app refresh failed", f"notebook:refresh:{run.pk}", owner_id=run.owner_id)
    except Exception:
        logger.exception("notebook_app_refresh_notification_failed", run_id=str(run.pk))
        return
    pending.update(failure_notification_pending=False)


def run_slot(team_id: int, run_id: UUID) -> None:
    runs = NotebookAppRefreshRun.objects.for_team(team_id)
    if not runs.filter(pk=run_id, status=NotebookAppRefreshRun.Status.QUEUED).update(
        status=NotebookAppRefreshRun.Status.RUNNING, started_at=timezone.now()
    ):
        return
    run = runs.select_related("schedule__owner", "schedule__notebook__team__organization").filter(pk=run_id).first()
    if run is None:
        return
    try:
        if not run.schedule.enabled or run.owner_id != run.schedule.owner_id or run.due_at < run.schedule.configured_at:
            finish_run(run, None, "This schedule was changed.")
            return
        outputs = refresh_outputs(run.schedule)
        checks = run.schedule.checked_node_ids
        if checks and outputs and not publish_sql_before_checks(run, outputs):
            finish_run(run, None, "This schedule was changed.")
            return
        run_checks(
            run.schedule.notebook,
            run.schedule.owner_id,
            run.revision,
            checks,
            lambda notebook, owner: check_query_access(notebook, owner, Action.EDIT),
        )
    except RuntimeCheckFailed as failure:
        finish_run(
            run,
            outputs,
            f"Runtime check failed for {failure.node_id}. Open the app and run the cell to inspect it.",
            checked_count=failure.completed,
        )
    except PermissionDenied:
        finish_run(run, None, "The schedule owner no longer has access.")
    except Conflict:
        finish_run(run, None, "A new release needs a new refresh schedule.", obsolete=True)
    except Exception:
        logger.exception("notebook_app_refresh_failed", run_id=str(run.pk))
        finish_run(run, None, "Could not refresh the SQL results.")
    else:
        finish_run(run, outputs, "", checked_count=len(checks))
