"""The scheduled personal ranking tick: a Temporal workflow that builds the lists of due (team, user) pairs.

The `tick` object of the `personal-inbox-ranking` flag payload holds every lever, and a missing or malformed
object turns the tick off. A pair is due when it has a ready activity summary, recent activity, and a latest
list that was built or checked longer ago than `target_interval_minutes`, or no list. The pair activity takes
the same per-person lock as the `for_me` read, so a tick and a read never build the same list together. It
compares the input hash first: a match records `checked_at` on the latest row and calls no model. A build that
calls the model spends the tick's daily limit and then the shared daily limit of the region.
"""

import uuid
import asyncio
import datetime
import dataclasses
from typing import Any, Literal

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, DateTimeField, Exists, F, Min, OuterRef, Q, QuerySet, Subquery, Value, Window
from django.db.models.functions import Coalesce, RowNumber
from django.utils import timezone

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import openai_gateway_configured
from posthog.models import OrganizationMembership, Team, User
from posthog.ph_client import ph_background_capture
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.activity_summary.config import read_config as read_activity_summary_config
from products.signals.backend.activity_summary.queue import read_enrolled_teams
from products.signals.backend.facade.api import has_enabled_source, team_ids_with_enabled_source
from products.signals.backend.models import PersonalInboxRanking, UserActivitySummary, UserActivitySummaryQueueState
from products.signals.backend.org_rollout import in_rollout, parse_organization_ids
from products.signals.backend.personal_ranking.build_budget import (
    refund_tick_build,
    spend_shared_build,
    spend_tick_build,
)
from products.signals.backend.personal_ranking.candidates import gather_candidates
from products.signals.backend.personal_ranking.config import (
    PersonalRankingConfig,
    PersonalRankingTickConfig,
    read_config,
)
from products.signals.backend.personal_ranking.logic import (
    CHANGED_NO_PREVIOUS,
    CHANGED_UNKNOWN,
    INPUT_PARTS,
    PIPELINE_DISTINCT_ID,
    RETRYABLE_FALLBACK_REASONS,
    build_personal_ranking,
    input_hash,
    latest_row,
    may_call_model,
)
from products.signals.backend.personal_ranking.serve import ready_summary_version
from products.signals.backend.personal_ranking_tasks import BUILD_LOCK_TTL_SECONDS, build_lock_key

logger = structlog.get_logger(__name__)

TICK_WORKFLOW_NAME = "personal-inbox-ranking-tick"
TICK_EVENT = "personal inbox ranking tick"

# Stop reasons of a tick. Null when the tick handled every due pair.
STOP_MAX_PAIRS_PER_TICK = "max_pairs_per_tick"
# Due pairs are left, but each organization with due pairs already has its share of the tick.
STOP_MAX_ORG_SHARE = "max_org_share"
STOP_MAX_TICK_BUILDS_PER_DAY = "max_tick_builds_per_day"
STOP_MAX_BUILDS_PER_DAY = "max_builds_per_day"
STOP_ERROR_RATE = "error_rate"
STOP_GATEWAY_NOT_CONFIGURED = "gateway_not_configured"
# The tick stopped before the next tick starts, so the schedule does not skip it.
STOP_TIME_BUDGET = "time_budget"

PairStatus = Literal[
    "built", "failed", "unchanged", "running", "not_enrolled", "tick_limited", "shared_limited", "disabled"
]
PAIR_STATUSES: tuple[PairStatus, ...] = (
    "built",
    "failed",
    "unchanged",
    "running",
    "not_enrolled",
    "tick_limited",
    "shared_limited",
    "disabled",
)
_LIMIT_STOPS: dict[PairStatus, str] = {
    "tick_limited": STOP_MAX_TICK_BUILDS_PER_DAY,
    "shared_limited": STOP_MAX_BUILDS_PER_DAY,
}

# A new salt reorders every organization, so change the version only to start a new rollout order.
_ROLLOUT_SALT = "personal-inbox-ranking-tick-v1"
# The circuit breaker waits for this many model calls, so a few early failures do not stop the tick.
_MIN_ERROR_RATE_SAMPLE = 10

_PLAN_TIMEOUT = datetime.timedelta(minutes=5)
# One build has a model call of at most 120 seconds, and the candidate reads around it.
_PAIR_TIMEOUT = datetime.timedelta(minutes=4)
_PAIR_HEARTBEAT_TIMEOUT = datetime.timedelta(minutes=1)
# No retry: an attempt can have called the model, and the next tick picks the pair again.
_PAIR_RETRY_POLICY = RetryPolicy(maximum_attempts=1)
# The tick starts no wave after this share of its interval, so the last wave ends before the next tick.
_TIME_BUDGET_SHARE = 0.6


@frozen
class PersonalRankingTickInput:
    # A manual run can override the per-tick cap of the payload.
    limit: int | None = None


@frozen
class TickPair:
    team_id: int
    user_id: int


@frozen
class TickEnrollment:
    team_ids: list[int]
    organization_ids: list[uuid.UUID]
    # The organizations that a 100 percent rollout enrolls, with or without manual enrollment.
    qualifying_organization_ids: list[uuid.UUID]


@frozen
class TickSelection:
    pairs: list[TickPair]
    due_pairs: int = 0
    due_without_list: int = 0
    # Hours since the oldest list of a due pair was built or checked. Null when no due pair has a list.
    oldest_due_hours: float | None = None
    # The share of eligible pairs whose list was built or checked inside `target_interval_minutes`.
    fresh_share: float | None = None


@frozen
class PersonalRankingTickPlan:
    enabled: bool
    pairs: list[TickPair]
    max_concurrency: int
    max_error_rate: float
    time_budget_seconds: float
    stop_reason: str | None
    due_pairs: int = 0
    due_without_list: int = 0
    oldest_due_hours: float | None = None
    fresh_share: float | None = None
    qualifying_organizations: int = 0
    enrolled_organizations: int = 0
    enrolled_teams: int = 0


@frozen
class PersonalRankingPairResult:
    status: PairStatus
    model_called: bool = False
    # The `changed_parts` of the build. Empty when the pair did not build.
    changed_parts: list[str] = dataclasses.field(default_factory=list)


@frozen
class PersonalRankingTickResult:
    enabled: bool = False
    due_pairs: int = 0
    due_without_list: int = 0
    picked: int = 0
    statuses: dict[str, int] = dataclasses.field(default_factory=dict)
    # Built pairs by changed input part. A pair with two changed parts counts in both.
    changed_parts: dict[str, int] = dataclasses.field(default_factory=dict)
    errored: int = 0
    stop_reason: str | None = None
    oldest_due_hours: float | None = None
    fresh_share: float | None = None
    qualifying_organizations: int = 0
    enrolled_organizations: int = 0
    enrolled_teams: int = 0
    duration_seconds: float = 0.0


def _in_rollout(percentage: float, organization_id: uuid.UUID) -> bool:
    return in_rollout(_ROLLOUT_SALT, percentage, organization_id)


def _eligible_teams(tick: PersonalRankingTickConfig) -> QuerySet[Team]:
    """Teams with AI data processing approval and a readable activity summary, minus the skip and deny lists."""
    teams = read_enrolled_teams(read_activity_summary_config(), Team.objects.all())
    return teams.exclude(id__in=tick.skip_team_ids).exclude(
        organization_id__in=parse_organization_ids(tick.deny_organization_ids)
    )


def enrollment(config: PersonalRankingConfig) -> TickEnrollment:
    """The teams that `is_team_enrolled` enrolls, in a fixed number of queries."""
    tick = config.tick
    if not config.enabled or not tick.enabled:
        return TickEnrollment(team_ids=[], organization_ids=[], qualifying_organization_ids=[])
    teams = _eligible_teams(tick)
    listed = parse_organization_ids(tick.organization_ids)
    with_source: dict[int, uuid.UUID] = dict(
        teams.filter(id__in=team_ids_with_enabled_source()).values_list("id", "organization_id")
    )
    enrolled = dict(teams.filter(organization_id__in=listed).values_list("id", "organization_id")) if listed else {}
    enrolled |= {
        team_id: organization_id
        for team_id, organization_id in with_source.items()
        if _in_rollout(tick.self_driving_organization_percentage, organization_id)
    }
    return TickEnrollment(
        team_ids=sorted(enrolled),
        organization_ids=sorted(set(enrolled.values())),
        qualifying_organization_ids=sorted(set(with_source.values())),
    )


def is_team_enrolled(config: PersonalRankingConfig, team: Team) -> bool:
    """The tick may build lists for the team. The single-team form of `enrollment`.

    Enrollment decides who gets scheduled builds. It does not change who can read `for_me`.
    """
    tick = config.tick
    if not config.enabled or not tick.enabled:
        return False
    if not _eligible_teams(tick).filter(id=team.id).exists():
        return False
    if team.organization_id in parse_organization_ids(tick.organization_ids):
        return True
    return _in_rollout(tick.self_driving_organization_percentage, team.organization_id) and has_enabled_source(team.id)


def _list_at() -> Subquery:
    """When the pair's latest list was built, or checked unchanged by a later tick."""
    return Subquery(
        PersonalInboxRanking.all_teams.filter(team_id=OuterRef("team_id"), user_id=OuterRef("user_id"))
        .order_by("-created_at", "-id")
        .annotate(at=Coalesce("checked_at", "created_at"))
        .values("at")[:1],
        output_field=DateTimeField(),
    )


def _eligible_pairs(tick: PersonalRankingTickConfig, now: datetime.datetime, team_ids: list[int]) -> QuerySet:
    """The pairs of these teams with a ready summary, an active member and activity in the last `active_days`."""
    last_activity_at = Subquery(
        UserActivitySummaryQueueState.all_teams.filter(team_id=OuterRef("team_id"), user_id=OuterRef("user_id")).values(
            "last_activity_at"
        )[:1],
        output_field=DateTimeField(),
    )
    is_member = OrganizationMembership.objects.filter(
        user_id=OuterRef("user_id"), organization_id=OuterRef("team__organization_id")
    )
    return (
        # nosemgrep: idor-lookup-without-team (system tick with no user input; filtered to the enrolled teams)
        UserActivitySummary.all_teams.filter(
            team_id__in=team_ids, summary__isnull=False, generated_at__isnull=False, user__is_active=True
        )
        .filter(Exists(is_member))
        .annotate(
            organization_id=F("team__organization_id"),
            paying=Coalesce(F("team__organization__has_active_subscription"), Value(False)),
            last_activity_at=last_activity_at,
            list_at=_list_at(),
        )
        .filter(last_activity_at__gte=now - datetime.timedelta(days=tick.active_days))
    )


def select_pairs(
    config: PersonalRankingConfig, now: datetime.datetime, limit: int, team_ids: list[int]
) -> TickSelection:
    """The due pairs of the enrolled teams, cut to `limit`.

    Paying organizations come first, then the most recent activity, then the oldest list. No organization
    takes more than `max_org_share` of `limit`.
    """
    if not team_ids:
        return TickSelection(pairs=[])
    tick = config.tick
    stale_before = now - datetime.timedelta(minutes=tick.target_interval_minutes)
    eligible = _eligible_pairs(tick, now, team_ids)
    due = eligible.filter(Q(list_at__isnull=True) | Q(list_at__lt=stale_before))
    order = (
        F("paying").desc(),
        F("last_activity_at").desc(nulls_last=True),
        F("list_at").asc(nulls_first=True),
        "team_id",
        "user_id",
    )
    rows = list(
        due.annotate(org_rank=Window(RowNumber(), partition_by=[F("organization_id")], order_by=order))
        .filter(org_rank__lte=max(1, int(tick.max_org_share * limit)))
        .order_by(*order)
        .values("team_id", "user_id")[:limit]
    )
    due_stats = due.aggregate(
        pairs=Count("id"), without_list=Count("id", filter=Q(list_at__isnull=True)), oldest=Min("list_at")
    )
    eligible_stats = eligible.aggregate(pairs=Count("id"), fresh=Count("id", filter=Q(list_at__gte=stale_before)))
    oldest: datetime.datetime | None = due_stats["oldest"]
    return TickSelection(
        pairs=[TickPair(team_id=row["team_id"], user_id=row["user_id"]) for row in rows],
        due_pairs=due_stats["pairs"],
        due_without_list=due_stats["without_list"],
        oldest_due_hours=(now - oldest).total_seconds() / 3600 if oldest is not None else None,
        fresh_share=eligible_stats["fresh"] / eligible_stats["pairs"] if eligible_stats["pairs"] else None,
    )


def plan_tick(limit: int | None, now: datetime.datetime) -> PersonalRankingTickPlan:
    config = read_config()
    tick = config.tick
    enabled = config.enabled and tick.enabled
    interval_seconds = settings.PERSONAL_INBOX_RANKING_TICK_INTERVAL_MINUTES * 60
    time_budget_seconds = interval_seconds * _TIME_BUDGET_SHARE
    if enabled and not openai_gateway_configured():
        # Every build would fail on the same missing gateway, so the tick runs none.
        logger.warning("personal_inbox_ranking_tick_gateway_not_configured")
        return PersonalRankingTickPlan(
            enabled=False,
            pairs=[],
            max_concurrency=tick.max_concurrency,
            max_error_rate=tick.max_error_rate,
            time_budget_seconds=time_budget_seconds,
            stop_reason=STOP_GATEWAY_NOT_CONFIGURED,
        )
    enrolled = enrollment(config)
    tick_limit = limit or tick.max_pairs_per_tick
    selection = select_pairs(config, now, tick_limit, enrolled.team_ids) if enabled else TickSelection(pairs=[])
    stop_reason: str | None = None
    if selection.due_pairs > len(selection.pairs):
        stop_reason = STOP_MAX_PAIRS_PER_TICK if len(selection.pairs) >= tick_limit else STOP_MAX_ORG_SHARE
    return PersonalRankingTickPlan(
        enabled=enabled,
        pairs=selection.pairs,
        max_concurrency=tick.max_concurrency,
        max_error_rate=tick.max_error_rate,
        time_budget_seconds=time_budget_seconds,
        stop_reason=stop_reason,
        due_pairs=selection.due_pairs,
        due_without_list=selection.due_without_list,
        oldest_due_hours=selection.oldest_due_hours,
        fresh_share=selection.fresh_share,
        qualifying_organizations=len(enrolled.qualifying_organization_ids),
        enrolled_organizations=len(enrolled.organization_ids),
        enrolled_teams=len(enrolled.team_ids),
    )


def _check_and_build(team: Team, user: User, config: PersonalRankingConfig) -> PersonalRankingPairResult:
    now = timezone.now()
    latest = latest_row(team, user)
    candidates = gather_candidates(team, user, config, now=now, with_sources=False)
    summary_version = ready_summary_version(team, user)
    current_hash = input_hash(candidates, activity_summary_version=summary_version, focus=None)
    if (
        latest is not None
        and latest.input_hash == current_hash
        and latest.fallback_reason not in RETRYABLE_FALLBACK_REASONS
    ):
        # The list is still current, so the pair leaves the due set until `target_interval_minutes` passes again.
        PersonalInboxRanking.objects.for_team(team.id).filter(id=latest.id).update(checked_at=now)
        return PersonalRankingPairResult(status="unchanged")
    calls_model = bool(candidates) and may_call_model(team, summary_ready=summary_version is not None)
    if calls_model:
        if not spend_tick_build(config):
            return PersonalRankingPairResult(status="tick_limited")
        if spend_shared_build(config) is not None:
            refund_tick_build(config)
            return PersonalRankingPairResult(status="shared_limited")
    build = build_personal_ranking(team, user, config=config, trigger="tick")
    if build.status == "disabled":
        return PersonalRankingPairResult(status="disabled")
    failed = build.model_called and build.status == "fallback"
    return PersonalRankingPairResult(
        status="failed" if failed else "built",
        model_called=build.model_called,
        changed_parts=list(build.input_changes.changed_parts) if build.input_changes is not None else [],
    )


def run_pair(pair: TickPair) -> PersonalRankingPairResult:
    # The payload can change between the plan and the pair, so the pair reads it again.
    config = read_config()
    team = Team.objects.select_related("organization").filter(id=pair.team_id).first()
    user = User.objects.filter(id=pair.user_id, is_active=True).first()
    if team is None or user is None or not is_team_enrolled(config, team):
        return PersonalRankingPairResult(status="not_enrolled")
    lock_key = build_lock_key(team.id, user.id)
    if not cache.add(lock_key, "1", timeout=BUILD_LOCK_TTL_SECONDS):
        return PersonalRankingPairResult(status="running")
    try:
        return _check_and_build(team, user, config)
    finally:
        cache.delete(lock_key)


def capture_tick(result: PersonalRankingTickResult) -> None:
    properties: dict[str, Any] = {
        "deployment": settings.CLOUD_DEPLOYMENT,
        "due_pairs": result.due_pairs,
        "due_without_list": result.due_without_list,
        "picked": result.picked,
        **{status: result.statuses.get(status, 0) for status in PAIR_STATUSES},
        **{
            f"changed_{part}": result.changed_parts.get(part, 0)
            for part in (*INPUT_PARTS, CHANGED_NO_PREVIOUS, CHANGED_UNKNOWN)
        },
        "errored": result.errored,
        "stop_reason": result.stop_reason,
        "oldest_due_hours": result.oldest_due_hours,
        "fresh_share": result.fresh_share,
        "qualifying_organizations": result.qualifying_organizations,
        "enrolled_organizations": result.enrolled_organizations,
        "enrolled_teams": result.enrolled_teams,
        "duration_seconds": result.duration_seconds,
    }
    logger.info("personal_inbox_ranking_tick_finished", **properties)
    ph_background_capture()(distinct_id=PIPELINE_DISTINCT_ID, event=TICK_EVENT, properties=properties)


@activity.defn
@scoped_temporal()
@close_db_connections
async def plan_personal_ranking_tick_activity(input: PersonalRankingTickInput) -> PersonalRankingTickPlan:
    return await database_sync_to_async(plan_tick, thread_sensitive=False)(input.limit, timezone.now())


@activity.defn
@scoped_temporal()
@close_db_connections
async def build_personal_ranking_pair_activity(pair: TickPair) -> PersonalRankingPairResult:
    async with Heartbeater():
        return await database_sync_to_async(run_pair, thread_sensitive=False)(pair)


@activity.defn
@scoped_temporal()
@close_db_connections
async def capture_personal_ranking_tick_activity(result: PersonalRankingTickResult) -> None:
    await database_sync_to_async(capture_tick, thread_sensitive=False)(result)


@workflow.defn(name=TICK_WORKFLOW_NAME)
class PersonalRankingTickWorkflow:
    @workflow.run
    async def run(self, inputs: PersonalRankingTickInput) -> PersonalRankingTickResult:
        started = workflow.now()
        plan = await workflow.execute_activity(
            plan_personal_ranking_tick_activity,
            inputs,
            start_to_close_timeout=_PLAN_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        if not plan.enabled:
            return PersonalRankingTickResult(stop_reason=plan.stop_reason)

        deadline = started + datetime.timedelta(seconds=plan.time_budget_seconds)
        statuses: dict[str, int] = {}
        changed_parts: dict[str, int] = {}
        errored = 0
        # Model calls of this tick and the calls among them that failed or raised, for the circuit breaker.
        calls = 0
        failures = 0
        picked = 0
        stop_reason = plan.stop_reason
        concurrency = max(1, plan.max_concurrency)
        index = 0
        while index < len(plan.pairs):
            # The pairs not attempted yet stay due, so the next tick picks them.
            if calls >= _MIN_ERROR_RATE_SAMPLE and failures >= plan.max_error_rate * calls:
                stop_reason = STOP_ERROR_RATE
                break
            if workflow.now() >= deadline:
                stop_reason = STOP_TIME_BUDGET
                break
            wave = plan.pairs[index : index + concurrency]
            index += len(wave)
            picked += len(wave)
            results = await asyncio.gather(
                *(
                    workflow.execute_activity(
                        build_personal_ranking_pair_activity,
                        pair,
                        start_to_close_timeout=_PAIR_TIMEOUT,
                        heartbeat_timeout=_PAIR_HEARTBEAT_TIMEOUT,
                        retry_policy=_PAIR_RETRY_POLICY,
                    )
                    for pair in wave
                ),
                return_exceptions=True,
            )
            limit_stop: str | None = None
            for outcome in results:
                if isinstance(outcome, BaseException):
                    # The attempt can have called the model, so it counts as a failed call.
                    errored += 1
                    calls += 1
                    failures += 1
                    continue
                statuses[outcome.status] = statuses.get(outcome.status, 0) + 1
                for part in outcome.changed_parts:
                    changed_parts[part] = changed_parts.get(part, 0) + 1
                calls += outcome.model_called
                failures += outcome.status == "failed"
                limit_stop = limit_stop or _LIMIT_STOPS.get(outcome.status)
            if limit_stop is not None:
                stop_reason = limit_stop
                break

        result = PersonalRankingTickResult(
            enabled=True,
            due_pairs=plan.due_pairs,
            due_without_list=plan.due_without_list,
            picked=picked,
            statuses=statuses,
            changed_parts=changed_parts,
            errored=errored,
            stop_reason=stop_reason,
            oldest_due_hours=plan.oldest_due_hours,
            fresh_share=plan.fresh_share,
            qualifying_organizations=plan.qualifying_organizations,
            enrolled_organizations=plan.enrolled_organizations,
            enrolled_teams=plan.enrolled_teams,
            duration_seconds=(workflow.now() - started).total_seconds(),
        )
        await workflow.execute_activity(
            capture_personal_ranking_tick_activity,
            result,
            start_to_close_timeout=datetime.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return result
