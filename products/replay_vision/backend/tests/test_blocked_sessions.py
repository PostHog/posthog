import datetime as dt

import pytest
from posthog.test.base import ClickhouseTestMixin, _create_event
from unittest.mock import patch

from posthog.schema import EventPropertyFilter, PropertyOperator, RecordingsQuery

from posthog.redis import get_client

from products.replay_vision.backend import blocked_sessions
from products.replay_vision.backend.blocked_sessions import (
    _SCAN_LIMIT,
    blocked_subset,
    blocklist_fingerprint,
    refresh_blocked_sessions,
)


def _fingerprint(team, query) -> str:
    fingerprint = blocklist_fingerprint(team, query)
    assert fingerprint is not None
    return fingerprint


def _negative_query(value: str = "internal.example.com") -> RecordingsQuery:
    return RecordingsQuery(
        properties=[EventPropertyFilter(key="$host", value=[value], operator=PropertyOperator.IS_NOT, type="event")]
    )


@pytest.fixture(autouse=True)
def _flush_redis():
    get_client().flushdb()


@pytest.mark.django_db
class TestBlocklistFingerprint:
    def test_none_without_negative_filters(self, team) -> None:
        assert blocklist_fingerprint(team, RecordingsQuery()) is None
        assert (
            blocklist_fingerprint(
                team,
                RecordingsQuery(
                    properties=[
                        EventPropertyFilter(
                            key="$host", value=["a.example.com"], operator=PropertyOperator.EXACT, type="event"
                        )
                    ]
                ),
            )
            is None
        )

    def test_changes_with_negative_filter_value(self, team) -> None:
        assert blocklist_fingerprint(team, _negative_query("a.example.com")) != blocklist_fingerprint(
            team, _negative_query("b.example.com")
        )

    def test_includes_test_account_filters(self, team) -> None:
        query = _negative_query()
        query.filter_test_accounts = True
        without_team_filters = blocklist_fingerprint(team, query)

        team.test_account_filters = [
            {"key": "email", "value": "@example.com", "operator": "not_icontains", "type": "person"}
        ]
        team.save()
        assert blocklist_fingerprint(team, query) != without_team_filters


@pytest.mark.django_db
class TestRefreshBlockedSessions:
    def _refresh(self, team, query, scan_results: list[list[list]]) -> list[bool]:
        outcomes = []
        with patch.object(blocked_sessions, "_execute_candidate_query", side_effect=scan_results) as mock_scan:
            for _ in scan_results:
                outcomes.append(
                    refresh_blocked_sessions(
                        scanner_id="scanner-1",
                        team=team,
                        query=query,
                        fingerprint=_fingerprint(team, query),
                        last_swept_at=dt.datetime.now(dt.UTC),
                    )
                )
        self.scan_calls = mock_scan.call_args_list
        return outcomes

    def test_rebuild_then_delta_and_membership(self, team) -> None:
        outcomes = self._refresh(team, _negative_query(), [[["sess-a"]], [["sess-b"]]])

        assert outcomes == [True, True]
        assert self.scan_calls[0].kwargs["query_type"] == "ReplayVisionBlocklistRebuildQuery"
        assert self.scan_calls[1].kwargs["query_type"] == "ReplayVisionBlocklistDeltaQuery"
        assert blocked_subset("scanner-1", ["sess-a", "sess-b", "sess-c"]) == {"sess-a", "sess-b"}

    def test_fingerprint_change_forces_rebuild(self, team) -> None:
        with patch.object(blocked_sessions, "_execute_candidate_query", return_value=[["sess-a"]]):
            refresh_blocked_sessions(
                scanner_id="scanner-1",
                team=team,
                query=_negative_query("a.example.com"),
                fingerprint=_fingerprint(team, _negative_query("a.example.com")),
                last_swept_at=dt.datetime.now(dt.UTC),
            )
        with patch.object(blocked_sessions, "_execute_candidate_query", return_value=[["sess-b"]]) as mock_scan:
            changed = _negative_query("b.example.com")
            assert refresh_blocked_sessions(
                scanner_id="scanner-1",
                team=team,
                query=changed,
                fingerprint=_fingerprint(team, changed),
                last_swept_at=dt.datetime.now(dt.UTC),
            )
        assert mock_scan.call_args.kwargs["query_type"] == "ReplayVisionBlocklistRebuildQuery"
        # The rebuild replaced the old filter's entries instead of unioning with them.
        assert blocked_subset("scanner-1", ["sess-a", "sess-b"]) == {"sess-b"}

    def test_saturated_scan_marks_overflow_and_stays_legacy(self, team) -> None:
        saturated = [[f"sess-{i}"] for i in range(_SCAN_LIMIT)]
        outcomes = self._refresh(team, _negative_query(), [saturated])
        assert outcomes == [False]

        # Overflowed state short-circuits: no further scans until the fingerprint changes.
        with patch.object(blocked_sessions, "_execute_candidate_query") as mock_scan:
            assert (
                refresh_blocked_sessions(
                    scanner_id="scanner-1",
                    team=team,
                    query=_negative_query(),
                    fingerprint=_fingerprint(team, _negative_query()),
                    last_swept_at=dt.datetime.now(dt.UTC),
                )
                is False
            )
        mock_scan.assert_not_called()

    def test_evicted_set_with_surviving_meta_rebuilds(self, team) -> None:
        # The two keys can be evicted independently on a shared Redis. A fresh watermark over a lost
        # set would report every session unblocked, which is the one failure this store must not have.
        query = _negative_query()
        with patch.object(blocked_sessions, "_execute_candidate_query", return_value=[["sess-a"]]):
            refresh_blocked_sessions(
                scanner_id="scanner-1",
                team=team,
                query=query,
                fingerprint=_fingerprint(team, query),
                last_swept_at=dt.datetime.now(dt.UTC),
            )
        get_client().delete("@posthog/replay-vision/blocked-sessions/scanner-1")

        with patch.object(blocked_sessions, "_execute_candidate_query", return_value=[["sess-a"]]) as mock_scan:
            assert refresh_blocked_sessions(
                scanner_id="scanner-1",
                team=team,
                query=query,
                fingerprint=_fingerprint(team, query),
                last_swept_at=dt.datetime.now(dt.UTC),
            )
        assert mock_scan.call_args.kwargs["query_type"] == "ReplayVisionBlocklistRebuildQuery"
        assert blocked_subset("scanner-1", ["sess-a"]) == {"sess-a"}

    def test_lagged_scanner_keeps_the_in_query_blocklist(self, team) -> None:
        # Its candidates reach back past what the store covers, so a miss would observe a session the
        # filter excludes. Pay the old cost instead.
        query = _negative_query()
        with patch.object(blocked_sessions, "_execute_candidate_query") as mock_scan:
            assert (
                refresh_blocked_sessions(
                    scanner_id="scanner-1",
                    team=team,
                    query=query,
                    fingerprint=_fingerprint(team, query),
                    last_swept_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=12),
                )
                is False
            )
        mock_scan.assert_not_called()

    def test_scan_failure_falls_back_to_legacy(self, team) -> None:
        with patch.object(blocked_sessions, "_execute_candidate_query", side_effect=RuntimeError("clickhouse down")):
            assert (
                refresh_blocked_sessions(
                    scanner_id="scanner-1",
                    team=team,
                    query=_negative_query(),
                    fingerprint=_fingerprint(team, _negative_query()),
                    last_swept_at=dt.datetime.now(dt.UTC),
                )
                is False
            )


class TestBlockedSessionsAgainstClickHouse(ClickhouseTestMixin):
    @pytest.mark.django_db
    def test_delta_catches_late_arriving_event_with_old_timestamp(self, team) -> None:
        query = _negative_query()
        fingerprint = _fingerprint(team, query)

        assert refresh_blocked_sessions(
            scanner_id="scanner-1",
            team=team,
            query=query,
            fingerprint=fingerprint,
            last_swept_at=dt.datetime.now(dt.UTC),
        )
        assert blocked_subset("scanner-1", ["late-sess"]) == set()

        # Arrives now (fresh inserted_at) but carries a timestamp from well before the delta
        # watermark, so a timestamp-based scan would miss it; only an arrival-time scan catches it.
        _create_event(
            team=team,
            event="$pageview",
            distinct_id="d1",
            timestamp=dt.datetime.now(dt.UTC) - dt.timedelta(hours=30),
            properties={"$session_id": "late-sess", "$host": "internal.example.com"},
        )

        assert refresh_blocked_sessions(
            scanner_id="scanner-1",
            team=team,
            query=query,
            fingerprint=fingerprint,
            last_swept_at=dt.datetime.now(dt.UTC),
        )
        assert blocked_subset("scanner-1", ["late-sess"]) == {"late-sess"}
