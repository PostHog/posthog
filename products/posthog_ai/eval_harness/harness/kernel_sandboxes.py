"""Reclaiming the notebook kernel sandboxes a case leaves behind.

A notebook python or duckdb cell run dispatches through the notebook Temporal
workflow, which provisions a **second** sandbox for the case — the notebook kernel —
alongside the agent sandbox the harness manages itself. Nothing else reclaims it
here: the docker backend ignores ``SandboxConfig.ttl_seconds``, and the harness's own
sweeps match agent containers by task id, which a kernel container's name
(``notebook-kernel-<short_id>-<hex>``) never carries. Left alone, every python case
would hold its kernel container for the rest of the run.

The eval test database only ever holds this harness's own teams, so an unscoped sweep
here can never touch a dev-stack kernel: those rows live in the development database.

``release_kernels`` is synchronous ORM and provider work; ``reclaim_kernels`` is the
async wrapper every caller in the harness actually uses.
"""

from __future__ import annotations

import asyncio
import logging

from products.notebooks.backend.models import KernelRuntime
from products.tasks.backend.facade.sandbox import get_sandbox_class_for_backend

logger = logging.getLogger(__name__)

_RELEASABLE_STATUSES = (
    KernelRuntime.Status.STARTING,
    KernelRuntime.Status.RUNNING,
    KernelRuntime.Status.ERROR,
)
"""Statuses that can still own a live sandbox. A row already marked stopped, timed out,
or discarded had its sandbox destroyed by whoever set that status."""


def release_kernels(team_id: int | None = None) -> int:
    """Destroy the kernel sandboxes recorded for ``team_id``, or for every team when ``None``.

    Returns the number of runtimes actually released. A row whose sandbox could not be
    destroyed keeps its status, so the end-of-run sweep gets a second attempt at it —
    a container that survived a transient provider failure would otherwise hold its
    memory for the rest of the run with nothing left to reclaim it.
    """
    runtimes = KernelRuntime.objects.filter(status__in=_RELEASABLE_STATUSES).exclude(sandbox_id__isnull=True)
    if team_id is not None:
        runtimes = runtimes.filter(team_id=team_id)

    released = 0
    for runtime in runtimes:
        if not runtime.sandbox_id:
            continue
        try:
            sandbox_class = get_sandbox_class_for_backend(runtime.backend)
            sandbox_class.get_by_id(runtime.sandbox_id).destroy()
        except Exception:
            logger.warning(
                "Could not destroy notebook kernel sandbox %s (team %d)",
                runtime.sandbox_id,
                runtime.team_id,
                exc_info=True,
            )
            continue
        runtime.status = KernelRuntime.Status.STOPPED
        runtime.save(update_fields=["status"])
        released += 1
    return released


async def reclaim_kernels(team_id: int | None = None, *, keep: bool = False) -> None:
    """Release kernel sandboxes off the event loop, without ever failing the caller.

    ``keep`` honors a run that deliberately preserves sandboxes for inspection. A
    kernel the provider cannot reach is a leaked container, not a wrong score, so
    every failure here is a warning.
    """
    if keep:
        return
    try:
        released = await asyncio.to_thread(release_kernels, team_id)
    except Exception:
        logger.warning("Notebook kernel release failed (team_id=%s)", team_id, exc_info=True)
        return
    if released:
        logger.info("Released %d notebook kernel sandbox(es) (team_id=%s)", released, team_id)
