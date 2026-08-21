import datetime as dt

import pytest

from parameterized import parameterized

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_scanner import SETTLE_INTERVAL
from products.replay_vision.backend.queries.scanner_candidate_query import (
    CandidateSession,
    ScannerCandidateQuery,
    build_candidate_batch,
    session_in_predicates,
)

_T0 = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)


def _sessions(count: int, prefix: str = "s") -> list[CandidateSession]:
    return [
        CandidateSession(session_id=f"{prefix}-{i}", session_end=_T0 + dt.timedelta(seconds=i)) for i in range(count)
    ]


class TestBuildCandidateBatch:
    @parameterized.expand(
        [
            # Fewer matches than room to dispatch: the walk covered every candidate, so it may move
            # past the ones that did not match. Stopping at the last match would re-walk them forever.
            ("all_matches_fit", 10, 3, 20, 100, 3, "s-9", False),
            # More matches than room: everything past the last dispatched one is unexamined ground.
            # Advancing to the last candidate here would drop matched sessions permanently.
            ("more_matches_than_room", 50, 40, 10, 100, 10, "m-9", True),
            # Candidate scan hit its own cap, so more sessions wait past the keyset.
            ("candidate_scan_saturated", 100, 2, 20, 100, 2, "s-99", True),
            ("nothing_matched", 10, 0, 20, 100, 0, "s-9", False),
        ]
    )
    def test_keyset_stops_where_the_tick_stopped(
        self,
        _name: str,
        considered_count: int,
        matched_count: int,
        dispatch_limit: int,
        scan_limit: int,
        expected_dispatched: int,
        expected_keyset_id: str,
        expected_saturated: bool,
    ) -> None:
        considered = _sessions(considered_count, "s")
        matched = _sessions(matched_count, "m")

        batch = build_candidate_batch(considered, matched, dispatch_limit, scan_limit)

        assert len(batch.matched) == expected_dispatched
        assert batch.keyset_session_id == expected_keyset_id
        assert batch.saturated is expected_saturated

    def test_no_candidates_leaves_the_watermark_alone(self) -> None:
        batch = build_candidate_batch([], [], 20, 100)

        assert batch.keyset_end is None
        assert batch.keyset_session_id == ""


@pytest.mark.django_db
class TestSessionInPredicates:
    def _query(self, *, filter_test_accounts: bool, with_event_filter: bool) -> ScannerCandidateQuery:
        org = Organization.objects.create(name="predicate-test-org")
        team = Team.objects.create(
            organization=org,
            name="predicate-test-team",
            test_account_filters=[
                {"key": "$host", "type": "event", "value": "app.example.com", "operator": "icontains"}
            ],
        )
        query: dict = {"kind": "RecordingsQuery", "filter_test_accounts": filter_test_accounts}
        if with_event_filter:
            query["properties"] = [{"key": "plan", "type": "event", "value": "pro", "operator": "exact"}]
        from posthog.schema import RecordingsQuery  # noqa: PLC0415

        return ScannerCandidateQuery(
            team=team,
            query=RecordingsQuery.model_validate(query),
            last_swept_at=dt.datetime.now(dt.UTC) - SETTLE_INTERVAL - dt.timedelta(minutes=10),
            sampling_rate=1.0,
            sampling_salt="salt",
            events_lookback=dt.timedelta(hours=4),
            skip_negative_blocklists=True,
        )

    def test_finds_the_test_account_subquery_as_well_as_the_scanners_own(self) -> None:
        # Test-account filters compile to a second events subquery. Restricting only the first leaves
        # the other scanning the whole events window, which silently costs the entire saving.
        predicates = session_in_predicates(self._query(filter_test_accounts=True, with_event_filter=True).get_query())

        assert len(predicates) == 2

    def test_a_scanner_without_event_filters_has_nothing_to_correlate(self) -> None:
        predicates = session_in_predicates(self._query(filter_test_accounts=False, with_event_filter=False).get_query())

        assert predicates == []
