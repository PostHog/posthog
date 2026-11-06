import asyncio
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import cast

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog
from pydantic import TypeAdapter
from temporalio.common import WorkflowIDReusePolicy

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.scopes import APIScopeObject
from posthog.temporal.common.client import sync_connect
from posthog.token_bucket import BucketDecision, Budget, consume, refund

from ...facade.contracts import NewsEdition, NewsFact, TodayNews
from ...facade.enums import NewsSkipReason, NewsStatus
from ...feature_flags import news_may_use_ai
from ...models import NewsPeriod, TodayHighlights, TodayNewsEdition
from ...temporal.inputs import NEWS_WORKFLOW_NAME, FailNewsInputs, GenerateNewsInputs, news_workflow_id
from ..highlight_registry import load_sources
from ..highlight_types import Context
from . import (
    facts as news_facts,
    writer,
)

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

STORED_EDITION = TypeAdapter(writer.StoredEdition)


class NewsWriteFailed(Exception):
    pass


def period_start(team: Team, now: datetime) -> date:
    local = now.astimezone(team.timezone_info).date()
    return local - timedelta(days=local.weekday())


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
                    team_id=team.id, period=NewsPeriod.WEEK, period_start=start
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
    row = TodayNewsEdition.objects.for_team(team.id).filter(period=NewsPeriod.WEEK, period_start=start).first()
    if row is None or _is_due(row, now):
        return _start(team, start, row, now)
    if row.status != NewsStatus.READY:
        reason = NewsSkipReason(row.skip_reason) if row.skip_reason else None
        return TodayNews(status=NewsStatus(row.status), skip_reason=reason, edition=None)
    viewer = Context(team, user, now.astimezone(team.timezone_info).date(), scopes)
    edition = visible_edition(
        STORED_EDITION.validate_python(row.content),
        {item.fact.key: item.fact for item in news_facts.SCORED_FACTS.validate_python(row.facts)},
        lambda fact: viewer_may_see(viewer, fact),
        edition_id=str(row.id),
        start=row.period_start,
    )
    if edition is None:
        return TodayNews(status=NewsStatus.SKIPPED, skip_reason=NewsSkipReason.NO_ACCESS, edition=None)
    return TodayNews(status=NewsStatus.READY, skip_reason=None, edition=edition)


def viewer_may_see(viewer: Context, fact: NewsFact) -> bool:
    if not viewer.allows(*fact.scopes):
        return False
    if fact.object_id is None:
        return True
    resource = cast(APIScopeObject, fact.resource)
    allowlisted = viewer.access.allowlisted_resource_ids_by_scope
    if resource in allowlisted:
        return fact.object_id in allowlisted[resource]
    return fact.object_id not in viewer.access.blocked_resource_ids_by_scope.get(resource, frozenset())


def visible_edition(
    stored: writer.StoredEdition,
    facts: Mapping[str, NewsFact],
    may_see: Callable[[NewsFact], bool],
    *,
    edition_id: str,
    start: date,
) -> NewsEdition | None:
    def visible(key: str) -> bool:
        return key in facts and may_see(facts[key])

    stories = [story for story in stored.stories if visible(story.id)]
    lead = stored.lead
    if not visible(lead.id):
        if not stories:
            return None
        promoted, *stories = stories
        lead = writer.lead_story(promoted, facts[promoted.id])
    return NewsEdition(
        id=edition_id,
        is_sample=False,
        period_start=start,
        lead=lead,
        stories=stories,
        briefs=[brief.text for brief in stored.briefs if all(visible(ref) for ref in brief.refs)],
    )


def _computing_row(team_id: int, edition_id: str) -> TodayNewsEdition | None:
    return TodayNewsEdition.objects.for_team(team_id).filter(id=edition_id, status=NewsStatus.COMPUTING).first()


def collect_facts(inputs: GenerateNewsInputs) -> bool:
    row = _computing_row(inputs.team_id, inputs.edition_id)
    if row is None:
        return False
    team = Team.objects.get(id=inputs.team_id)
    scored = news_facts.collect(team, timezone.now(), load_sources())
    row.facts = news_facts.SCORED_FACTS.dump_python(scored, mode="json")
    if news_facts.enough(scored):
        row.save(update_fields=["facts"])
        return True
    row.status = NewsStatus.SKIPPED
    row.skip_reason = NewsSkipReason.QUIET
    row.ready_at = timezone.now()
    row.save(update_fields=["facts", "status", "skip_reason", "ready_at"])
    refund(BUDGET_KEY, BUDGET)
    return False


def write_edition(inputs: GenerateNewsInputs) -> None:
    row = _computing_row(inputs.team_id, inputs.edition_id)
    if row is None:
        return
    team = Team.objects.get(id=inputs.team_id)
    scored = news_facts.SCORED_FACTS.validate_python(row.facts)[: news_facts.MAX_PROMPT_FACTS]
    end = row.created_at.astimezone(team.timezone_info).date()
    completion = writer.complete(
        team_id=team.id,
        edition_id=str(row.id),
        project_name=team.name,
        period=writer.period_label(end - timedelta(days=news_facts.WINDOW_DAYS), end),
        facts=scored,
    )
    stored = writer.build_edition(completion.reply, scored)
    if stored is None:
        raise NewsWriteFailed("The model reply named no known fact")
    TodayNewsEdition.objects.for_team(inputs.team_id).filter(id=inputs.edition_id, status=NewsStatus.COMPUTING).update(
        status=NewsStatus.READY,
        content=STORED_EDITION.dump_python(stored, mode="json"),
        model=completion.model[:64],
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        ready_at=timezone.now(),
    )


def _mark_failed(team_id: int, edition_id: str, error: str) -> None:
    TodayNewsEdition.objects.for_team(team_id).filter(id=edition_id, status=NewsStatus.COMPUTING).update(
        status=NewsStatus.FAILED, error=error[:MAX_ERROR_LENGTH], ready_at=timezone.now()
    )


def mark_failed(inputs: FailNewsInputs) -> None:
    _mark_failed(inputs.team_id, inputs.edition_id, inputs.error)


def delete_for_teams(team_ids: list[int]) -> None:
    TodayNewsEdition.objects.unscoped().filter(team_id__in=team_ids).delete()
