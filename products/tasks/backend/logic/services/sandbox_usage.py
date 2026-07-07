"""Raw usage ledger for cloud task sandboxes.

One ``SandboxSession`` row per provisioned sandbox records its resource shape and
the boundary timestamps of its lifetime (provisioned / user-attributed / last user
activity / ended). The ledger stores raw usage only — no pricing or credit
conversion — so any billable-window policy can be computed later without a
backfill. Pre-warm time is PostHog's cost: a warm sandbox stays unattributed until
a user claims its run with their first message.

The write helpers swallow and log every failure: the ledger must never break
sandbox provisioning, cleanup, or user-message delivery.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

import structlog

from products.tasks.backend.logic.services.sandbox import SandboxConfig
from products.tasks.backend.models import SandboxSession, TaskRun

logger = structlog.get_logger(__name__)


def _best_effort(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("sandbox_usage.ledger_write_failed", helper=fn.__name__)
            return None

    return wrapper


@_best_effort
def open_sandbox_session(*, run_id: str | UUID, sandbox_id: str, config: SandboxConfig) -> None:
    """Record a freshly provisioned sandbox against its run.

    Reads the live ``TaskRun`` row rather than any workflow-start snapshot: a warm
    run claimed while its sandbox was still provisioning has already lost the
    ``await_user_message`` marker, so the session is created attributed. Upserts on
    ``sandbox_id`` so activity retries stay idempotent, and never regresses
    ``user_attributed_at`` on an existing row.
    """
    run = TaskRun.objects.only("id", "team_id", "state").get(id=run_id)
    state = run.state or {}
    shape = {
        "team_id": run.team_id,
        "task_run_id": run.id,
        "prewarmed": bool(state.get("prewarmed")),
        "cpu_cores": config.cpu_cores,
        "memory_gb": config.memory_gb,
        "ttl_seconds": config.ttl_seconds,
        "burstable": config.burstable_resources,
        "cpu_request_cores": config.cpu_request_cores if config.burstable_resources else None,
        "memory_request_mb": config.memory_request_mb if config.burstable_resources else None,
    }
    SandboxSession.objects.update_or_create(
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
    SandboxSession.objects.filter(sandbox_id=sandbox_id, ended_at__isnull=True).update(
        ended_at=timezone.now(), ended_reason=reason
    )


@_best_effort
def record_task_run_user_activity(run_id: str | UUID) -> None:
    """Stamp a user message against the run's open sandbox sessions.

    Sets ``last_user_activity_at`` on every message and ``user_attributed_at``
    set-if-NULL, so the first message both claims a warm sandbox and self-heals the
    race where a claim lands mid-provision (before ``open_sandbox_session`` read the
    run state).
    """
    now = timezone.now()
    open_sessions = SandboxSession.objects.filter(task_run_id=run_id, ended_at__isnull=True)
    open_sessions.update(last_user_activity_at=now)
    open_sessions.filter(user_attributed_at__isnull=True).update(user_attributed_at=now)


@dataclass(frozen=True)
class SandboxUsageByTeam:
    """Raw per-team sandbox usage over a period, as (team_id, amount) rows."""

    seconds: list[tuple[int, int]]
    cpu_core_seconds: list[tuple[int, int]]
    memory_gib_seconds: list[tuple[int, int]]


def get_posthog_code_sandbox_usage_by_team(begin: datetime, end: datetime) -> SandboxUsageByTeam:
    """Aggregate user-attributed sandbox time per team over ``[begin, end)``.

    Only the attributed slice of a session bills: ``[user_attributed_at,
    effective_end)``, clipped to the period so sessions spanning report boundaries
    apportion across them. Sessions with no ``ended_at`` (crashed workflows, cleanup
    that never ran) are clamped to ``created_at + ttl_seconds`` — the provider kills
    the sandbox by then regardless — or to now while genuinely live. Resource-second
    metrics use the configured limits; burstable request floors are recorded on the
    row for future pricing policy but don't affect raw usage.
    """
    now = timezone.now()
    sessions = SandboxSession.objects.filter(
        user_attributed_at__isnull=False,
        user_attributed_at__lt=end,
    ).filter(Q(ended_at__isnull=True) | Q(ended_at__gt=begin))

    usage: dict[int, list[float]] = {}
    for session in sessions.iterator():
        start = max(session.user_attributed_at, begin)
        ttl_end = session.created_at + timedelta(seconds=session.ttl_seconds)
        effective_end = session.ended_at or min(now, ttl_end)
        stop = min(effective_end, end)
        if stop <= start:
            continue
        seconds = (stop - start).total_seconds()
        team_usage = usage.setdefault(session.team_id, [0.0, 0.0, 0.0])
        team_usage[0] += seconds
        team_usage[1] += seconds * session.cpu_cores
        team_usage[2] += seconds * session.memory_gb

    return SandboxUsageByTeam(
        seconds=[(team_id, round(totals[0])) for team_id, totals in usage.items()],
        cpu_core_seconds=[(team_id, round(totals[1])) for team_id, totals in usage.items()],
        memory_gib_seconds=[(team_id, round(totals[2])) for team_id, totals in usage.items()],
    )
