"""Usage events for notebook kernel sandboxes: one when a sandbox starts, and one when it ends.

Modal exports metrics for each sandbox, but those metrics carry no team and no size. These events
carry both, so product analytics can count sandboxes, add up sandbox-hours, and estimate the price
of the compute per team.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.event_usage import report_user_or_team_action
from posthog.models import Team

from products.notebooks.backend.compute_pricing import find_matching_preset, get_compute_rates
from products.notebooks.backend.models import KernelRuntime

logger = structlog.get_logger(__name__)

KERNEL_SANDBOX_STARTED_EVENT = "notebook kernel sandbox started"
KERNEL_SANDBOX_ENDED_EVENT = "notebook kernel sandbox ended"

CUSTOM_COMPUTE_PRESET = "custom"


def estimated_runtime_seconds(
    *,
    created_at: datetime,
    ended_at: datetime,
    ttl_expires_at: datetime,
    sandbox_still_running: bool,
) -> float:
    # The provider kills a sandbox at its TTL at the latest, whatever PostHog does. A sandbox that
    # PostHog stopped tracking without destroying it keeps running until that deadline.
    end = ttl_expires_at if sandbox_still_running else min(ended_at, ttl_expires_at)
    return max((end - created_at).total_seconds(), 0.0)


def record_sandbox_started(runtime: KernelRuntime, *, sandbox_id: str, ttl_seconds: int) -> None:
    """Report that the provider created a sandbox for `runtime`.

    Call it as soon as the provider returns the sandbox, because the sandbox costs money from
    that moment even if the kernel inside it never starts. Never raises, because telemetry must
    not fail a kernel start.
    """
    try:
        properties: dict[str, Any] = {
            **_shape_properties(runtime),
            "kernel_runtime_id": str(runtime.id),
            "sandbox_id": sandbox_id,
            "notebook_short_id": runtime.notebook_short_id,
            "ttl_seconds": ttl_seconds,
            "provision_seconds": round(max((timezone.now() - runtime.created_at).total_seconds(), 0.0), 3),
        }
        _report(runtime, KERNEL_SANDBOX_STARTED_EVENT, properties)
    except Exception:
        logger.exception("notebook_kernel_sandbox_started_report_failed", kernel_runtime_id=str(runtime.id))


def record_sandbox_ended(runtime: KernelRuntime, *, reason: str, sandbox_still_running: bool) -> None:
    """Stamp the end of the sandbox behind `runtime` and report it, at most once.

    A stop, a dead handle, a discard and the status poll can each notice the same end, in
    different processes. The conditional update lets only the first of them claim it, so a
    sandbox is never counted twice. Rows without `ttl_expires_at` started before this
    instrumentation existed and have no start event, so they are skipped. Never raises.
    """
    if runtime.ended_at is not None:
        return
    try:
        runtime.refresh_from_db(fields=["created_at", "ended_at", "ttl_expires_at"])
        if runtime.ended_at is not None or runtime.ttl_expires_at is None:
            return

        # Build the event before the claim, so that a failure here leaves the end unclaimed for the
        # next path that notices it.
        ended_at = timezone.now()
        properties = _ended_properties(runtime, ended_at, reason=reason, sandbox_still_running=sandbox_still_running)
        team = Team.objects.filter(pk=runtime.team_id).first()
        user = runtime.user

        claimed = KernelRuntime.objects.filter(pk=runtime.pk, ended_at__isnull=True).update(ended_at=ended_at)
        if not claimed:
            return
        runtime.ended_at = ended_at
        try:
            report_user_or_team_action(KERNEL_SANDBOX_ENDED_EVENT, properties, user=user, team=team)
        except Exception:
            KernelRuntime.objects.filter(pk=runtime.pk, ended_at=ended_at).update(ended_at=None)
            runtime.ended_at = None
            raise
    except Exception:
        logger.exception("notebook_kernel_sandbox_ended_report_failed", kernel_runtime_id=str(runtime.id))


def record_sandbox_ended_by_id(
    kernel_runtime_id: UUID, *, team_id: int, user_id: int | None, reason: str, sandbox_still_running: bool
) -> None:
    """Record the end of a sandbox for a caller that holds only the runtime id.

    The facade accepts ids and not model rows, so the kernel status endpoint uses this function. The
    lookup also filters on the team and the user, so a caller can only end a runtime that it owns. The
    lookup skips a row that has already ended, so a status poll on an ended runtime costs one query.
    Never raises.
    """
    try:
        if user_id is None:
            runtime = KernelRuntime.objects.filter(
                pk=kernel_runtime_id, team_id=team_id, user=None, ended_at__isnull=True
            ).first()
        else:
            runtime = KernelRuntime.objects.filter(
                pk=kernel_runtime_id, team_id=team_id, user_id=user_id, ended_at__isnull=True
            ).first()
    except Exception:
        logger.exception("notebook_kernel_sandbox_ended_report_failed", kernel_runtime_id=str(kernel_runtime_id))
        return
    if runtime is not None:
        record_sandbox_ended(runtime, reason=reason, sandbox_still_running=sandbox_still_running)


def _ended_properties(
    runtime: KernelRuntime, ended_at: datetime, *, reason: str, sandbox_still_running: bool
) -> dict[str, Any]:
    assert runtime.ttl_expires_at is not None
    runtime_seconds = estimated_runtime_seconds(
        created_at=runtime.created_at,
        ended_at=ended_at,
        ttl_expires_at=runtime.ttl_expires_at,
        sandbox_still_running=sandbox_still_running,
    )
    shape = _shape_properties(runtime)
    hourly_price = shape["hourly_price_usd"]
    return {
        **shape,
        "kernel_runtime_id": str(runtime.id),
        "notebook_short_id": runtime.notebook_short_id,
        "ended_reason": reason,
        "sandbox_still_running": sandbox_still_running,
        "tracked_seconds": round(max((ended_at - runtime.created_at).total_seconds(), 0.0), 3),
        "estimated_runtime_seconds": round(runtime_seconds, 3),
        "estimated_price_usd": (round(runtime_seconds / 3600 * hourly_price, 4) if hourly_price is not None else None),
    }


def _shape_properties(runtime: KernelRuntime) -> dict[str, Any]:
    cpu_cores = runtime.provisioned_cpu_cores
    memory_gb = runtime.provisioned_memory_gb
    preset = find_matching_preset(cpu_cores=cpu_cores, memory_gb=memory_gb)
    hourly_price = None
    if runtime.backend == KernelRuntime.Backend.MODAL and cpu_cores is not None and memory_gb is not None:
        hourly_price = get_compute_rates().hourly_price(cpu_cores=cpu_cores, memory_gb=memory_gb)
    return {
        "backend": runtime.backend,
        "cpu_cores": cpu_cores,
        "memory_gb": memory_gb,
        "compute_preset": preset.key if preset else CUSTOM_COMPUTE_PRESET,
        "hourly_price_usd": hourly_price,
    }


def _report(runtime: KernelRuntime, event: str, properties: dict[str, Any]) -> None:
    # Resolve the runtime's own team. With team=None, report_user_or_team_action attributes the
    # event to the user's currently active project, which can differ from the notebook's project.
    team = Team.objects.filter(pk=runtime.team_id).first()
    report_user_or_team_action(event, properties, user=runtime.user, team=team)
