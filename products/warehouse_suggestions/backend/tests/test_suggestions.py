from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.warehouse_suggestions.backend.facade.contracts import SuggestionAlreadyDecidedError, SuggestionDraft
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
    WarehouseSuggestionSubjectKind,
)
from products.warehouse_suggestions.backend.logic.suggestions import transition_to, upsert_suggestions
from products.warehouse_suggestions.backend.models import WarehouseSuggestion

WINDOW_START = datetime(2026, 9, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 30, tzinfo=UTC)
SUBJECT_ID = UUID("01a11171-0000-7000-8000-000000000001")


def make_draft(
    *,
    fingerprint: str = "certify:orders",
    subject_kind: WarehouseSuggestionSubjectKind = WarehouseSuggestionSubjectKind.SAVED_QUERY,
    subject_id: UUID = SUBJECT_ID,
    score: float = 1.0,
    evidence_window_end: datetime = WINDOW_END,
) -> SuggestionDraft:
    return SuggestionDraft(
        kind=WarehouseSuggestionKind.CERTIFY,
        fingerprint=fingerprint,
        subject_kind=subject_kind,
        subject_id=subject_id,
        payload={"name": "orders"},
        payload_version=1,
        rules_version="abc123",
        evidence={"distinct_readers": 4},
        evidence_window_start=WINDOW_START,
        evidence_window_end=evidence_window_end,
        score=score,
        score_inputs={"readers": 4},
        run_id="run-1",
    )


def ingest_one(team_id: int, draft: SuggestionDraft) -> WarehouseSuggestion:
    upsert_suggestions(team_id, [draft])
    return WarehouseSuggestion.objects.for_team(team_id).get(fingerprint=draft.fingerprint)


class TestTransitions(BaseTest):
    @parameterized.expand(
        [
            ("proposed_to_accepted", WarehouseSuggestionStatus.PROPOSED, WarehouseSuggestionStatus.ACCEPTED, True),
            ("proposed_to_dismissed", WarehouseSuggestionStatus.PROPOSED, WarehouseSuggestionStatus.DISMISSED, True),
            ("proposed_to_expired", WarehouseSuggestionStatus.PROPOSED, WarehouseSuggestionStatus.EXPIRED, True),
            (
                "proposed_to_auto_resolved",
                WarehouseSuggestionStatus.PROPOSED,
                WarehouseSuggestionStatus.AUTO_RESOLVED,
                True,
            ),
            ("dismissed_to_proposed", WarehouseSuggestionStatus.DISMISSED, WarehouseSuggestionStatus.PROPOSED, True),
            ("expired_to_proposed", WarehouseSuggestionStatus.EXPIRED, WarehouseSuggestionStatus.PROPOSED, True),
            ("proposed_to_proposed", WarehouseSuggestionStatus.PROPOSED, WarehouseSuggestionStatus.PROPOSED, False),
            ("dismissed_to_accepted", WarehouseSuggestionStatus.DISMISSED, WarehouseSuggestionStatus.ACCEPTED, False),
            ("accepted_to_dismissed", WarehouseSuggestionStatus.ACCEPTED, WarehouseSuggestionStatus.DISMISSED, False),
            ("accepted_to_proposed", WarehouseSuggestionStatus.ACCEPTED, WarehouseSuggestionStatus.PROPOSED, False),
            (
                "auto_resolved_to_proposed",
                WarehouseSuggestionStatus.AUTO_RESOLVED,
                WarehouseSuggestionStatus.PROPOSED,
                False,
            ),
            ("expired_to_dismissed", WarehouseSuggestionStatus.EXPIRED, WarehouseSuggestionStatus.DISMISSED, False),
        ]
    )
    def test_status_moves(
        self, _name: str, start: WarehouseSuggestionStatus, target: WarehouseSuggestionStatus, allowed: bool
    ) -> None:
        suggestion = ingest_one(self.team.id, make_draft())
        WarehouseSuggestion.objects.for_team(self.team.id).filter(id=suggestion.id).update(status=start)

        if not allowed:
            with self.assertRaises(SuggestionAlreadyDecidedError):
                transition_to(suggestion.id, self.team.id, target, user_id=self.user.id)
            suggestion.refresh_from_db()
            assert suggestion.status == start
            return

        transition_to(suggestion.id, self.team.id, target, user_id=self.user.id)
        suggestion.refresh_from_db()
        assert suggestion.status == target


class TestIngest(BaseTest):
    def test_ingest_inserts_new_drafts_and_refreshes_proposed_ones(self) -> None:
        first = ingest_one(self.team.id, make_draft(score=1.0))

        assert first.status == WarehouseSuggestionStatus.PROPOSED
        assert first.team_id == self.team.id

        refreshed = ingest_one(self.team.id, make_draft(score=7.5))

        assert refreshed.id == first.id
        assert refreshed.score == 7.5
        assert refreshed.last_seen_at > first.last_seen_at

    @parameterized.expand(
        [
            ("dismissed", {"status": WarehouseSuggestionStatus.DISMISSED}, {}),
            ("accepted", {"status": WarehouseSuggestionStatus.ACCEPTED}, {}),
            ("draft_with_older_evidence", {}, {"evidence_window_end": WINDOW_END - timedelta(days=1)}),
            ("draft_about_another_subject", {}, {"subject_id": uuid4()}),
        ]
    )
    def test_ingest_leaves_the_suggestion_untouched(
        self, _name: str, row_changes: dict[str, Any], draft_changes: dict[str, Any]
    ) -> None:
        suggestion = ingest_one(self.team.id, make_draft(score=1.0))
        WarehouseSuggestion.objects.for_team(self.team.id).filter(id=suggestion.id).update(**row_changes)

        after = ingest_one(self.team.id, make_draft(score=9.0, **draft_changes))

        assert (after.subject_id, after.score, after.last_seen_at) == (SUBJECT_ID, 1.0, suggestion.last_seen_at)

    def test_ingest_keeps_one_row_per_fingerprint_and_logs_no_activity(self) -> None:
        draft = make_draft()

        upsert_suggestions(self.team.id, [draft, draft])
        upsert_suggestions(self.team.id, [draft])

        assert WarehouseSuggestion.objects.for_team(self.team.id).count() == 1
        assert not ActivityLog.objects.filter(team_id=self.team.id, scope="WarehouseSuggestion").exists()
