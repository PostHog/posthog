from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.quota import MONTHLY_OBSERVATION_QUOTA, compute_quota_snapshot
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for


class _VisionQuotaTestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="quota-test-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
        )

    def tearDown(self) -> None:
        self.flag_patcher.stop()
        super().tearDown()

    def _make_observation(
        self,
        *,
        status: ObservationStatus,
        completed_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> ReplayObservation:
        observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id=f"sess-{ReplayObservation.objects.count()}",
            status=status,
            scanner_snapshot=_snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            completed_at=completed_at,
        )
        if created_at is not None:
            ReplayObservation.objects.filter(pk=observation.pk).update(created_at=created_at)
            observation.refresh_from_db()
        return observation


class TestComputeQuotaSnapshot(_VisionQuotaTestCase):
    @parameterized.expand(
        [
            (ObservationStatus.SUCCEEDED, 1),
            (ObservationStatus.PENDING, 1),
            (ObservationStatus.RUNNING, 1),
            (ObservationStatus.FAILED, 0),
            (ObservationStatus.INELIGIBLE, 0),
        ]
    )
    def test_counts_only_succeeded_and_in_flight_this_month(
        self, status: ObservationStatus, expected_count: int
    ) -> None:
        self._make_observation(
            status=status,
            completed_at=timezone.now()
            if status != ObservationStatus.PENDING and status != ObservationStatus.RUNNING
            else None,
        )
        assert compute_quota_snapshot(organization_id=self.organization.id).usage_this_month == expected_count

    def test_excludes_observations_created_in_a_previous_month(self) -> None:
        last_month = (datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)) - timedelta(days=1)
        self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=last_month, created_at=last_month)
        assert compute_quota_snapshot(organization_id=self.organization.id).usage_this_month == 0

    def test_period_bounds_are_first_of_month_utc(self) -> None:
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.period_start.day == 1
        assert snapshot.period_start.tzinfo == UTC
        assert snapshot.period_end.day == 1
        assert snapshot.period_end > snapshot.period_start

    def test_december_rollover_advances_year(self) -> None:
        with patch("products.replay_vision.backend.quota.datetime", wraps=datetime) as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 12, 15, 10, tzinfo=UTC)
            snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.period_start == datetime(2026, 12, 1, tzinfo=UTC)
        assert snapshot.period_end == datetime(2027, 1, 1, tzinfo=UTC)

    def test_observations_at_period_boundaries(self) -> None:
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        self._make_observation(
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            created_at=snapshot.period_end - timedelta(microseconds=1),
        )
        self._make_observation(
            status=ObservationStatus.SUCCEEDED, completed_at=timezone.now(), created_at=snapshot.period_end
        )
        assert compute_quota_snapshot(organization_id=self.organization.id).usage_this_month == 1

    def test_other_orgs_observations_not_counted(self) -> None:
        other_org = Organization.objects.create(name="other-org")
        other_team = Team.objects.create(organization=other_org, name="other-team")
        other_scanner = ReplayScanner.objects.create(
            team=other_team,
            name="other-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
        ReplayObservation.objects.create(
            scanner=other_scanner,
            team=other_team,
            session_id="other-sess",
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot=_snapshot_for(other_scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            completed_at=timezone.now(),
        )

        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.usage_this_month == 0

    def test_exhausted_when_usage_meets_quota(self) -> None:
        with patch("products.replay_vision.backend.quota.MONTHLY_OBSERVATION_QUOTA", 2):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())

            snapshot = compute_quota_snapshot(organization_id=self.organization.id)

            assert snapshot.usage_this_month == 2
            assert snapshot.exhausted is True
            assert snapshot.remaining == 0


class TestVisionQuotaEndpoint(_VisionQuotaTestCase):
    @property
    def quota_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/quota/"

    def test_returns_static_quota_and_zero_usage_when_empty(self) -> None:
        resp = self.client.get(self.quota_url)
        assert resp.status_code == 200, resp.json()
        body = resp.json()
        assert body["monthly_quota"] == MONTHLY_OBSERVATION_QUOTA
        assert body["usage_this_month"] == 0
        assert body["remaining"] == MONTHLY_OBSERVATION_QUOTA
        assert body["exhausted"] is False
        assert "period_start" in body
        assert "period_end" in body

    def test_reflects_recent_succeeded_observations(self) -> None:
        for _ in range(3):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())

        resp = self.client.get(self.quota_url)
        assert resp.json()["usage_this_month"] == 3
        assert resp.json()["remaining"] == MONTHLY_OBSERVATION_QUOTA - 3

    def test_requires_feature_flag(self) -> None:
        with patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            resp = self.client.get(self.quota_url)
        assert resp.status_code == 404


@patch("products.replay_vision.backend.api.scanners.async_to_sync")
@patch("products.replay_vision.backend.api.scanners.sync_connect")
class TestObserveQuotaEnforcement(_VisionQuotaTestCase):
    @property
    def observe_url(self) -> str:
        return f"/api/environments/{self.team.id}/vision/scanners/{self.scanner.id}/observe/"

    def test_returns_402_when_quota_exhausted(
        self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock
    ) -> None:
        with patch("products.replay_vision.backend.quota.MONTHLY_OBSERVATION_QUOTA", 1):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())

            resp = self.client.post(self.observe_url, data={"session_id": "sess-blocked"}, format="json")

            assert resp.status_code == 402, resp.json()
            body = resp.json()
            assert body["code"] == "quota_limit_exceeded"
            assert "Monthly Replay Vision quota of 1 observations reached" in body["detail"]
            mock_sync_connect.assert_not_called()
            mock_async_to_sync.assert_not_called()

    def test_allows_observe_when_under_quota(self, mock_sync_connect: MagicMock, mock_async_to_sync: MagicMock) -> None:
        mock_sync_connect.return_value = MagicMock()
        mock_async_to_sync.return_value = MagicMock()

        resp = self.client.post(self.observe_url, data={"session_id": "sess-ok"}, format="json")
        assert resp.status_code == 202, resp.json()
        mock_sync_connect.assert_called_once()
