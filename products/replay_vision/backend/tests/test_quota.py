from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_quota_grant import ReplayQuotaGrant
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.quota import (
    MONTHLY_OBSERVATION_QUOTA,
    QuotaSnapshot,
    compute_quota_snapshot,
    pace_candidate_limit,
)
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
        if status == ObservationStatus.SUCCEEDED:
            # Mirror production: a succeeded observation has a usage receipt, which is what quota counts.
            self._make_receipt(observation)
        return observation

    @staticmethod
    def _make_receipt(observation: ReplayObservation) -> None:
        ReplayObservationUsage.objects.get_or_create(
            observation_id=observation.id,
            defaults={
                "organization_id": observation.team.organization_id,
                "observation_created_at": observation.created_at,
            },
        )


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
        other_obs = ReplayObservation.objects.create(
            scanner=other_scanner,
            team=other_team,
            session_id="other-sess",
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot=_snapshot_for(other_scanner),
            triggered_by=ObservationTrigger.ON_DEMAND,
            completed_at=timezone.now(),
        )
        self._make_receipt(other_obs)

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

    def test_deleting_scanner_does_not_refund_spent_usage(self) -> None:
        # Deleting a scanner cascade-deletes its observations, but the usage they spent must not be refunded.
        for _ in range(3):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        assert compute_quota_snapshot(organization_id=self.organization.id).usage_this_month == 3

        self.scanner.delete()

        assert ReplayObservation.objects.filter(team=self.team).count() == 0  # observations cascade-deleted
        assert compute_quota_snapshot(organization_id=self.organization.id).usage_this_month == 3  # receipts survive

    def test_deleting_observation_does_not_refund_spent_usage(self) -> None:
        observation = self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
        assert compute_quota_snapshot(organization_id=self.organization.id).usage_this_month == 1

        observation.delete()  # e.g. the admin recording-delete flow

        assert compute_quota_snapshot(organization_id=self.organization.id).usage_this_month == 1

    def test_no_double_count_across_pending_to_succeeded(self) -> None:
        observation = self._make_observation(status=ObservationStatus.PENDING)
        assert compute_quota_snapshot(organization_id=self.organization.id).usage_this_month == 1  # counted in-flight

        # The success transition flips status and writes the receipt, so the total stays 1.
        ReplayObservation.objects.filter(pk=observation.pk).update(
            status=ObservationStatus.SUCCEEDED, completed_at=timezone.now()
        )
        self._make_receipt(observation)
        assert compute_quota_snapshot(organization_id=self.organization.id).usage_this_month == 1


class TestPaceCandidateLimit:
    @staticmethod
    def _snapshot(remaining: int, period_end: datetime, enabled_scanner_count: int = 1) -> QuotaSnapshot:
        return QuotaSnapshot(
            monthly_quota=remaining,
            usage_this_month=0,
            period_start=period_end - timedelta(days=30),
            period_end=period_end,
            projected_monthly_observations=0,
            enabled_scanner_count=enabled_scanner_count,
        )

    @parameterized.expand(
        [
            ("exhausted", 0, 100),
            ("period_already_over", 100, -1),  # period ended in the past
        ]
    )
    def test_returns_zero(self, _name: str, remaining: int, hours_until_end: int) -> None:
        now = datetime(2026, 6, 15, tzinfo=UTC)
        period_end = now + timedelta(hours=hours_until_end)
        result = pace_candidate_limit(self._snapshot(remaining, period_end), now)
        assert result == 0

    def test_paces_remaining_across_remaining_ticks(self) -> None:
        now = datetime(2026, 6, 15, tzinfo=UTC)
        period_end = now + timedelta(minutes=50)  # 10 ticks of 5 minutes
        snapshot = self._snapshot(remaining=100, period_end=period_end)
        result = pace_candidate_limit(snapshot, now, tick_interval=timedelta(minutes=5))
        assert result == 10

    def test_minimum_of_one_when_remaining_is_positive(self) -> None:
        now = datetime(2026, 6, 15, tzinfo=UTC)
        period_end = now + timedelta(days=20)  # ~5760 ticks of 5 minutes
        snapshot = self._snapshot(remaining=10, period_end=period_end)
        result = pace_candidate_limit(snapshot, now, tick_interval=timedelta(minutes=5))
        assert result == 1

    def test_divides_by_enabled_scanner_count(self) -> None:
        now = datetime(2026, 6, 15, tzinfo=UTC)
        period_end = now + timedelta(minutes=50)  # 10 ticks of 5 minutes
        snapshot = self._snapshot(remaining=100, period_end=period_end, enabled_scanner_count=5)
        result = pace_candidate_limit(snapshot, now, tick_interval=timedelta(minutes=5))
        # 100 remaining / 10 ticks / 5 scanners = 2 per tick per scanner
        assert result == 2


class TestProjectedMonthlyObservations(_VisionQuotaTestCase):
    def _make_scanner(self, *, team: Team, name: str, enabled: bool = True, estimate: int | None = None) -> None:
        scanner = ReplayScanner.objects.create(
            team=team,
            name=name,
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_FLASH,
            enabled=enabled,
        )
        if estimate is not None:
            ReplayScanner.objects.filter(pk=scanner.pk).update(
                estimated_monthly_observations=estimate, estimated_at=timezone.now()
            )

    def test_sums_enabled_scanners_across_org_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="second-team")
        self._make_scanner(team=self.team, name="a", estimate=100)
        self._make_scanner(team=other_team, name="b", estimate=250)
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.projected_monthly_observations == 350

    def test_disabled_and_unestimated_scanners_contribute_zero(self) -> None:
        self._make_scanner(team=self.team, name="disabled", enabled=False, estimate=500)
        self._make_scanner(team=self.team, name="unestimated", estimate=None)
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.projected_monthly_observations == 0

    def test_other_orgs_scanners_not_counted(self) -> None:
        other_org = Organization.objects.create(name="other-projection-org")
        other_team = Team.objects.create(organization=other_org, name="other-projection-team")
        self._make_scanner(team=other_team, name="other", estimate=999)
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.projected_monthly_observations == 0


class TestQuotaGrants(_VisionQuotaTestCase):
    def test_active_grant_adds_to_monthly_quota(self) -> None:
        ReplayQuotaGrant.objects.create(
            organization=self.organization,
            amount=500,
            expires_at=timezone.now() + timedelta(days=10),
        )
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.monthly_quota == MONTHLY_OBSERVATION_QUOTA + 500

    def test_multiple_active_grants_stack(self) -> None:
        for amount in (100, 200, 700):
            ReplayQuotaGrant.objects.create(
                organization=self.organization,
                amount=amount,
                expires_at=timezone.now() + timedelta(days=10),
            )
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.monthly_quota == MONTHLY_OBSERVATION_QUOTA + 1000

    def test_expired_grant_does_not_count(self) -> None:
        grant = ReplayQuotaGrant(
            organization=self.organization,
            amount=500,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        grant.save()  # bypass full_clean — simulate the case where a grant has aged past its expiry
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.monthly_quota == MONTHLY_OBSERVATION_QUOTA

    def test_other_orgs_grants_not_counted(self) -> None:
        other_org = Organization.objects.create(name="other-grant-org")
        ReplayQuotaGrant.objects.create(
            organization=other_org,
            amount=500,
            expires_at=timezone.now() + timedelta(days=10),
        )
        snapshot = compute_quota_snapshot(organization_id=self.organization.id)
        assert snapshot.monthly_quota == MONTHLY_OBSERVATION_QUOTA

    @parameterized.expand(
        [
            ("past_expires_at", 500, timedelta(seconds=-1), "expires_at"),
            ("amount_zero", 0, timedelta(days=10), "amount"),
            ("amount_above_cap", 10_000_000, timedelta(days=10), "amount"),
        ]
    )
    def test_full_clean_rejects(self, _name: str, amount: int, expires_offset: timedelta, expected_field: str) -> None:
        # timezone.now() resolves inside the test body so we don't freeze it at import time.
        grant = ReplayQuotaGrant(
            organization=self.organization,
            amount=amount,
            expires_at=timezone.now() + expires_offset,
        )
        with self.assertRaises(ValidationError) as cm:
            grant.full_clean()
        assert expected_field in cm.exception.message_dict

    def test_grant_pushes_exhaustion_back(self) -> None:
        with patch("products.replay_vision.backend.quota.MONTHLY_OBSERVATION_QUOTA", 2):
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
            self._make_observation(status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())
            assert compute_quota_snapshot(organization_id=self.organization.id).exhausted is True

            ReplayQuotaGrant.objects.create(
                organization=self.organization,
                amount=1,
                expires_at=timezone.now() + timedelta(days=10),
            )
            snapshot = compute_quota_snapshot(organization_id=self.organization.id)
            assert snapshot.exhausted is False
            assert snapshot.remaining == 1


class TestReplayQuotaGrantAdmin(_VisionQuotaTestCase):
    def test_initial_form_renders(self) -> None:
        # Regression: `expires_at` initial must be a datetime, not a str. The admin's
        # SplitDateTimeWidget.decompress runs `to_current_timezone` → `is_aware` →
        # `value.utcoffset()`, which AttributeErrors on a str and 500s the add page in prod.
        # We render the form directly instead of GETting /admin/...add/ because the admin
        # URLs are gated on ADMIN_PORTAL_ENABLED, which defaults False in product test env.
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from products.replay_vision.backend.admin import ReplayQuotaGrantAdmin

        self.user.is_staff = True
        self.user.save()
        request = RequestFactory().get("/admin/replay_vision/replayquotagrant/add/")
        request.user = self.user

        grant_admin = ReplayQuotaGrantAdmin(ReplayQuotaGrant, django_admin.site)
        form_class = grant_admin.get_form(request)
        form = form_class(initial=grant_admin.get_changeform_initial_data(request))
        # `as_p()` triggers widget render, which is where the bug fires.
        html = form.as_p()
        assert 'name="expires_at_0"' in html
        assert 'name="granted_by"' in html


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
        assert body["projected_monthly_observations"] == 0
        assert "period_start" in body
        assert "period_end" in body

    def test_returns_fleet_projection(self) -> None:
        ReplayScanner.objects.filter(pk=self.scanner.pk).update(
            estimated_monthly_observations=120, estimated_at=timezone.now()
        )
        resp = self.client.get(self.quota_url)
        assert resp.json()["projected_monthly_observations"] == 120

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


@patch("products.replay_vision.backend.api.trigger.async_to_sync")
@patch("products.replay_vision.backend.api.trigger.sync_connect")
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
