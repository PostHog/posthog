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
from products.tasks.backend.loop_service import pause_loop_schedules, signal_loop_run_cancelled
from products.tasks.backend.models import Loop, LoopTrigger, Task, TaskRun

logger = logging.getLogger(__name__)

_NON_TERMINAL_TASK_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)

DISABLED_REASON_OWNER_DEACTIVATED = "owner_deactivated"
DISABLED_REASON_OWNER_REMOVED = "owner_removed_from_org"
DISABLED_REASON_GITHUB_DISCONNECTED = "github_integration_disconnected"

_PAUSE_MESSAGES = {
    DISABLED_REASON_OWNER_DEACTIVATED: "This loop's owner was deactivated, so it has been paused.",
    DISABLED_REASON_OWNER_REMOVED: "This loop's owner was removed from the organization, so it has been paused.",
}


def pause_loops_for_deactivated_user(user_id: int) -> None:
    """Pause every enabled loop owned by a deactivated user and cancel their in-flight runs.

    Best-effort per loop: one loop's Temporal failure never stops the rest from being paused.
    Safe to call for a user with no loops.
    """
    loops = list(Loop.objects.unscoped().filter(created_by_id=user_id, enabled=True, deleted=False))
    for loop in loops:
        try:
            _pause_loop_and_cancel_runs(loop, DISABLED_REASON_OWNER_DEACTIVATED)
        except Exception:
            logger.exception("loop_lifecycle.owner_deactivation_pause_failed", extra={"loop_id": str(loop.id)})

    # A run mints its sandbox credentials from `task.created_by` (snapshotted at fire time), and loop
    # ownership can transfer via takeover after a run starts. Pausing only loops the user still owns
    # would miss a run they authored on a since-transferred loop, leaving it executing under the
    # deactivated user's credentials. Cancel those independently, keyed on the run's credential owner.
    try:
        _cancel_loop_runs_authored_by(user_id)
    except Exception:
        logger.exception("loop_lifecycle.owner_deactivation_run_cancel_failed", extra={"user_id": user_id})


def pause_loops_for_removed_member(user_id: int, organization_id: str) -> None:
    """Pause every enabled loop a removed member owns in this org and cancel their in-flight runs.

    Org membership removal, unlike account deactivation, leaves `is_active=True`, so the fire-time
    membership guard blocks new fires but already-dispatched runs keep resolving `task.created_by`
    as their credential owner and minting the former org's OAuth/GitHub/MCP tokens. Offboard those:
    pause the loops and cancel + signal the in-flight runs, scoped to this organization's teams.
    """
    loops = list(
        Loop.objects.unscoped().filter(
            created_by_id=user_id, team__organization_id=organization_id, enabled=True, deleted=False
        )
    )
    for loop in loops:
        try:
            _pause_loop_and_cancel_runs(loop, DISABLED_REASON_OWNER_REMOVED)
        except Exception:
            logger.exception("loop_lifecycle.member_removal_pause_failed", extra={"loop_id": str(loop.id)})

    try:
        _cancel_loop_runs_authored_by(user_id, organization_id=organization_id)
    except Exception:
        logger.exception("loop_lifecycle.member_removal_run_cancel_failed", extra={"user_id": user_id})


def _cancel_loop_runs_authored_by(user_id: int, *, organization_id: str | None = None) -> None:
    """Cancel and signal every non-terminal loop run whose task this user created, regardless of who
    currently owns the loop. Runs the loop-ownership pass already cancelled are terminal by now, so
    they don't re-match; this only catches runs on loops that were taken over after firing.
    `organization_id` scopes the cancellation to that org's teams (membership removal is per-org)."""
    now = django_timezone.now()
    queryset = TaskRun.objects.filter(
        task__created_by_id=user_id,
        task__origin_product=Task.OriginProduct.LOOP,
        status__in=_NON_TERMINAL_TASK_RUN_STATUSES,
    )
    if organization_id is not None:
        queryset = queryset.filter(task__team__organization_id=organization_id)
    runs = list(queryset)
    if not runs:
        return
    TaskRun.objects.filter(id__in=[run.id for run in runs]).update(
        status=TaskRun.Status.CANCELLED, completed_at=now, updated_at=now
    )
    for run in runs:
        signal_loop_run_cancelled(run.workflow_id)


def _pause_loop_and_cancel_runs(loop: Loop, reason: str) -> None:
    loop.enabled = False
    loop.disabled_reason = reason
    loop.save(update_fields=["enabled", "disabled_reason", "updated_at"])
    pause_loop_schedules(loop)

    now = django_timezone.now()
    # Matches both the FK (`Task.loop`) and the pre-FK run-state snapshot (`TaskRun.state["loop_id"]`),
    # same transitional lookup as `facade/loops.py::list_loop_runs`.
    runs = list(
        TaskRun.objects.filter(
            Q(task__loop_id=loop.id) | Q(state__loop_id=str(loop.id)),
            team_id=loop.team_id,
            status__in=_NON_TERMINAL_TASK_RUN_STATUSES,
        )
    )
    if runs:
        TaskRun.objects.filter(id__in=[run.id for run in runs]).update(
            status=TaskRun.Status.CANCELLED, completed_at=now, updated_at=now
        )
        # Cancelling the DB row isn't enough: signal each workflow so the live sandbox actually winds
        # down instead of running to completion under the deactivated owner's freshly minted
        # credentials. That's the entire point of the security response (see module docstring).
        for run in runs:
            signal_loop_run_cancelled(run.workflow_id)

    dispatch_loop_event(
        loop,
        "needs_attention",
        {
            "reason": reason,
            "body": _PAUSE_MESSAGES.get(reason, "This loop has been paused."),
        },
    )


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
                loop.disabled_reason = DISABLED_REASON_GITHUB_DISCONNECTED
                loop.save(update_fields=["enabled", "disabled_reason", "updated_at"])
                pause_loop_schedules(loop)
                dispatch_loop_event(
                    loop,
                    "needs_attention",
                    {
                        "reason": DISABLED_REASON_GITHUB_DISCONNECTED,
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


__all__ = [
    "pause_loops_for_deactivated_user",
    "pause_loops_for_removed_member",
    "pause_loops_referencing_integrations",
]
