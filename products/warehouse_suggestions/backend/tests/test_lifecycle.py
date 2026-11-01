from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_suggestions.backend.facade.contracts import (
    CertifyPayload,
    DeprecatePayload,
    MaterializePayload,
    SuggestionDraft,
    SuggestionPayload,
    UnmaterializePayload,
)
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionAssetOutcome,
    WarehouseSuggestionDismissalReason,
    WarehouseSuggestionKind,
    WarehouseSuggestionStatus,
)
from products.warehouse_suggestions.backend.logic.access import can_take
from products.warehouse_suggestions.backend.logic.candidates.base import CandidateContext
from products.warehouse_suggestions.backend.logic.candidates.registry import CANDIDATES
from products.warehouse_suggestions.backend.logic.lifecycle import _pick_in_turns, apply_run
from products.warehouse_suggestions.backend.logic.reads import SubjectReads, SubjectRefreshes
from products.warehouse_suggestions.backend.logic.suggestions import transition_to
from products.warehouse_suggestions.backend.models import WarehouseSuggestion
from products.warehouse_suggestions.backend.tests.factories import busy_reads, context, team_reads, view, view_subject

from .test_accept import REPORT

NOTIFY = "products.warehouse_suggestions.backend.logic.assignment.create_notification"
CAN_TAKE = "products.warehouse_suggestions.backend.logic.assignment.can_take"
NOW = datetime(2026, 10, 7, 9, tzinfo=UTC)
READ_COST_BEFORE = {"read_seconds_per_month": 5000.0, "read_bytes_per_month": 5e12, "human_reads_per_month": 200.0}
REFRESH_COST_BEFORE = {"refresh_seconds_per_month": 5000.0, "refresh_bytes_per_month": 5e12}
READS_NOW = busy_reads(
    human_reads=200,
    human_duration_ms=100_000,
    human_read_bytes=10**9,
    background_duration_ms=50_000,
    background_read_bytes=10**9,
)
REFRESHES_NOW = SubjectRefreshes(runs=30, duration_ms=600_000, read_bytes=10**12)
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
    WarehouseSuggestionKind.UNMATERIALIZE: UnmaterializePayload(
        subject_name="orders",
        refresh_seconds_per_month=3600,
        refresh_bytes_per_month=0,
        live_seconds_per_month=20,
        live_bytes_per_month=0,
        read_seconds=5,
        query_fingerprint="fingerprint",
    ),
}


class TestApplyRun(BaseTest):
    def _context(self, *view_ids: UUID, recent_days_with_data: int = 7) -> CandidateContext:
        return context(
            team_reads({}, recent_days_with_data=recent_days_with_data),
            views=[view(view_id, materializes=True) for view_id in view_ids],
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
                self.team,
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

        apply_run(ctx, self.team, drafts, NOW, surface=True)
        apply_run(ctx, self.team, drafts, NOW + timedelta(hours=1), surface=True)

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
            ctx,
            self.team,
            [self._draft(ctx, WarehouseSuggestionKind.CERTIFY, view_id, dismissed_score)],
            NOW,
            surface=False,
        )
        row = WarehouseSuggestion.objects.for_team(self.team.pk).get()
        transition_to(row.id, self.team.pk, WarehouseSuggestionStatus.DISMISSED, user_id=self.user.id, reason=reason)

        with patch(REPORT) as report:
            with self.captureOnCommitCallbacks() as on_commit:
                apply_run(
                    ctx,
                    self.team,
                    [self._draft(ctx, WarehouseSuggestionKind.CERTIFY, view_id, new_score)],
                    NOW,
                    surface=False,
                )
            reports_before_commit = report.call_count
            for callback in on_commit:
                callback()

        row.refresh_from_db()
        reported_counts = [
            call.args[1]["reproposed_count"]
            for call in report.call_args_list
            if call.args[0] == "warehouse suggestion reproposed"
        ]
        assert (row.status, row.reproposed_count) == (
            (WarehouseSuggestionStatus.PROPOSED, 1) if expect_reproposed else (WarehouseSuggestionStatus.DISMISSED, 0)
        )
        assert (reports_before_commit, reported_counts) == (0, [1] if expect_reproposed else [])

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
        apply_run(ctx, self.team, [self._draft(ctx, WarehouseSuggestionKind.DEPRECATE, view_id, 1)], NOW, surface=False)
        WarehouseSuggestion.objects.for_team(self.team.pk).update(last_seen_at=NOW - timedelta(days=8))

        apply_run(ctx, self.team, [], NOW, surface=False)

        assert WarehouseSuggestion.objects.for_team(self.team.pk).get().status == expected

    @parameterized.expand(
        [
            ("unmaterialized_by_a_suggestion", 60, True, WarehouseSuggestionStatus.PROPOSED, 1),
            ("stopped_by_a_deprecate_or_a_manual_revert", 60, False, WarehouseSuggestionStatus.PROPOSED, 1),
            ("accepted_inside_the_cooldown", 10, False, WarehouseSuggestionStatus.ACCEPTED, 0),
        ]
    )
    def test_an_accepted_materialize_returns_when_drafted_again_after_the_cooldown(
        self,
        _name: str,
        accepted_days_ago: int,
        unmaterialized_by_a_suggestion: bool,
        expected_status: WarehouseSuggestionStatus,
        reproposed: int,
    ) -> None:
        view_id = uuid4()
        ctx = self._context(view_id)
        materialize = self._draft(ctx, WarehouseSuggestionKind.MATERIALIZE, view_id, 1)
        first_run = [materialize]
        if unmaterialized_by_a_suggestion:
            first_run.append(self._draft(ctx, WarehouseSuggestionKind.UNMATERIALIZE, view_id, 1))
        apply_run(ctx, self.team, first_run, NOW - timedelta(days=accepted_days_ago), surface=True)
        suggestions = WarehouseSuggestion.objects.for_team(self.team.pk)
        suggestions.filter(kind=WarehouseSuggestionKind.MATERIALIZE).update(
            status=WarehouseSuggestionStatus.ACCEPTED,
            reviewed_at=NOW - timedelta(days=accepted_days_ago),
            realized_seconds_saved_per_month=1.0,
        )
        suggestions.filter(kind=WarehouseSuggestionKind.UNMATERIALIZE).update(
            status=WarehouseSuggestionStatus.ACCEPTED, reviewed_at=NOW - timedelta(days=40)
        )

        apply_run(ctx, self.team, [materialize], NOW, surface=False)

        row = suggestions.get(kind=WarehouseSuggestionKind.MATERIALIZE)
        assert (row.status, row.reproposed_count, row.realized_seconds_saved_per_month) == (
            expected_status,
            reproposed,
            None,
        )

    @parameterized.expand(
        [("expired", WarehouseSuggestionStatus.EXPIRED), ("auto_resolved", WarehouseSuggestionStatus.AUTO_RESOLVED)]
    )
    def test_a_closed_suggestion_revives_into_the_queue_when_its_evidence_returns(
        self, _name: str, closed_status: WarehouseSuggestionStatus
    ) -> None:
        view_id = uuid4()
        ctx = self._context(view_id)
        draft = self._draft(ctx, WarehouseSuggestionKind.DEPRECATE, view_id, 1)
        apply_run(ctx, self.team, [draft], NOW - timedelta(days=10), surface=True)
        WarehouseSuggestion.objects.for_team(self.team.pk).update(status=closed_status)

        apply_run(ctx, self.team, [draft], NOW, surface=False)

        revived = WarehouseSuggestion.objects.for_team(self.team.pk).get()
        assert (revived.status, revived.surfaced_at) == (WarehouseSuggestionStatus.PROPOSED, None)

    @parameterized.expand(
        [
            ("creator_who_can_edit", "member", WarehouseSuggestionKind.MATERIALIZE, True),
            ("creator_who_left_the_organization", "left", WarehouseSuggestionKind.MATERIALIZE, False),
            ("creator_who_cannot_edit_the_catalog", "catalog_viewer", WarehouseSuggestionKind.CERTIFY, False),
            ("no_creator", "none", WarehouseSuggestionKind.MATERIALIZE, False),
        ]
    )
    def test_assigns_surfaced_view_suggestions_to_a_creator_who_can_accept_them(
        self, _name: str, creator_state: str, kind: WarehouseSuggestionKind, expect_assigned: bool
    ) -> None:
        creator = self._creator(creator_state)
        views = [
            DataWarehouseSavedQuery.objects.create(
                team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1"}, created_by=creator
            )
            for name in ("orders", "refunds")
        ]
        if creator_state == "catalog_viewer":
            self._restrict_catalog_to_viewer()
        ctx = context(
            team_reads({}),
            views=[view(saved_query.id, created_by_id=creator.pk if creator else None) for saved_query in views],
            team_id=self.team.pk,
        )
        drafts = [self._draft(ctx, kind, saved_query.id, 1) for saved_query in views]

        with patch(NOTIFY) as notify, self.captureOnCommitCallbacks(execute=True):
            apply_run(ctx, self.team, drafts, NOW, surface=True)

        assignee_ids = set(WarehouseSuggestion.objects.for_team(self.team.pk).values_list("assignee_id", flat=True))
        notified = [call.args[0].target_id for call in notify.call_args_list]
        expected_assignee = creator.pk if expect_assigned and creator else None
        assert (assignee_ids, notified) == (
            {expected_assignee},
            [str(expected_assignee)] if expect_assigned else [],
        )

    @parameterized.expand([("kept_access_to_the_view", False), ("lost_access_to_the_view", True)])
    def test_a_resurfaced_suggestion_keeps_its_assignee_only_while_they_can_accept_it(
        self, _name: str, access_revoked: bool
    ) -> None:
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", None)
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )
        ctx = context(team_reads({}), views=[view(saved_query.id)], team_id=self.team.pk)
        draft = self._draft(ctx, WarehouseSuggestionKind.MATERIALIZE, saved_query.id, 1)
        apply_run(ctx, self.team, [draft], NOW, surface=False)
        WarehouseSuggestion.objects.for_team(self.team.pk).update(assignee=teammate)
        if access_revoked:
            self._enable_access_control()
            AccessControl.objects.create(
                team=self.team,
                resource="warehouse_view",
                resource_id=str(saved_query.id),
                organization_member=teammate.organization_memberships.get(),
                access_level="none",
            )

        with patch(NOTIFY) as notify, self.captureOnCommitCallbacks(execute=True):
            apply_run(ctx, self.team, [draft], NOW, surface=True)

        row = WarehouseSuggestion.objects.for_team(self.team.pk).get()
        notified = [call.args[0].target_id for call in notify.call_args_list]
        assert (row.surfaced_at is not None, row.assignee_id, notified) == (
            True,
            None if access_revoked else teammate.pk,
            [] if access_revoked else [str(teammate.pk)],
        )

    @parameterized.expand(
        [
            ("accepted_during_the_run", {"status": WarehouseSuggestionStatus.ACCEPTED}, None),
            ("reassigned_during_the_run", {"assignee_id": "teammate"}, "teammate"),
        ]
    )
    def test_the_job_leaves_a_suggestion_someone_changed_while_it_was_assigning(
        self, _name: str, change: dict[str, object], expected_assignee: str | None
    ) -> None:
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", None)
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1"}, created_by=self.user
        )
        ctx = context(team_reads({}), views=[view(saved_query.id, created_by_id=self.user.pk)], team_id=self.team.pk)
        draft = self._draft(ctx, WarehouseSuggestionKind.MATERIALIZE, saved_query.id, 1)
        concurrent_change = {key: teammate.pk if value == "teammate" else value for key, value in change.items()}

        def checked_while_someone_changes_it(team: Team, user: User, suggestion: WarehouseSuggestion) -> bool:
            WarehouseSuggestion.objects.for_team(self.team.pk).update(**concurrent_change)
            return can_take(team, user, suggestion)

        with (
            patch(CAN_TAKE, side_effect=checked_while_someone_changes_it),
            patch(NOTIFY) as notify,
            self.captureOnCommitCallbacks(execute=True),
        ):
            apply_run(ctx, self.team, [draft], NOW, surface=True)

        row = WarehouseSuggestion.objects.for_team(self.team.pk).get()
        assert (row.assignee_id, notify.call_count) == (teammate.pk if expected_assignee else None, 0)

    def _enable_access_control(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])

    def _creator(self, creator_state: str) -> User | None:
        if creator_state == "none":
            return None
        if creator_state == "left":
            return User.objects.create(email="left@example.com", first_name="Left")
        return self.user

    def _restrict_catalog_to_viewer(self) -> None:
        self._enable_access_control()
        AccessControl.objects.create(
            team=self.team,
            resource="data_catalog",
            organization_member=self.organization_membership,
            access_level="viewer",
        )

    def test_auto_resolves_when_the_view_is_gone_or_already_handled(self) -> None:
        deleted_id, materialized_id = uuid4(), uuid4()
        ctx = self._context(deleted_id, materialized_id)
        apply_run(
            ctx,
            self.team,
            [
                self._draft(ctx, WarehouseSuggestionKind.CERTIFY, deleted_id, 1),
                self._draft(ctx, WarehouseSuggestionKind.MATERIALIZE, materialized_id, 1),
            ],
            NOW,
            surface=False,
        )

        apply_run(self._context(materialized_id), self.team, [], NOW, surface=False)

        assert set(WarehouseSuggestion.objects.for_team(self.team.pk).values_list("status", flat=True)) == {
            WarehouseSuggestionStatus.AUTO_RESOLVED
        }

    @parameterized.expand(
        [
            ("read_after_acceptance", True, NOW - timedelta(days=1), WarehouseSuggestionAssetOutcome.LIVE),
            ("read_only_before_acceptance", True, NOW - timedelta(days=3), WarehouseSuggestionAssetOutcome.UNUSED),
            ("never_read", True, None, WarehouseSuggestionAssetOutcome.UNUSED),
            ("materialization_turned_off", False, NOW - timedelta(days=1), WarehouseSuggestionAssetOutcome.DELETED),
        ]
    )
    def test_records_what_became_of_an_accepted_materialization(
        self,
        _name: str,
        materialized: bool,
        last_read_at: datetime | None,
        expected: WarehouseSuggestionAssetOutcome,
    ) -> None:
        view_id = uuid4()
        ctx = self._context(view_id)
        apply_run(
            ctx, self.team, [self._draft(ctx, WarehouseSuggestionKind.MATERIALIZE, view_id, 1)], NOW, surface=False
        )
        WarehouseSuggestion.objects.for_team(self.team.pk).update(
            status=WarehouseSuggestionStatus.ACCEPTED, reviewed_at=NOW - timedelta(days=2)
        )
        later = context(
            team_reads({view_subject(view_id): busy_reads(last_read_at=last_read_at)} if last_read_at else {}),
            views=[view(view_id, materializes=materialized)],
            team_id=self.team.pk,
        )

        apply_run(later, self.team, [], NOW, surface=False)

        assert WarehouseSuggestion.objects.for_team(self.team.pk).get().asset_outcome == expected

    @parameterized.expand(
        [
            (
                "materialize_measured_after_acceptance",
                WarehouseSuggestionKind.MATERIALIZE,
                True,
                timedelta(days=40),
                READ_COST_BEFORE,
                READS_NOW,
                REFRESHES_NOW,
                (4300.0, 5e12 - 1e12 - 10**9),
            ),
            (
                "materialize_priced_at_todays_read_volume",
                WarehouseSuggestionKind.MATERIALIZE,
                True,
                timedelta(days=40),
                READ_COST_BEFORE,
                replace(READS_NOW, human_reads=2000, human_duration_ms=1_000_000, human_read_bytes=10 * 10**9),
                REFRESHES_NOW,
                (48400.0, 50e12 - 1e12 - 10 * 10**9),
            ),
            (
                "materialize_nobody_reads_it",
                WarehouseSuggestionKind.MATERIALIZE,
                True,
                timedelta(days=40),
                READ_COST_BEFORE,
                None,
                REFRESHES_NOW,
                (-600.0, -1e12),
            ),
            (
                "materialize_no_refresh_rows",
                WarehouseSuggestionKind.MATERIALIZE,
                True,
                timedelta(days=40),
                READ_COST_BEFORE,
                READS_NOW,
                None,
                (None, None),
            ),
            (
                "materialize_window_holds_reads_from_before",
                WarehouseSuggestionKind.MATERIALIZE,
                True,
                timedelta(days=2),
                READ_COST_BEFORE,
                READS_NOW,
                REFRESHES_NOW,
                (None, None),
            ),
            (
                "materialize_scored_before_read_cost_was_kept",
                WarehouseSuggestionKind.MATERIALIZE,
                True,
                timedelta(days=40),
                {},
                READS_NOW,
                REFRESHES_NOW,
                (None, None),
            ),
            (
                "unmaterialize_measured_after_acceptance",
                WarehouseSuggestionKind.UNMATERIALIZE,
                False,
                timedelta(days=40),
                REFRESH_COST_BEFORE,
                READS_NOW,
                None,
                (4850.0, 5e12 - 2 * 10**9),
            ),
            (
                "unmaterialize_materialized_again",
                WarehouseSuggestionKind.UNMATERIALIZE,
                True,
                timedelta(days=40),
                REFRESH_COST_BEFORE,
                READS_NOW,
                REFRESHES_NOW,
                (None, None),
            ),
        ]
    )
    def test_records_the_savings_an_accepted_suggestion_realized(
        self,
        _name: str,
        kind: WarehouseSuggestionKind,
        materialized_now: bool,
        accepted_ago: timedelta,
        score_inputs: dict[str, float],
        reads_now: SubjectReads | None,
        refreshes_now: SubjectRefreshes | None,
        expected: tuple[float | None, float | None],
    ) -> None:
        view_id = uuid4()
        ctx = self._context(view_id)
        apply_run(ctx, self.team, [self._draft(ctx, kind, view_id, 1)], NOW, surface=False)
        WarehouseSuggestion.objects.for_team(self.team.pk).update(
            status=WarehouseSuggestionStatus.ACCEPTED, reviewed_at=NOW - accepted_ago, score_inputs=score_inputs
        )
        later = context(
            team_reads(
                {view_subject(view_id): reads_now} if reads_now else {},
                refreshes={view_id: refreshes_now} if refreshes_now else None,
            ),
            views=[view(view_id, materializes=materialized_now)],
            team_id=self.team.pk,
        )

        apply_run(later, self.team, [], NOW, surface=False)

        row = WarehouseSuggestion.objects.for_team(self.team.pk).get()
        assert (row.realized_seconds_saved_per_month, row.realized_bytes_saved_per_month) == expected


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
