import datetime as dt

import pytest
from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.models.group.util import create_group
from posthog.uuidt import uuid7

from products.replay_vision.backend.queries.session_group_keys import (
    fetch_group_display_names,
    fetch_session_group_keys,
)

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


class TestFetchGroupDisplayNames(ClickhouseTestMixin):
    @pytest.mark.django_db
    def test_returns_the_name_property_per_group_type_index(self, team) -> None:
        create_group(team_id=team.pk, group_type_index=0, group_key="acme-inc", properties={"name": "Acme Inc"})
        create_group(team_id=team.pk, group_type_index=2, group_key="proj-9", properties={"name": "Project Nine"})

        names = fetch_group_display_names(team=team, group_keys={0: "acme-inc", 2: "proj-9"})

        assert names == {0: "Acme Inc", 2: "Project Nine"}

    @pytest.mark.django_db
    def test_skips_groups_with_no_usable_name(self, team) -> None:
        # A group key is customer-chosen and often a UUID, so a group without a `name` has nothing worth
        # showing — better omitted than rendered as an opaque id the model might repeat as a company.
        create_group(team_id=team.pk, group_type_index=0, group_key="acme-inc", properties={"name": "Acme Inc"})
        create_group(team_id=team.pk, group_type_index=1, group_key="no-name", properties={"plan": "paid"})
        create_group(team_id=team.pk, group_type_index=2, group_key="blank", properties={"name": "   "})

        names = fetch_group_display_names(team=team, group_keys={0: "acme-inc", 1: "no-name", 2: "blank"})

        assert names == {0: "Acme Inc"}

    @pytest.mark.django_db
    def test_ignores_a_matching_key_on_a_different_group_type(self, team) -> None:
        # Keys are only unique within a group type; matching on key alone would cross-label the session's org.
        create_group(team_id=team.pk, group_type_index=1, group_key="acme-inc", properties={"name": "Acme Projects"})

        assert fetch_group_display_names(team=team, group_keys={0: "acme-inc"}) == {}

    @pytest.mark.django_db
    def test_returns_empty_without_group_keys(self, team) -> None:
        assert fetch_group_display_names(team=team, group_keys={}) == {}
