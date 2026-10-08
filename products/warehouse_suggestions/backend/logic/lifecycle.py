from collections import Counter, defaultdict, deque
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime, time, timedelta
from functools import partial
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
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
from .analytics import SuggestionOutcome, report_outcomes
from .candidates.base import CandidateContext
from .candidates.registry import CANDIDATES
from .reads import Subject
from .rules import LifecycleRules, kind_position
from .suggestions import transition_to, upsert_suggestions

if TYPE_CHECKING:
    from posthog.models.team import Team


@frozen
class LifecycleResult:
    created: int
    reproposed: int
    revived: int
    auto_resolved: int
    expired: int
    surfaced: int
    assets_reconciled: int


OutcomeBatches = Sequence[tuple[SuggestionOutcome, Sequence[WarehouseSuggestion]]]


@frozen
class Reopened:
    reproposed: tuple[WarehouseSuggestion, ...]
    revived: tuple[WarehouseSuggestion, ...]


def apply_run(
    context: CandidateContext, team: "Team", drafts: Sequence[SuggestionDraft], now: datetime, *, surface: bool
) -> LifecycleResult:
    """Apply one run's drafts to the stored suggestions, then show new ones when `surface` is set."""
    fingerprints = {draft.fingerprint for draft in drafts}
    reopened = _reopen(context, drafts)
    created = _upsert(context.team_id, drafts)
    auto_resolved = _auto_resolve(context, fingerprints)
    expired = _expire(context, fingerprints, now)
    surfaced = _surface(context.team_id, context.rules.lifecycle, now) if surface else []
    assets_reconciled = _reconcile_assets(context)
    outcomes: OutcomeBatches = (
        (SuggestionOutcome.CREATED, created),
        (SuggestionOutcome.REPROPOSED, reopened.reproposed),
        (SuggestionOutcome.REVIVED, reopened.revived),
        (SuggestionOutcome.AUTO_RESOLVED, auto_resolved),
        (SuggestionOutcome.EXPIRED, expired),
        (SuggestionOutcome.SURFACED, surfaced),
    )
    transaction.on_commit(partial(_report_all, outcomes, team))
    return LifecycleResult(
        created=len(created),
        reproposed=len(reopened.reproposed),
        revived=len(reopened.revived),
        auto_resolved=len(auto_resolved),
        expired=len(expired),
        surfaced=len(surfaced),
        assets_reconciled=assets_reconciled,
    )


def _report_all(outcomes: "OutcomeBatches", team: "Team") -> None:
    for outcome, rows in outcomes:
        report_outcomes(outcome, rows, team=team)


def _upsert(team_id: int, drafts: Sequence[SuggestionDraft]) -> list[WarehouseSuggestion]:
    suggestions = WarehouseSuggestion.objects.for_team(team_id)
    fingerprints = {draft.fingerprint for draft in drafts}
    existing = set(suggestions.filter(fingerprint__in=fingerprints).values_list("fingerprint", flat=True))
    upsert_suggestions(team_id, drafts)
    return list(suggestions.filter(fingerprint__in=fingerprints - existing))


REVIVABLE_STATUSES = (WarehouseSuggestionStatus.EXPIRED, WarehouseSuggestionStatus.AUTO_RESOLVED)


def _reopen(context: CandidateContext, drafts: Sequence[SuggestionDraft]) -> Reopened:
    """Move closed suggestions that match a draft back to proposed and unshown, dismissed ones only if they earn it."""
    drafts_by_fingerprint = {draft.fingerprint: draft for draft in drafts}
    suggestions = WarehouseSuggestion.objects.for_team(context.team_id)
    closed = suggestions.filter(
        fingerprint__in=drafts_by_fingerprint,
        status__in=[WarehouseSuggestionStatus.DISMISSED, *REVIVABLE_STATUSES],
    )
    reproposed: list[WarehouseSuggestion] = []
    revived: list[WarehouseSuggestion] = []
    for row in closed:
        if row.status in REVIVABLE_STATUSES:
            revived.extend(_moved(row, context.team_id, WarehouseSuggestionStatus.PROPOSED))
        elif _earns_reproposal(row, drafts_by_fingerprint[row.fingerprint], context.rules.lifecycle):
            reproposed.extend(_moved(row, context.team_id, WarehouseSuggestionStatus.PROPOSED))
    reproposed_ids = [row.id for row in reproposed]
    revived_ids = [row.id for row in revived]
    suggestions.filter(id__in=reproposed_ids).update(reproposed_count=F("reproposed_count") + 1)
    suggestions.filter(id__in=[*reproposed_ids, *revived_ids]).update(surfaced_at=None)
    return Reopened(
        reproposed=tuple(suggestions.filter(id__in=reproposed_ids)),
        revived=tuple(suggestions.filter(id__in=revived_ids)),
    )


def _earns_reproposal(row: WarehouseSuggestion, draft: SuggestionDraft, rules: LifecycleRules) -> bool:
    """Whether a not-now dismissal now scores above, and at least `reproposal_score_multiple` times, its old score."""
    return (
        row.dismissal_reason == WarehouseSuggestionDismissalReason.NOT_NOW
        and row.dismissed_at_score is not None
        and draft.score > row.dismissed_at_score
        and draft.score >= rules.reproposal_score_multiple * row.dismissed_at_score
    )


def _auto_resolve(context: CandidateContext, refreshed_fingerprints: Collection[str]) -> list[WarehouseSuggestion]:
    """Auto-resolve proposed suggestions with no draft this run whose subject no longer needs them."""
    open_rows = (
        WarehouseSuggestion.objects.for_team(context.team_id)
        .filter(status=WarehouseSuggestionStatus.PROPOSED)
        .exclude(fingerprint__in=refreshed_fingerprints)
    )
    resolved = (
        row for row in open_rows if CANDIDATES[WarehouseSuggestionKind(row.kind)].is_resolved(context, _subject(row))
    )
    return _move_all(resolved, context.team_id, WarehouseSuggestionStatus.AUTO_RESOLVED)


def _expire(
    context: CandidateContext, refreshed_fingerprints: Collection[str], now: datetime
) -> list[WarehouseSuggestion]:
    """Expire proposed suggestions with no draft for `expire_after_days`, unless the read data is too short to tell."""
    rules = context.rules.lifecycle
    if context.reads.recent_days_with_data < rules.expire_after_days:
        return []
    stale = (
        WarehouseSuggestion.objects.for_team(context.team_id)
        .filter(
            status=WarehouseSuggestionStatus.PROPOSED, last_seen_at__lt=now - timedelta(days=rules.expire_after_days)
        )
        .exclude(fingerprint__in=refreshed_fingerprints)
    )
    return _move_all(stale, context.team_id, WarehouseSuggestionStatus.EXPIRED)


def _surface(team_id: int, rules: LifecycleRules, now: datetime) -> list[WarehouseSuggestion]:
    """Show waiting suggestions within the daily, open and per-kind limits, and return the ones shown."""
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
        return []
    first_week = not suggestions.filter(
        surfaced_at__lt=start_of_day - timedelta(days=rules.first_week_runs - 1)
    ).exists()
    waiting = suggestions.filter(status=WarehouseSuggestionStatus.PROPOSED, surfaced_at__isnull=True).only(
        "id", "kind", "score"
    )
    chosen = _pick_in_turns(
        list(waiting),
        rules.first_week_kind_order if first_week else rules.kind_order,
        slots,
        open_kinds,
        rules.max_open_per_kind,
    )
    suggestions.filter(id__in=chosen).update(surfaced_at=now)
    return list(suggestions.filter(id__in=chosen))


def _pick_in_turns(
    waiting: Sequence[WarehouseSuggestion],
    kind_order: Sequence[WarehouseSuggestionKind],
    slots: int,
    open_kinds: Counter[str],
    max_open_per_kind: int,
) -> list[UUID]:
    """Pick up to `slots` suggestions in turns across `kind_order`, highest score first, skipping full kinds."""
    queues: defaultdict[str, deque[WarehouseSuggestion]] = defaultdict(deque)
    for row in sorted(waiting, key=lambda row: (-row.score, str(row.id))):
        queues[row.kind].append(row)
    turns = sorted(queues, key=lambda kind: (kind_position(kind_order, kind), kind))
    open_now = Counter(open_kinds)
    chosen: list[UUID] = []
    while len(chosen) < slots:
        ready = [kind for kind in turns if queues[kind] and open_now[kind] < max_open_per_kind]
        if not ready:
            break
        for kind in ready[: slots - len(chosen)]:
            chosen.append(queues[kind].popleft().id)
            open_now[kind] += 1
    return chosen


def _reconcile_assets(context: CandidateContext) -> int:
    suggestions = WarehouseSuggestion.objects.for_team(context.team_id)
    changed = 0
    for row in suggestions.filter(status=WarehouseSuggestionStatus.ACCEPTED).only(
        "id", "kind", "subject_kind", "subject_id", "reviewed_at", "asset_outcome"
    ):
        outcome = CANDIDATES[WarehouseSuggestionKind(row.kind)].asset_outcome(
            context, _subject(row), accepted_at=row.reviewed_at
        )
        if outcome != row.asset_outcome:
            changed += suggestions.filter(id=row.id).update(asset_outcome=outcome)
    return changed


def _move_all(
    rows: Iterable[WarehouseSuggestion], team_id: int, status: WarehouseSuggestionStatus
) -> list[WarehouseSuggestion]:
    return [moved for row in rows for moved in _moved(row, team_id, status)]


def _moved(row: WarehouseSuggestion, team_id: int, status: WarehouseSuggestionStatus) -> list[WarehouseSuggestion]:
    """The suggestion moved to `status` as the system, or nothing when a person already decided it."""
    try:
        return [transition_to(row.id, team_id, status, user_id=None)]
    except SuggestionAlreadyDecidedError:
        return []


def _subject(row: WarehouseSuggestion) -> Subject:
    return Subject(kind=WarehouseSuggestionSubjectKind(row.subject_kind), id=row.subject_id)
