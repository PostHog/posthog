"""Keep the workflows scout running exactly where someone asked for suggestions.

The scout only reads live workflows whose owner turned on "Suggest improvements", so a project with
none gains nothing from its runs. The first live opted-in workflow switches the scout on for the
project, and losing the last one, by opting out, archiving or deleting it, removes it again.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.db import connection, transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import ActivityLog, Team, User
from posthog.schema_enums import ProductKey

from products.signals.backend.facade.api import (
    ScoutEnableRefusal,
    ScoutSchedule,
    disable_scout_for_product,
    enable_scout_for_product,
    scout_emits_for_product,
    scout_enable_refusal_for_product,
    scout_schedule_for_product,
    scout_status_for_product,
)
from products.workflows.backend.facade.contracts import SuggestionsSample, SuggestionsScoutRunReason
from products.workflows.backend.metrics import (
    HOG_FLOW_VERSION_APP_SOURCE,
    MIN_EVIDENCE_SAMPLE,
    RUN_STARTED_METRIC,
    TARGET_SEND_METRIC,
    TARGET_UNTRACKED_METRIC,
)
from products.workflows.backend.models import HogFlow, HogFlowOptimization, HogFlowRevision, WorkflowProposal
from products.workflows.backend.services.workflow_proposals import ConversionBasis, scout_conversion_window

SUGGESTIONS_SCOUT = "signals-scout-workflows"
SOURCE_PRODUCT = "workflows"
PROPOSAL_WRITE_SCOPE = "hog_flow_proposal:write"
# The scout's sample floor: tracked sends per email step, read over this window, from a version live this long.
SAMPLE_WINDOW = timedelta(days=7)
SAMPLE_MIN_VERSION_AGE = timedelta(hours=48)
# Arbitrary, fixed namespace for the per-project advisory lock that serializes reconciliation.
_LOCK_NAMESPACE = 72_031
# The scout skill reads a send only once it is this old, because opens and bounces arrive after the send.
SEND_MATURITY = timedelta(hours=48)
# The scout skill ends its conversion read this long after the conversion window closes, on a whole UTC day.
CONVERSION_SETTLE_ALLOWANCE = timedelta(hours=2)
EMAIL_METRICS_MAX_EXECUTION_S = 5
# The longest the scout goes without a run, so workflows a short run left unread still get read.
BACKSTOP_INTERVAL = timedelta(days=7)
_SAMPLE_QUERY_TIMEOUT_SECONDS = 5
# Bounds compare on the hour because the table collapses rows per clock hour and keeps one arbitrary timestamp.
_STEP_SENDS_QUERY = """
    SELECT
        instance_id,
        sumIf(count, metric_name = %(sent)s AND toStartOfHour(timestamp) >= toDateTime64(%(after)s, 6)
            AND toStartOfHour(timestamp) < toDateTime64(%(before)s, 6)) AS sent,
        sumIf(count, metric_name = %(untracked)s AND toStartOfHour(timestamp) >= toDateTime64(%(after)s, 6)
            AND toStartOfHour(timestamp) < toDateTime64(%(before)s, 6)) AS untracked,
        min(toStartOfHour(timestamp)) AS first_send
    FROM app_metrics2
    WHERE team_id = %(team_id)s
    AND app_source = %(app_source)s
    AND app_source_id = %(app_source_id)s
    AND instance_id IN %(step_ids)s
    AND metric_name IN (%(sent)s, %(untracked)s)
    GROUP BY instance_id
"""


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
    """`running`, `dry_run`, `paused_by_user`, `paused_by_system` or `not_running` for the project's suggestions scout."""
    project = team.parent_team or team
    status = scout_status_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT)
    if status is None:
        return "not_running"
    if status in ("paused_by_user", "paused_by_system"):
        return status
    # A dry run holds no write scopes, so it can never file a suggestion.
    if scout_emits_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT) is False:
        return "dry_run"
    return "running"


def suggestions_scout_schedule(team: Team) -> ScoutSchedule | None:
    """When the project's suggestions scout last checked its workflows and roughly when it checks next."""
    project = team.parent_team or team
    return scout_schedule_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT)


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
    conversion: dict[str, Any] | None
    trigger: dict[str, Any] | None
    actions: list[Any]

    @property
    def version_source_id(self) -> str:
        return f"{self.id}/{self.version}"

    @property
    def has_email_step(self) -> bool:
        return any(isinstance(action, dict) and action.get("type") == "function_email" for action in self.actions)


def suggestions_scout_run_reason(
    project_id: int, *, last_run_at: datetime | None, now: datetime
) -> SuggestionsScoutRunReason | None:
    """Why the suggestions scout has something new to read since its last run, or None when it has nothing.

    The scout decides only from opted-in live workflows: their opt-in, their published versions, how
    people resolved its suggestions, email sends of the live version, and its runs whose conversion
    window closed. When none of these changed since `last_run_at`, a new run reads the same input as
    the last one.
    """
    if last_run_at is None:
        return "first_run"
    # A run can cover only part of the opted-in workflows, and nothing records which part.
    if now - last_run_at >= BACKSTOP_INTERVAL:
        return "backstop"
    environments = Team.objects.filter(Q(id=project_id) | Q(parent_team_id=project_id)).values("id")
    opted_in = [
        _OptedInWorkflow(
            id=flow_id,
            team_id=team_id,
            version=version,
            opted_in_at=created_at,
            conversion=conversion,
            trigger=trigger,
            actions=actions or [],
        )
        for flow_id, team_id, version, created_at, conversion, trigger, actions in _live_opt_ins(
            project_id
        ).values_list(
            "hog_flow_id",
            "hog_flow__team_id",
            "hog_flow__version",
            "created_at",
            "hog_flow__conversion",
            "hog_flow__trigger",
            "hog_flow__actions",
        )
    ]
    if not opted_in:
        return None
    flow_ids = [workflow.id for workflow in opted_in]

    # The row keeps its first `created_at` when someone turns suggestions off and on again, so a
    # re-enable is only visible in the activity log.
    if any(workflow.opted_in_at >= last_run_at for workflow in opted_in):
        return "opted_in"
    if ActivityLog.objects.filter(
        team_id__in=environments,
        scope="HogFlow",
        item_id__in=[str(flow_id) for flow_id in flow_ids],
        activity="optimization_enabled",
        created_at__gte=last_run_at,
    ).exists():
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
    # One read per environment, because an environment can have its own ClickHouse host.
    by_team: dict[int, list[_OptedInWorkflow]] = {}
    for workflow in opted_in:
        by_team.setdefault(workflow.team_id, []).append(workflow)
    if any(
        _has_matured_sends(team_id, workflows, last_run_at=last_run_at, now=now)
        for team_id, workflows in by_team.items()
    ):
        return "sends_matured"
    if any(
        _has_settled_conversions(team_id, workflows, last_run_at=last_run_at, now=now)
        for team_id, workflows in by_team.items()
    ):
        return "conversions_settled"
    return None


def _has_matured_sends(team_id: int, opted_in: list[_OptedInWorkflow], *, last_run_at: datetime, now: datetime) -> bool:
    """Whether a send of a live version reached `SEND_MATURITY` after `last_run_at`.

    Reads the per-version source because a batch send records its email metrics under the batch job
    id on the per-flow source, and under `<flow id>/<version>` here for every trigger type. Sends of
    an older version need no run, because the skill reads the live version only.
    """
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY, query_type="SuggestionsScoutEmailMetrics")
    rows = sync_execute(
        """
        SELECT 1
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = %(app_source)s
          AND app_source_id IN %(version_source_ids)s
          AND metric_name = %(sent)s
          AND timestamp >= toDateTime64(%(matured_after)s, 6)
          AND timestamp < toDateTime64(%(matured_before)s, 6)
          AND count > 0
        LIMIT 1
        """,
        {
            "team_id": team_id,
            "app_source": HOG_FLOW_VERSION_APP_SOURCE,
            "version_source_ids": [workflow.version_source_id for workflow in opted_in],
            "sent": TARGET_SEND_METRIC,
            "matured_after": _clickhouse_time(last_run_at - SEND_MATURITY),
            "matured_before": _clickhouse_time(now - SEND_MATURITY),
        },
        workload=Workload.OFFLINE,
        team_id=team_id,
        # A slow read raises, and the pre-check runs the scout on any error.
        settings={"max_execution_time": EMAIL_METRICS_MAX_EXECUTION_S, "timeout_overflow_mode": "throw"},
    )
    return bool(rows)


@frozen
class _SettledRuns:
    """The runs of one live version that the scout can read, and the first of them its last run could not."""

    start: datetime
    new_from: datetime
    end: datetime


def _settled_runs(basis: ConversionBasis, *, last_run_at: datetime, now: datetime) -> _SettledRuns | None:
    window = scout_conversion_window(basis)
    if window is None:
        return None

    def settled_day(moment: datetime) -> datetime:
        settled = (moment - window - CONVERSION_SETTLE_ALLOWANCE).astimezone(UTC)
        return settled.replace(hour=0, minute=0, second=0, microsecond=0)

    start, end = basis.recorded_since, settled_day(now)
    new_from = max(start, settled_day(last_run_at))
    return _SettledRuns(start=start, new_from=new_from, end=end) if new_from < end else None


def _has_settled_conversions(
    team_id: int, opted_in: list[_OptedInWorkflow], *, last_run_at: datetime, now: datetime
) -> bool:
    """Whether runs of a live version finished their conversion window after `last_run_at`, with a sample to judge."""
    # A suggestion aimed at conversion changes an email step, so a workflow without one has nothing to read.
    with_conversion = [workflow for workflow in opted_in if workflow.conversion and workflow.has_email_step]
    # The scheduler has no team context, so this names its team instead of relying on the scope.
    published = {
        (flow_id, version): ConversionBasis(conversion=conversion, trigger=trigger)
        for flow_id, version, conversion, trigger in HogFlowRevision.objects.unscoped()
        .filter(
            hog_flow__team_id=team_id,
            hog_flow_id__in=[workflow.id for workflow in with_conversion],
            version=F("hog_flow__version"),
        )
        .values_list("hog_flow_id", "version", "content__conversion", "content__trigger")
    }
    settled_by_source: dict[str, _SettledRuns] = {}
    for workflow in with_conversion:
        basis = published.get(
            (workflow.id, workflow.version),
            ConversionBasis(conversion=workflow.conversion, trigger=workflow.trigger),
        )
        if settled := _settled_runs(basis, last_run_at=last_run_at, now=now):
            settled_by_source[workflow.version_source_id] = settled
    if not settled_by_source:
        return False
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY, query_type="SuggestionsScoutSettledRuns")
    rows = sync_execute(
        """
        SELECT app_source_id, toDate(timestamp, 'UTC') AS day, sum(count)
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = %(app_source)s
          AND app_source_id IN %(version_source_ids)s
          AND metric_name = %(started)s
          AND timestamp >= toDateTime64(%(after)s, 6)
          AND timestamp < toDateTime64(%(before)s, 6)
        GROUP BY app_source_id, day
        """,
        {
            "team_id": team_id,
            "app_source": HOG_FLOW_VERSION_APP_SOURCE,
            "version_source_ids": list(settled_by_source),
            "started": RUN_STARTED_METRIC,
            "after": _clickhouse_time(min(settled.start for settled in settled_by_source.values())),
            "before": _clickhouse_time(max(settled.end for settled in settled_by_source.values())),
        },
        workload=Workload.OFFLINE,
        team_id=team_id,
        # A slow read raises, and the pre-check runs the scout on any error.
        settings={"max_execution_time": EMAIL_METRICS_MAX_EXECUTION_S, "timeout_overflow_mode": "throw"},
    )
    runs_by_source: dict[str, int] = defaultdict(int)
    sources_with_new_runs: set[str] = set()
    for source_id, day, count in rows:
        settled = settled_by_source[source_id]
        if settled.start.date() <= day < settled.end.date():
            runs_by_source[source_id] += count
            if count > 0 and day >= settled.new_from.date():
                sources_with_new_runs.add(source_id)
    return any(runs_by_source[source_id] >= MIN_EVIDENCE_SAMPLE for source_id in sources_with_new_runs)


def _clickhouse_time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def suggestions_sample(*, team_id: int, hog_flow_id: UUID) -> SuggestionsSample | None:
    """Whether any email step of the live version clears the scout's sample floor, or None without an email step."""
    flow = (
        HogFlow.objects.filter(team_id=team_id, pk=hog_flow_id).only("id", "version", "actions", "created_at").first()
    )
    if flow is None:
        return None
    step_ids = [
        str(action["id"])
        for action in flow.actions or []
        if isinstance(action, dict) and action.get("type") == "function_email" and action.get("id")
    ]
    if not step_ids:
        return None
    now = timezone.now()
    # The scout reads whole UTC days that have closed, so the window ends at the last midnight.
    window_end = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = sync_execute(
        _STEP_SENDS_QUERY,
        {
            "team_id": team_id,
            "app_source": HOG_FLOW_VERSION_APP_SOURCE,
            "app_source_id": f"{flow.id}/{flow.version}",
            "step_ids": step_ids,
            "sent": TARGET_SEND_METRIC,
            "untracked": TARGET_UNTRACKED_METRIC,
            "after": (window_end - SAMPLE_WINDOW).strftime("%Y-%m-%dT%H:%M:%S"),
            "before": window_end.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        settings={"max_execution_time": _SAMPLE_QUERY_TIMEOUT_SECONDS},
        team_id=team_id,
    )
    tracked_sends = max((int(sent) - int(untracked) for _, sent, untracked, _ in rows), default=0)
    first_sends = [first_send for *_, first_send in rows]
    if first_sends:
        # Activating a draft does not create a revision, so the version's first send is when it went live.
        live_since = min(first_sends)
    else:
        # A flow with no revision for its version predates revision tracking, so it has been live at least since creation.
        revision = (
            HogFlowRevision.objects.for_team(team_id)
            .filter(hog_flow=flow, version=flow.version)
            .values_list("created_at", flat=True)
        )
        live_since = revision.first() or flow.created_at
    return SuggestionsSample(
        reached=tracked_sends >= MIN_EVIDENCE_SAMPLE and now - live_since >= SAMPLE_MIN_VERSION_AGE,
        tracked_sends=tracked_sends,
        required_sends=MIN_EVIDENCE_SAMPLE,
        version_live_since=live_since,
    )
