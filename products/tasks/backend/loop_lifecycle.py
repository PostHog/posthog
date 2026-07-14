"""Lifecycle pausing for Loops: owner deactivation and integration disconnects.

See products/tasks/docs/LOOPS.md "Lifecycle and reconciliation": deactivating a user is often
the security response, so every loop they own must pause immediately (not lazily at next fire)
and their in-flight runs must be cancelled. A live sandbox must never keep running with that
owner's freshly minted credentials after the account has been deactivated. Likewise, a GitHub
App uninstall hard-deletes the Integration rows, so loops referencing them pause first.

Wired from the ``pre_save`` signal on ``User`` in ``posthog/models/user.py`` and the GitHub
``installation`` webhook in ``posthog/api/github_callback/installation_events.py``.
"""

import logging

from django.db.models import Q
from django.utils import timezone as django_timezone

from posthog.models.integration import Integration

from products.tasks.backend.loop_notifications import dispatch_loop_event
from products.tasks.backend.loop_service import pause_loop_schedules
from products.tasks.backend.models import Loop, LoopTrigger, TaskRun

logger = logging.getLogger(__name__)

_NON_TERMINAL_TASK_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)


def pause_loops_for_deactivated_user(user_id: int) -> None:
    """Pause every enabled loop owned by a deactivated user and cancel their in-flight runs.

    Best-effort per loop: one loop's Temporal failure never stops the rest from being paused.
    Safe to call for a user with no loops.
    """
    loops = list(Loop.objects.unscoped().filter(created_by_id=user_id, enabled=True, deleted=False))
    for loop in loops:
        try:
            _pause_loop_and_cancel_runs(loop)
        except Exception:
            logger.exception("loop_lifecycle.owner_deactivation_pause_failed", extra={"loop_id": str(loop.id)})


def _pause_loop_and_cancel_runs(loop: Loop) -> None:
    loop.enabled = False
    loop.save(update_fields=["enabled", "updated_at"])
    pause_loop_schedules(loop)

    now = django_timezone.now()
    # Matches both the FK (`Task.loop`) and the pre-FK run-state snapshot (`TaskRun.state["loop_id"]`),
    # same transitional lookup as `facade/loops.py::list_loop_runs`.
    TaskRun.objects.filter(
        Q(task__loop_id=loop.id) | Q(state__loop_id=str(loop.id)),
        team_id=loop.team_id,
        status__in=_NON_TERMINAL_TASK_RUN_STATUSES,
    ).update(status=TaskRun.Status.CANCELLED, completed_at=now, updated_at=now)


def pause_loops_referencing_integrations(integrations: list[Integration], installation_id: str) -> None:
    """Auto-pause every loop referencing a GitHub integration that's about to be hard-deleted.

    The App uninstall hard-deletes the Integration row with no downstream hooks, and loop
    references to it are JSON, so no FK machinery helps. Called from the GitHub ``installation``
    webhook before the delete; best-effort per integration and per loop so a loops-side failure
    never breaks the deletion path.
    """
    for integration in integrations:
        try:
            triggered_loop_ids = set(
                LoopTrigger.objects.for_team(integration.team_id)
                .filter(
                    Q(config__github_integration_id=integration.id)
                    | Q(config__github_integration_id=str(integration.id))
                )
                .values_list("loop_id", flat=True)
            )
            references_integration = Q(repositories__contains=[{"github_integration_id": integration.id}]) | Q(
                repositories__contains=[{"github_integration_id": str(integration.id)}]
            )
            loops = list(
                Loop.objects.for_team(integration.team_id)
                .filter(enabled=True, deleted=False)
                .filter(references_integration | Q(id__in=triggered_loop_ids))
            )
        except Exception:
            logger.exception(
                "github_installation_webhook_loop_lookup_failed",
                extra={"installation_id": installation_id, "integration_id": integration.id},
            )
            continue

        for loop in loops:
            try:
                loop.enabled = False
                loop.save(update_fields=["enabled", "updated_at"])
                pause_loop_schedules(loop)
                dispatch_loop_event(
                    loop,
                    "needs_attention",
                    {
                        "reason": "github_integration_disconnected",
                        "installation_id": installation_id,
                        "body": (
                            f'The GitHub integration "{integration.display_name}" was disconnected '
                            "and this loop has been paused."
                        ),
                    },
                )
                logger.info(
                    "github_installation_webhook_loop_paused",
                    extra={"loop_id": str(loop.id), "installation_id": installation_id},
                )
            except Exception:
                logger.exception(
                    "github_installation_webhook_loop_pause_failed",
                    extra={"loop_id": str(loop.id), "installation_id": installation_id},
                )


__all__ = ["pause_loops_for_deactivated_user", "pause_loops_referencing_integrations"]
