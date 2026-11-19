"""Read one person's stored list for the report list. The reads never build.

Each read takes one `PersonalInboxRanking` row and nothing else: no candidate pools, no queued build, no model call.
So a page load can use them. For `sort=personal`, the order puts the ranked reports first by stored rank, then the
folded reports, and the view orders every other report in the person's `recommended` order. With no usable row there
is no order, and the list is the plain `recommended` order. For every sort, the status says what the person's latest
row holds, so the client can record whether a personal ranking was ready.
"""

import uuid
import datetime
from collections.abc import Mapping
from typing import Literal

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.models import PersonalInboxRanking
from products.signals.backend.personal_ranking.config import read_config

PersonalRankingState = Literal["real", "one_report", "not_personalized", "empty", "fallback", "none"]


@frozen
class PersonalRowNote:
    tier: str
    reason: str


@frozen
class PersonalListOrder:
    ranking_id: str
    # The ranked reports by stored rank, then the folded reports.
    report_ids: tuple[uuid.UUID, ...]
    # Only the reports the language model ranked, by report id.
    notes: Mapping[str, PersonalRowNote]


def _parse_id(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def personal_list_order(team: Team, user: User, ranking_id: str | None = None) -> PersonalListOrder | None:
    """The order of the row `ranking_id` names, else of the latest personalized row. None when nothing is ranked."""
    if not read_config().enabled:
        return None
    rows = PersonalInboxRanking.objects.for_team(team.id).filter(user_id=user.id, personalized=True)
    # A later page names the row of the first page, so a rebuild between pages does not reshuffle them.
    row = rows.filter(id=ranking_id).first() if ranking_id else None
    if row is None:
        row = rows.order_by("-created_at", "-id").first()
    if row is None:
        return None
    result = row.result or {}
    ranked = sorted(result.get("ranked") or (), key=lambda entry: entry["rank"])
    report_ids: dict[uuid.UUID, None] = {}
    notes: dict[str, PersonalRowNote] = {}
    for entry in [*ranked, *(result.get("folded") or ())]:
        report_id = _parse_id(entry.get("report_id"))
        if report_id is None:
            continue
        report_ids.setdefault(report_id)
        if entry.get("ranked_by") == "llm":
            notes[str(report_id)] = PersonalRowNote(tier=entry["tier"], reason=entry["reason"])
    if not report_ids:
        return None
    return PersonalListOrder(ranking_id=str(row.id), report_ids=tuple(report_ids), notes=notes)


@frozen
class PersonalRankingStatus:
    state: PersonalRankingState
    # The ranked and folded reports of the row. None when there is no row.
    size: int | None
    age_minutes: int | None
    # Minutes since a build or the scheduled tick last confirmed the row's inputs.
    checked_age_minutes: int | None
    fallback_reason: str | None


NO_PERSONAL_RANKING = PersonalRankingStatus(
    state="none", size=None, age_minutes=None, checked_age_minutes=None, fallback_reason=None
)


def personal_ranking_state(status: str, personalized: bool, size: int) -> PersonalRankingState:
    """Only an ok, personalized row of 2 or more reports can change the order of the list."""
    if status == PersonalInboxRanking.Status.EMPTY:
        return "empty"
    if status != PersonalInboxRanking.Status.OK:
        return "fallback"
    if not personalized:
        return "not_personalized"
    if size == 0:
        return "empty"
    return "real" if size >= 2 else "one_report"


def _minutes_since(moment: datetime.datetime, now: datetime.datetime) -> int:
    return max(int((now - moment).total_seconds() // 60), 0)


def personal_ranking_status(team: Team, user: User, now: datetime.datetime) -> PersonalRankingStatus | None:
    """What the person's latest stored row holds, with one indexed query. None when personal ranking is off."""
    if not read_config().enabled:
        return None
    row = (
        PersonalInboxRanking.objects.for_team(team.id)
        .filter(user_id=user.id)
        .order_by("-created_at", "-id")
        .only("created_at", "checked_at", "status", "personalized", "fallback_reason", "result")
        .first()
    )
    if row is None:
        return NO_PERSONAL_RANKING
    result = row.result or {}
    size = len(result.get("ranked") or ()) + len(result.get("folded") or ())
    state = personal_ranking_state(row.status, row.personalized, size)
    return PersonalRankingStatus(
        state=state,
        size=size,
        age_minutes=_minutes_since(row.created_at, now),
        checked_age_minutes=_minutes_since(row.checked_at or row.created_at, now),
        fallback_reason=row.fallback_reason if state == "fallback" else None,
    )
