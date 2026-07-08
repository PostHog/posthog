from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from posthog.models.organization import Organization
from posthog.models.team.production_event_activation import RECHECK_BACKOFF
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


# The backoff tests need timestamps relative to real wall-clock time — the
# candidate filter and ClickHouse's `now()` both use it, so freezing time here
# would desynchronize the two. Kept out of test bodies for the
# test-no-datetime-now semgrep rule; relative offsets are midnight-safe.
def _real_now() -> datetime:
    return datetime.now(tz=UTC)


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

    def test_demo_team_is_excluded_from_the_sweep(self) -> None:
        demo_team = Team.objects.create(organization=self.organization, name="demo", is_demo=True)
        _seed_event(demo_team.id, host="hedgebox.net")

        with _mock_capture() as capture:
            result = detect_first_team_production_event_job.execute_in_process()

        self.assertTrue(result.success)
        demo_team.refresh_from_db()
        self.assertFalse(demo_team.ingested_production_event)
        # Never evaluated at all — not even the bookkeeping stamp.
        self.assertIsNone(demo_team.ingested_production_event_last_checked_at)
        capture.assert_not_called()

    def test_internal_metrics_org_team_is_excluded_from_the_sweep(self) -> None:
        internal_org = Organization.objects.create(name="internal", for_internal_metrics=True)
        internal_team = Team.objects.create(organization=internal_org, name="internal")
        _seed_event(internal_team.id, host="app.example.com")

        with _mock_capture():
            result = detect_first_team_production_event_job.execute_in_process()

        self.assertTrue(result.success)
        internal_team.refresh_from_db()
        self.assertFalse(internal_team.ingested_production_event)
        self.assertIsNone(internal_team.ingested_production_event_last_checked_at)

    def test_recently_checked_team_is_skipped(self) -> None:
        recently_checked_at = _real_now() - timedelta(hours=1)
        Team.objects.filter(id=self.team.id).update(
            ingested_production_event_last_checked_at=recently_checked_at,
        )
        _seed_event(self.team.id, host="app.example.com")

        with _mock_capture() as capture:
            result = detect_first_team_production_event_job.execute_in_process()

        self.assertTrue(result.success)
        self.team.refresh_from_db()
        self.assertFalse(self.team.ingested_production_event)
        # Untouched: skipped teams keep their previous check timestamp.
        self.assertEqual(self.team.ingested_production_event_last_checked_at, recently_checked_at)
        capture.assert_not_called()

    def test_stale_checked_team_is_rechecked(self) -> None:
        Team.objects.filter(id=self.team.id).update(
            ingested_production_event_last_checked_at=_real_now() - RECHECK_BACKOFF - timedelta(days=1),
        )
        _seed_event(self.team.id, host="app.example.com")

        with _mock_capture():
            result = detect_first_team_production_event_job.execute_in_process()

        self.assertTrue(result.success)
        self.team.refresh_from_db()
        self.assertTrue(self.team.ingested_production_event)
