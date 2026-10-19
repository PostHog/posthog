from datetime import timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.utils import timezone

from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.replay_vision.backend.queries.session_last_activity import fetch_session_last_activity


class TestFetchSessionLastActivity(ClickhouseTestMixin, BaseTest):
    def test_returns_every_session_past_hogql_default_row_limit(self) -> None:
        now = timezone.now()
        session_ids = [str(uuid7()) for _ in range(101)]
        for session_id in session_ids:
            produce_replay_summary(
                team_id=self.team.pk,
                session_id=session_id,
                first_timestamp=now - timedelta(hours=2),
                last_timestamp=now - timedelta(hours=1),
                ensure_analytics_event_in_session=False,
            )

        last_activity = fetch_session_last_activity(team=self.team, session_ids=session_ids, now=now)

        assert set(last_activity) == set(session_ids)
