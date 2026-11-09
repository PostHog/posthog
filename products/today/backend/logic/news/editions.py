import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from pydantic import TypeAdapter
from temporalio.common import WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect
from posthog.token_bucket import BucketDecision, Budget, consume, refund

from products.access_control.backend.facade.api import (
    object_ids_restricted_from_any_member,
    team_has_property_access_rules,
)

from ...facade.contracts import NewsEdition, TodayNews
from ...facade.enums import NewsSkipReason, NewsStatus
from ...feature_flags import news_may_use_ai
from ...models import NewsPeriod, TodayHighlights, TodayNewsEdition
from ...temporal.inputs import (
    MAX_NEWS_ERROR_LENGTH,
    WRITE_NEWS_WORKFLOW_NAME,
    WRITE_NEWS_WORKFLOW_TIMEOUT,
    FailNewsInputs,
    WriteNewsInputs,
    write_news_workflow_id,
)
from ..highlight_types import Context
from .agent import EDITION_SCOPES, EarlierEdition, NewsAssignment, StoredEdition

logger = structlog.get_logger(__name__)

COMPUTING_SECONDS = int((WRITE_NEWS_WORKFLOW_TIMEOUT + timedelta(minutes=4)).total_seconds())
FAILED_RETRY_SECONDS = 60 * 60
WRITE_LOCK_SECONDS = 30
ACTIVE_DAYS = 7
MIN_ACTIVE_PEOPLE = 2
DAILY_CAP = 2000
BUDGET = Budget(burst=DAILY_CAP // 4, per_hour=DAILY_CAP // 24)
BUDGET_KEY = "today_news_agent_rate:global"

STORED_EDITION = TypeAdapter(StoredEdition)
WRITTEN_EVENT = "today news edition written"


@frozen
class NewsRunReport:
    outcome: Literal["ready", "quiet", "failed"]
    seconds: float
    model: str
    items: int = 0
    task_run_id: str | None = None
    cost_usd: float | None = None
    cost_complete: bool = False


def _local_day(team: Team, now: datetime) -> date:
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


def _blocked(team: Team) -> NewsSkipReason | None:
    if team.parent_team_id is not None:
        return NewsSkipReason.ENVIRONMENT
    if not news_may_use_ai(team):
        return NewsSkipReason.AI_NOT_APPROVED
    if team_has_property_access_rules(team_id=team.id):
        return NewsSkipReason.PROPERTY_RULES
    return None


def _gate(team: Team, now: datetime) -> NewsSkipReason | None:
    blocked = _blocked(team)
    if blocked is not None:
        return blocked
    if _active_people(team, now) < MIN_ACTIVE_PEOPLE:
        return NewsSkipReason.FEW_PEOPLE
    return None


def _within_budget(team: Team) -> bool:
    decision = consume(BUDGET_KEY, BUDGET)
    if not isinstance(decision, BucketDecision):
        logger.warning("today_news_budget_unavailable", team_id=team.id)
        return False
    return decision.allowed


def _claimed(inputs: WriteNewsInputs | FailNewsInputs) -> QuerySet[TodayNewsEdition]:
    return TodayNewsEdition.objects.for_team(inputs.team_id).filter(
        id=inputs.edition_id, status=NewsStatus.COMPUTING, created_at=datetime.fromisoformat(inputs.claimed_at)
    )


def mark_failed(inputs: FailNewsInputs) -> None:
    _claimed(inputs).update(
        status=NewsStatus.FAILED, error=inputs.error[:MAX_NEWS_ERROR_LENGTH], ready_at=timezone.now()
    )


def _claim(team: Team, day: date, existing: TodayNewsEdition | None, now: datetime) -> TodayNewsEdition | None:
    if existing is None:
        try:
            with transaction.atomic():
                return TodayNewsEdition.objects.for_team(team.id).create(
                    team_id=team.id, period=NewsPeriod.DAY, period_start=day
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
            facts={},
            content={},
            created_at=now,
            ready_at=None,
        )
    )
    return TodayNewsEdition.objects.for_team(team.id).get(id=existing.id) if claimed else None


def _write_lock(team: Team, day: date) -> str:
    return f"today_news:write:{team.id}:{day.isoformat()}"


def _start(team: Team, user: User, day: date, existing: TodayNewsEdition | None, now: datetime) -> None:
    lock = _write_lock(team, day)
    if not cache.add(lock, True, WRITE_LOCK_SECONDS):
        return
    if not _within_budget(team):
        cache.delete(lock)
        return
    row = _claim(team, day, existing, now)
    if row is None:
        refund(BUDGET_KEY, BUDGET)
        return
    claimed_at = row.created_at.isoformat()
    try:
        asyncio.run(
            sync_connect().start_workflow(
                WRITE_NEWS_WORKFLOW_NAME,
                WriteNewsInputs(team_id=team.id, user_id=user.id, edition_id=str(row.id), claimed_at=claimed_at),
                id=write_news_workflow_id(team.id, str(row.id), int(row.created_at.timestamp())),
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                execution_timeout=WRITE_NEWS_WORKFLOW_TIMEOUT,
            )
        )
    except Exception as error:
        logger.exception("today_news_start_failed", edition_id=str(row.id))
        capture_exception(error, {"edition_id": str(row.id), "product": "today"})
        mark_failed(FailNewsInputs(team_id=team.id, edition_id=str(row.id), error=str(error), claimed_at=claimed_at))
        refund(BUDGET_KEY, BUDGET)


def _today_row(team: Team, day: date) -> TodayNewsEdition | None:
    return (
        TodayNewsEdition.objects.for_team(team.id)
        .filter(period=NewsPeriod.DAY, period_start=day)
        .defer("facts")
        .first()
    )


def _earlier_row(team_id: int, day: date) -> TodayNewsEdition | None:
    return (
        TodayNewsEdition.objects.for_team(team_id)
        .filter(period=NewsPeriod.DAY, status=NewsStatus.READY, period_start__lt=day)
        .defer("facts")
        .order_by("-period_start")
        .first()
    )


def _restricted_surveys(team_id: int) -> set[str]:
    return object_ids_restricted_from_any_member(team_id=team_id, resource="survey", required_level="viewer")


def _visible(viewer: Context, row: TodayNewsEdition) -> NewsEdition | None:
    stored = STORED_EDITION.validate_python(row.content)
    if not viewer.allows(*EDITION_SCOPES) or not _restricted_surveys(viewer.team.id) <= set(stored.withheld_surveys):
        return None
    return NewsEdition(
        id=str(row.id),
        is_sample=False,
        period_start=row.period_start,
        lead=stored.lead,
        stories=list(stored.stories),
        briefs=list(stored.briefs),
        ongoing=list(stored.ongoing),
        this_week=list(stored.this_week),
    )


def _report(viewer: Context, row: TodayNewsEdition | None, now: datetime) -> TodayNews:
    if row is not None and row.status == NewsStatus.READY:
        edition = _visible(viewer, row)
        if edition is None:
            return TodayNews(status=NewsStatus.SKIPPED, skip_reason=NewsSkipReason.NO_ACCESS, edition=None)
        return TodayNews(status=NewsStatus.READY, skip_reason=None, edition=edition)
    status = NewsStatus.NOT_STARTED if row is None or _is_due(row, now) else NewsStatus(row.status)
    reason = NewsSkipReason(row.skip_reason) if row is not None and row.skip_reason else None
    earlier = _earlier_row(viewer.team.id, viewer.today)
    return TodayNews(
        status=status, skip_reason=reason, edition=_visible(viewer, earlier) if earlier is not None else None
    )


def get_news(*, team: Team, user: User, scopes: frozenset[str] | None) -> TodayNews:
    now = timezone.now()
    reason = _gate(team, now)
    if reason is not None:
        return TodayNews(status=NewsStatus.SKIPPED, skip_reason=reason, edition=None)
    viewer = Context(team, user, _local_day(team, now), scopes)
    return _report(viewer, _today_row(team, viewer.today), now)


def request_write(*, team: Team, user: User, scopes: frozenset[str] | None) -> TodayNews:
    now = timezone.now()
    reason = _gate(team, now)
    if reason is not None:
        return TodayNews(status=NewsStatus.SKIPPED, skip_reason=reason, edition=None)
    viewer = Context(team, user, _local_day(team, now), scopes)
    row = _today_row(team, viewer.today)
    if row is None or _is_due(row, now):
        _start(team, user, viewer.today, row, now)
        row = _today_row(team, viewer.today)
    return _report(viewer, row, now)


def assignment(inputs: WriteNewsInputs) -> NewsAssignment | None:
    row = _claimed(inputs).defer("facts", "content").first()
    if row is None:
        return None
    team = Team.objects.select_related("organization").get(id=inputs.team_id)
    blocked = _blocked(team)
    if blocked is not None:
        _claimed(inputs).update(status=NewsStatus.SKIPPED, skip_reason=blocked, ready_at=timezone.now())
        return None
    withheld = _restricted_surveys(team.id)
    earlier_row = _earlier_row(team.id, row.period_start)
    earlier = STORED_EDITION.validate_python(earlier_row.content) if earlier_row is not None else None
    return NewsAssignment(
        team_id=team.id,
        day=row.period_start,
        end=row.created_at.astimezone(UTC).replace(microsecond=0),
        timezone=team.timezone,
        earlier=EarlierEdition(day=earlier_row.period_start, edition=earlier)
        if earlier_row is not None and earlier is not None and withheld <= set(earlier.withheld_surveys)
        else None,
        withheld_surveys=tuple(sorted(withheld)),
    )


def store_edition(inputs: WriteNewsInputs, edition: StoredEdition | None, model: str) -> None:
    if edition is None:
        _claimed(inputs).update(
            status=NewsStatus.SKIPPED, skip_reason=NewsSkipReason.QUIET, model=model, ready_at=timezone.now()
        )
        return
    _claimed(inputs).update(
        status=NewsStatus.READY,
        content=STORED_EDITION.dump_python(edition, mode="json"),
        model=model,
        ready_at=timezone.now(),
    )


def capture_written(inputs: WriteNewsInputs, report: NewsRunReport) -> None:
    team = Team.objects.select_related("organization").get(id=inputs.team_id)
    posthoganalytics.capture(
        distinct_id=f"team_{team.id}",
        event=WRITTEN_EVENT,
        groups=groups(team.organization, team),
        properties={
            "edition_id": inputs.edition_id,
            "outcome": report.outcome,
            "items": report.items,
            "model": report.model,
            "task_run_id": report.task_run_id,
            "cost_usd": report.cost_usd,
            "cost_complete": report.cost_complete,
            "write_seconds": round(report.seconds, 1),
        },
    )


def delete_for_teams(team_ids: list[int]) -> None:
    TodayNewsEdition.objects.unscoped().filter(team_id__in=team_ids).delete()
