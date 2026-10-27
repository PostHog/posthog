import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from functools import partial
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

import structlog
from dateutil.relativedelta import relativedelta
from pydantic import TypeAdapter, ValidationError
from temporalio.common import WorkflowIDReusePolicy

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect
from posthog.week_start_day import WeekStartDay

from ..facade import contracts
from ..facade.contracts import HighlightCandidate, HighlightFindings, HighlightSource
from ..facade.enums import HighlightInterval, HighlightLabel, HighlightPinStatus, HighlightPriority, HighlightsStatus
from ..feature_flags import pulse_ranking
from ..models import TodayHighlights
from ..temporal.inputs import (
    HIGHLIGHTS_WORKFLOW_NAME,
    ComputeHighlightsInputs,
    FinalizeHighlightsInputs,
    HighlightSourceInputs,
    HighlightSourceResult,
    PinnedNumber,
    highlights_workflow_id,
)
from . import pulse_pins
from .highlight_registry import load_sources
from .highlight_types import CACHE_SECONDS, Context, property_restrictions
from .pinned import PINNED_METRICS

logger = structlog.get_logger(__name__)

FAILED_CACHE_SECONDS = 60
COMPUTING_SECONDS = 5 * 60
START_LOCK_SECONDS = 30
MAX_ITEMS = 6
MAX_PER_FAMILY = 2
MIN_SCORE = 0.2
PULSE_TILES = 4
URGENT_RISK_SCORE = 0.75
MINOR_OPPORTUNITY_SCORE = 0.4

_FINDINGS = TypeAdapter(HighlightFindings)
_HIGHLIGHTS = TypeAdapter(contracts.Highlights)


def get_highlights(*, team: Team, user: User, scopes: frozenset[str] | None) -> contracts.Highlights:
    now = timezone.now()
    day = now.astimezone(team.timezone_info).date()
    pins = [
        PinnedNumber(key=pin.key, dashboard_id=pin.dashboard_id)
        for pin in pulse_pins.get_pins(team=team, user_id=user.id, scopes=scopes)
    ]
    key = _key(team, user, scopes)
    pins_key = _pins_key(pins)
    rows = (
        TodayHighlights.objects.for_team(team.id)
        .filter(user_id=user.id, key=key, local_day=day)
        .order_by("-created_at")
    )
    latest = rows.first()
    if latest is None or latest.pins_key != pins_key or _is_due(latest, now):
        _start(team, user, scopes, day, key, pins, pins_key, after=latest.id if latest else None)
        status = HighlightsStatus.COMPUTING
    else:
        status = HighlightsStatus(latest.status)
    ready = (
        latest
        if latest is not None and latest.status == HighlightsStatus.READY
        else rows.filter(status=HighlightsStatus.READY).first()
    )
    if ready is not None:
        with suppress(ValidationError):
            return replace(_HIGHLIGHTS.validate_python(ready.content), status=status)
    return contracts.Highlights(
        status=status, generated_at=None, day=day, refresh_at=_refresh_at(team, day), pulse=[], items=[]
    )


def _key(team: Team, user: User, scopes: frozenset[str] | None) -> str:
    granted = "session" if scopes is None else ",".join(sorted(scopes))
    restrictions = property_restrictions(team, user)
    return hashlib.sha256(f"{granted}:{restrictions}:{pulse_ranking(user, team)}".encode()).hexdigest()[:32]


def _pins_key(pins: Sequence[PinnedNumber]) -> str:
    if not pins:
        return ""
    signature = ",".join(f"{pin.key}@{pin.dashboard_id or ''}" for pin in pins)
    return hashlib.sha256(signature.encode()).hexdigest()[:32]


def _is_due(row: TodayHighlights, now: datetime) -> bool:
    if row.status == HighlightsStatus.COMPUTING:
        return row.created_at < now - timedelta(seconds=COMPUTING_SECONDS)
    fresh_seconds = FAILED_CACHE_SECONDS if row.failed_sources else CACHE_SECONDS
    return row.ready_at is None or row.ready_at < now - timedelta(seconds=fresh_seconds)


def _start(
    team: Team,
    user: User,
    scopes: frozenset[str] | None,
    day: date,
    key: str,
    pins: list[PinnedNumber],
    pins_key: str,
    after: UUID | None,
) -> None:
    lock = f"today_highlights:start:{team.id}:{user.id}:{key}:{pins_key}:{day.isoformat()}:{after}"
    if not cache.add(lock, True, START_LOCK_SECONDS):
        return
    row = TodayHighlights.objects.for_team(team.id).create(
        team_id=team.id, user_id=user.id, local_day=day, key=key, pins_key=pins_key
    )
    inputs = ComputeHighlightsInputs(
        team_id=team.id,
        user_id=user.id,
        highlights_id=str(row.id),
        local_day=day.isoformat(),
        scopes=None if scopes is None else sorted(scopes),
        source_names=[source.name for source in load_sources()],
        pins=pins,
    )
    try:
        asyncio.run(
            sync_connect().start_workflow(
                HIGHLIGHTS_WORKFLOW_NAME,
                inputs,
                id=highlights_workflow_id(team.id, user.id, str(row.id)),
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        )
    except Exception as error:
        logger.exception("today_highlights_start_failed", highlights_id=str(row.id))
        capture_exception(error, {"highlights_id": str(row.id), "product": "today"})


def run_source(inputs: HighlightSourceInputs) -> HighlightSourceResult:
    source = next((source for source in load_sources() if source.name == inputs.source_name), None)
    context = Context(
        Team.objects.get(id=inputs.team_id),
        User.objects.get(id=inputs.user_id),
        date.fromisoformat(inputs.local_day),
        None if inputs.scopes is None else frozenset(inputs.scopes),
        frozenset(inputs.pinned),
    )
    if source is None or not context.allows(*source.scopes):
        return HighlightSourceResult(source_name=inputs.source_name, found=None, failed=False)
    with tags_context(product=Product.TODAY, feature=Feature.QUERY, team_id=context.team.id):
        found = context.guard(source.name, partial(source.find, context), HighlightFindings())
    return HighlightSourceResult(
        source_name=source.name, found=_FINDINGS.dump_json(found).decode(), failed=bool(context.failures)
    )


def finalize(inputs: FinalizeHighlightsInputs) -> None:
    row = TodayHighlights.objects.for_team(inputs.team_id).filter(id=inputs.highlights_id).first()
    if row is None:
        return
    found = {result.source_name: _FINDINGS.validate_json(result.found) for result in inputs.results if result.found}
    highlights = build_highlights(
        load_sources(),
        found,
        Team.objects.get(id=inputs.team_id),
        row.local_day,
        pins=[pin.key for pin in inputs.pins],
        pinned={metric.key: metric for metric in PINNED_METRICS.validate_json(inputs.pinned)},
    )
    failed = [result for result in inputs.results if result.failed]
    usable = bool(highlights.items or highlights.pulse)
    row.status = (
        HighlightsStatus.FAILED
        if failed and len(failed) == len(inputs.results) and not usable
        else HighlightsStatus.READY
    )
    row.content = _HIGHLIGHTS.dump_python(highlights, mode="json")
    row.failed_sources = bool(failed)
    row.ready_at = timezone.now()
    row.save(update_fields=["status", "content", "failed_sources", "ready_at"])
    if row.status == HighlightsStatus.READY:
        TodayHighlights.objects.for_team(inputs.team_id).filter(
            user_id=row.user_id, key=row.key, created_at__lt=row.created_at
        ).delete()


def delete_for_teams(team_ids: list[int]) -> None:
    TodayHighlights.objects.unscoped().filter(team_id__in=team_ids).delete()
    pulse_pins.delete_for_teams(team_ids)


def build_highlights(
    sources: Sequence[HighlightSource],
    found: Mapping[str, HighlightFindings],
    team: Team,
    day: date,
    pins: Sequence[str] = (),
    pinned: Mapping[str, contracts.HighlightMetric] | None = None,
) -> contracts.Highlights:
    offered: dict[str, contracts.HighlightMetric] = {}
    for source in sorted(sources, key=lambda source: source.pulse_order):
        for metric in found[source.name].pulse if source.name in found else ():
            offered.setdefault(metric.key, metric)
    resolved = {**offered, **(pinned or {})}
    chosen = [resolved[key] for key in pins if key in resolved]
    pulse = [*chosen, *(metric for key, metric in offered.items() if key not in pins)][:PULSE_TILES]
    ranked = rank([replace(c, source=name) for name, result in found.items() for c in result.items])
    return contracts.Highlights(
        status=HighlightsStatus.READY,
        generated_at=timezone.now(),
        day=day,
        refresh_at=_refresh_at(team, day),
        pulse=[
            metric if metric.period_starts else replace(metric, period_starts=_period_starts(metric, team, day))
            for metric in pulse
        ],
        items=sorted((_item(c) for c in ranked), key=lambda item: item.priority),
        pins=[
            contracts.HighlightPin(
                key=key, status=HighlightPinStatus.READY if key in resolved else HighlightPinStatus.UNAVAILABLE
            )
            for key in pins
        ],
    )


def _refresh_at(team: Team, day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, team.timezone_info)


def _score(candidate: HighlightCandidate) -> float:
    floor = 0.5 if candidate.importance >= 0.9 else 0.2
    return candidate.importance * (floor + (1 - floor) * candidate.relevance)


def _item(candidate: HighlightCandidate) -> contracts.HighlightItem:
    score = round(_score(candidate), 3)
    return contracts.HighlightItem(
        key=candidate.key,
        source=candidate.source,
        label=candidate.label,
        priority=priority(candidate.label, score),
        title=candidate.title,
        detail=candidate.detail,
        url=candidate.url,
        series=candidate.series,
        score=score,
    )


def priority(label: HighlightLabel, score: float) -> HighlightPriority:
    if label == HighlightLabel.RISK:
        return HighlightPriority.P1 if score >= URGENT_RISK_SCORE else HighlightPriority.P2
    return HighlightPriority.P3 if score >= MINOR_OPPORTUNITY_SCORE else HighlightPriority.P4


def _period_starts(metric: contracts.HighlightMetric, team: Team, day: date) -> list[date]:
    back = range(len(metric.series), 0, -1)
    if metric.interval == HighlightInterval.WEEK:
        first_weekday = 0 if team.week_start_day == WeekStartDay.MONDAY else 6
        this_week = day - timedelta(days=(day.weekday() - first_weekday) % 7)
        return [this_week - timedelta(weeks=weeks) for weeks in back]
    if metric.interval == HighlightInterval.MONTH:
        return [day.replace(day=1) - relativedelta(months=months) for months in back]
    return [day - timedelta(days=days) for days in back]


def rank(candidates: list[HighlightCandidate]) -> list[HighlightCandidate]:
    shown: list[HighlightCandidate] = []
    for candidate in sorted(candidates, key=lambda c: -_score(c)):
        if _score(candidate) < MIN_SCORE or len(shown) == MAX_ITEMS:
            break
        if sum(1 for s in shown if s.family == candidate.family) >= MAX_PER_FAMILY:
            continue
        if any(
            s.family != candidate.family
            and (s.title == candidate.title or (candidate.ref is not None and s.ref == candidate.ref))
            for s in shown
        ):
            continue
        shown.append(candidate)
    return shown
