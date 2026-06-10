from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from posthog.models.team.team import Team

from products.growth.dags.team_production_event_activation import detect_first_team_production_event_job


@contextmanager
def _mock_capture():
    capture_fn: Any = MagicMock()
    with patch("posthog.models.team.production_event_activation.ph_scoped_capture") as mock_csm:
        mock_csm.return_value.__enter__.return_value = capture_fn
        mock_csm.return_value.__exit__.return_value = False
        yield capture_fn


def _seed_event(team_id: int, host: str, days_ago: float = 1) -> None:
    _create_event(
        team=Team.objects.get(id=team_id),
        event="$pageview",
        distinct_id="user-0",
        timestamp=datetime.now(tz=UTC) - timedelta(days=days_ago),
        properties={"$host": host},
    )
    flush_persons_and_events()


class TestDetectFirstTeamProductionEventJob(ClickhouseTestMixin, BaseTest):
    def test_no_unflagged_teams_skips_evaluation(self) -> None:
        # All teams already flagged → the dynamic op yields zero batches → criterion is never queried.
        Team.objects.filter(id=self.team.id).update(ingested_production_event=True)

        with patch("posthog.models.team.production_event_activation._teams_meeting_criterion") as mock_criterion:
            result = detect_first_team_production_event_job.execute_in_process()

        self.assertTrue(result.success)
        mock_criterion.assert_not_called()

    def test_qualifying_team_is_flagged(self) -> None:
        _seed_event(self.team.id, host="app.example.com")

        with freeze_time("2026-06-05T12:00:00Z"), _mock_capture():
            result = detect_first_team_production_event_job.execute_in_process()

        self.assertTrue(result.success)
        self.team.refresh_from_db()
        self.assertTrue(self.team.ingested_production_event)
        self.assertEqual(
            self.team.ingested_production_event_last_checked_at,
            datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC),
        )

    def test_non_qualifying_team_only_gets_last_checked_at_bumped(self) -> None:
        _seed_event(self.team.id, host="localhost:3000")

        with freeze_time("2026-06-05T12:00:00Z"):
            result = detect_first_team_production_event_job.execute_in_process()

        self.assertTrue(result.success)
        self.team.refresh_from_db()
        self.assertFalse(self.team.ingested_production_event)
        self.assertEqual(
            self.team.ingested_production_event_last_checked_at,
            datetime(2026, 6, 5, 12, 0, 0, tzinfo=UTC),
        )
