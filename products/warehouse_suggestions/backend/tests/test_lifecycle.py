from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_suggestions.backend.facade.contracts import (
    CertifyPayload,
    DeprecatePayload,
    MaterializePayload,
    SuggestionDraft,
    SuggestionPayload,
)
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionDismissalReason,
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
)
from products.warehouse_suggestions.backend.logic.candidates.base import CandidateContext
from products.warehouse_suggestions.backend.logic.candidates.registry import CANDIDATES
from products.warehouse_suggestions.backend.logic.lifecycle import _pick_in_turns, apply_run
from products.warehouse_suggestions.backend.logic.suggestions import transition_to
from products.warehouse_suggestions.backend.models import WarehouseSuggestion
from products.warehouse_suggestions.backend.tests.factories import context, team_reads, view, view_subject

NOW = datetime(2026, 10, 7, 9, tzinfo=UTC)
PAYLOADS: dict[WarehouseSuggestionKind, SuggestionPayload] = {
    WarehouseSuggestionKind.CERTIFY: CertifyPayload(subject_name="orders"),
    WarehouseSuggestionKind.DEPRECATE: DeprecatePayload(
        subject_name="orders", refresh_seconds_per_month=0, refresh_bytes_per_month=0
    ),
    WarehouseSuggestionKind.MATERIALIZE: MaterializePayload(
        subject_name="orders",
        refresh_interval_seconds=86400,
        saves_seconds_per_month=900,
        saves_bytes_per_month=0,
        freshness_today_seconds=None,
        freshness_after_seconds=86400,
        live_sources=(),
        unknown_sources=(),
    ),
}


class TestApplyRun(BaseTest):
    def _context(self, *view_ids: UUID, recent_days_with_data: int = 7) -> CandidateContext:
        return context(
            team_reads({}, recent_days_with_data=recent_days_with_data),
            views=[view(view_id, is_materialized=True) for view_id in view_ids],
            team_id=self.team.pk,
        )

    def _draft(
        self, ctx: CandidateContext, kind: WarehouseSuggestionKind, view_id: UUID, score: float
    ) -> SuggestionDraft:
        return CANDIDATES[kind].draft(ctx, view_subject(view_id), PAYLOADS[kind], score=score, score_inputs={})

    def _surfaced_kinds(self) -> Counter[str]:
        return Counter(
            WarehouseSuggestion.objects.for_team(self.team.pk)
            .filter(surfaced_at__isnull=False)
            .values_list("kind", flat=True)
        )

    @parameterized.expand(
        [
            ("first_week_puts_certify_first", False, {"certify": 3, "materialize": 2}),
            ("later_weeks_put_materialize_first_despite_a_lower_score", True, {"materialize": 3, "certify": 2}),
        ]
    )
    def test_surfaces_five_a_day_at_most_three_per_kind(
        self, _name: str, surfaced_before: bool, expected: dict[str, int]
    ) -> None:
        if surfaced_before:
            old_id = uuid4()
            apply_run(
                self._context(old_id),
                [self._draft(self._context(old_id), WarehouseSuggestionKind.DEPRECATE, old_id, 1)],
                NOW - timedelta(days=10),
                surface=True,
            )
            WarehouseSuggestion.objects.for_team(self.team.pk).update(status=WarehouseSuggestionStatus.ACCEPTED)
        view_ids = [uuid4() for _ in range(8)]
        ctx = self._context(*view_ids)
        drafts = [
            *(self._draft(ctx, WarehouseSuggestionKind.CERTIFY, view_id, 1000) for view_id in view_ids[:4]),
            *(self._draft(ctx, WarehouseSuggestionKind.MATERIALIZE, view_id, 1) for view_id in view_ids[4:]),
        ]

        apply_run(ctx, drafts, NOW, surface=True)
        apply_run(ctx, drafts, NOW + timedelta(hours=1), surface=True)

        surfaced = self._surfaced_kinds()
        if surfaced_before:
            surfaced.pop(WarehouseSuggestionKind.DEPRECATE)
        assert surfaced == expected

    @parameterized.expand(
        [
            ("not_now_below_three_times", WarehouseSuggestionDismissalReason.NOT_NOW, 10.0, 29.0, False),
            ("not_now_at_three_times", WarehouseSuggestionDismissalReason.NOT_NOW, 10.0, 30.0, True),
            ("not_now_zero_stays_zero", WarehouseSuggestionDismissalReason.NOT_NOW, 0.0, 0.0, False),
            ("not_useful_never_returns", WarehouseSuggestionDismissalReason.NOT_USEFUL, 10.0, 1000.0, False),
        ]
    )
    def test_reproposes_a_dismissal_only_when_the_score_triples_after_not_now(
        self,
        _name: str,
        reason: WarehouseSuggestionDismissalReason,
        dismissed_score: float,
        new_score: float,
        expect_reproposed: bool,
    ) -> None:
        view_id = uuid4()
        ctx = self._context(view_id)
        apply_run(
            ctx, [self._draft(ctx, WarehouseSuggestionKind.CERTIFY, view_id, dismissed_score)], NOW, surface=False
        )
        row = WarehouseSuggestion.objects.for_team(self.team.pk).get()
        transition_to(row.id, self.team.pk, WarehouseSuggestionStatus.DISMISSED, user_id=self.user.id, reason=reason)

        apply_run(ctx, [self._draft(ctx, WarehouseSuggestionKind.CERTIFY, view_id, new_score)], NOW, surface=False)

        row.refresh_from_db()
        assert (row.status, row.reproposed_count) == (
            (WarehouseSuggestionStatus.PROPOSED, 1) if expect_reproposed else (WarehouseSuggestionStatus.DISMISSED, 0)
        )

    @parameterized.expand(
        [
            ("seven_days_unseen_with_data", 7, WarehouseSuggestionStatus.EXPIRED),
            ("a_missing_day_does_not_count", 6, WarehouseSuggestionStatus.PROPOSED),
        ]
    )
    def test_expires_after_seven_days_without_evidence(
        self, _name: str, recent_days_with_data: int, expected: WarehouseSuggestionStatus
    ) -> None:
        view_id = uuid4()
        ctx = self._context(view_id, recent_days_with_data=recent_days_with_data)
        apply_run(ctx, [self._draft(ctx, WarehouseSuggestionKind.DEPRECATE, view_id, 1)], NOW, surface=False)
        WarehouseSuggestion.objects.for_team(self.team.pk).update(last_seen_at=NOW - timedelta(days=8))

        apply_run(ctx, [], NOW, surface=False)

        assert WarehouseSuggestion.objects.for_team(self.team.pk).get().status == expected

    @parameterized.expand(
        [("expired", WarehouseSuggestionStatus.EXPIRED), ("auto_resolved", WarehouseSuggestionStatus.AUTO_RESOLVED)]
    )
    def test_a_closed_suggestion_revives_into_the_queue_when_its_evidence_returns(
        self, _name: str, closed_status: WarehouseSuggestionStatus
    ) -> None:
        view_id = uuid4()
        ctx = self._context(view_id)
        draft = self._draft(ctx, WarehouseSuggestionKind.DEPRECATE, view_id, 1)
        apply_run(ctx, [draft], NOW - timedelta(days=10), surface=True)
        WarehouseSuggestion.objects.for_team(self.team.pk).update(status=closed_status)

        apply_run(ctx, [draft], NOW, surface=False)

        revived = WarehouseSuggestion.objects.for_team(self.team.pk).get()
        assert (revived.status, revived.surfaced_at) == (WarehouseSuggestionStatus.PROPOSED, None)

    def test_auto_resolves_when_the_view_is_gone_or_already_handled(self) -> None:
        deleted_id, materialized_id = uuid4(), uuid4()
        ctx = self._context(deleted_id, materialized_id)
        apply_run(
            ctx,
            [
                self._draft(ctx, WarehouseSuggestionKind.CERTIFY, deleted_id, 1),
                self._draft(ctx, WarehouseSuggestionKind.MATERIALIZE, materialized_id, 1),
            ],
            NOW,
            surface=False,
        )

        apply_run(self._context(materialized_id), [], NOW, surface=False)

        assert set(WarehouseSuggestion.objects.for_team(self.team.pk).values_list("status", flat=True)) == {
            WarehouseSuggestionStatus.AUTO_RESOLVED
        }


CERTIFY = WarehouseSuggestionKind.CERTIFY
DEPRECATE = WarehouseSuggestionKind.DEPRECATE
MATERIALIZE = WarehouseSuggestionKind.MATERIALIZE
WAITING = [
    WarehouseSuggestion(id=UUID(int=1), kind=CERTIFY, score=5.0),
    WarehouseSuggestion(id=UUID(int=2), kind=CERTIFY, score=900.0),
    WarehouseSuggestion(id=UUID(int=3), kind=DEPRECATE, score=1.0),
    WarehouseSuggestion(id=UUID(int=4), kind=MATERIALIZE, score=2.0),
    WarehouseSuggestion(id=UUID(int=5), kind=MATERIALIZE, score=3.0),
]


class TestPickInTurns(SimpleTestCase):
    @parameterized.expand(
        [
            ("one_of_each_kind_per_turn_best_score_first", 5, {}, [5, 3, 2, 4, 1]),
            ("a_kind_at_its_cap_is_skipped", 5, {MATERIALIZE: 3}, [3, 2, 1]),
            ("slots_run_out_mid_turn", 2, {}, [5, 3]),
        ]
    )
    def test_picks_kinds_in_order_and_rows_by_score_within_a_kind(
        self, _name: str, slots: int, already_open: dict[str, int], expected_ids: list[int]
    ) -> None:
        chosen = _pick_in_turns(WAITING, (MATERIALIZE, DEPRECATE, CERTIFY), slots, Counter(already_open), 3)

        assert chosen == [UUID(int=row_id) for row_id in expected_ids]
