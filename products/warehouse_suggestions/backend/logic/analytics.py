from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from prometheus_client import Counter

from posthog.event_usage import report_user_or_team_action

from ..models import WarehouseSuggestion

if TYPE_CHECKING:
    from posthog.models import Team, User

SECONDS_PER_DAY = 24 * 60 * 60

CANDIDATES_FOUND = Counter(
    "warehouse_suggestions_candidates_total",
    "Suggestion candidates the daily job found, by kind.",
    labelnames=["kind"],
)
SUGGESTION_OUTCOMES = Counter(
    "warehouse_suggestions_total",
    "Suggestions that changed state, by kind and outcome.",
    labelnames=["kind", "outcome"],
)


class SuggestionOutcome(StrEnum):
    CREATED = "created"
    SURFACED = "surfaced"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    RESUMED = "resumed"
    REPROPOSED = "reproposed"
    REVIVED = "revived"
    EXPIRED = "expired"
    AUTO_RESOLVED = "auto resolved"


def report_candidates(kind: str, count: int) -> None:
    CANDIDATES_FOUND.labels(kind=kind).inc(count)


def report_outcomes(
    outcome: SuggestionOutcome,
    suggestions: Iterable[WarehouseSuggestion],
    *,
    team: "Team",
    user: "User | None" = None,
) -> None:
    now = timezone.now()
    for suggestion in suggestions:
        SUGGESTION_OUTCOMES.labels(kind=suggestion.kind, outcome=outcome.value).inc()
        report_user_or_team_action(
            f"warehouse suggestion {outcome.value}",
            _properties(suggestion, now, is_system=user is None),
            user=user,
            team=team,
        )


def _properties(suggestion: WarehouseSuggestion, now: datetime, *, is_system: bool) -> dict[str, Any]:
    return {
        "suggestion_id": str(suggestion.id),
        "kind": suggestion.kind,
        "subject_kind": suggestion.subject_kind,
        "score": suggestion.score,
        "rules_version": suggestion.rules_version,
        "reproposed_count": suggestion.reproposed_count,
        "reason": suggestion.dismissal_reason,
        "days_open": (now - suggestion.surfaced_at).total_seconds() / SECONDS_PER_DAY
        if suggestion.surfaced_at
        else None,
        "is_system": is_system,
    }
