"""Let a scout start the report actions a person granted it.

The report actions endpoint refuses a request from a task sandbox, because an agent that can start
agents can loop. A scout runs in a sandbox, and as an orchestrator it needs to start a run that
fixes a report's pull request. This module is the one exception to the refusal.

A sandbox request passes only when the task its OAuth token is bound to is a live scout run, and
both that run and the scout's current config hold the action. The run's grant is stamped at
dispatch (`runner._create_run_row`), so a grant widened mid-run does not reach a run already going,
and the config is read again under its row lock when the start is admitted, so a revoke takes
effect at once. The task a scout action starts is a report discussion, not a scout run, so it
cannot start another action. Its run also records the scout's run as its parent, so the tasks API
refuses a run start from its sandbox too: chains stop at one level.

The started run is an inbox discussion that acts as the scout's acting user with that person's
posture, wider than the scout's own, except that tasks gives a run with a parent none of that
person's personal MCP servers. Whoever can steer the scout (its skill, its run notes, event
text reaching a workflow-triggered run) must not choose what that run does, so only a fixed-prompt
action is grantable and a scout cannot send its own message with it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.signals.backend.enums import ReportTaskActionKind
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.scout_harness.limits import WORKFLOW_HARD_CEILING_S
from products.tasks.backend.facade import api as tasks_facade

# Only actions whose request text is fixed. Merging stays a human decision, so `get_it_merged` is
# not here, and `ask` and `suggested_prompt` carry text a scout can write.
SCOUT_GRANTABLE_REPORT_ACTIONS = frozenset({ReportTaskActionKind.MAKE_IT_GREEN, ReportTaskActionKind.RESOLVE_CONFLICTS})
MAX_SCOUT_REPORT_ACTIONS_PER_DAY = 20

REPORT_ACTION_SANDBOX_REFUSED = "report_action_sandbox_refused"
REPORT_ACTION_NOT_GRANTED = "report_action_not_granted"
REPORT_ACTION_SCOUT_DAILY_CAP = "report_action_scout_daily_cap"

SCOUT_DAILY_CAP_WINDOW = timedelta(hours=24)
# On the run row, so the cap counts the starts of every run of the scout without a table of its own.
STARTS_METADATA_KEY = "report_action_starts"


@frozen
class ScoutReportActionGrant:
    team_id: int
    skill_name: str
    scout_run_id: str
    config_id: str
    task_id: str
    task_run_id: str


@frozen
class ScoutReportActionRefusal:
    code: str
    detail: str


SANDBOX_REFUSAL = ScoutReportActionRefusal(
    code=REPORT_ACTION_SANDBOX_REFUSED, detail="A task sandbox cannot start report actions."
)
DAILY_CAP_REFUSAL = ScoutReportActionRefusal(
    code=REPORT_ACTION_SCOUT_DAILY_CAP,
    detail="This scout started as many report actions as it may in 24 hours. Leave a note for a person instead.",
)


def _not_granted(kind: ReportTaskActionKind) -> ScoutReportActionRefusal:
    return ScoutReportActionRefusal(
        code=REPORT_ACTION_NOT_GRANTED,
        detail=f"This scout is not granted {kind.value}. A person grants report actions in the scout's settings.",
    )


def stored_report_actions(raw: object) -> list[str]:
    """The grantable kinds in a stored grant. A hand-edited value grants nothing outside the allowlist."""
    if not isinstance(raw, list):
        return []
    return sorted({kind for kind in raw if isinstance(kind, str) and kind in SCOUT_GRANTABLE_REPORT_ACTIONS})


def granted_report_actions_for_run(config: SignalScoutConfig) -> list[str]:
    """The report actions the scout's next run holds. A dry run holds none, like its write scopes."""
    return stored_report_actions(config.report_actions) if config.emit else []


def _holds(run: SignalScoutRun, config: SignalScoutConfig, kind: ReportTaskActionKind) -> bool:
    stamped = set(stored_report_actions((run.metadata or {}).get("report_actions")))
    return kind in stamped & set(granted_report_actions_for_run(config))


def resolve_scout_report_action_grant(
    *, sandbox_task_id: UUID | None, team_id: int, kind: ReportTaskActionKind, message: str | None
) -> ScoutReportActionGrant | ScoutReportActionRefusal:
    """Whether the scout run behind a sandbox token may start `kind`.

    `team_id` is the team scout rows belong to. The token's task binding is written server-side at
    mint time, so a sandbox cannot name another run here.
    """
    if sandbox_task_id is None:
        return SANDBOX_REFUSAL
    run = (
        SignalScoutRun.objects.for_team(team_id)
        .filter(task_run__task_id=sandbox_task_id)
        .select_related("scout_config")
        .order_by("-created_at", "-id")
        .first()
    )
    if run is None or run.scout_config is None:
        return SANDBOX_REFUSAL
    latest = tasks_facade.get_latest_run_by_task([sandbox_task_id]).get(str(sandbox_task_id))
    if latest is None or str(latest.id) != str(run.task_run_id) or latest.is_terminal:
        return SANDBOX_REFUSAL
    if kind == ReportTaskActionKind.GET_IT_MERGED:
        return ScoutReportActionRefusal(
            code=REPORT_ACTION_NOT_GRANTED, detail="A scout cannot start get_it_merged. A person merges."
        )
    if message:
        return ScoutReportActionRefusal(
            code=REPORT_ACTION_NOT_GRANTED,
            detail="A scout cannot send its own message with a report action. Send the action alone.",
        )
    if not _holds(run, run.scout_config, kind):
        return _not_granted(kind)
    return ScoutReportActionGrant(
        team_id=team_id,
        skill_name=run.skill_name,
        scout_run_id=str(run.id),
        config_id=str(run.scout_config.id),
        task_id=str(sandbox_task_id),
        task_run_id=str(latest.id),
    )


def _start_times(metadata: object) -> Iterable[datetime]:
    entries = metadata.get(STARTS_METADATA_KEY) if isinstance(metadata, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        try:
            yield datetime.fromisoformat(entry["at"])
        except (TypeError, KeyError, ValueError):
            continue


def reserve_scout_report_action(
    grant: ScoutReportActionGrant, *, report_id: str, kind: ReportTaskActionKind
) -> ScoutReportActionRefusal | None:
    """Admit the start and spend one of the scout's daily starts, or say why not.

    The grant is checked again under the config row lock, which a config edit also takes, so a
    revoke that commits while the request waits on its earlier checks still refuses it. The lock
    also serializes concurrent requests from the scout's runs. A reservation stays spent when the
    start fails afterwards, so a failing start cannot be retried without bound.
    """
    now = timezone.now()
    window_start = now - SCOUT_DAILY_CAP_WINDOW
    with transaction.atomic():
        config = (
            SignalScoutConfig.objects.for_team(grant.team_id).select_for_update().filter(id=grant.config_id).first()
        )
        run = SignalScoutRun.objects.for_team(grant.team_id).select_for_update().filter(id=grant.scout_run_id).first()
        if config is None or run is None or not _holds(run, config, kind):
            return _not_granted(kind)
        # A run records its starts while it runs, so one created a run budget before the window can hold a start inside it.
        recent_metadata = (
            SignalScoutRun.objects.for_team(grant.team_id)
            .filter(
                skill_name=grant.skill_name,
                created_at__gte=window_start - timedelta(seconds=WORKFLOW_HARD_CEILING_S),
            )
            .values_list("metadata", flat=True)
        )
        started = sum(1 for metadata in recent_metadata for at in _start_times(metadata) if at >= window_start)
        if started >= config.max_report_actions_per_day:
            return DAILY_CAP_REFUSAL
        metadata = run.metadata if isinstance(run.metadata, dict) else {}
        starts = metadata.get(STARTS_METADATA_KEY)
        run.metadata = {
            **metadata,
            STARTS_METADATA_KEY: [
                *(starts if isinstance(starts, list) else []),
                {"at": now.isoformat(), "report_id": report_id, "action": kind.value},
            ],
        }
        run.save(update_fields=["metadata"])
    return None
