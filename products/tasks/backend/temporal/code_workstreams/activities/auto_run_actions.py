from dataclasses import dataclass
from typing import Optional

from django.utils import timezone

import posthoganalytics
from temporalio import activity

from posthog.models import OrganizationMembership, Team
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.logic.code_workstreams.auto_run import build_auto_run_prompt, select_auto_actions
from products.tasks.backend.logic.code_workstreams.grouping import RUNNING_STATUSES
from products.tasks.backend.models import CodeWorkflowConfig, CodeWorkstream, Task, TaskRun
from products.tasks.backend.temporal.code_workstreams.constants import HOME_AUTO_ACTIONS_FLAG, MAX_AUTO_RUNS_PER_TEAM
from products.tasks.backend.temporal.process_task.utils import RunSource


@dataclass
class AutoRunWorkstreamActionsInput:
    team_id: int


@dataclass
class AutoRunWorkstreamActionsOutput:
    considered: int
    fired: int


def _org_auto_actions_enabled(organization_id: str) -> bool:
    # Evaluate locally and fail closed so a flag-service blip never auto-starts work.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                HOME_AUTO_ACTIONS_FLAG,
                distinct_id=organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        activity.logger.warning(
            "code_workstreams_auto_actions_flag_check_failed", organization_id=organization_id, error=str(e)
        )
        return False


def _running_task_ids(team_id: int) -> set[str]:
    # One query for the whole team, then set-membership in the loop — avoids an
    # EXISTS round-trip per workstream (N+1) when many workstreams have auto actions.
    return {
        str(task_id)
        for task_id in TaskRun.objects.filter(team_id=team_id, status__in=tuple(RUNNING_STATUSES)).values_list(
            "task_id", flat=True
        )
    }


def _fire_auto_action(team: Team, ws: CodeWorkstream, action: dict) -> Optional[Task]:
    """Start one cloud task for an auto action; returns the Task or None on failure.

    Uses `branch=ws.branch` exactly like the manual quick action so the resulting
    run.branch + pr_base_branch match — the new run regroups onto the same PR
    workstream (PR-by-branch resolution) on the next rebuild cycle.
    """
    title = str(action.get("label") or "").strip() or "Auto action"
    # Build the prompt before the try: it's a pure function, so a failure here is a
    # bug to surface, not an action-creation failure to swallow.
    description = build_auto_run_prompt(
        action,
        repo_full_path=ws.repo_full_path,
        branch=ws.branch,
        pr_url=ws.pr_url,
        pr=ws.pr,
    )
    try:
        task = Task.create_and_run(
            team=team,
            user_id=ws.user_id,
            title=title,
            description=description,
            origin_product=Task.OriginProduct.USER_CREATED,
            repository=ws.repo_full_path,
            branch=ws.branch,
            runtime_adapter=action.get("adapter"),
            model=action.get("model"),
            # Background run: skip plan mode and let it act, same as a manual quick action.
            initial_permission_mode="auto",
            home_quick_action=title,
            run_source=RunSource.HOME_AUTO.value,
        )
        activity.logger.info(
            "code_workstreams_auto_action_fired",
            team_id=team.id,
            user_id=ws.user_id,
            workstream_key=ws.key,
            action_id=action.get("id"),
            situation=ws.primary_situation,
            task_id=str(task.id),
        )
        return task
    except Exception as e:
        # A user missing a usable GitHub integration (or any creation failure) must
        # not abort the whole team's auto-run pass — log and move on.
        activity.logger.warning(
            "code_workstreams_auto_action_failed",
            team_id=team.id,
            user_id=ws.user_id,
            workstream_key=ws.key,
            action_id=action.get("id"),
            error=str(e),
        )
        return None


@activity.defn
@close_db_connections
def auto_run_workstream_actions(input: AutoRunWorkstreamActionsInput) -> AutoRunWorkstreamActionsOutput:
    """Auto-run quick actions for freshly-classified workstreams.

    Runs after `rebuild_team_workstreams` so it reads consistent, persisted state.
    For each workstream, fires an auto-enabled action bound to its primary situation,
    gated four ways: (1) only for current, active members of the org; (2) skip if the
    workstream already has a running task; (3) fire each action at most once per
    workstream (a persisted marker in `auto_run_state`) so a long fix can't relaunch
    every cycle; and (4) at most one auto-run per workstream per pass.
    """
    team = Team.objects.filter(id=input.team_id).select_related("organization").first()
    if team is None:
        return AutoRunWorkstreamActionsOutput(considered=0, fired=0)
    if not _org_auto_actions_enabled(str(team.organization_id)):
        return AutoRunWorkstreamActionsOutput(considered=0, fired=0)

    # Bindings are stored per (team, user); load once and key by user.
    bindings_by_user: dict[int, dict] = {
        user_id: (bindings or {})
        for user_id, bindings in CodeWorkflowConfig.objects.filter(team_id=input.team_id).values_list(
            "user_id", "bindings"
        )
    }
    if not bindings_by_user:
        return AutoRunWorkstreamActionsOutput(considered=0, fired=0)

    # Only current, active members of the org may trigger auto-runs. A user who left or was
    # deactivated must not keep launching cloud tasks under their identity/GitHub context via
    # a leftover auto-enabled binding (their stale config/workstream rows get pruned later).
    active_member_ids = set(
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            user__is_active=True,
            user_id__in=list(bindings_by_user.keys()),
        ).values_list("user_id", flat=True)
    )
    bindings_by_user = {
        user_id: bindings for user_id, bindings in bindings_by_user.items() if user_id in active_member_ids
    }
    if not bindings_by_user:
        return AutoRunWorkstreamActionsOutput(considered=0, fired=0)

    workstreams = list(CodeWorkstream.objects.filter(team_id=input.team_id, user_id__in=list(bindings_by_user.keys())))
    running_task_ids = _running_task_ids(input.team_id)

    considered = 0
    fired = 0
    for ws in workstreams:
        if fired >= MAX_AUTO_RUNS_PER_TEAM:
            activity.logger.warning(
                "code_workstreams_auto_actions_capped", team_id=input.team_id, cap=MAX_AUTO_RUNS_PER_TEAM
            )
            break

        actions = select_auto_actions(bindings_by_user.get(ws.user_id) or {}, ws.primary_situation)
        if not actions:
            continue
        considered += 1

        # Dedup gate: never pile a second cloud run onto a workstream that's already
        # working (a manual run, or an earlier auto run still in flight).
        task_ids = [str(t["id"]) for t in (ws.tasks or []) if isinstance(t, dict) and t.get("id")]
        if any(task_id in running_task_ids for task_id in task_ids):
            continue

        auto_state = dict(ws.auto_run_state or {})
        changed = False
        for action in actions:
            action_id = str(action.get("id"))
            # Re-fire suppression: once we've auto-fired an action for this workstream,
            # don't fire it again (avoids relaunching e.g. "Fix CI" every cycle).
            if action_id in auto_state:
                continue
            task = _fire_auto_action(team, ws, action)
            if task is None:
                continue
            auto_state[action_id] = {
                "fired_at": timezone.now().isoformat(),
                "task_id": str(task.id),
                "situation": ws.primary_situation,
            }
            changed = True
            fired += 1
            # At most one auto-run per workstream per pass: two auto actions on the same
            # primary situation must not spawn two concurrent cloud tasks for one workstream.
            # The running-task gate + per-action marker handle the rest on later cycles.
            break

        if changed:
            # Persist outside the rebuild's defaults so the marker survives the next
            # update_or_create (rebuild never touches auto_run_state).
            ws.auto_run_state = auto_state
            ws.save(update_fields=["auto_run_state", "updated_at"])

    return AutoRunWorkstreamActionsOutput(considered=considered, fired=fired)
