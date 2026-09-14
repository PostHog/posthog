"""Usage events for notebook kernel sandboxes: one when a sandbox starts, and one when it ends.

Modal exports metrics for each sandbox, but those metrics carry no team and no size. These events
carry both, so product analytics can count sandboxes, add up sandbox-hours, and estimate the price
of the compute per team.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
    # The status poll calls this on every poll of a stopped kernel, so skip the UPDATE when this
    # copy of the row already carries the end.
    if runtime.ended_at is not None:
        return
    try:
        ended_at = timezone.now()
        claimed = KernelRuntime.objects.filter(
            pk=runtime.pk, ended_at__isnull=True, ttl_expires_at__isnull=False
        ).update(ended_at=ended_at)
        if not claimed:
            return
        runtime.refresh_from_db(fields=["created_at", "ended_at", "ttl_expires_at"])
        if runtime.ttl_expires_at is None:
            return

        runtime_seconds = estimated_runtime_seconds(
            created_at=runtime.created_at,
            ended_at=ended_at,
            ttl_expires_at=runtime.ttl_expires_at,
            sandbox_still_running=sandbox_still_running,
        )
        shape = _shape_properties(runtime)
        hourly_price = shape["hourly_price_usd"]
        properties: dict[str, Any] = {
            **shape,
            "kernel_runtime_id": str(runtime.id),
            "notebook_short_id": runtime.notebook_short_id,
            "ended_reason": reason,
            "sandbox_still_running": sandbox_still_running,
            "tracked_seconds": round(max((ended_at - runtime.created_at).total_seconds(), 0.0), 3),
            "estimated_runtime_seconds": round(runtime_seconds, 3),
            "estimated_price_usd": (
                round(runtime_seconds / 3600 * hourly_price, 4) if hourly_price is not None else None
            ),
        }
        _report(runtime, KERNEL_SANDBOX_ENDED_EVENT, properties)
    except Exception:
        logger.exception("notebook_kernel_sandbox_ended_report_failed", kernel_runtime_id=str(runtime.id))


def _shape_properties(runtime: KernelRuntime) -> dict[str, Any]:
    cpu_cores = runtime.provisioned_cpu_cores
    memory_gb = runtime.provisioned_memory_gb
    preset = find_matching_preset(cpu_cores=cpu_cores, memory_gb=memory_gb)
    hourly_price = None
    # The rates price a Modal sandbox. The Docker backend runs kernels on a local machine in
    # development, so it has no price.
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
