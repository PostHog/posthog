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
from django.db import transaction
from django.utils import timezone

import structlog
from dateutil.relativedelta import relativedelta
from pydantic import TypeAdapter, ValidationError
from temporalio.common import WorkflowIDReusePolicy

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect
from posthog.week_start_day import WeekStartDay

from ..facade import contracts
from ..facade.contracts import HighlightCandidate, HighlightFindings, HighlightSource
from ..facade.enums import (
    HighlightInterval,
    HighlightLabel,
    HighlightMetricReason,
    HighlightPinStatus,
    HighlightPriority,
    HighlightsStatus,
    PulseSlotStatus,
)
from ..models import TodayHighlights
from ..temporal.inputs import (
    HIGHLIGHTS_WORKFLOW_NAME,
    ComputeHighlightsInputs,
    FinalizeHighlightsInputs,
    HighlightSourceInputs,
    HighlightSourceResult,
    PinnedNumber,
    ResolvePinsInputs,
    highlights_workflow_id,
)
from . import pulse_pins
from .highlight_registry import load_sources, source_product
from .highlight_types import CACHE_SECONDS, Context, property_restrictions
from .pinned import PINNED_METRICS
from .today_highlights import key_metrics as key_metrics_source
from .today_highlights.routine import PULSE_CANDIDATES

logger = structlog.get_logger(__name__)

FAILED_CACHE_SECONDS = 60
COMPUTING_SECONDS = 5 * 60
START_LOCK_SECONDS = 30
MAX_ITEMS = 6
ROW_TILES = 4
KEY_METRICS_SOURCE = key_metrics_source.SOURCE.name
MAX_PER_FAMILY = 2
MIN_SCORE = 0.2
URGENT_RISK_SCORE = 0.75
MINOR_OPPORTUNITY_SCORE = 0.4
PINNED_SOURCE = "pinned"

_FINDINGS = TypeAdapter(HighlightFindings)
_HIGHLIGHTS = TypeAdapter(contracts.Highlights)


@frozen
class PulseSourceProgress:
    found: HighlightFindings
    slots: list[contracts.PulseSlot]


_PROGRESS = TypeAdapter(dict[str, PulseSourceProgress])


def get_highlights(
    *, team: Team, user: User, scopes: frozenset[str] | None, refresh: bool = False
) -> contracts.Highlights:
    now = timezone.now()
    day = now.astimezone(team.timezone_info).date()
    choices = pulse_pins.get_choices(team=team, user_id=user.id, scopes=scopes)
    pins = [PinnedNumber(key=pin.key, dashboard_id=pin.dashboard_id) for pin in choices.pins]
    hidden = choices.hidden
    key = _key(team, user, scopes)
    pins_key = _pins_key(pins, hidden)
    rows = (
        TodayHighlights.objects.for_team(team.id)
        .filter(user_id=user.id, key=key, local_day=day)
        .order_by("-created_at")
    )
    latest = rows.first()
    retry_failed = (
        refresh
        and latest is not None
        and latest.failed_sources
        and latest.status != HighlightsStatus.COMPUTING
        and cache.add(f"today_highlights:retry:{team.id}:{user.id}", True, FAILED_CACHE_SECONDS)
    )
    if latest is None or latest.pins_key != pins_key or _is_due(latest, now) or retry_failed:
        _start(
            team,
            user,
            scopes,
            day,
            key,
            pins,
            pins_key,
            hidden,
            after=latest.id if latest else None,
        )
        status = HighlightsStatus.COMPUTING
    else:
        status = HighlightsStatus(latest.status)
    ready = (
        latest
        if latest is not None and latest.status == HighlightsStatus.READY
        else rows.filter(status=HighlightsStatus.READY).first()
    )
    if latest is not None and latest.content.get("pulse_slots"):
        with suppress(ValidationError):
            content = _HIGHLIGHTS.validate_python(latest.content)
            if status == HighlightsStatus.COMPUTING and ready is not None and ready.id != latest.id:
                old = _HIGHLIGHTS.validate_python(ready.content)
                pending = {slot.key for slot in content.pulse_slots or [] if slot.status == PulseSlotStatus.PENDING}
                shown = {metric.key for metric in content.pulse}
                pin_keys = {pin.key for pin in pins}
                retained = [
                    metric
                    for metric in old.pulse
                    if metric.key in pending or (metric.key in pin_keys and metric.key not in shown)
                ]
                retained_keys = {metric.key for metric in retained}
                content = replace(
                    content,
                    pulse=[*content.pulse, *retained],
                    pulse_slots=[
                        replace(slot, status=PulseSlotStatus.READY) if slot.key in retained_keys else slot
                        for slot in content.pulse_slots or []
                    ],
                )
            return replace(content, status=status)
    if ready is not None:
        with suppress(ValidationError):
            return replace(_with_slots(_HIGHLIGHTS.validate_python(ready.content)), status=status)
    return contracts.Highlights(
        status=status,
        generated_at=None,
        day=day,
        refresh_at=_refresh_at(team, day),
        pulse=[],
        items=[],
        pulse_slots=[],
    )


def _key(team: Team, user: User, scopes: frozenset[str] | None) -> str:
    granted = "session" if scopes is None else ",".join(sorted(scopes))
    restrictions = property_restrictions(team, user)
    return hashlib.sha256(f"{granted}:{restrictions}".encode()).hexdigest()[:32]


def _pins_key(pins: Sequence[PinnedNumber], hidden: Sequence[str] = ()) -> str:
    if not pins and not hidden:
        return ""
    signature = ",".join(f"{pin.key}@{pin.dashboard_id or ''}" for pin in pins)
    if hidden:
        signature += "|" + ",".join(sorted(hidden))
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
    hidden: list[str],
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
        hidden=hidden,
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


def _with_slots(content: contracts.Highlights) -> contracts.Highlights:
    return content if content.pulse_slots is not None else _pulse_content(content, {}, [])


def _pulse_content(
    content: contracts.Highlights,
    progress: dict[str, PulseSourceProgress],
    previous: list[contracts.PulseSlot],
    *,
    complete: bool = False,
) -> contracts.Highlights:
    metrics = {metric.key: metric for metric in content.pulse}
    offered = {metric.key for source in progress.values() for metric in source.found.pulse}
    slots = {slot.key: slot for slot in previous}
    owners: dict[str, int] = {}
    order = {source.name: source.pulse_order for source in load_sources()}
    for name, source in progress.items():
        for metric in source.found.pulse:
            owners[metric.key] = order.get(name, 0)
        for slot in source.slots:
            slots[slot.key] = slot
            owners[slot.key] = order.get(name, 0)
    for metric in content.pulse:
        slots[metric.key] = contracts.PulseSlot(
            key=metric.key,
            name=metric.name,
            url=metric.url,
            interval=metric.interval,
            reason=metric.reason,
            status=PulseSlotStatus.READY,
        )
    pin_order = {pin.key: index for index, pin in enumerate(content.pins)}
    selected = [
        slot
        for slot in slots.values()
        if slot.status != PulseSlotStatus.EMPTY and (slot.key not in offered or slot.key in metrics)
    ]
    selected.sort(
        key=lambda slot: (
            slot.key not in pin_order,
            pin_order.get(slot.key, 0),
            owners.get(slot.key, 0),
        )
    )
    if complete:
        selected = [
            replace(slot, status=PulseSlotStatus.ERROR) if slot.status == PulseSlotStatus.PENDING else slot
            for slot in selected
        ]
    key_metrics = (
        {
            *(slot.key for slot in progress[KEY_METRICS_SOURCE].slots),
            *(metric.key for metric in progress[KEY_METRICS_SOURCE].found.pulse),
        }
        if KEY_METRICS_SOURCE in progress
        else set()
    )
    key_metrics |= {m.key for m in content.pulse if m.reason == HighlightMetricReason.KEY_METRIC}
    selected = _key_metrics_without_own_numbers(selected, key_metrics, set(pin_order))
    selected = _popular_within_row(selected, set(pin_order))
    kept = {slot.key for slot in selected}
    fallbacks = key_metrics | {m.key for m in content.pulse if m.reason == HighlightMetricReason.POPULAR}
    pulse = [m for m in content.pulse if m.key in kept or m.key not in fallbacks]
    return replace(content, pulse=pulse, pulse_slots=selected)


def _with_fallbacks(
    chosen: list[contracts.HighlightMetric], suggested: list[contracts.HighlightMetric]
) -> list[contracts.HighlightMetric]:
    fallback_reasons = (HighlightMetricReason.KEY_METRIC, HighlightMetricReason.POPULAR)
    own = [metric for metric in suggested if metric.reason not in fallback_reasons]
    key_metrics = [] if chosen or own else [m for m in suggested if m.reason == HighlightMetricReason.KEY_METRIC]
    popular = [metric for metric in suggested if metric.reason == HighlightMetricReason.POPULAR]
    room = max(0, ROW_TILES - len(chosen) - len(own) - len(key_metrics))
    return [*chosen, *own, *key_metrics, *popular[:room]]


def _key_metrics_without_own_numbers(
    slots: list[contracts.PulseSlot], key_metrics: set[str], pinned: set[str]
) -> list[contracts.PulseSlot]:
    own = any(
        slot.status != PulseSlotStatus.ERROR
        and (slot.key in pinned or (slot.key not in key_metrics and slot.reason != HighlightMetricReason.POPULAR))
        for slot in slots
    )
    if not own:
        return slots
    return [slot for slot in slots if slot.key not in key_metrics or slot.key in pinned]


def _popular_within_row(slots: list[contracts.PulseSlot], pinned: set[str]) -> list[contracts.PulseSlot]:
    popular = sorted(
        (slot for slot in slots if slot.reason == HighlightMetricReason.POPULAR),
        key=lambda slot: slot.status == PulseSlotStatus.ERROR,
    )
    others = [slot for slot in slots if slot.reason != HighlightMetricReason.POPULAR]
    live = sum(slot.status != PulseSlotStatus.ERROR for slot in others)
    shown = {slot.key for slot in popular[: max(0, ROW_TILES - live)]}
    released = [slot.key for slot in others if slot.status == PulseSlotStatus.ERROR and slot.key not in pinned]
    overflow = min(len(shown), len(others) + len(shown) - ROW_TILES)
    dropped = set(released[::-1][: max(0, overflow)])
    return [
        slot
        for slot in slots
        if slot.key not in dropped and (slot.reason != HighlightMetricReason.POPULAR or slot.key in shown)
    ]


def publish_pulse(inputs: HighlightSourceInputs, found: HighlightFindings, slots: list[contracts.PulseSlot]) -> None:
    if inputs.highlights_id is None:
        return
    with transaction.atomic():
        row = (
            TodayHighlights.objects.for_team(inputs.team_id)
            .select_for_update()
            .filter(id=inputs.highlights_id, status=HighlightsStatus.COMPUTING)
            .first()
        )
        if row is None:
            return
        progress = _PROGRESS.validate_python(row.content.get("_pulse_sources", {}))
        previous = progress.get(inputs.source_name)
        if previous is not None:
            metrics = {metric.key: metric for metric in previous.found.pulse}
            metrics.update({metric.key: metric for metric in found.pulse})
            found = replace(found, pulse=tuple(metrics.values()))
            slots = list({slot.key: slot for slot in [*previous.slots, *slots]}.values())
        progress[inputs.source_name] = PulseSourceProgress(found=found, slots=slots)
        pinned = _published_pins(progress)
        content = build_highlights(
            load_sources(),
            {name: source.found for name, source in progress.items()},
            Team.objects.get(id=inputs.team_id),
            row.local_day,
            pins=list(pinned),
            pinned=pinned,
        )
        previous_slots = _HIGHLIGHTS.validate_python(row.content).pulse_slots if row.content else []
        content = _pulse_content(content, progress, previous_slots or [])
        row.content = _HIGHLIGHTS.dump_python(replace(content, status=HighlightsStatus.COMPUTING), mode="json")
        row.content["_pulse_sources"] = _PROGRESS.dump_python(progress, mode="json")
        row.save(update_fields=["content"])


def publish_pinned(inputs: ResolvePinsInputs, metric: contracts.HighlightMetric) -> None:
    source = HighlightSourceInputs(
        team_id=inputs.team_id,
        user_id=inputs.user_id,
        local_day=inputs.local_day,
        scopes=inputs.scopes,
        source_name=PINNED_SOURCE,
        highlights_id=inputs.highlights_id,
    )
    publish_pulse(source, HighlightFindings(pulse=(metric,)), [])


def _published_pins(progress: Mapping[str, PulseSourceProgress]) -> dict[str, contracts.HighlightMetric]:
    published = progress.get(PINNED_SOURCE)
    return {metric.key: metric for metric in published.found.pulse} if published else {}


def run_source(inputs: HighlightSourceInputs) -> HighlightSourceResult:
    source = next((source for source in load_sources() if source.name == inputs.source_name), None)
    context = Context(
        Team.objects.get(id=inputs.team_id),
        User.objects.get(id=inputs.user_id),
        date.fromisoformat(inputs.local_day),
        None if inputs.scopes is None else frozenset(inputs.scopes),
        frozenset(inputs.pinned),
        publish_pulse=partial(publish_pulse, inputs) if inputs.highlights_id is not None else None,
        hidden=frozenset(inputs.hidden),
    )
    if source is None or not context.allows(*source.scopes):
        return HighlightSourceResult(source_name=inputs.source_name, found=None, failed=False)
    with tags_context(product=Product.TODAY, feature=Feature.QUERY, team_id=context.team.id):
        found = context.guard(source.name, partial(source.find, context), HighlightFindings())
    context.publish_pulse(found, [])
    return HighlightSourceResult(
        source_name=source.name, found=_FINDINGS.dump_json(found).decode(), failed=bool(context.failures)
    )


@transaction.atomic
def finalize(inputs: FinalizeHighlightsInputs) -> None:
    row = (
        TodayHighlights.objects.for_team(inputs.team_id)
        .select_for_update()
        .filter(id=inputs.highlights_id, status=HighlightsStatus.COMPUTING)
        .first()
    )
    if row is None:
        return
    found = {result.source_name: _FINDINGS.validate_json(result.found) for result in inputs.results if result.found}
    progress = _PROGRESS.validate_python(row.content.get("_pulse_sources", {}))
    for name, source in progress.items():
        final = found.get(name, source.found)
        metrics = {metric.key: metric for metric in source.found.pulse}
        metrics.update({metric.key: metric for metric in final.pulse})
        found[name] = replace(final, pulse=tuple(metrics.values()))
    highlights = build_highlights(
        load_sources(),
        found,
        Team.objects.get(id=inputs.team_id),
        row.local_day,
        pins=[pin.key for pin in inputs.pins],
        pinned={
            **_published_pins(progress),
            **{metric.key: metric for metric in PINNED_METRICS.validate_json(inputs.pinned)},
        },
    )
    previous_slots = _HIGHLIGHTS.validate_python(row.content).pulse_slots if "_pulse_sources" in row.content else []
    highlights = _pulse_content(highlights, progress, previous_slots or [], complete=True)
    failed = [result for result in inputs.results if result.failed]
    usable = bool(highlights.items or highlights.pulse)
    row.status = (
        HighlightsStatus.FAILED
        if failed and len(failed) == len(inputs.results) and not usable
        else HighlightsStatus.READY
    )
    row.content = _HIGHLIGHTS.dump_python(highlights, mode="json")
    row.failed_sources = bool(failed) or inputs.pins_failed
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
    suggested = [metric for key, metric in offered.items() if key not in pins]
    pulse = _with_fallbacks(chosen, suggested)[:PULSE_CANDIDATES]
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
        product=source_product(candidate.source),
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
