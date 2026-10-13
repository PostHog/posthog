"""Keep the workflows scout running exactly where someone asked for suggestions.

The scout only reads live workflows whose owner turned on "Suggest improvements", so a project with
none gains nothing from its runs. The first live opted-in workflow switches the scout on for the
project, and losing the last one, by opting out, archiving or deleting it, removes it again.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
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
from products.workflows.backend.metrics import HOG_FLOW_VERSION_APP_SOURCE, TARGET_SEND_METRIC
from products.workflows.backend.models import HogFlow, HogFlowOptimization, HogFlowRevision, WorkflowProposal

SUGGESTIONS_SCOUT = "signals-scout-workflows"
SOURCE_PRODUCT = "workflows"
PROPOSAL_WRITE_SCOPE = "hog_flow_proposal:write"
# Arbitrary, fixed namespace for the per-project advisory lock that serializes reconciliation.
_LOCK_NAMESPACE = 72_031
# The scout skill reads a send only once it is this old, because opens and bounces arrive after the send.
SEND_MATURITY = timedelta(hours=48)
SENDS_MATURED_MAX_EXECUTION_S = 5


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
        environments = Team.objects.filter(Q(id=project.id) | Q(parent_team_id=project.id)).values("id")
        wanted = (
            HogFlowOptimization.objects.unscoped()
            .filter(team_id__in=environments, enabled=True, hog_flow__status=HogFlow.State.ACTIVE)
            .exists()
        )
        if not wanted:
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


def suggestions_scout_run_reason(
    project_id: int, *, last_run_at: datetime | None, now: datetime
) -> SuggestionsScoutRunReason | None:
    """Why the suggestions scout has something new to read since its last run, or None when it has nothing.

    The scout decides only from opted-in live workflows: their opt-in, their published versions, how
    people resolved its suggestions, and email sends old enough to carry their opens. When none of
    these changed since `last_run_at`, a new run reads the same input as the last one.
    """
    if last_run_at is None:
        return "first_run"
    environments = Team.objects.filter(Q(id=project_id) | Q(parent_team_id=project_id)).values("id")
    opted_in = list(
        HogFlowOptimization.objects.unscoped()
        .filter(team_id__in=environments, enabled=True, hog_flow__status=HogFlow.State.ACTIVE)
        # The opt-in row is scoped to the project, while metrics are recorded under the workflow's environment.
        .values_list("hog_flow_id", "hog_flow__team_id", "created_at")
    )
    if not opted_in:
        return None
    flow_ids = [flow_id for flow_id, _, _ in opted_in]

    # The row keeps its first `created_at` when someone turns suggestions off and on again, so a
    # re-enable is only visible in the activity log.
    if any(created_at >= last_run_at for _, _, created_at in opted_in) or (
        ActivityLog.objects.filter(
            team_id__in=environments,
            scope="HogFlow",
            activity="optimization_enabled",
            item_id__in=[str(flow_id) for flow_id in flow_ids],
            created_at__gte=last_run_at,
        ).exists()
    ):
        return "opted_in"
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
    if _sends_matured_since(opted_in, last_run_at=last_run_at, now=now):
        return "sends_matured"
    return None


def _sends_matured_since(opted_in: list[tuple[UUID, int, datetime]], *, last_run_at: datetime, now: datetime) -> bool:
    """Whether any opted-in workflow sent email that reached `SEND_MATURITY` after `last_run_at`.

    Reads the per-version source because a batch send records its email metrics under the batch
    job id on the per-flow source, and under `<flow id>/<version>` here for every trigger type.
    """
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY, query_type="SuggestionsScoutSendsMatured")
    rows = sync_execute(
        """
        SELECT 1
        FROM app_metrics2
        WHERE team_id IN %(team_ids)s
          AND app_source = %(app_source)s
          AND metric_name = %(metric_name)s
          AND timestamp >= toDateTime64(%(after)s, 6)
          AND timestamp < toDateTime64(%(before)s, 6)
          AND splitByChar('/', app_source_id)[1] IN %(flow_ids)s
          AND count > 0
        LIMIT 1
        """,
        {
            "team_ids": sorted({team_id for _, team_id, _ in opted_in}),
            "app_source": HOG_FLOW_VERSION_APP_SOURCE,
            "metric_name": TARGET_SEND_METRIC,
            "after": (last_run_at - SEND_MATURITY).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "before": (now - SEND_MATURITY).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "flow_ids": [str(flow_id) for flow_id, _, _ in opted_in],
        },
        workload=Workload.OFFLINE,
        # The pre-check activity gives up after its own timeout and runs the scout, so a longer read
        # would only hold a worker thread and a connection for an answer nobody uses.
        settings={"max_execution_time": SENDS_MATURED_MAX_EXECUTION_S, "timeout_overflow_mode": "throw"},
    )
    return bool(rows)
