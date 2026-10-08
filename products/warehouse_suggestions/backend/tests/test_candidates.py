from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_suggestions.backend.facade.contracts import CertifyPayload
from products.warehouse_suggestions.backend.logic.candidates.certify import CertifyCandidate
from products.warehouse_suggestions.backend.logic.candidates.deprecate import DeprecateCandidate
from products.warehouse_suggestions.backend.logic.candidates.materialize import (
    MaterializeCandidate,
    allowed_intervals,
    estimate_savings,
)
from products.warehouse_suggestions.backend.logic.rules import RULES, Surface
from products.warehouse_suggestions.backend.tests.factories import (
    busy_reads,
    context,
    table_subject,
    team_reads,
    view,
    view_subject,
)

VIEW_ID = uuid4()
AT_CERTIFY_FLOORS = {"human_users": 5, "human_days": 20}
HOUR = timedelta(hours=1)
DAY = timedelta(hours=24)


class TestCertifyCandidate(SimpleTestCase):
    @parameterized.expand(
        [
            ("at_every_floor", {}, 30, False, True),
            ("one_person_short", {"human_users": 4}, 30, False, False),
            ("one_day_short", {"human_days": 19}, 30, False, False),
            ("one_surface", {"requests_by_surface": {Surface.SQL_EDITOR: 200}}, 30, False, False),
            (
                "unknown_surface_does_not_count",
                {"requests_by_surface": {Surface.SQL_EDITOR: 100, Surface.UNKNOWN: 100}},
                30,
                False,
                False,
            ),
            ("day_floor_scales_while_warming_up", {"human_days": 10}, 15, False, True),
            ("already_certified", {}, 30, True, False),
        ]
    )
    def test_floors(
        self, _name: str, overrides: dict, days_with_data: int, certified: bool, expect_draft: bool
    ) -> None:
        subject = view_subject(VIEW_ID)
        reads = team_reads({subject: busy_reads(**{**AT_CERTIFY_FLOORS, **overrides})}, days_with_data=days_with_data)

        result = CertifyCandidate().evaluate(
            context(reads, views=[view(VIEW_ID)], certified=frozenset({subject}) if certified else frozenset())
        )

        assert [draft.subject_id for draft in result.drafts] == ([VIEW_ID] if expect_draft else [])

    @parameterized.expand(
        [
            ("two_person_team_read_by_both", 2, 2, True),
            ("solo_team", 1, 1, False),
            ("small_team_read_by_half", 6, 3, True),
            ("small_team_read_by_fewer_than_half", 6, 2, False),
            ("large_team_caps_at_five", 100, 5, True),
        ]
    )
    def test_people_floor_follows_team_size(
        self, _name: str, team_readers: int, human_users: int, expect_draft: bool
    ) -> None:
        reads = team_reads(
            {view_subject(VIEW_ID): busy_reads(**{**AT_CERTIFY_FLOORS, "human_users": human_users})},
            readers=team_readers,
        )

        result = CertifyCandidate().evaluate(context(reads, views=[view(VIEW_ID)]))

        assert [draft.subject_id for draft in result.drafts] == ([VIEW_ID] if expect_draft else [])

    def test_only_the_top_share_by_requests_times_people_is_proposed(self) -> None:
        views = [view(uuid4(), name=f"view_{position}") for position in range(10)]
        reads = team_reads(
            {view_subject(v.id): busy_reads(human_requests=100 + position) for position, v in enumerate(views)}
        )

        result = CertifyCandidate().evaluate(context(reads, views=views))

        assert [draft.subject_id for draft in result.drafts] == [views[-1].id]

    def test_proposes_warehouse_tables_but_not_backing_tables_of_materialized_views(self) -> None:
        table_id, backing_table_id = uuid4(), uuid4()
        reads = team_reads({table_subject(table_id): busy_reads(), table_subject(backing_table_id): busy_reads()})

        result = CertifyCandidate().evaluate(context(reads, table_names={table_id: "stripe_charges"}))

        assert [(draft.subject_id, draft.payload) for draft in result.drafts] == [
            (table_id, CertifyPayload(subject_name="stripe_charges"))
        ]


class TestMaterializeRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("read_most_days", 25, [HOUR, timedelta(hours=6), DAY]),
            ("read_on_few_days", 10, [DAY]),
        ]
    )
    def test_read_cadence_sets_the_shortest_interval(self, _name: str, human_days: int, expected: list) -> None:
        reads = busy_reads(human_days=human_days)

        intervals = allowed_intervals(
            context(team_reads({})), [HOUR, timedelta(hours=6), DAY, timedelta(days=7)], reads
        )

        assert intervals == expected

    @parameterized.expand([("at_floor", 90, True), ("one_read_short", 89, False)])
    def test_time_saved_floor(self, _name: str, human_reads: int, expect_clear: bool) -> None:
        reads = busy_reads(
            human_reads=human_reads,
            human_duration_ms=human_reads * 10_000,
            alone_duration_ms_median=10_000.0,
            human_read_bytes=human_reads,
            alone_read_bytes_median=1.0,
        )

        estimate = estimate_savings(context(team_reads({})), reads, DAY)

        assert estimate.clears_a_floor is expect_clear

    def test_a_view_that_cannot_refresh_incrementally_is_not_proposed(self) -> None:
        reads = team_reads({view_subject(VIEW_ID): busy_reads()})
        not_incremental = view(VIEW_ID, hogql="SELECT timestamp, event FROM events ORDER BY timestamp DESC LIMIT 10")

        result = MaterializeCandidate().evaluate(context(reads, views=[not_incremental]))

        assert result.drafts == ()
        assert [rejection.reason for rejection in result.rejections] == ["its query cannot refresh incrementally"]


class TestDeprecateCandidate(SimpleTestCase):
    def test_waits_for_a_full_window_of_read_data(self) -> None:
        materialized = view(VIEW_ID, materializes=True)

        result = DeprecateCandidate().evaluate(context(team_reads({}, days_with_data=29), views=[materialized]))

        assert (result.drafts, result.skipped_reason) == ((), "needs 30 days of read data, has 29")


class TestDeprecateBackgroundReads(BaseTest):
    @parameterized.expand([("background_reads_count", True, []), ("only_people_count", False, [VIEW_ID])])
    def test_a_view_read_only_by_background_traffic(
        self, _name: str, counts_background_reads: bool, expected_subjects: list
    ) -> None:
        rules = replace(RULES, deprecate=replace(RULES.deprecate, counts_background_reads=counts_background_reads))
        reads = team_reads(
            {view_subject(VIEW_ID): busy_reads(human_requests=0, human_users=0, human_days=0, background_requests=40)}
        )
        candidate_context = context(reads, views=[view(VIEW_ID, materializes=True)], team_id=self.team.pk, rules=rules)

        result = DeprecateCandidate().evaluate(candidate_context)

        assert [draft.subject_id for draft in result.drafts] == expected_subjects
