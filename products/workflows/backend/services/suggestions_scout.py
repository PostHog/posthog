"""Keep the workflows scout running exactly where someone asked for suggestions.

The scout only reads live workflows whose owner turned on "Suggest improvements", so a project with
none gains nothing from its runs. The first live opted-in workflow switches the scout on for the
project, and losing the last one, by opting out, archiving or deleting it, removes it again.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q, QuerySet

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import ActivityLog, Team, User
from posthog.schema_enums import ProductKey

from products.signals.backend.facade.api import (
    ScoutEnableRefusal,
    disable_scout_for_product,
    enable_scout_for_product,
    scout_enable_refusal_for_product,
    scout_status_for_product,
)
from products.workflows.backend.facade.contracts import SuggestionsScoutRunReason
from products.workflows.backend.metrics import HOG_FLOW_VERSION_APP_SOURCE, TARGET_OPEN_METRIC, TARGET_SEND_METRIC
from products.workflows.backend.models import HogFlow, HogFlowOptimization, HogFlowRevision, WorkflowProposal

SUGGESTIONS_SCOUT = "signals-scout-workflows"
SOURCE_PRODUCT = "workflows"
PROPOSAL_WRITE_SCOPE = "hog_flow_proposal:write"
# Arbitrary, fixed namespace for the per-project advisory lock that serializes reconciliation.
_LOCK_NAMESPACE = 72_031
# The scout skill reads a send only once it is this old, because opens and bounces arrive after the send.
SEND_MATURITY = timedelta(hours=48)
EMAIL_METRICS_MAX_EXECUTION_S = 5
# The longest the scout goes without a run, so workflows a short run left unread still get read.
BACKSTOP_INTERVAL = timedelta(days=7)


def sync_suggestions_scout(team: Team, *, acting_user: User | None, may_grant: bool) -> None:
    """Switch the scout on or off to match the project's live opted-in workflows.

    Switching it on grants `hog_flow_proposal:write` and makes `acting_user` the person its runs act as,
    so it happens only with an `acting_user` and `may_grant` set. Switching it off needs neither.
    When the project still needs the scout but nobody here may grant it, the scout config stays as it is.
    """
    # Scouts belong to the project's main environment, while workflows can live in any of its environments.
    project = team.parent_team or team
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_LOCK_NAMESPACE, project.id])
        if not _live_opt_ins(project.id).exists():
            disable_scout_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT, source_product=SOURCE_PRODUCT)
        elif acting_user is not None and may_grant:
            enable_scout_for_product(
                team=project,
                skill_name=SUGGESTIONS_SCOUT,
                source_product=SOURCE_PRODUCT,
                acting_user=acting_user,
                write_scopes=[PROPOSAL_WRITE_SCOPE],
            )


def suggestions_scout_refusal(team: Team, *, acting_user: User, may_grant: bool) -> ScoutEnableRefusal | str | None:
    """Why turning suggestions on here would leave the project with no scout, or None when it would not.

    A project that already has the scout needs nothing new, so nothing is refused there.
    """
    project = team.parent_team or team
    if scout_status_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT) is not None:
        return None
    if not may_grant:
        return "key_cannot_grant"
    return scout_enable_refusal_for_product(
        team=project, skill_name=SUGGESTIONS_SCOUT, acting_user=acting_user, write_scopes=[PROPOSAL_WRITE_SCOPE]
    )


def suggestions_scout_status(team: Team) -> str:
    """`running`, `paused_by_user`, `paused_by_system` or `not_running` for the project's suggestions scout."""
    project = team.parent_team or team
    status = scout_status_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT)
    if status in ("paused_by_user", "paused_by_system"):
        return status
    return "running" if status is not None else "not_running"


def _live_opt_ins(project_id: int) -> QuerySet[HogFlowOptimization]:
    environments = Team.objects.filter(Q(id=project_id) | Q(parent_team_id=project_id)).values("id")
    return HogFlowOptimization.objects.unscoped().filter(
        team_id__in=environments, enabled=True, hog_flow__status=HogFlow.State.ACTIVE
    )


def suggestions_scout_no_input_reason(project_id: int) -> str | None:
    """`no_opted_in_workflow` when the project has no live workflow that asks for suggestions, else None.

    A scout switched on without one, for example from the Inbox, has nothing to read on any run.
    """
    return None if _live_opt_ins(project_id).exists() else "no_opted_in_workflow"


@frozen
class _OptedInWorkflow:
    id: UUID
    # The workflow's environment, which its metrics are recorded under. The opt-in row is scoped to the project.
    team_id: int
    version: int
    opted_in_at: datetime

    @property
    def version_source_id(self) -> str:
        return f"{self.id}/{self.version}"


def suggestions_scout_run_reason(
    project_id: int, *, last_run_at: datetime | None, now: datetime
) -> SuggestionsScoutRunReason | None:
    """Why the suggestions scout has something new to read since its last run, or None when it has nothing.

    The scout decides only from opted-in live workflows: their opt-in, their status and published
    versions, how people resolved its suggestions, and email metrics of the live version. When none
    of these changed since `last_run_at`, a new run reads the same input as the last one.
    """
    if last_run_at is None:
        return "first_run"
    # A run can cover only part of the opted-in workflows, and nothing records which part.
    if now - last_run_at >= BACKSTOP_INTERVAL:
        return "backstop"
    environments = Team.objects.filter(Q(id=project_id) | Q(parent_team_id=project_id)).values("id")
    opted_in = [
        _OptedInWorkflow(id=flow_id, team_id=team_id, version=version, opted_in_at=created_at)
        for flow_id, team_id, version, created_at in _live_opt_ins(project_id).values_list(
            "hog_flow_id", "hog_flow__team_id", "hog_flow__version", "created_at"
        )
    ]
    if not opted_in:
        return None
    flow_ids = [workflow.id for workflow in opted_in]

    # The row keeps its first `created_at` when someone turns suggestions off and on again, so a
    # re-enable is only visible in the activity log.
    if any(workflow.opted_in_at >= last_run_at for workflow in opted_in):
        return "opted_in"
    # Turning suggestions back on and making an archived workflow live again write no revision, so the
    # activity log is the only record of either.
    activity = ActivityLog.objects.filter(
        team_id__in=environments,
        scope="HogFlow",
        item_id__in=[str(flow_id) for flow_id in flow_ids],
        created_at__gte=last_run_at,
    )
    if activity.filter(activity="optimization_enabled").exists():
        return "opted_in"
    if activity.filter(activity="updated", detail__changes__contains=[{"field": "status", "after": "active"}]).exists():
        return "reactivated"
    if (
        HogFlowRevision.objects.unscoped()
        .filter(team_id__in=environments, hog_flow_id__in=flow_ids, created_at__gte=last_run_at)
        .exists()
    ):
        return "published"
    if (
        WorkflowProposal.objects.unscoped()
        .filter(team_id__in=environments, hog_flow_id__in=flow_ids, resolved_at__gte=last_run_at)
        .exists()
    ):
        return "suggestion_resolved"
    return _email_metrics_reason(opted_in, last_run_at=last_run_at, now=now)


def _email_metrics_reason(
    opted_in: list[_OptedInWorkflow], *, last_run_at: datetime, now: datetime
) -> SuggestionsScoutRunReason | None:
    # One read per environment, because an environment can have its own ClickHouse host.
    by_team: dict[int, list[_OptedInWorkflow]] = {}
    for workflow in opted_in:
        by_team.setdefault(workflow.team_id, []).append(workflow)
    deadline = monotonic() + EMAIL_METRICS_MAX_EXECUTION_S
    reasons = {
        _environment_email_metrics_reason(team_id, workflows, last_run_at=last_run_at, now=now, deadline=deadline)
        for team_id, workflows in by_team.items()
    }
    for reason in ("sends_matured", "first_opens"):
        if reason in reasons:
            return reason
    return None


def _environment_email_metrics_reason(
    team_id: int, opted_in: list[_OptedInWorkflow], *, last_run_at: datetime, now: datetime, deadline: float
) -> SuggestionsScoutRunReason | None:
    """`sends_matured` when a send of a live version reached `SEND_MATURITY` after `last_run_at`, and
    `first_opens` when a live version recorded its first opens since then.

    The skill rules out a step with zero opens as a measurement gap and reads it again once opens
    appear, which can happen after its sends matured. Reads the per-version source because a batch
    send records its email metrics under the batch job id on the per-flow source, and under
    `<flow id>/<version>` here for every trigger type. Sends of an older version need no run,
    because the skill reads the live version only.
    """
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY, query_type="SuggestionsScoutEmailMetrics")
    params = {
        "team_id": team_id,
        "app_source": HOG_FLOW_VERSION_APP_SOURCE,
        "version_source_ids": [workflow.version_source_id for workflow in opted_in],
        "sent": TARGET_SEND_METRIC,
        "opened": TARGET_OPEN_METRIC,
        "matured_after": _clickhouse_time(last_run_at - SEND_MATURITY),
        "matured_before": _clickhouse_time(now - SEND_MATURITY),
        "last_run_at": _clickhouse_time(last_run_at),
    }
    recent = _bounded_metrics_read(
        """
        SELECT
            app_source_id,
            sumIf(count, metric_name = %(sent)s AND timestamp < toDateTime64(%(matured_before)s, 6)) AS matured_sends,
            sumIf(count, metric_name = %(opened)s AND timestamp >= toDateTime64(%(last_run_at)s, 6)) AS new_opens
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = %(app_source)s
          AND app_source_id IN %(version_source_ids)s
          AND metric_name IN (%(sent)s, %(opened)s)
          AND timestamp >= toDateTime64(%(matured_after)s, 6)
        GROUP BY app_source_id
        """,
        params,
        team_id=team_id,
        deadline=deadline,
    )
    if any(matured_sends > 0 for _, matured_sends, _ in recent):
        return "sends_matured"
    opened_versions = [source_id for source_id, _, new_opens in recent if new_opens > 0]
    if not opened_versions:
        return None
    # Only versions with new opens reach this read of their history, which is a quiet tick's rare case.
    opened_before = _bounded_metrics_read(
        """
        SELECT DISTINCT app_source_id
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = %(app_source)s
          AND app_source_id IN %(version_source_ids)s
          AND metric_name = %(opened)s
          AND timestamp < toDateTime64(%(last_run_at)s, 6)
          AND count > 0
        """,
        {**params, "version_source_ids": opened_versions},
        team_id=team_id,
        deadline=deadline,
    )
    return "first_opens" if len(opened_before) < len(opened_versions) else None


def _bounded_metrics_read(query: str, params: Mapping[str, object], *, team_id: int, deadline: float) -> list:
    """Run one read inside the time left before `deadline`. Raises when none is left, which runs the scout."""
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("The suggestions scout pre-check used up its metrics read budget.")
    return sync_execute(
        query,
        params,
        workload=Workload.OFFLINE,
        team_id=team_id,
        # The pre-check activity gives up after its own timeout and runs the scout, so a longer read
        # would only hold a worker thread and a connection for an answer nobody uses.
        settings={"max_execution_time": remaining, "timeout_overflow_mode": "throw"},
    )


def _clickhouse_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
