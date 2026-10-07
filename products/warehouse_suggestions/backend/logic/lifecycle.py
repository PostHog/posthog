from collections import Counter
from collections.abc import Collection, Sequence
from datetime import datetime, time, timedelta

from django.db.models import F

from posthog.dataclasses import frozen

from ..facade.contracts import SuggestionAlreadyDecidedError, SuggestionDraft
from ..facade.enums import (
    WarehouseSuggestionDismissalReason,
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)
from ..models import WarehouseSuggestion
from .candidates import CANDIDATES, CandidateContext
from .reads import Subject
from .rules import LifecycleRules
from .suggestions import transition_to, upsert_suggestions


@frozen
class LifecycleResult:
    reproposed: int
    revived: int
    auto_resolved: int
    expired: int
    surfaced: int


def apply_run(
    context: CandidateContext, drafts: Sequence[SuggestionDraft], now: datetime, *, surface: bool
) -> LifecycleResult:
    fingerprints = {draft.fingerprint for draft in drafts}
    reproposed, revived = _reopen(context, drafts)
    upsert_suggestions(context.team_id, drafts)
    auto_resolved = _auto_resolve(context, fingerprints)
    expired = _expire(context, fingerprints, now)
    surfaced = _surface(context.team_id, context.rules.lifecycle, now) if surface else 0
    return LifecycleResult(
        reproposed=reproposed, revived=revived, auto_resolved=auto_resolved, expired=expired, surfaced=surfaced
    )


def _reopen(context: CandidateContext, drafts: Sequence[SuggestionDraft]) -> tuple[int, int]:
    drafts_by_fingerprint = {draft.fingerprint: draft for draft in drafts}
    closed = WarehouseSuggestion.objects.for_team(context.team_id).filter(
        fingerprint__in=drafts_by_fingerprint,
        status__in=[WarehouseSuggestionStatus.DISMISSED, WarehouseSuggestionStatus.EXPIRED],
    )
    reproposed = 0
    revived = 0
    for row in closed:
        if row.status == WarehouseSuggestionStatus.EXPIRED:
            revived += _move(row, context.team_id, WarehouseSuggestionStatus.PROPOSED)
        elif _earns_reproposal(row, drafts_by_fingerprint[row.fingerprint], context.rules.lifecycle):
            if _move(row, context.team_id, WarehouseSuggestionStatus.PROPOSED):
                WarehouseSuggestion.objects.for_team(context.team_id).filter(id=row.id).update(
                    reproposed_count=F("reproposed_count") + 1
                )
                reproposed += 1
    return reproposed, revived


def _earns_reproposal(row: WarehouseSuggestion, draft: SuggestionDraft, rules: LifecycleRules) -> bool:
    return (
        row.dismissal_reason == WarehouseSuggestionDismissalReason.NOT_NOW
        and row.dismissed_at_score is not None
        and draft.score >= rules.reproposal_score_multiple * row.dismissed_at_score
    )


def _auto_resolve(context: CandidateContext, refreshed_fingerprints: Collection[str]) -> int:
    open_rows = (
        WarehouseSuggestion.objects.for_team(context.team_id)
        .filter(status=WarehouseSuggestionStatus.PROPOSED)
        .exclude(fingerprint__in=refreshed_fingerprints)
    )
    return sum(
        _move(row, context.team_id, WarehouseSuggestionStatus.AUTO_RESOLVED)
        for row in open_rows
        if CANDIDATES[WarehouseSuggestionKind(row.kind)].is_resolved(context, _subject(row))
    )


def _expire(context: CandidateContext, refreshed_fingerprints: Collection[str], now: datetime) -> int:
    rules = context.rules.lifecycle
    if context.reads.recent_days_with_data < rules.expire_after_days:
        return 0
    stale = (
        WarehouseSuggestion.objects.for_team(context.team_id)
        .filter(
            status=WarehouseSuggestionStatus.PROPOSED, last_seen_at__lt=now - timedelta(days=rules.expire_after_days)
        )
        .exclude(fingerprint__in=refreshed_fingerprints)
    )
    return sum(_move(row, context.team_id, WarehouseSuggestionStatus.EXPIRED) for row in stale)


def _surface(team_id: int, rules: LifecycleRules, now: datetime) -> int:
    suggestions = WarehouseSuggestion.objects.for_team(team_id)
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    open_kinds = Counter(
        suggestions.filter(status=WarehouseSuggestionStatus.PROPOSED, surfaced_at__isnull=False).values_list(
            "kind", flat=True
        )
    )
    slots = min(
        rules.max_surfaced_per_day - suggestions.filter(surfaced_at__gte=start_of_day).count(),
        rules.max_open - open_kinds.total(),
    )
    if slots <= 0:
        return 0
    first_week = not suggestions.filter(
        surfaced_at__lt=start_of_day - timedelta(days=rules.first_week_runs - 1)
    ).exists()
    waiting = sorted(
        suggestions.filter(status=WarehouseSuggestionStatus.PROPOSED, surfaced_at__isnull=True).only(
            "id", "kind", "score"
        ),
        key=lambda row: (first_week and row.kind not in rules.first_week_kinds, -row.score, str(row.id)),
    )
    chosen = []
    for row in waiting:
        if len(chosen) == slots:
            break
        if open_kinds[row.kind] >= rules.max_open_per_kind:
            continue
        open_kinds[row.kind] += 1
        chosen.append(row.id)
    return suggestions.filter(id__in=chosen).update(surfaced_at=now)


def _move(row: WarehouseSuggestion, team_id: int, status: WarehouseSuggestionStatus) -> bool:
    try:
        transition_to(row.id, team_id, status, user_id=None)
    except SuggestionAlreadyDecidedError:
        return False
    return True


def _subject(row: WarehouseSuggestion) -> Subject:
    return Subject(kind=WarehouseSuggestionSubjectKind(row.subject_kind), id=row.subject_id)
