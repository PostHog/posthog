import datetime as dt

import pytest
from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event

from posthog.schema import EventPropertyFilter, FilterLogicalOperator, PropertyOperator, RecordingsQuery

from products.replay_vision.backend.models.replay_scanner import SamplingMode
from products.replay_vision.backend.queries.excluded_sessions import excluded_session_ids
from products.replay_vision.backend.queries.scanner_candidate_query import (
    EXCLUDED_SESSIONS_QUERY_TYPE,
    CandidateSession,
    ScannerCandidateQuery,
)

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_FROZEN_TIME = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def _not_host(value: str = "internal.example.com") -> RecordingsQuery:
    return RecordingsQuery(
        properties=[EventPropertyFilter(key="$host", value=[value], operator=PropertyOperator.IS_NOT, type="event")]
    )


def _query_for(team, query: RecordingsQuery, *, last_swept_at: dt.datetime | None = None) -> ScannerCandidateQuery:
    return ScannerCandidateQuery(
        team=team,
        query=query,
        last_swept_at=last_swept_at or (_NOW - dt.timedelta(minutes=5)),
        sampling_rate=1.0,
        sampling_salt="salt",
        sampling_mode=SamplingMode.BALANCED,
    )


def _candidates(*session_ids: str) -> list[CandidateSession]:
    return [CandidateSession(session_id=s, session_end=_NOW - dt.timedelta(hours=1)) for s in session_ids]


def _event(team, session_id: str, at: dt.datetime, **props) -> None:
    _create_event(
        team=team,
        event="$pageview",
        distinct_id="d1",
        timestamp=at,
        properties={"$session_id": session_id, **props},
    )


@freeze_time(_FROZEN_TIME)
class TestExcludedSessions(ClickhouseTestMixin):
    @pytest.mark.django_db
    def test_excludes_only_the_sessions_carrying_a_disqualifying_event(self, team) -> None:
        _event(team, "dirty", _NOW - dt.timedelta(hours=2), **{"$host": "internal.example.com"})
        _event(team, "clean", _NOW - dt.timedelta(hours=2), **{"$host": "app.example.com"})
        # Blocked, but not in this batch: the answer must be scoped to what was asked about.
        _event(team, "elsewhere", _NOW - dt.timedelta(hours=2), **{"$host": "internal.example.com"})

        excluded = excluded_session_ids(
            query_type=EXCLUDED_SESSIONS_QUERY_TYPE,
            team=team,
            candidate_query=_query_for(team, _not_host()),
            candidates=_candidates("dirty", "clean"),
        )

        assert excluded == {"dirty"}

    @pytest.mark.django_db
    def test_excludes_when_the_watermark_lags_behind_the_default_window(self, team) -> None:
        # The scanner's stored query carries no dates, so an exclusion rebuilt from it would scan a
        # window anchored to now and miss a backlog entirely, dispatching it unfiltered.
        lagged = _NOW - dt.timedelta(days=10)
        _event(team, "old-dirty", lagged - dt.timedelta(hours=1), **{"$host": "internal.example.com"})

        excluded = excluded_session_ids(
            query_type=EXCLUDED_SESSIONS_QUERY_TYPE,
            team=team,
            candidate_query=_query_for(team, _not_host(), last_swept_at=lagged),
            candidates=_candidates("old-dirty"),
        )

        assert excluded == {"old-dirty"}

    @pytest.mark.django_db
    def test_library_filters_do_not_exclude(self, team) -> None:
        # $lib is routed to a snapshot_library predicate before the events builder sees it, so
        # treating it as an event filter here would drop sessions the recordings list keeps.
        query = RecordingsQuery(
            properties=[EventPropertyFilter(key="$lib", value=["web"], operator=PropertyOperator.IS_NOT, type="event")]
        )
        _event(team, "web-session", _NOW - dt.timedelta(hours=2), **{"$lib": "web"})

        excluded = excluded_session_ids(
            query_type=EXCLUDED_SESSIONS_QUERY_TYPE,
            team=team,
            candidate_query=_query_for(team, query),
            candidates=_candidates("web-session"),
        )

        assert excluded == set()

    @pytest.mark.django_db
    def test_future_dated_disqualifying_event_still_excludes(self, team) -> None:
        # The sender picks the timestamp, so capping the scan at now() would let this session through.
        _event(team, "future", _NOW + dt.timedelta(hours=2), **{"$host": "internal.example.com"})

        assert excluded_session_ids(
            query_type=EXCLUDED_SESSIONS_QUERY_TYPE,
            team=team,
            candidate_query=_query_for(team, _not_host()),
            candidates=_candidates("future"),
        ) == {"future"}

    @pytest.mark.django_db
    def test_team_test_account_filters_exclude(self, team) -> None:
        # Team config AND'd on top of the scanner's own filters, from a separate builder that would
        # silently stop applying if it were dropped.
        team.test_account_filters = [
            {"key": "$host", "value": ["staging.example.com"], "operator": "is_not", "type": "event"}
        ]
        team.save()
        query = _not_host()
        query.filter_test_accounts = True
        _event(team, "staging", _NOW - dt.timedelta(hours=2), **{"$host": "staging.example.com"})
        _event(team, "clean", _NOW - dt.timedelta(hours=2), **{"$host": "app.example.com"})

        excluded = excluded_session_ids(
            query_type=EXCLUDED_SESSIONS_QUERY_TYPE,
            team=team,
            candidate_query=_query_for(team, query),
            candidates=_candidates("staging", "clean"),
        )

        assert excluded == {"staging"}

    # pytest's own parametrize, not parameterized.expand, which does not compose with fixtures.
    @pytest.mark.parametrize(
        "operator,operand,expected",
        [
            (PropertyOperator.EXACT, FilterLogicalOperator.AND_, False),
            (PropertyOperator.IS_NOT, FilterLogicalOperator.AND_, True),
            # Under OR the in-query blocklist does not apply either, so neither must this.
            (PropertyOperator.IS_NOT, FilterLogicalOperator.OR_, False),
        ],
    )
    @pytest.mark.django_db
    def test_only_negative_and_operand_queries_produce_an_exclusion(
        self, operator: PropertyOperator, operand: FilterLogicalOperator, expected: bool, team
    ) -> None:
        # Turning the in-query blocklist off is unconditional, so this decides what replaces it.
        query = RecordingsQuery(
            properties=[EventPropertyFilter(key="$host", value=["x.example.com"], operator=operator, type="event")],
            operand=operand,
        )

        assert bool(_query_for(team, query).excluded_sessions_queries(["s1"])) is expected

    @pytest.mark.django_db
    def test_no_candidates_asks_nothing(self, team) -> None:
        # Where the saving comes from: most ticks have no candidates and must issue no query.
        assert (
            excluded_session_ids(
                query_type=EXCLUDED_SESSIONS_QUERY_TYPE,
                team=team,
                candidate_query=_query_for(team, _not_host()),
                candidates=[],
            )
            == set()
        )
