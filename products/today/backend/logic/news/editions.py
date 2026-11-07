import time
import asyncio
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog
import posthoganalytics
from pydantic import TypeAdapter
from temporalio.common import WorkflowIDReusePolicy

from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect
from posthog.token_bucket import BucketDecision, Budget, consume, refund

from ...facade.contracts import NewsEdition, TodayNews
from ...facade.enums import NewsSkipReason, NewsStatus
from ...feature_flags import news_may_use_ai
from ...models import NewsPeriod, TodayHighlights, TodayNewsEdition
from ...temporal.inputs import NEWS_WORKFLOW_NAME, FailNewsInputs, GenerateNewsInputs, news_workflow_id
from ..highlight_types import Context
from . import (
    assemble,
    candidates as news_candidates,
    plan as news_plan,
    queries,
    writer,
)
from .assemble import StoredEdition
from .candidates import Candidate

logger = structlog.get_logger(__name__)

COMPUTING_SECONDS = 10 * 60
FAILED_RETRY_SECONDS = 60 * 60
START_LOCK_SECONDS = 30
ACTIVE_DAYS = 7
MIN_ACTIVE_PEOPLE = 2
DAILY_CAP = 1000
BUDGET = Budget(burst=DAILY_CAP // 4, per_hour=DAILY_CAP // 24)
BUDGET_KEY = "today_news_rate:global"
MAX_ERROR_LENGTH = 2000

STORED_EDITION = TypeAdapter(StoredEdition)
CANDIDATES = TypeAdapter(list[Candidate])
GENERATED_EVENT = "today news edition generated"


class NewsWriteFailed(Exception):
    pass


def period_start(team: Team, now: datetime) -> date:
    return now.astimezone(team.timezone_info).date()


def _is_due(row: TodayNewsEdition, now: datetime) -> bool:
    if row.status == NewsStatus.COMPUTING:
        return row.created_at < now - timedelta(seconds=COMPUTING_SECONDS)
    if row.status == NewsStatus.FAILED:
        return (row.ready_at or row.created_at) < now - timedelta(seconds=FAILED_RETRY_SECONDS)
    return False


def _active_people(team: Team, now: datetime) -> int:
    return (
        TodayHighlights.objects.for_team(team.id)
        .filter(created_at__gte=now - timedelta(days=ACTIVE_DAYS))
        .values("user_id")
        .distinct()
        .count()
    )


def _gate(team: Team, now: datetime) -> NewsSkipReason | None:
    if not news_may_use_ai(team):
        return NewsSkipReason.AI_NOT_APPROVED
    if _active_people(team, now) < MIN_ACTIVE_PEOPLE:
        return NewsSkipReason.FEW_PEOPLE
    decision = consume(BUDGET_KEY, BUDGET)
    if not isinstance(decision, BucketDecision):
        logger.warning("today_news_budget_unavailable", team_id=team.id)
        return NewsSkipReason.BUDGET
    if not decision.allowed:
        return NewsSkipReason.BUDGET
    return None


def _claim(team: Team, start: date, existing: TodayNewsEdition | None, now: datetime) -> TodayNewsEdition | None:
    if existing is None:
        try:
            with transaction.atomic():
                return TodayNewsEdition.objects.for_team(team.id).create(
                    team_id=team.id, period=NewsPeriod.DAY, period_start=start
                )
        except IntegrityError:
            return None
    claimed = (
        TodayNewsEdition.objects.for_team(team.id)
        .filter(id=existing.id, status=existing.status, created_at=existing.created_at)
        .update(
            status=NewsStatus.COMPUTING,
            skip_reason="",
            error="",
            facts=[],
            content={},
            created_at=now,
            ready_at=None,
        )
    )
    return TodayNewsEdition.objects.for_team(team.id).get(id=existing.id) if claimed else None


def _start(team: Team, start: date, existing: TodayNewsEdition | None, now: datetime) -> TodayNews:
    computing = TodayNews(status=NewsStatus.COMPUTING, skip_reason=None, edition=None)
    lock = f"today_news:start:{team.id}:{start.isoformat()}"
    if not cache.add(lock, True, START_LOCK_SECONDS):
        return computing
    reason = _gate(team, now)
    if reason is not None:
        cache.delete(lock)
        return TodayNews(status=NewsStatus.SKIPPED, skip_reason=reason, edition=None)
    row = _claim(team, start, existing, now)
    if row is None:
        refund(BUDGET_KEY, BUDGET)
        return computing
    try:
        asyncio.run(
            sync_connect().start_workflow(
                NEWS_WORKFLOW_NAME,
                GenerateNewsInputs(team_id=team.id, edition_id=str(row.id)),
                id=news_workflow_id(team.id, row.period, start.isoformat(), int(row.created_at.timestamp())),
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        )
    except Exception as error:
        logger.exception("today_news_start_failed", edition_id=str(row.id))
        capture_exception(error, {"edition_id": str(row.id), "product": "today"})
        refund(BUDGET_KEY, BUDGET)
        _mark_failed(team.id, str(row.id), str(error))
        return TodayNews(status=NewsStatus.FAILED, skip_reason=None, edition=None)
    return computing


def get_news(*, team: Team, user: User, scopes: frozenset[str] | None) -> TodayNews:
    now = timezone.now()
    start = period_start(team, now)
    row = TodayNewsEdition.objects.for_team(team.id).filter(period=NewsPeriod.DAY, period_start=start).first()
    if row is None or _is_due(row, now):
        return _start(team, start, row, now)
    if row.status != NewsStatus.READY:
        reason = NewsSkipReason(row.skip_reason) if row.skip_reason else None
        return TodayNews(status=NewsStatus(row.status), skip_reason=reason, edition=None)
    viewer = Context(team, user, now.astimezone(team.timezone_info).date(), scopes)
    edition = visible_edition(
        STORED_EDITION.validate_python(row.content),
        lambda required: viewer.allows(*required),
        str(row.id),
        row.period_start,
    )
    if edition is None:
        return TodayNews(status=NewsStatus.SKIPPED, skip_reason=NewsSkipReason.NO_ACCESS, edition=None)
    return TodayNews(status=NewsStatus.READY, skip_reason=None, edition=edition)


def visible_edition(
    stored: StoredEdition, allows: Callable[[tuple[str, ...]], bool], edition_id: str, start: date
) -> NewsEdition | None:
    stories = [item.story for item in stored.stories if allows(item.scopes)]
    lead = stored.lead.story if allows(stored.lead.scopes) else None
    if lead is None:
        if not stories:
            return None
        promoted, *stories = stories
        lead = assemble.lead_story(promoted)
    return NewsEdition(
        id=edition_id,
        is_sample=False,
        period_start=start,
        lead=lead,
        stories=stories,
        briefs=[item.brief for item in stored.briefs if allows(item.scopes)],
    )


def _computing_row(team_id: int, edition_id: str) -> TodayNewsEdition | None:
    return TodayNewsEdition.objects.for_team(team_id).filter(id=edition_id, status=NewsStatus.COMPUTING).first()


def _anchor(row: TodayNewsEdition) -> datetime:
    return row.created_at.replace(minute=0, second=0, microsecond=0)


def _skip_quiet(row: TodayNewsEdition, fields: list[str]) -> None:
    row.status = NewsStatus.SKIPPED
    row.skip_reason = NewsSkipReason.QUIET
    row.ready_at = timezone.now()
    row.save(update_fields=[*fields, "status", "skip_reason", "ready_at"])
    refund(BUDGET_KEY, BUDGET)


def _track(team: Team, edition_id: str, outcome: str, **properties: Any) -> None:
    posthoganalytics.capture(
        distinct_id=f"team_{team.id}",
        event=GENERATED_EVENT,
        groups=groups(team.organization, team),
        properties={"edition_id": edition_id, "outcome": outcome, **properties},
    )


def gather(team: Team, anchor: datetime) -> list[Candidate]:
    def run(statement: str, name: str, **values: Any) -> list[tuple[Any, ...]]:
        return queries.run(team, statement, anchor, name, **values)

    actions = list(news_candidates.from_actions(run(queries.ACTIONS, "actions")))
    acted = {candidate.key for candidate in actions}
    found = [
        *news_candidates.from_errors(run(queries.ERRORS, "errors")),
        *(c for c in news_candidates.from_key_events(run(queries.KEY_EVENTS, "key_events")) if c.key not in acted),
        *news_candidates.from_surveys(run(queries.SURVEYS, "surveys")),
        *actions,
        *news_candidates.from_traffic(run(queries.TRAFFIC, "traffic")),
    ]
    return news_candidates.number(found)


def collect_facts(inputs: GenerateNewsInputs) -> bool:
    row = _computing_row(inputs.team_id, inputs.edition_id)
    if row is None:
        return False
    team = Team.objects.get(id=inputs.team_id)
    started = time.monotonic()
    found = gather(team, _anchor(row))
    seconds = round(time.monotonic() - started, 1)
    row.facts = {"candidates": CANDIDATES.dump_python(found, mode="json"), "gather_seconds": seconds}
    if not found:
        _skip_quiet(row, ["facts"])
        _track(team, inputs.edition_id, "quiet", candidates=0, gather_seconds=seconds)
        return False
    row.save(update_fields=["facts"])
    return True


def _series(team: Team, anchor: datetime, picked: list[Candidate]) -> dict[tuple[str, str], dict[int, float]]:
    keys: dict[str, set[str]] = defaultdict(set)
    for candidate in picked:
        keys[candidate.source].add(candidate.key)
    series: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    for source, wanted in keys.items():
        for key, days_ago, value in queries.run(team, queries.SERIES[source], anchor, "series", keys=sorted(wanted)):
            series[(source, str(key))][int(days_ago)] = float(value)
    return series


def write_edition(inputs: GenerateNewsInputs) -> None:
    row = _computing_row(inputs.team_id, inputs.edition_id)
    if row is None:
        return
    team = Team.objects.get(id=inputs.team_id)
    started = time.monotonic()
    found = {candidate.id: candidate for candidate in CANDIDATES.validate_python(row.facts["candidates"])}
    reply, analyst = writer.analyze(
        team_id=team.id, edition_id=str(row.id), candidates=[asdict(candidate) for candidate in found.values()]
    )
    plan = news_plan.build(news_plan.parse_facts(reply, found))
    usage = {"analyst_tokens_in": analyst.input_tokens, "analyst_tokens_out": analyst.output_tokens}
    if plan is None:
        _skip_quiet(row, [])
        _track(team, inputs.edition_id, "quiet", candidates=len(found), **usage)
        return
    draft, editor = writer.write(team_id=team.id, edition_id=str(row.id), plan=news_plan.writer_input(plan, team.name))
    if draft is None:
        raise NewsWriteFailed("The writer reply did not match the plan")
    anchor = _anchor(row)
    stored = assemble.edition(plan, draft, _series(team, anchor, assemble.picked(plan)), anchor)
    TodayNewsEdition.objects.for_team(inputs.team_id).filter(id=inputs.edition_id, status=NewsStatus.COMPUTING).update(
        status=NewsStatus.READY,
        content=STORED_EDITION.dump_python(stored, mode="json"),
        model=editor.model[:64],
        input_tokens=analyst.input_tokens + editor.input_tokens,
        output_tokens=analyst.output_tokens + editor.output_tokens,
        ready_at=timezone.now(),
    )
    _track(
        team,
        inputs.edition_id,
        "ready",
        candidates=len(found),
        stories=1 + len(stored.stories),
        briefs=len(stored.briefs),
        writer_calls=editor.calls,
        writer_tokens_in=editor.input_tokens,
        writer_tokens_out=editor.output_tokens,
        gather_seconds=row.facts.get("gather_seconds"),
        write_seconds=round(time.monotonic() - started, 1),
        **usage,
    )


def _mark_failed(team_id: int, edition_id: str, error: str) -> None:
    TodayNewsEdition.objects.for_team(team_id).filter(id=edition_id, status=NewsStatus.COMPUTING).update(
        status=NewsStatus.FAILED, error=error[:MAX_ERROR_LENGTH], ready_at=timezone.now()
    )


def mark_failed(inputs: FailNewsInputs) -> None:
    _mark_failed(inputs.team_id, inputs.edition_id, inputs.error)


def delete_for_teams(team_ids: list[int]) -> None:
    TodayNewsEdition.objects.unscoped().filter(team_id__in=team_ids).delete()
