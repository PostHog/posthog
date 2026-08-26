import datetime as dt

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.apm.backend.facade.api import BaselineStage, Direction, IssueState, TrafficTier, VerdictType
from products.logs.backend.anomaly_scan import ScanBucket, ScanBudgetExceeded, ScanIssue, ScanResult, ScanSeries
from products.logs.backend.presentation.views.anomalies_api import LogsAnomalyScanRequestSerializer
from products.logs.backend.series_bands import BandBucket, BandSeries, SeriesBandsFetchTruncated, SeriesBandsResult

UTC = dt.UTC
T0 = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _scan_result(**overrides) -> ScanResult:
    defaults: dict = {
        "service_name": "svc",
        "eval_start": T0,
        "eval_end": T0 + dt.timedelta(hours=1),
        "lookback_buckets": 6 * 7 * 288,
        "eval_clipped": False,
        "degraded": False,
        "binding_constraints": [],
        "series": [
            ScanSeries(
                severity="info",
                stage=BaselineStage.MATURE,
                tier=TrafficTier.B,
                history_start=T0 - dt.timedelta(days=42),
                limited_by=None,
                buckets=[
                    ScanBucket(
                        time=T0,
                        observed=120.0,
                        expected=100.0,
                        lower=60.0,
                        upper=150.0,
                        stage=BaselineStage.MATURE,
                        verdict=None,
                    )
                ],
            )
        ],
        "issues": [
            ScanIssue(
                direction=Direction.UP,
                severity="info",
                kind=VerdictType.SPIKE,
                state=IssueState.ACTIVE,
                opened_at=T0 + dt.timedelta(minutes=10),
                last_anomalous_at=T0 + dt.timedelta(minutes=30),
                resolved_at=None,
                anomalous_bucket_times=[T0 + dt.timedelta(minutes=10)],
            )
        ],
    }
    defaults.update(overrides)
    return ScanResult(**defaults)


class TestScanRequestValidation(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "missing_service",
                {"dateRange": {"date_from": "2026-06-01T00:00:00Z", "date_to": "2026-06-02T00:00:00Z"}},
            ),
            ("missing_window", {"serviceName": "svc"}),
            (
                "inverted_window",
                {
                    "serviceName": "svc",
                    "dateRange": {"date_from": "2026-06-02T00:00:00Z", "date_to": "2026-06-01T00:00:00Z"},
                },
            ),
            (
                "window_over_seven_days",
                {
                    "serviceName": "svc",
                    "dateRange": {"date_from": "2026-06-01T00:00:00Z", "date_to": "2026-06-09T00:00:00Z"},
                },
            ),
        ]
    )
    def test_invalid_payloads(self, _name: str, payload: dict) -> None:
        serializer = LogsAnomalyScanRequestSerializer(data=payload)
        assert not serializer.is_valid()

    def test_valid_payload(self) -> None:
        serializer = LogsAnomalyScanRequestSerializer(
            data={
                "serviceName": "svc",
                "dateRange": {"date_from": "2026-06-01T00:00:00Z", "date_to": "2026-06-02T00:00:00Z"},
            }
        )
        assert serializer.is_valid(), serializer.errors


class TestLogsAnomalyScanAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/logs/anomalies/scan/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _payload(self) -> dict:
        return {
            "serviceName": "svc",
            "dateRange": {"date_from": "2026-06-01T12:00:00Z", "date_to": "2026-06-01T13:00:00Z"},
        }

    def test_flag_off_is_forbidden(self):
        self._ff_patcher.stop()
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.post(self.url, self._payload(), format="json")
        self._ff_patcher.start()
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_invalid_body_is_rejected_before_scanning(self):
        with patch("products.logs.backend.presentation.views.anomalies_api.run_scan") as run:
            response = self.client.post(self.url, {"serviceName": "svc"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        run.assert_not_called()

    def test_scan_response_shape(self):
        with patch(
            "products.logs.backend.presentation.views.anomalies_api.run_scan", return_value=_scan_result()
        ) as run:
            response = self.client.post(self.url, self._payload(), format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        run.assert_called_once()
        data = response.json()
        assert data["service_name"] == "svc"
        assert data["binding_constraints"] == []
        assert data["lookback_days"] == 42.0
        series = data["series"][0]
        assert series["severity"] == "info"
        assert series["buckets"][0]["observed"] == 120.0
        assert series["buckets"][0]["verdict"] is None
        issue = data["issues"][0]
        assert issue["direction"] == "up"
        assert issue["state"] == "active"
        assert issue["resolved_at"] is None

    def test_repeat_scan_is_served_from_cache(self):
        with patch(
            "products.logs.backend.presentation.views.anomalies_api.run_scan", return_value=_scan_result()
        ) as run:
            first = self.client.post(self.url, self._payload(), format="json")
            second = self.client.post(self.url, self._payload(), format="json")

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        run.assert_called_once()
        assert first.json() == second.json()

    def test_budget_exhaustion_returns_422(self):
        with patch(
            "products.logs.backend.presentation.views.anomalies_api.run_scan",
            side_effect=ScanBudgetExceeded("over budget"),
        ):
            response = self.client.post(self.url, self._payload(), format="json")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestLogsSeriesBandsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/logs/anomalies/series_bands/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def test_invalid_body_is_rejected_before_querying(self):
        with patch("products.logs.backend.presentation.views.anomalies_api.run_series_bands") as run:
            response = self.client.post(self.url, {}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        run.assert_not_called()

    def test_response_shape(self):
        result = SeriesBandsResult(
            service_name="svc",
            window_start=T0 - dt.timedelta(days=7),
            window_end=T0,
            interval_minutes=60,
            series_truncated=False,
            series=[
                BandSeries(
                    namespace="ns",
                    environment="prod",
                    severity="error",
                    total_count=25,
                    baseline_weeks=5,
                    buckets=[BandBucket(time=T0 - dt.timedelta(hours=1), observed=25, lower=9.0, upper=57.0)],
                )
            ],
        )
        with patch(
            "products.logs.backend.presentation.views.anomalies_api.run_series_bands", return_value=result
        ) as run:
            response = self.client.post(self.url, {"serviceName": "svc"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        run.assert_called_once_with(self.team, "svc", interval_minutes=60)
        data = response.json()
        assert data["service_name"] == "svc"
        assert data["interval_minutes"] == 60
        assert data["series_truncated"] is False
        series = data["series"][0]
        assert (series["namespace"], series["environment"], series["severity"]) == ("ns", "prod", "error")
        assert series["baseline_weeks"] == 5
        assert series["buckets"][0] == {
            "time": (T0 - dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "observed": 25,
            "lower": 9.0,
            "upper": 57.0,
        }

    def test_truncated_fetch_returns_422(self):
        with patch(
            "products.logs.backend.presentation.views.anomalies_api.run_series_bands",
            side_effect=SeriesBandsFetchTruncated("too many rows"),
        ):
            response = self.client.post(self.url, {"serviceName": "svc"}, format="json")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
