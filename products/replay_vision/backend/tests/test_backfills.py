import datetime as dt

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from posthog.models import Organization, Team

from products.replay_vision.backend.api.backfills import (
    MAX_BACKFILL_WINDOW_DAYS,
    BackfillEnumerationThrottle,
    ReplayScannerBackfillViewSet,
)
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ObservationTrigger
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.replay_scanner_backfill import BackfillStatus, ReplayScannerBackfill
from products.replay_vision.backend.quota import compute_quota_snapshot, sum_active_backfill_remaining_credits
from products.replay_vision.backend.temporal.activities.backfill import (
    advance_backfill_cursor_activity,
    prepare_backfill_tick_activity,
)
from products.replay_vision.backend.temporal.activities.create_observation import create_observation_activity
from products.replay_vision.backend.temporal.backfill_types import (
    AdvanceBackfillCursorInputs,
    BackfillTickAction,
    BackfillTickInputs,
)
from products.replay_vision.backend.temporal.constants import (
    MAX_IN_FLIGHT_APPLIES_PER_BACKFILL,
    MAX_IN_FLIGHT_APPLIES_PER_SCANNER,
    MAX_IN_FLIGHT_APPLIES_PER_TEAM,
    backfill_dispatch_budget,
)
from products.replay_vision.backend.temporal.snapshots import BackfillScannerSnapshot
from products.replay_vision.backend.temporal.types import CreateObservationInputs

_WINDOW_END = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
_WINDOW_START = _WINDOW_END - dt.timedelta(days=30)


def _make_scanner(**overrides) -> ReplayScanner:
    org = Organization.objects.create(name="backfill-test-org")
    team = Team.objects.create(organization=org, name="backfill-test-team")
    defaults: dict = {
        "team": team,
        "name": "t",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "p"},
        "model": ScannerModel.GEMINI_3_6_FLASH,
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


def _frozen_snapshot(scanner: ReplayScanner, **overrides) -> dict:
    return {**BackfillScannerSnapshot.from_scanner(scanner).model_dump(mode="json"), **overrides}


def _make_backfill(scanner: ReplayScanner, **overrides) -> ReplayScannerBackfill:
    defaults: dict = {
        "scanner": scanner,
        "team": scanner.team,
        "window_start": _WINDOW_START,
        "window_end": _WINDOW_END,
        "scanner_snapshot": _frozen_snapshot(scanner),
        "credits_per_observation": 5,
        "total_count": 100,
    }
    defaults.update(overrides)
    return ReplayScannerBackfill.objects.for_team(scanner.team_id).create(**defaults)


@pytest.mark.parametrize(
    "scanner_in_flight,team_in_flight,backfill_in_flight,expected",
    [
        (0, 0, 0, MAX_IN_FLIGHT_APPLIES_PER_BACKFILL),
        (0, 0, MAX_IN_FLIGHT_APPLIES_PER_BACKFILL, 0),
        (0, 0, 30, MAX_IN_FLIGHT_APPLIES_PER_BACKFILL - 30),
        (MAX_IN_FLIGHT_APPLIES_PER_SCANNER - 10, 0, 0, 10),
        (0, MAX_IN_FLIGHT_APPLIES_PER_TEAM - 5, 0, 5),
    ],
)
def test_backfill_dispatch_budget_takes_the_tightest_cap(
    scanner_in_flight: int, team_in_flight: int, backfill_in_flight: int, expected: int
) -> None:
    assert backfill_dispatch_budget(scanner_in_flight, team_in_flight, backfill_in_flight) == expected


@pytest.mark.django_db(transaction=True)
class TestBackfillQuotaCommitment:
    def test_only_active_backfills_contribute_their_remaining_commitment(self) -> None:
        scanner = _make_scanner()
        org_id = scanner.team.organization_id
        _make_backfill(scanner, total_count=100, dispatched_count=40, credits_per_observation=5)
        # Terminal rows and fully-dispatched rows must not inflate the prognosis.
        cancelled_scanner = ReplayScanner.objects.create(
            team=scanner.team,
            name="c",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_6_FLASH,
        )
        _make_backfill(cancelled_scanner, status=BackfillStatus.CANCELLED, total_count=100, credits_per_observation=5)

        assert sum_active_backfill_remaining_credits(org_id) == 60 * 5
        assert compute_quota_snapshot(org_id).projected_monthly_credits == 60 * 5

    def test_paused_backfill_still_counts_as_committed(self) -> None:
        scanner = _make_scanner()
        _make_backfill(
            scanner, status=BackfillStatus.PAUSED_QUOTA, total_count=10, dispatched_count=4, credits_per_observation=2
        )
        assert sum_active_backfill_remaining_credits(scanner.team.organization_id) == 12


@pytest.mark.django_db(transaction=True)
class TestCreateObservationForBackfill:
    def test_backfill_observation_uses_frozen_snapshot_not_live_scanner(self) -> None:
        scanner = _make_scanner(scanner_config={"prompt": "new prompt"})
        backfill = _make_backfill(
            scanner, scanner_snapshot=_frozen_snapshot(scanner, scanner_config={"prompt": "frozen prompt"})
        )
        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.BACKFILL,
                triggered_by_user_id=None,
                workflow_id="wf-1",
                backfill_id=backfill.id,
            )
        )
        assert result.was_created
        observation = backfill.observations.get()
        assert observation.scanner_snapshot["scanner_config"] == {"prompt": "frozen prompt"}
        assert observation.triggered_by == ObservationTrigger.BACKFILL

    def test_cancelled_backfill_skips_creation(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner, status=BackfillStatus.CANCELLED, finished_at=timezone.now())
        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.BACKFILL,
                triggered_by_user_id=None,
                workflow_id="wf-1",
                backfill_id=backfill.id,
            )
        )
        assert not result.was_created
        assert not backfill.observations.exists()


@pytest.mark.django_db(transaction=True)
class TestBackfillTickActivities:
    @staticmethod
    def _tick_inputs(backfill: ReplayScannerBackfill) -> BackfillTickInputs:
        return BackfillTickInputs(backfill_id=backfill.id, team_id=backfill.team_id, scanner_id=backfill.scanner_id)

    def test_prepare_finishes_on_terminal_row_and_skips_on_disabled_scanner(self) -> None:
        scanner = _make_scanner()
        cancelled = _make_backfill(scanner, status=BackfillStatus.CANCELLED, finished_at=timezone.now())
        assert prepare_backfill_tick_activity(self._tick_inputs(cancelled)).action == BackfillTickAction.FINISHED

        scanner.enabled = False
        scanner.save()
        running = _make_backfill(scanner)
        assert prepare_backfill_tick_activity(self._tick_inputs(running)).action == BackfillTickAction.SKIP

    def test_prepare_repauses_a_quota_paused_row(self) -> None:
        # The reaper can recreate a paused backfill's schedule unpaused; a SKIP here would tick forever.
        scanner = _make_scanner()
        backfill = _make_backfill(scanner, status=BackfillStatus.PAUSED_QUOTA)
        assert prepare_backfill_tick_activity(self._tick_inputs(backfill)).action == BackfillTickAction.PAUSE

    def test_prepare_skips_without_org_ai_consent(self) -> None:
        # Children would decline at create while the cursor walks past their sessions.
        scanner = _make_scanner()
        org = scanner.team.organization
        org.is_ai_data_processing_approved = False
        org.save()
        backfill = _make_backfill(scanner)
        assert prepare_backfill_tick_activity(self._tick_inputs(backfill)).action == BackfillTickAction.SKIP

    def test_prepare_clamps_batch_to_remaining_quota(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner, credits_per_observation=5)
        headroom = MagicMock()
        headroom.would_exceed.return_value = False
        headroom.remaining = 7
        with patch(
            "products.replay_vision.backend.temporal.activities.backfill.compute_quota_snapshot",
            return_value=headroom,
        ):
            result = prepare_backfill_tick_activity(self._tick_inputs(backfill))
        assert result.action == BackfillTickAction.DISPATCH
        assert result.dispatch_budget == 1

    def test_prepare_pauses_when_org_quota_exhausted(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        exhausted = MagicMock()
        exhausted.would_exceed.return_value = True
        with patch(
            "products.replay_vision.backend.temporal.activities.backfill.compute_quota_snapshot",
            return_value=exhausted,
        ):
            result = prepare_backfill_tick_activity(self._tick_inputs(backfill))
        assert result.action == BackfillTickAction.PAUSE
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.PAUSED_QUOTA

    def test_prepare_dispatches_with_budget_when_headroom_available(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        result = prepare_backfill_tick_activity(self._tick_inputs(backfill))
        assert result.action == BackfillTickAction.DISPATCH
        assert result.dispatch_budget > 0

    def test_advance_updates_cursor_and_short_batch_completes(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        cursor_time = _WINDOW_END - dt.timedelta(days=2)
        result = advance_backfill_cursor_activity(
            AdvanceBackfillCursorInputs(
                backfill_id=backfill.id,
                team_id=backfill.team_id,
                new_cursor_end_time=cursor_time,
                new_cursor_session_id="sess-9",
                dispatched_delta=2,
                exhausted=False,
            )
        )
        assert not result.finished
        backfill.refresh_from_db()
        assert (backfill.cursor_end_time, backfill.cursor_session_id) == (cursor_time, "sess-9")
        assert backfill.dispatched_count == 2
        assert backfill.status == BackfillStatus.RUNNING

        result = advance_backfill_cursor_activity(
            AdvanceBackfillCursorInputs(backfill_id=backfill.id, team_id=backfill.team_id, exhausted=True)
        )
        assert result.finished
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.COMPLETED
        assert backfill.finished_at is not None

    def test_advance_loses_to_concurrent_cancel(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner, status=BackfillStatus.CANCELLED, finished_at=timezone.now())
        result = advance_backfill_cursor_activity(
            AdvanceBackfillCursorInputs(backfill_id=backfill.id, team_id=backfill.team_id, exhausted=True)
        )
        assert not result.finished
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.CANCELLED


class TestBackfillsApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="backfill-api-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_6_FLASH,
        )
        self.base_url = f"/api/projects/{self.team.id}/vision/scanners/{self.scanner.id}/backfills"

    def tearDown(self) -> None:
        self.flag_patcher.stop()
        super().tearDown()

    def _window_body(self) -> dict:
        return {
            "window_start": (self.scanner.last_swept_at - dt.timedelta(days=30)).isoformat(),
            "window_end": (self.scanner.last_swept_at + dt.timedelta(days=1)).isoformat(),
        }

    @patch("products.replay_vision.backend.temporal.schedule.a_upsert_backfill_schedule", new_callable=AsyncMock)
    @patch("products.replay_vision.backend.api.backfills.BackfillCandidateQuery")
    def test_create_freezes_config_clamps_window_and_rejects_second_active(
        self, mock_query: MagicMock, mock_upsert: AsyncMock
    ) -> None:
        mock_query.return_value.count.return_value = 7
        response = self.client.post(f"{self.base_url}/", self._window_body(), format="json")
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["total_count"] == 7
        assert body["status"] == "running"

        backfill = ReplayScannerBackfill.objects.for_team(self.team.id).get(pk=body["id"])
        # The upper bound never crosses the live sweep's watermark.
        assert backfill.window_end == self.scanner.last_swept_at
        assert backfill.scanner_snapshot["scanner_config"] == {"prompt": "p"}
        assert backfill.credits_per_observation > 0
        assert mock_upsert.await_count == 1

        response = self.client.post(f"{self.base_url}/", self._window_body(), format="json")
        assert response.status_code == 400
        assert "active backfill" in response.json()["detail"]

    @patch("products.replay_vision.backend.api.backfills.BackfillCandidateQuery")
    def test_estimate_returns_exact_ceiling_without_creating_rows(self, mock_query: MagicMock) -> None:
        mock_query.return_value.count.return_value = 40
        response = self.client.post(f"{self.base_url}/estimate/", self._window_body(), format="json")
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["total_sessions"] == 40
        assert body["total_credits"] == 40 * body["credits_per_observation"]
        assert not ReplayScannerBackfill.objects.for_team(self.team.id).filter(scanner=self.scanner).exists()

    def test_estimate_rejects_window_longer_than_the_cap(self) -> None:
        # An unbounded window makes the synchronous enumeration pay for the whole partition range.
        body = {
            "window_start": (self.scanner.last_swept_at - dt.timedelta(days=MAX_BACKFILL_WINDOW_DAYS + 1)).isoformat(),
            "window_end": self.scanner.last_swept_at.isoformat(),
        }
        response = self.client.post(f"{self.base_url}/estimate/", body, format="json")
        assert response.status_code == 400
        assert "365 days" in str(response.json())

    def test_estimate_rejects_window_entirely_past_the_watermark(self) -> None:
        body = {
            "window_start": (self.scanner.last_swept_at + dt.timedelta(hours=1)).isoformat(),
            "window_end": (self.scanner.last_swept_at + dt.timedelta(hours=2)).isoformat(),
        }
        response = self.client.post(f"{self.base_url}/estimate/", body, format="json")
        assert response.status_code == 400

    @patch("products.replay_vision.backend.temporal.schedule.a_delete_backfill_schedule", new_callable=AsyncMock)
    def test_cancel_marks_terminal(self, _mock_delete: AsyncMock) -> None:
        backfill = _make_backfill(self.scanner)
        response = self.client.post(f"{self.base_url}/{backfill.id}/cancel/")
        assert response.status_code == 200, response.json()
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.CANCELLED
        assert backfill.finished_at is not None

    @patch("products.replay_vision.backend.temporal.schedule.a_resume_backfill_schedule", new_callable=AsyncMock)
    def test_resume_only_applies_to_quota_paused_backfills(self, _mock_resume: AsyncMock) -> None:
        backfill = _make_backfill(self.scanner, status=BackfillStatus.PAUSED_QUOTA)
        response = self.client.post(f"{self.base_url}/{backfill.id}/resume/")
        assert response.status_code == 200, response.json()
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.RUNNING

        running = backfill
        response = self.client.post(f"{self.base_url}/{running.id}/resume/")
        assert response.status_code == 400

    def test_enumerating_actions_are_throttled_for_session_auth(self) -> None:
        # The global burst/sustained throttles only cover personal API keys, so dropping this wiring
        # would leave the synchronous ClickHouse enumeration open to an ordinary UI session.
        viewset = ReplayScannerBackfillViewSet()
        for enumerating_action in ("estimate", "create"):
            viewset.action = enumerating_action
            assert any(isinstance(t, BackfillEnumerationThrottle) for t in viewset.get_throttles())
        viewset.action = "cancel"
        assert not any(isinstance(t, BackfillEnumerationThrottle) for t in viewset.get_throttles())

    def test_list_includes_observation_progress_counts(self) -> None:
        backfill = _make_backfill(self.scanner, dispatched_count=3)
        for i, status in enumerate([ObservationStatus.SUCCEEDED, ObservationStatus.FAILED, ObservationStatus.PENDING]):
            backfill.observations.create(
                scanner=self.scanner,
                team=self.team,
                session_id=f"sess-{i}",
                status=status,
                triggered_by=ObservationTrigger.BACKFILL,
                scanner_snapshot=backfill.scanner_snapshot,
                completed_at=timezone.now() if status != ObservationStatus.PENDING else None,
            )
        response = self.client.get(f"{self.base_url}/")
        assert response.status_code == 200
        row = response.json()["results"][0]
        assert (row["succeeded_count"], row["failed_count"], row["in_flight_count"]) == (1, 1, 1)
