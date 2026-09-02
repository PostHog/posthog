import datetime as dt

import pytest
from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.uuidt import uuid7

from products.replay_vision.backend.queries.session_group_keys import fetch_session_group_keys

_START = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_END = _START + dt.timedelta(minutes=5)


def _event(team, session_id: str, *, at: dt.datetime, **properties) -> None:
    _create_event(
        team=team,
        event="$pageview",
        distinct_id="user-1",
        timestamp=at,
        properties={"$session_id": session_id, **properties},
    )


class TestFetchSessionGroupKeys(ClickhouseTestMixin):
    @pytest.mark.django_db
    def test_returns_only_the_indexes_the_session_carries(self, team) -> None:
        session_id = str(uuid7())
        _event(team, session_id, at=_START, **{"$group_0": "acme-inc", "$group_2": "proj-9"})
        flush_persons_and_events()

        assert fetch_session_group_keys(team=team, session_id=session_id, start=_START, end=_END) == {
            0: "acme-inc",
            2: "proj-9",
        }

    @pytest.mark.django_db
    def test_ignores_events_from_other_sessions(self, team) -> None:
        # The scanner watches one recording; picking up a neighbouring session's org would misattribute the spend.
        session_id = str(uuid7())
        _event(team, session_id, at=_START, **{"$group_0": "acme-inc"})
        _event(team, str(uuid7()), at=_START, **{"$group_0": "other-co"})
        flush_persons_and_events()

        assert fetch_session_group_keys(team=team, session_id=session_id, start=_START, end=_END) == {0: "acme-inc"}

    @pytest.mark.django_db
    def test_finds_keys_on_a_later_event_when_the_first_carries_none(self, team) -> None:
        # Group keys ride on the events that have them, not necessarily the one that opened the session.
        session_id = str(uuid7())
        _event(team, session_id, at=_START)
        _event(team, session_id, at=_START + dt.timedelta(minutes=1), **{"$group_0": "acme-inc"})
        flush_persons_and_events()

        assert fetch_session_group_keys(team=team, session_id=session_id, start=_START, end=_END) == {0: "acme-inc"}

    @pytest.mark.django_db
    def test_takes_the_latest_key_when_one_group_type_carries_two(self, team) -> None:
        # A user switching org mid-session leaves two keys on the same index. The later one is the group the
        # observed activity belongs to; the keys here are ordered so a lexicographic pick would return the earlier.
        session_id = str(uuid7())
        _event(team, session_id, at=_START, **{"$group_0": "zeta-co"})
        _event(team, session_id, at=_START + dt.timedelta(minutes=2), **{"$group_0": "alpha-co"})
        flush_persons_and_events()

        assert fetch_session_group_keys(team=team, session_id=session_id, start=_START, end=_END) == {0: "alpha-co"}

    @pytest.mark.django_db
    def test_returns_empty_for_a_session_with_no_groups(self, team) -> None:
        session_id = str(uuid7())
        _event(team, session_id, at=_START)
        flush_persons_and_events()

        assert fetch_session_group_keys(team=team, session_id=session_id, start=_START, end=_END) == {}
