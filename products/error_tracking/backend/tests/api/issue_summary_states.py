from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.redis import get_client

from products.error_tracking.backend.logic import issue_summaries, team_flags
from products.error_tracking.backend.models import ErrorTrackingIssueSummary

GENERATED_AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
STORED_CONTENT = {
    "what_happened": "Checkout throws a TypeError when the cart is empty.",
    "likely_cause": "The cart total reads a property of an undefined line item.",
    "who_is_affected": "Users who open checkout with an empty cart.",
    "suggested_next_step": "Guard the line item lookup in the cart total.",
}

# name, flag on, sources readable, AI approved, summary stored, expected status, expected reason
SUMMARY_STATES: list[tuple[str, bool, bool, bool, bool, str, str | None]] = [
    ("ready", True, True, True, True, "ready", None),
    ("not_generated", True, True, True, False, "not_generated", None),
    ("disabled_hides_stored", False, True, True, True, "unavailable", "disabled"),
    ("restricted_hides_stored", True, False, True, True, "unavailable", "restricted"),
    ("ai_not_approved_hides_stored", True, True, False, True, "unavailable", "ai_not_approved"),
    ("ai_not_approved", True, True, False, False, "unavailable", "ai_not_approved"),
]


@contextmanager
def summary_state(
    test: APIBaseTest, issue_id: UUID | str, *, flag: bool, readable: bool, approved: bool, stored: bool
) -> Iterator[None]:
    test.organization.is_ai_data_processing_approved = approved
    test.organization.save()
    if stored:
        ErrorTrackingIssueSummary.objects.for_team(test.team.id).create(
            team=test.team,
            issue_id=issue_id,
            content=STORED_CONTENT,
            input_hash="hash",
            model="test-model",
            generated_at=GENERATED_AT,
            checked_at=GENERATED_AT,
        )
    with (
        patch.object(team_flags, "feature_enabled_or_false", return_value=flag),
        patch.object(issue_summaries, "summary_sources_readable", return_value=readable),
    ):
        yield


def lock_held(team_id: int, issue_id: UUID | str) -> bool:
    return bool(get_client().exists(issue_summaries._lock_key(team_id, issue_id)))
