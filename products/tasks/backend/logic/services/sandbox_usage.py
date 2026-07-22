"""Usage ledger and aggregation for cloud task sandboxes.

One ``SandboxSession`` row per provisioned sandbox records its resource shape and
the boundary timestamps of its lifetime (provisioned / user-attributed / last user
activity / ended). Aggregation preserves raw usage and prices user-created compute
with provisional rates. Pre-warm time is PostHog's cost: a warm sandbox stays
unattributed until a user claims its run with their first message.

The write helpers swallow and log every failure: the ledger must never break
sandbox provisioning, cleanup, or user-message delivery.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from functools import wraps
from math import ceil
from typing import ParamSpec, TypeVar
from uuid import UUID

from django.db.models import F, Q
from django.utils import timezone

import structlog

from products.tasks.backend.logic.services.sandbox import SandboxConfig
from products.tasks.backend.models import SandboxSession, Task, TaskRun

logger = structlog.get_logger(__name__)

PROVISIONAL_MODAL_CPU_USD_PER_CORE_SECOND_WITH_MARGIN = Decimal("0.00001572")
PROVISIONAL_MODAL_MEMORY_USD_PER_GIB_SECOND_WITH_MARGIN = Decimal("0.000002664")
CREDITS_PER_USD = Decimal(100)
BILLABLE_DIRECT_ORIGINS = frozenset(
    {
        Task.OriginProduct.USER_CREATED,
        Task.OriginProduct.IMAGE_BUILDER,
        Task.OriginProduct.AUTOMATION,
    }
)

P = ParamSpec("P")
R = TypeVar("R")


def _best_effort(fn: Callable[P, R]) -> Callable[P, R | None]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("sandbox_usage.ledger_write_failed", helper=fn.__name__)
            return None

    return wrapper


@_best_effort
def open_sandbox_session(
    *, run_id: str | UUID, sandbox_id: str, config: SandboxConfig, sandbox_created_at: datetime | None = None
) -> None:
    """Record a freshly provisioned sandbox against its run.

    ``sandbox_created_at`` is the ``Sandbox.create()`` boundary — the provider's TTL
    clock starts there, minutes before repo setup finishes and this row is opened, so
    the TTL deadline must anchor on it rather than on insert time.

    Reads the live ``TaskRun`` row rather than any workflow-start snapshot: a warm
    run claimed while its sandbox was still provisioning has already lost the
    ``await_user_message`` marker, so the session is created attributed. Upserts on
    ``sandbox_id`` so activity retries stay idempotent, and never regresses
    ``user_attributed_at`` on an existing row.
    """
    run = TaskRun.objects.select_related("task").only("id", "team_id", "state", "task__origin_product").get(id=run_id)
    state = run.state or {}
    created_at = sandbox_created_at or timezone.now()
    shape = {
        "team_id": run.team_id,
        "task_run_id": run.id,
        "origin_product": run.task.origin_product,
        "prewarmed": bool(state.get("prewarmed")),
        "vm_runtime": config.is_vm,
        "cpu_cores": config.cpu_cores,
        "memory_gb": config.memory_gb,
        "ttl_seconds": config.ttl_seconds,
        "burstable": config.burstable_resources,
        "cpu_request_cores": config.cpu_request_cores if config.burstable_resources else None,
        "memory_request_mb": config.memory_request_mb if config.burstable_resources else None,
        "created_at": created_at,
        "ttl_expires_at": created_at + timedelta(seconds=config.ttl_seconds),
    }
    SandboxSession.objects.for_team(run.team_id).update_or_create(
        sandbox_id=sandbox_id,
        defaults=shape,
        create_defaults={
            **shape,
            "user_attributed_at": None if state.get("await_user_message") else timezone.now(),
        },
    )


@_best_effort
def close_sandbox_session(sandbox_id: str, *, reason: str) -> None:
    """Stamp the sandbox's end. Idempotent — the first stamp wins."""
    # Unscoped: cleanup/reap activities only carry the globally-unique provider
    # sandbox id, not team context.
    SandboxSession.objects.unscoped().filter(sandbox_id=sandbox_id, ended_at__isnull=True).update(
        ended_at=timezone.now(), ended_reason=reason
    )


@_best_effort
def record_task_run_user_activity(run_id: str | UUID, team_id: int) -> None:
    """Stamp a user message against the run's open sandbox sessions.

    Sets ``last_user_activity_at`` on every message and ``user_attributed_at``
    set-if-NULL, so the first message both claims a warm sandbox and self-heals the
    race where a claim lands mid-provision (before ``open_sandbox_session`` read the
    run state).
    """
    now = timezone.now()
    run_uuid = run_id if isinstance(run_id, UUID) else UUID(run_id)
    open_sessions = SandboxSession.objects.for_team(team_id).filter(task_run_id=run_uuid, ended_at__isnull=True)
    open_sessions.update(last_user_activity_at=now)
    open_sessions.filter(user_attributed_at__isnull=True).update(user_attributed_at=now)


@dataclass(frozen=True)
class SandboxUsageByTeam:
    """Per-team sandbox usage over a period, as (team_id, amount) rows."""

    seconds: list[tuple[int, int]]
    cpu_core_seconds: list[tuple[int, int]]
    memory_gib_seconds: list[tuple[int, int]]
    sandbox_compute_credits: list[tuple[int, int]]


def get_task_sandbox_usage_by_team(begin: datetime, end: datetime) -> SandboxUsageByTeam:
    """Aggregate user-attributed sandbox time per team over ``[begin, end)``.

    Only the attributed slice of a session bills: ``[user_attributed_at,
    effective_end)``, clipped to the period so sessions spanning report boundaries
    apportion across them. Every end is clamped to ``ttl_expires_at`` — the provider
    kills the sandbox by then regardless, whether cleanup never ran (crashed
    workflows), stamped late, or the session is genuinely live (clamped to now).
    Open rows whose TTL expired before the period are excluded in the query itself,
    so missed close stamps can't grow the scan without bound. Resource-second
    metrics use configured limits. Compute credits use burstable request floors or
    the fixed shape and only include work initiated or configured in the Code app.
    """
    now = timezone.now()
    # Unscoped: the usage report aggregates across every team in the region.
    sessions = (
        SandboxSession.objects.unscoped()
        .annotate(task_loop_internal=F("task_run__task__loop__internal"))
        .filter(
            user_attributed_at__isnull=False,
            user_attributed_at__lt=end,
        )
        .filter(Q(ended_at__isnull=True, ttl_expires_at__gt=begin) | Q(ended_at__gt=begin))
    )

    usage: dict[int, list[float]] = {}
    compute_cost_usd: dict[int, Decimal] = {}
    for session in sessions.iterator():
        assert session.user_attributed_at is not None
        start = max(session.user_attributed_at, begin)
        effective_end = min(session.ended_at or now, session.ttl_expires_at)
        stop = min(effective_end, end)
        if stop <= start:
            continue
        seconds = (stop - start).total_seconds()
        team_usage = usage.setdefault(session.team_id, [0.0, 0.0, 0.0])
        team_usage[0] += seconds
        team_usage[1] += seconds * session.cpu_cores
        team_usage[2] += seconds * session.memory_gb
        is_billable_loop = (
            session.origin_product == Task.OriginProduct.LOOP and getattr(session, "task_loop_internal", None) is False
        )
        if session.origin_product in BILLABLE_DIRECT_ORIGINS or is_billable_loop:
            billable_seconds = Decimal(ceil(seconds))
            if session.burstable:
                assert session.cpu_request_cores is not None
                assert session.memory_request_mb is not None
            cpu_cores = session.cpu_request_cores if session.burstable else session.cpu_cores
            memory_gib = (
                Decimal(str(session.memory_request_mb)) / Decimal(1024)
                if session.burstable
                else Decimal(str(session.memory_gb))
            )
            session_cost = billable_seconds * (
                Decimal(str(cpu_cores)) * PROVISIONAL_MODAL_CPU_USD_PER_CORE_SECOND_WITH_MARGIN
                + memory_gib * PROVISIONAL_MODAL_MEMORY_USD_PER_GIB_SECOND_WITH_MARGIN
            )
            compute_cost_usd[session.team_id] = compute_cost_usd.get(session.team_id, Decimal(0)) + session_cost

    return SandboxUsageByTeam(
        seconds=[(team_id, round(totals[0])) for team_id, totals in usage.items()],
        cpu_core_seconds=[(team_id, round(totals[1])) for team_id, totals in usage.items()],
        memory_gib_seconds=[(team_id, round(totals[2])) for team_id, totals in usage.items()],
        sandbox_compute_credits=[
            (team_id, int((cost * CREDITS_PER_USD).to_integral_value(rounding=ROUND_CEILING)))
            for team_id, cost in compute_cost_usd.items()
        ],
    )
