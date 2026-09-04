import datetime as dt

import pytest
from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.models import Team

from products.actions.backend.models.action import Action
from products.replay_vision.backend.queries.action_volume import recent_action_sessions

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_FROZEN_TIME = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(team, event: str, session_id: str, at: dt.datetime) -> None:
    _create_event(
        team=team,
        event=event,
        distinct_id="d1",
        timestamp=at,
        properties={"$session_id": session_id},
    )


def _action(team, name: str, event: str) -> Action:
    return Action.objects.create(team=team, name=name, steps_json=[{"event": event}])


@freeze_time(_FROZEN_TIME)
class TestRecentActionSessions(ClickhouseTestMixin):
    @pytest.mark.django_db
    def test_a_dead_action_separates_from_a_live_one_by_its_session_count(self, team) -> None:
        live = _action(team, "Completed checkout", "checkout completed")
        dead = _action(team, "Clicked the old button", "button clicked v1")
        _event(team, "checkout completed", "s1", _NOW - dt.timedelta(hours=2))
        # Same session twice: the count is sessions, not events, so this must not read as two.
        _event(team, "checkout completed", "s1", _NOW - dt.timedelta(hours=1))
        _event(team, "checkout completed", "s2", _NOW - dt.timedelta(days=3))

        counts = recent_action_sessions(team=team, action_ids=[live.id, dead.id])

        assert counts == {live.id: 2, dead.id: 0}

    @pytest.mark.django_db
    def test_an_action_that_only_fired_before_the_window_reads_as_dead(self, team) -> None:
        # The whole point of the measurement is recency: an action that fired years ago and stopped
        # is the case that produces a scanner with nothing to scan.
        stale = _action(team, "Clicked the old button", "button clicked v1")
        _event(team, "button clicked v1", "s1", _NOW - dt.timedelta(days=30))

        assert recent_action_sessions(team=team, action_ids=[stale.id]) == {stale.id: 0}

    @pytest.mark.django_db
    def test_an_action_with_no_steps_is_never_measured(self, team) -> None:
        # A stepless action compiles to a condition that matches every event, so measuring it would
        # report the team's whole session count and read as the liveliest action in the briefing.
        stepless = Action.objects.create(team=team, name="Never finished", steps_json=[])
        _event(team, "checkout completed", "s1", _NOW - dt.timedelta(hours=2))
        # This path returns before it queries, and `_create_event` only writes its batch when a
        # query runs. Without the flush the event stays pending and fails the next test's teardown.
        flush_persons_and_events()

        assert recent_action_sessions(team=team, action_ids=[stepless.id]) == {}

    @pytest.mark.django_db
    def test_an_action_from_another_project_is_never_measured(self, team) -> None:
        # The ids come from a search, so a measurement that trusted them would read another
        # project's action and report its volume back into this team's briefing.
        other_team = Team.objects.create(organization=team.organization, name="other")
        theirs = _action(other_team, "Completed checkout", "checkout completed")

        assert recent_action_sessions(team=team, action_ids=[theirs.id]) == {}
