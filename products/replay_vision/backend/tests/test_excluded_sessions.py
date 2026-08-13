import datetime as dt

import pytest
from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event

from posthog.schema import EventPropertyFilter, FilterLogicalOperator, PropertyOperator, RecordingsQuery

from products.replay_vision.backend.queries.excluded_sessions import excluded_session_ids, has_negative_filters
from products.replay_vision.backend.queries.scanner_candidate_query import CandidateSession

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_FROZEN_TIME = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def _not_host(value: str = "internal.example.com") -> RecordingsQuery:
    return RecordingsQuery(
        properties=[EventPropertyFilter(key="$host", value=[value], operator=PropertyOperator.IS_NOT, type="event")]
    )


def _candidates(*session_ids: str) -> list[CandidateSession]:
    return [CandidateSession(session_id=s, session_end=_NOW - dt.timedelta(hours=1)) for s in session_ids]


def _event(team, session_id: str, host: str, at: dt.datetime) -> None:
    _create_event(
        team=team,
        event="$pageview",
        distinct_id="d1",
        timestamp=at,
        properties={"$session_id": session_id, "$host": host},
    )


@freeze_time(_FROZEN_TIME)
class TestExcludedSessionsAgainstClickHouse(ClickhouseTestMixin):
    @pytest.mark.django_db
    def test_excludes_only_the_sessions_carrying_a_disqualifying_event(self, team) -> None:
        _event(team, "dirty", "internal.example.com", _NOW - dt.timedelta(hours=2))
        _event(team, "clean", "app.example.com", _NOW - dt.timedelta(hours=2))
        # Blocked, but not in this batch: the answer must be scoped to what was asked about.
        _event(team, "dirty-elsewhere", "internal.example.com", _NOW - dt.timedelta(hours=2))

        excluded = excluded_session_ids(team=team, query=_not_host(), candidates=_candidates("dirty", "clean"))

        assert excluded == {"dirty"}

    @pytest.mark.django_db
    def test_future_dated_disqualifying_event_still_excludes(self, team) -> None:
        # The sender picks the timestamp, so capping the scan at now() would let this session through.
        _event(team, "future", "internal.example.com", _NOW + dt.timedelta(hours=2))

        assert excluded_session_ids(team=team, query=_not_host(), candidates=_candidates("future")) == {"future"}

    @pytest.mark.django_db
    def test_team_test_account_filters_exclude(self, team) -> None:
        # These are team config AND'd on top of the scanner's own filters, so they come from a
        # separate builder and would silently stop applying if that were dropped.
        team.test_account_filters = [
            {"key": "$host", "value": ["staging.example.com"], "operator": "is_not", "type": "event"}
        ]
        team.save()
        query = _not_host()
        query.filter_test_accounts = True
        _event(team, "staging", "staging.example.com", _NOW - dt.timedelta(hours=2))
        _event(team, "clean", "app.example.com", _NOW - dt.timedelta(hours=2))

        excluded = excluded_session_ids(team=team, query=query, candidates=_candidates("staging", "clean"))

        assert excluded == {"staging"}


@pytest.mark.django_db
class TestHasNegativeFilters:
    def test_positive_only_query_needs_no_exclusion(self, team) -> None:
        query = RecordingsQuery(
            properties=[
                EventPropertyFilter(
                    key="$host", value=["app.example.com"], operator=PropertyOperator.EXACT, type="event"
                )
            ]
        )
        assert has_negative_filters(team, query) is False

    def test_negative_filter_needs_exclusion(self, team) -> None:
        assert has_negative_filters(team, _not_host()) is True

    def test_or_operand_needs_no_exclusion(self, team) -> None:
        # Under OR the in-query blocklist does not apply either, so the sweep must not turn it off
        # and then skip its own check as well.
        query = _not_host()
        query.operand = FilterLogicalOperator.OR_
        assert has_negative_filters(team, query) is False

    def test_test_account_filters_alone_need_exclusion(self, team) -> None:
        team.test_account_filters = [
            {"key": "$host", "value": ["staging.example.com"], "operator": "is_not", "type": "event"}
        ]
        team.save()
        query = RecordingsQuery(filter_test_accounts=True)
        assert has_negative_filters(team, query) is True
