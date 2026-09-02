import random
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Protocol

from django.db import close_old_connections, transaction
from django.db.models import Count, F, Min, Q
from django.utils import timezone as django_timezone

from posthog.dataclasses import frozen
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.metrics import (
    WORKFLOW_DISPATCH_CLAIMED,
    WORKFLOW_DISPATCH_CREATED_TOTAL,
    WORKFLOW_DISPATCH_DEAD_TOTAL,
    WORKFLOW_DISPATCH_LEASE_EXPIRED_TOTAL,
    WORKFLOW_DISPATCH_OLDEST_READY_AGE_SECONDS,
    WORKFLOW_DISPATCH_READY,
    observe_task_run_dispatch_callback,
)
from products.tasks.backend.models import TaskRun, TaskWorkflowDispatch, execute_after_commit
from products.tasks.backend.temporal.process_task.workflow import PendingFollowup

DISPATCH_PAYLOAD_VERSION = 1


@frozen
class WorkflowDispatchOptions:
    user_id: int | None = None
    create_pr: bool = True
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"
    slack_thread_context: dict[str, Any] | None = None
    prewarmed: bool = False
    workflow_id_prefix: str | None = None
    initial_message: PendingFollowup | None = None
    skip_user_check: bool = False


@frozen
class RestartSnapshot:
    status: str
    environment: str
    completed_at: str | None
    queued_at: str | None
    state: dict[str, Any]


@frozen
class WorkflowDispatchFlags:
    shadow_enabled: bool
    async_enabled: bool


class SlackThreadContextLike(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


def build_create_payload(options: WorkflowDispatchOptions) -> dict[str, Any]:
    return {
        "version": DISPATCH_PAYLOAD_VERSION,
        "user_id": options.user_id,
        "create_pr": options.create_pr,
        "posthog_mcp_scopes": options.posthog_mcp_scopes,
        "slack_thread_context": options.slack_thread_context,
        "prewarmed": options.prewarmed,
        "skip_user_check": options.skip_user_check,
        "initial_message": asdict(options.initial_message) if options.initial_message else None,
    }


def parse_create_payload(payload: dict[str, Any]) -> WorkflowDispatchOptions:
    if payload.get("version") != DISPATCH_PAYLOAD_VERSION:
        raise ValueError("Unsupported workflow dispatch payload version")
    initial_message = payload.get("initial_message")
    return WorkflowDispatchOptions(
        user_id=payload.get("user_id"),
        create_pr=payload["create_pr"],
        posthog_mcp_scopes=payload["posthog_mcp_scopes"],
        slack_thread_context=payload.get("slack_thread_context"),
        prewarmed=payload.get("prewarmed", False),
        skip_user_check=payload.get("skip_user_check", False),
        initial_message=PendingFollowup(**initial_message) if initial_message else None,
    )


def build_restart_payload(user_id: int | None, snapshot: RestartSnapshot) -> dict[str, Any]:
    return {"version": DISPATCH_PAYLOAD_VERSION, "user_id": user_id, "snapshot": asdict(snapshot)}


def parse_restart_payload(payload: dict[str, Any]) -> tuple[int | None, RestartSnapshot]:
    if payload.get("version") != DISPATCH_PAYLOAD_VERSION:
        raise ValueError("Unsupported workflow dispatch payload version")
    return payload.get("user_id"), RestartSnapshot(**payload["snapshot"])


def create_dispatch(task_run: TaskRun, kind: str, payload: dict[str, Any], workflow_id: str) -> TaskWorkflowDispatch:
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Workflow dispatch creation requires an atomic transaction")
    defaults = {
        "team_id": task_run.team_id,
        "workflow_id": workflow_id,
        "payload": payload,
        "status": TaskWorkflowDispatch.Status.PENDING,
        "attempt_count": 0,
        "next_attempt_at": django_timezone.now(),
        "claimed_by": "",
        "lease_expires_at": None,
        "accepted_at": None,
        "last_error": "",
        "enqueued_at": django_timezone.now(),
    }
    queryset = TaskWorkflowDispatch.objects.for_team(task_run.team_id)
    if kind == TaskWorkflowDispatch.Kind.RESTART:
        dispatch, created = queryset.update_or_create(task_run=task_run, dispatch_kind=kind, defaults=defaults)
    else:
        dispatch, created = queryset.get_or_create(task_run=task_run, dispatch_kind=kind, defaults=defaults)
    if created:
        WORKFLOW_DISPATCH_CREATED_TOTAL.labels(kind=kind).inc()
    return dispatch


def claim_dispatches(instance_id: str, batch_size: int, lease: timedelta) -> list[TaskWorkflowDispatch]:
    now = django_timezone.now()
    with transaction.atomic():
        # This process intentionally claims work across every team.
        rows = list(
            TaskWorkflowDispatch.objects.unscoped()
            .filter(
                Q(status=TaskWorkflowDispatch.Status.PENDING, next_attempt_at__lte=now)
                | Q(status=TaskWorkflowDispatch.Status.CLAIMED, lease_expires_at__lte=now)
            )
            .order_by("next_attempt_at", "created_at")
            .select_for_update(skip_locked=True)[:batch_size]
        )
        expired_count = sum(row.status == TaskWorkflowDispatch.Status.CLAIMED for row in rows)
        if expired_count:
            WORKFLOW_DISPATCH_LEASE_EXPIRED_TOTAL.inc(expired_count)
        ids = [row.id for row in rows]
        TaskWorkflowDispatch.objects.unscoped().filter(id__in=ids).update(
            status=TaskWorkflowDispatch.Status.CLAIMED,
            claimed_by=instance_id,
            lease_expires_at=now + lease,
            attempt_count=F("attempt_count") + 1,
        )
        return list(
            TaskWorkflowDispatch.objects.unscoped().filter(id__in=ids).order_by("next_attempt_at", "created_at")
        )


def sample_dispatch_metrics() -> None:
    now = django_timezone.now()
    values = (
        TaskWorkflowDispatch.objects.unscoped()
        .filter(status__in=[TaskWorkflowDispatch.Status.PENDING, TaskWorkflowDispatch.Status.CLAIMED])
        .aggregate(
            ready=Count("id", filter=Q(status=TaskWorkflowDispatch.Status.PENDING, next_attempt_at__lte=now)),
            claimed=Count("id", filter=Q(status=TaskWorkflowDispatch.Status.CLAIMED)),
            oldest_ready=Min(
                "enqueued_at", filter=Q(status=TaskWorkflowDispatch.Status.PENDING, next_attempt_at__lte=now)
            ),
        )
    )
    WORKFLOW_DISPATCH_READY.set(values["ready"] or 0)
    WORKFLOW_DISPATCH_CLAIMED.set(values["claimed"] or 0)
    oldest = values["oldest_ready"]
    WORKFLOW_DISPATCH_OLDEST_READY_AGE_SECONDS.set(max(0.0, (now - oldest).total_seconds()) if oldest else 0)


def dispatch_exceeded_max_age(
    dispatch: TaskWorkflowDispatch, max_age_seconds: int, *, now: datetime | None = None
) -> bool:
    current_time = now or django_timezone.now()
    return current_time - dispatch.enqueued_at > timedelta(seconds=max_age_seconds)


def renew_leases(instance_id: str, dispatch_ids: list[Any], lease: timedelta) -> int:
    return (
        TaskWorkflowDispatch.objects.unscoped()
        .filter(id__in=dispatch_ids, claimed_by=instance_id, status=TaskWorkflowDispatch.Status.CLAIMED)
        .update(lease_expires_at=django_timezone.now() + lease)
    )


def mark_accepted(dispatch_id: Any, instance_id: str) -> int:
    return (
        TaskWorkflowDispatch.objects.unscoped()
        .filter(id=dispatch_id, claimed_by=instance_id, status=TaskWorkflowDispatch.Status.CLAIMED)
        .update(
            status=TaskWorkflowDispatch.Status.ACCEPTED,
            accepted_at=django_timezone.now(),
            claimed_by="",
            lease_expires_at=None,
        )
    )


def reschedule(dispatch_id: Any, instance_id: str, error: str) -> int:
    dispatch = TaskWorkflowDispatch.objects.unscoped().get(id=dispatch_id)
    delay = random.uniform(1.0, 2.0 ** min(dispatch.attempt_count, 8))
    return (
        TaskWorkflowDispatch.objects.unscoped()
        .filter(id=dispatch_id, claimed_by=instance_id, status=TaskWorkflowDispatch.Status.CLAIMED)
        .update(
            status=TaskWorkflowDispatch.Status.PENDING,
            next_attempt_at=django_timezone.now() + timedelta(seconds=delay),
            last_error=error[:2000],
            claimed_by="",
            lease_expires_at=None,
        )
    )


def release_claims(instance_id: str) -> int:
    return (
        TaskWorkflowDispatch.objects.unscoped()
        .filter(claimed_by=instance_id, status=TaskWorkflowDispatch.Status.CLAIMED)
        .update(status=TaskWorkflowDispatch.Status.PENDING, claimed_by="", lease_expires_at=None)
    )


def mark_dead(dispatch_id: Any, instance_id: str, error: str, reason: str = "payload") -> int:
    with transaction.atomic():
        dispatch = (
            TaskWorkflowDispatch.objects.unscoped().select_for_update().select_related("task_run").get(id=dispatch_id)
        )
        if dispatch.claimed_by != instance_id or dispatch.status != TaskWorkflowDispatch.Status.CLAIMED:
            return 0
        dispatch.status = TaskWorkflowDispatch.Status.DEAD
        dispatch.last_error = error[:2000]
        dispatch.claimed_by = ""
        dispatch.lease_expires_at = None
        dispatch.save(update_fields=["status", "last_error", "claimed_by", "lease_expires_at", "updated_at"])
        WORKFLOW_DISPATCH_DEAD_TOTAL.labels(kind=dispatch.dispatch_kind, reason=reason).inc()
        run = dispatch.task_run
        if dispatch.dispatch_kind == TaskWorkflowDispatch.Kind.RESTART:
            try:
                _, snapshot = parse_restart_payload(dispatch.payload)
            except (KeyError, TypeError, ValueError):
                from products.tasks.backend.temporal.client import _terminalize_unstarted_task_run  # noqa: PLC0415

                transaction.on_commit(lambda: _terminalize_unstarted_task_run(str(run.id), error[:2000]))
                return 1
            run.status = snapshot.status
            run.environment = snapshot.environment
            run.completed_at = datetime.fromisoformat(snapshot.completed_at) if snapshot.completed_at else None
            run.queued_at = datetime.fromisoformat(snapshot.queued_at) if snapshot.queued_at else None
            run.state = snapshot.state
            run.error_message = "Failed to start cloud workflow"
        else:
            from products.tasks.backend.temporal.client import _terminalize_unstarted_task_run  # noqa: PLC0415

            execute_after_commit(lambda: _terminalize_unstarted_task_run(str(run.id), error[:2000]))
            return 1
        run.save(
            update_fields=[
                "status",
                "environment",
                "completed_at",
                "queued_at",
                "state",
                "error_message",
                "updated_at",
            ]
        )
        execute_after_commit(run.publish_stream_state_event)
        return 1


def resolve_ineligible(dispatch_id: Any, instance_id: str) -> int:
    updated = mark_accepted(dispatch_id, instance_id)
    if updated:
        TaskWorkflowDispatch.objects.unscoped().filter(id=dispatch_id).update(last_error="resolved: run left QUEUED")
    return updated


def renew_leases_in_worker_thread(instance_id: str, dispatch_ids: list[Any], lease: timedelta) -> int:
    """Renew leases without retaining a connection owned by the shared thread pool."""
    close_old_connections()
    try:
        return renew_leases(instance_id, dispatch_ids, lease)
    finally:
        close_old_connections()


def evaluate_workflow_dispatch_flags(task_run: TaskRun) -> WorkflowDispatchFlags:
    from products.tasks.backend.feature_flags import (
        is_workflow_dispatch_async_enabled,
        is_workflow_dispatch_shadow_enabled,
    )

    distinct_id = (
        task_run.task.created_by.distinct_id
        if task_run.task.created_by and task_run.task.created_by.distinct_id
        else str(task_run.id)
    )
    organization_id = str(task_run.task.team.organization_id)
    return WorkflowDispatchFlags(
        shadow_enabled=is_workflow_dispatch_shadow_enabled(),
        async_enabled=is_workflow_dispatch_async_enabled(organization_id, distinct_id),
    )


def enqueue_or_start_workflow(
    task_run: TaskRun,
    *,
    options: WorkflowDispatchOptions,
    precomputed_flags: WorkflowDispatchFlags | None = None,
    start_workflow: Callable[..., None] | None = None,
) -> None:
    if start_workflow is None:
        from products.tasks.backend.temporal.client import execute_task_processing_workflow

        start_workflow = execute_task_processing_workflow

    flags = precomputed_flags or evaluate_workflow_dispatch_flags(task_run)
    workflow_id = TaskRun.get_workflow_id(str(task_run.task_id), str(task_run.id), options.workflow_id_prefix)
    if options.workflow_id_prefix:
        TaskRun.update_state_atomic(task_run.id, updates={"workflow_id": workflow_id})
        task_run.state = {**(task_run.state or {}), "workflow_id": workflow_id}
    dispatch_written = False
    if flags.shadow_enabled or flags.async_enabled:
        if transaction.get_connection().in_atomic_block:
            create_dispatch(task_run, TaskWorkflowDispatch.Kind.CREATE, build_create_payload(options), workflow_id)
        else:
            with transaction.atomic():
                locked_run = (
                    TaskRun.objects.select_for_update().select_related("task", "task__team").get(id=task_run.id)
                )
                create_dispatch(
                    locked_run, TaskWorkflowDispatch.Kind.CREATE, build_create_payload(options), workflow_id
                )
        dispatch_written = True
    if flags.async_enabled:
        return

    def start_synchronously() -> None:
        observe_task_run_dispatch_callback(task_run, phase="fired")
        workflow_kwargs: dict[str, Any] = {
            "task_id": str(task_run.task_id),
            "run_id": str(task_run.id),
            "team_id": task_run.team_id,
            "user_id": options.user_id,
            "posthog_mcp_scopes": options.posthog_mcp_scopes,
        }
        if not options.create_pr:
            workflow_kwargs["create_pr"] = False
        if options.slack_thread_context is not None:
            workflow_kwargs["slack_thread_context"] = options.slack_thread_context
        if options.prewarmed:
            workflow_kwargs["prewarmed"] = True
        if options.workflow_id_prefix is not None:
            workflow_kwargs["workflow_id_prefix"] = options.workflow_id_prefix
        if options.initial_message is not None:
            workflow_kwargs["initial_message"] = options.initial_message
        if options.skip_user_check:
            workflow_kwargs["skip_user_check"] = True
        if dispatch_written:
            workflow_kwargs["durable_dispatch"] = True
        start_workflow(**workflow_kwargs)

    execute_after_commit(start_synchronously)


async def aenqueue_or_start_workflow(task_run: TaskRun, *, options: WorkflowDispatchOptions) -> None:
    from asgiref.sync import sync_to_async

    await sync_to_async(enqueue_or_start_workflow)(task_run, options=options)


def dispatch_task_processing_workflow(
    task_id: str,
    run_id: str,
    team_id: int,
    user_id: int | None = None,
    create_pr: bool = True,
    slack_thread_context: "SlackThreadContextLike | dict[str, Any] | None" = None,
    skip_user_check: bool = False,
    posthog_mcp_scopes: PosthogMcpScopes = "read_only",
) -> None:
    """Outbox-aware drop-in for ``execute_task_processing_workflow`` when the caller did not create the run itself."""
    if slack_thread_context is None or isinstance(slack_thread_context, dict):
        normalized_context = slack_thread_context
    else:
        normalized_context = slack_thread_context.to_dict()
    task_run = TaskRun.objects.select_related("task", "task__team", "task__created_by").get(
        id=run_id, task_id=task_id, team_id=team_id
    )
    enqueue_or_start_workflow(
        task_run,
        options=WorkflowDispatchOptions(
            user_id=user_id,
            create_pr=create_pr,
            slack_thread_context=normalized_context,
            posthog_mcp_scopes=posthog_mcp_scopes,
            skip_user_check=skip_user_check,
        ),
    )
