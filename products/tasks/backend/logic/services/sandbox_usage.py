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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from functools import wraps
from typing import ParamSpec, TypeVar
from uuid import UUID

from django.db import transaction
from django.db.models import Case, F, Q, Value, When
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.compute_quota import is_billable_compute
from products.tasks.backend.logic.services.sandbox import SandboxBase, SandboxConfig, get_sandbox_class_for_sandbox_id
from products.tasks.backend.logic.services.sandbox_pricing import (
    COMPUTE_RATE_CARDS,
    ComputeRateCard,
    calculate_sandbox_compute_cost,
    validate_compute_rate_cards,
    validate_reporting_window,
)
from products.tasks.backend.models import SandboxSession, Task, TaskClientProvenance, TaskRun

logger = structlog.get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


@frozen
class SandboxCpuAttribution:
    cpu_usage_usec: int
    billed_cpu_usage_usec: int | None
    measured_at: datetime


def measure_sandbox_cpu_usage(sandbox: SandboxBase) -> tuple[int | None, datetime | None]:
    try:
        value = sandbox.read_cpu_usage_usec()
    except Exception:
        logger.exception("sandbox_usage.cpu_usage_read_failed", sandbox_id=sandbox.id)
        return None, None
    if not isinstance(value, int):
        return None, None
    return value, timezone.now()


def measure_sandbox_billed_cpu_usage(sandbox: SandboxBase) -> int | None:
    try:
        value = sandbox.read_billed_cpu_usage_usec()
    except Exception:
        logger.exception("sandbox_usage.billed_cpu_usage_read_failed", sandbox_id=sandbox.id)
        return None
    return value if isinstance(value, int) else None


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
def measure_task_run_cpu_attribution(run_id: str | UUID, team_id: int) -> dict[str, SandboxCpuAttribution]:
    run_uuid = run_id if isinstance(run_id, UUID) else UUID(run_id)
    sessions = SandboxSession.objects.for_team(team_id).filter(
        task_run_id=run_uuid,
        ended_at__isnull=True,
        user_attributed_at__isnull=True,
    )
    measurements: dict[str, SandboxCpuAttribution] = {}
    for session in sessions:
        try:
            sandbox = get_sandbox_class_for_sandbox_id(session.sandbox_id).get_by_id(session.sandbox_id)
        except Exception:
            logger.exception("sandbox_usage.sandbox_get_failed", sandbox_id=session.sandbox_id)
            continue
        value, measured_at = measure_sandbox_cpu_usage(sandbox)
        if value is not None and measured_at is not None:
            measurements[session.sandbox_id] = SandboxCpuAttribution(
                cpu_usage_usec=value,
                billed_cpu_usage_usec=measure_sandbox_billed_cpu_usage(sandbox),
                measured_at=measured_at,
            )
    return measurements


def open_sandbox_session(
    *,
    run_id: str | UUID,
    sandbox_id: str,
    config: SandboxConfig,
    sandbox_created_at: datetime | None = None,
    cpu_usage_attribution_usec: int | None = None,
    billed_cpu_usage_attribution_usec: int | None = None,
    cpu_usage_attribution_measured_at: datetime | None = None,
    required: bool = False,
) -> None:
    """Record a freshly provisioned sandbox against its run."""
    try:
        with transaction.atomic():
            run = (
                TaskRun.objects.select_for_update(of=("self",))
                .select_related("task")
                .only("id", "team_id", "state", "task__origin_product", "task__client_provenance")
                .get(id=run_id)
            )
            state = run.state or {}
            created_at = sandbox_created_at or timezone.now()
            shape = {
                "team_id": run.team_id,
                "task_run_id": run.id,
                "origin_product": run.task.origin_product,
                "prewarmed": bool(state.get("prewarmed")),
                "vm_runtime": config.is_vm,
                "sandbox_backend": state.get("sandbox_backend"),
                "cpu_cores": config.cpu_cores,
                "memory_gb": config.memory_gb,
                "ttl_seconds": config.ttl_seconds,
                "burstable": config.burstable_resources,
                "cpu_request_cores": config.effective_cpu_request_cores if config.burstable_resources else None,
                "memory_request_mb": config.effective_memory_request_mb if config.burstable_resources else None,
                "created_at": created_at,
                "ttl_expires_at": created_at + timedelta(seconds=config.ttl_seconds),
            }
            SandboxSession.objects.for_team(run.team_id).update_or_create(
                sandbox_id=sandbox_id,
                defaults=shape,
                create_defaults={
                    **shape,
                    "client_provenance": run.task.client_provenance,
                    "user_attributed_at": (
                        None if state.get("await_user_message") else cpu_usage_attribution_measured_at or timezone.now()
                    ),
                    "provider_cpu_usage_attribution_usec": (
                        None if state.get("await_user_message") else cpu_usage_attribution_usec
                    ),
                    "provider_billed_cpu_usage_attribution_usec": (
                        None if state.get("await_user_message") else billed_cpu_usage_attribution_usec
                    ),
                    "provider_cpu_usage_attribution_measured_at": (
                        None if state.get("await_user_message") else cpu_usage_attribution_measured_at
                    ),
                },
            )
    except Exception:
        logger.exception("sandbox_usage.ledger_write_failed", helper="open_sandbox_session")
        if required:
            raise


def _elapsed_seconds(start: datetime | None, end: datetime) -> float | None:
    return None if start is None else round((end - start).total_seconds(), 1)


def _capture_sandbox_session_closed(
    task_run: TaskRun, sandbox_session: SandboxSession, *, reason: str, ended_at: datetime
) -> None:
    task_run.capture_event(
        "sandbox_session_closed",
        {
            "sandbox_id": sandbox_session.sandbox_id,
            "ended_reason": reason,
            "runtime_seconds": _elapsed_seconds(sandbox_session.created_at, ended_at),
            "attributed_seconds": _elapsed_seconds(sandbox_session.user_attributed_at, ended_at),
            "idle_seconds": _elapsed_seconds(sandbox_session.last_user_activity_at, ended_at),
            "prewarmed": sandbox_session.prewarmed,
            "vm_runtime": sandbox_session.vm_runtime,
        },
    )


@_best_effort
def close_sandbox_session(
    sandbox_id: str,
    *,
    reason: str,
    cpu_usage_usec: int | None = None,
    billed_cpu_usage_usec: int | None = None,
    cpu_usage_measured_at: datetime | None = None,
) -> None:
    """Stamp the sandbox's end. Idempotent — the first stamp wins."""
    # Unscoped: cleanup/reap activities only carry the globally-unique provider
    # sandbox id, not team context.
    sandbox_session = SandboxSession.objects.unscoped().filter(sandbox_id=sandbox_id).first()
    if sandbox_session is None:
        return
    with transaction.atomic():
        task_run = TaskRun.objects.select_for_update().get(id=sandbox_session.task_run_id)
        ended_at = timezone.now()
        updates: dict[str, object] = {"ended_at": ended_at, "ended_reason": reason}
        if cpu_usage_usec is not None:
            updates["provider_cpu_usage_usec"] = cpu_usage_usec
            updates["provider_usage_measured_at"] = cpu_usage_measured_at or timezone.now()
        if billed_cpu_usage_usec is not None:
            updates["provider_billed_cpu_usage_usec"] = billed_cpu_usage_usec
        stamped = (
            SandboxSession.objects.unscoped()
            .filter(
                id=sandbox_session.id,
                ended_at__isnull=True,
            )
            .update(**updates)
        )
    if stamped:
        _capture_sandbox_session_closed(task_run, sandbox_session, reason=reason, ended_at=ended_at)


@_best_effort
def record_task_run_user_activity(
    run_id: str | UUID,
    team_id: int,
    cpu_attribution: dict[str, SandboxCpuAttribution] | None = None,
) -> None:
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
    client_provenance = (
        TaskRun.objects.filter(id=run_uuid, team_id=team_id).values_list("task__client_provenance", flat=True).first()
    )
    unattributed_sessions = list(open_sessions.filter(user_attributed_at__isnull=True))
    for session in unattributed_sessions:
        measurement = (cpu_attribution or {}).get(session.sandbox_id)
        attribution_time = measurement.measured_at if measurement else now
        updates: dict[str, object] = {
            "user_attributed_at": attribution_time,
            "client_provenance": Case(
                When(client_provenance__isnull=True, then=Value(client_provenance)),
                default=F("client_provenance"),
            ),
        }
        if measurement:
            updates["provider_cpu_usage_attribution_usec"] = measurement.cpu_usage_usec
            updates["provider_billed_cpu_usage_attribution_usec"] = measurement.billed_cpu_usage_usec
            updates["provider_cpu_usage_attribution_measured_at"] = measurement.measured_at
        open_sessions.filter(id=session.id, user_attributed_at__isnull=True).update(**updates)

    open_sessions.filter(user_attributed_at__isnull=True).update(
        user_attributed_at=now,
        client_provenance=Case(
            When(client_provenance__isnull=True, then=Value(client_provenance)),
            default=F("client_provenance"),
        ),
    )


@dataclass(frozen=True)
class SandboxUsageByTeam:
    """Raw per-team sandbox usage over a period, as (team_id, amount) rows."""

    seconds: list[tuple[int, int]]
    cpu_core_seconds: list[tuple[int, int]]
    memory_gib_seconds: list[tuple[int, int]]


@dataclass(frozen=True)
class SandboxComputeUsageByTeam:
    credits: list[tuple[int, int]]
    cpu_millicore_seconds: list[tuple[int, int]]
    memory_mib_seconds: list[tuple[int, int]]


def get_billable_sandbox_compute_usage_by_team(
    begin: datetime,
    end: datetime,
    *,
    rate_cards: Sequence[ComputeRateCard] | None = None,
) -> SandboxComputeUsageByTeam:
    validate_reporting_window(begin, end)
    rate_cards = COMPUTE_RATE_CARDS if rate_cards is None else rate_cards
    if not rate_cards:
        return SandboxComputeUsageByTeam([], [], [])

    cards = validate_compute_rate_cards(rate_cards)
    sessions = (
        SandboxSession.objects.unscoped()
        .select_related("task_run__task__loop")
        .filter(
            client_provenance=TaskClientProvenance.POSTHOG_DESKTOP,
            user_attributed_at__isnull=False,
            user_attributed_at__lt=end,
        )
        .filter(Q(origin_product=Task.OriginProduct.USER_CREATED) | Q(origin_product=Task.OriginProduct.LOOP))
        .filter(Q(ended_at__isnull=True, ttl_expires_at__gt=begin) | Q(ended_at__gt=begin))
    )

    usage: dict[int, list[Decimal]] = {}
    calculated_at = timezone.now()
    for session in sessions.iterator():
        task = session.task_run.task
        source_loop = task.loop if task.loop_id is not None else None
        if not is_billable_compute(
            origin_product=session.origin_product,
            client_provenance=session.client_provenance,
            source_loop_id=task.loop_id,
            source_loop_internal=source_loop.internal if source_loop is not None else None,
        ):
            continue
        cost = calculate_sandbox_compute_cost(session, begin, end, calculated_at=calculated_at, rate_cards=cards)
        totals = usage.setdefault(session.team_id, [Decimal(0) for _ in range(3)])
        totals[0] += cost.cpu_core_seconds
        totals[1] += cost.memory_gib_seconds
        totals[2] += cost.cpu_cost_usd + cost.memory_cost_usd

    credits: list[tuple[int, int]] = []
    cpu_millicore_seconds: list[tuple[int, int]] = []
    memory_mib_seconds: list[tuple[int, int]] = []
    for team_id, totals in usage.items():
        cpu_quantity, memory_quantity, total_usd = totals
        credits.append((team_id, int((total_usd * 100).to_integral_value(rounding=ROUND_HALF_EVEN))))
        cpu_millicore_seconds.append((team_id, int((cpu_quantity * 1000).to_integral_value(rounding=ROUND_HALF_EVEN))))
        memory_mib_seconds.append((team_id, int((memory_quantity * 1024).to_integral_value(rounding=ROUND_HALF_EVEN))))

    return SandboxComputeUsageByTeam(credits, cpu_millicore_seconds, memory_mib_seconds)


def get_task_sandbox_usage_by_team(begin: datetime, end: datetime) -> SandboxUsageByTeam:
    """Aggregate user-attributed sandbox time per team over ``[begin, end)``.

    Only the attributed slice of a session bills: ``[user_attributed_at,
    effective_end)``, clipped to the period so sessions spanning report boundaries
    apportion across them. A Modal end is clamped to ``ttl_expires_at`` — the provider
    kills the sandbox by then regardless, whether cleanup never ran (crashed
    workflows), stamped late, or the session is genuinely live (clamped to now).
    Hogland's TTL is an idle timeout, not a kill deadline, so hogland rows keep their
    real end time.
    Open rows whose TTL expired before the period are excluded in the query itself,
    so missed close stamps can't grow the scan without bound. Resource-second
    metrics use the configured limits; burstable request floors are recorded on the
    row for future pricing policy but don't affect raw usage.
    """
    now = timezone.now()
    # Unscoped: the usage report aggregates across every team in the region.
    sessions = (
        SandboxSession.objects.unscoped()
        .filter(
            user_attributed_at__isnull=False,
            user_attributed_at__lt=end,
        )
        .filter(
            Q(ended_at__isnull=True, ttl_expires_at__gt=begin)
            # An open hogland box extends its idle TTL on every proxied request, so
            # ttl_expires_at can fall before the period while the box still runs. The
            # first clause would drop it and bill zero for every later period. Keep an
            # open hogland row for any period after it started; the loop bills it to now.
            # Bounded by created_at so a never-closed row can't grow the scan without bound.
            | Q(sandbox_backend="hogland", ended_at__isnull=True, created_at__lte=end)
            | Q(ended_at__gt=begin)
        )
    )

    usage: dict[int, list[float]] = {}
    for session in sessions.iterator():
        assert session.user_attributed_at is not None
        start = max(session.user_attributed_at, begin)
        end_time = session.ended_at or now
        # Modal's TTL is a hard kill deadline, so its end clamps to ttl_expires_at. Hogland's
        # TTL is an idle timeout that every proxied request extends, so a hogland box can
        # outlive created_at + ttl_seconds; clamping there would undercount its billed window.
        if session.sandbox_backend == "hogland":
            effective_end = end_time
        else:
            effective_end = min(end_time, session.ttl_expires_at)
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
