"""Read one person's stored list for `sort=personal` on the report list. The read never builds.

It reads one `PersonalInboxRanking` row and nothing else: no candidate pools, no queued build, no model call. So a
page load can use it. The order puts the ranked reports first by stored rank, then the folded reports, and the view
orders every other report in the person's `recommended` order. With no usable row there is no order, and the list is
the plain `recommended` order.
"""

import uuid
from collections.abc import Mapping

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.models import PersonalInboxRanking
from products.signals.backend.personal_ranking.config import read_config


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
