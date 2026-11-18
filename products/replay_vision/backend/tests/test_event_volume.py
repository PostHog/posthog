import datetime as dt

import pytest
import time_machine
from posthog.test.base import ClickhouseTestMixin, _create_event

from posthog.models import Team

from products.replay_vision.backend.queries.event_volume import recent_event_sessions

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
_FROZEN_TIME = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(team, event: str, session_id: str | None, at: dt.datetime) -> None:
    _create_event(
        team=team,
        event=event,
        distinct_id="d1",
        timestamp=at,
        properties={"$session_id": session_id} if session_id else {},
    )


class TestRecentEventSessions(ClickhouseTestMixin):
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(_FROZEN_TIME, tick=False):
            yield

    @pytest.mark.django_db
    def test_a_busy_event_separates_from_a_quiet_one_by_its_session_count(self, team) -> None:
        # Both names exist on the team, so a definition lookup ranks them the same. Only the count
        # tells the model which one is worth filtering a scanner on.
        _event(team, "scanner_created", "s1", _NOW - dt.timedelta(hours=2))
        # Same session twice: the count is sessions, not events, so this must not read as two.
        _event(team, "scanner_created", "s1", _NOW - dt.timedelta(hours=1))
        _event(team, "scanner_created", "s2", _NOW - dt.timedelta(days=3))
        _event(team, "scanner_drafted", "s3", _NOW - dt.timedelta(days=1))
        # Outside the window, so it must not count: an event that stopped firing takes an AND
        # filter to zero, and absence is how the briefing shows that it went quiet.
        _event(team, "old_flow_started", "s4", _NOW - dt.timedelta(days=30))

        counts = recent_event_sessions(
            team=team, event_names=["scanner_created", "scanner_drafted", "old_flow_started"]
        )

        assert counts == {"scanner_created": 2, "scanner_drafted": 1}

    @pytest.mark.django_db
    def test_an_event_with_no_session_is_not_counted(self, team) -> None:
        # A scanner watches recordings, so an event fired outside a session (a backend capture) says
        # nothing about how many sessions a filter on it would match.
        _event(team, "invoice_paid", None, _NOW - dt.timedelta(hours=1))

        assert recent_event_sessions(team=team, event_names=["invoice_paid"]) == {}

    @pytest.mark.django_db
    def test_the_name_is_matched_exactly(self, team) -> None:
        # `event` is the third column of the events sort key, so the filter stays an exact match on
        # the bare column. Callers pass the team's own spelling; a case-folded filter here would
        # read the whole window instead of skipping granules.
        _event(team, "Survey Sent", "s1", _NOW - dt.timedelta(hours=1))

        assert recent_event_sessions(team=team, event_names=["survey sent"]) == {}
        assert recent_event_sessions(team=team, event_names=["Survey Sent"]) == {"Survey Sent": 1}

    @pytest.mark.django_db
    def test_another_projects_events_are_never_counted(self, team) -> None:
        # The names come from a definition search, and a count that leaked across teams would
        # report another project's traffic into this team's briefing.
        other_team = Team.objects.create(organization=team.organization, name="other")
        _event(other_team, "scanner_created", "s1", _NOW - dt.timedelta(hours=1))

        assert recent_event_sessions(team=team, event_names=["scanner_created"]) == {}
