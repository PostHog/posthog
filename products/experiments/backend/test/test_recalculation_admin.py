from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.cache import SessionStore
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from parameterized import parameterized

from products.experiments.backend.admin.recalculation_admin import ExperimentMetricsRecalculationAdmin
from products.experiments.backend.admin.recalculation_panel import build_recalculation_panel, format_duration
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.recalculation import _recalc_fingerprints_for_run
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _mean_metric(uuid: str, name: str | None = None) -> dict:
    metric: dict = {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase"},
    }
    if name is not None:
        metric["name"] = name
    return metric


_BASE = datetime(2026, 1, 1, tzinfo=UTC)


class TestFormatDuration:
    @parameterized.expand(
        [
            ("sub_minute", 45, "45s"),
            ("minutes_and_seconds", 250, "4m 10s"),
            ("exact_minute_drops_seconds", 120, "2m"),
            ("zero_reads_as_seconds", 0, "0s"),
            ("hours", 3661, "1h 1m 1s"),
        ]
    )
    def test_formats_elapsed(self, _name: str, elapsed_seconds: int, expected: str) -> None:
        assert format_duration(_BASE, _BASE + timedelta(seconds=elapsed_seconds)) == expected

    @parameterized.expand([("missing_start", None, _BASE), ("missing_end", _BASE, None)])
    def test_missing_bound_is_none(self, _name: str, started: datetime | None, completed: datetime | None) -> None:
        assert format_duration(started, completed) is None

    def test_negative_duration_is_none(self) -> None:
        assert format_duration(_BASE + timedelta(seconds=10), _BASE) is None


@pytest.mark.django_db(transaction=True)
class TestRecalculationAdminPanel(BaseTest):
    def _launched_experiment(self) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="admin-panel-flag",
            name="Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        exp = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="exp",
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        exp.metrics = [_mean_metric("m-named", name="Signups"), _mean_metric("m-discovery")]
        exp.save()
        return exp

    def test_failures_prefer_metric_errors_and_include_discovery_only(self) -> None:
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.FAILED,
            total_metrics=2,
            metric_uuids=["m-named", "m-discovery"],
            # m-discovery failed in discovery (no result row); m-named has a metric_errors entry that must
            # win over any result-row message.
            metric_errors={
                "m-named": {"message": "row-level query failed"},
                "m-discovery": {"message": "metric could not be resolved"},
            },
            started_at=datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 1, 2, 10, 4, 10, tzinfo=UTC),
        )

        panel = build_recalculation_panel(recalc)

        assert panel["has_failures"] is True
        assert panel["duration_human"] == "4m 10s"
        by_uuid = {f["metric_uuid"]: f for f in panel["failures"]}
        # metric_errors message wins, and a named metric shows its name not its uuid.
        assert by_uuid["m-named"]["error"] == "row-level query failed"
        assert by_uuid["m-named"]["metric_name"] == "Signups"
        # a discovery-only failure with no result row is still surfaced.
        assert by_uuid["m-discovery"]["error"] == "metric could not be resolved"

    def test_failure_falls_back_to_result_row_message(self) -> None:
        exp = self._launched_experiment()
        query_to = datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC)
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.FAILED,
            total_metrics=2,
            metric_uuids=["m-named"],
            metric_errors={},
            query_to=query_to,
            started_at=datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 1, 2, 10, 0, 30, tzinfo=UTC),
        )
        # No metric_errors entry, so the failure text comes from the FAILED result row's error_message.
        fingerprints = _recalc_fingerprints_for_run(exp, recalc)
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m-named",
            fingerprint=fingerprints["m-named"],
            query_from=datetime(2026, 1, 1, tzinfo=UTC),
            query_to=query_to,
            status=ExperimentMetricResult.Status.FAILED,
            error_message="timeout in ClickHouse",
        )

        panel = build_recalculation_panel(recalc)

        by_uuid = {f["metric_uuid"]: f for f in panel["failures"]}
        assert by_uuid["m-named"]["error"] == "timeout in ClickHouse"

    @patch("products.experiments.backend.admin.recalculation_panel.start_metrics_recalculation_workflow")
    def test_retry_failures_reuses_window_and_redirects_to_new_run(self, mock_start: MagicMock) -> None:
        exp = self._launched_experiment()
        prior = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.FAILED,
            total_metrics=2,
            metric_uuids=["m-named", "m-discovery"],
            metric_errors={"m-discovery": {"message": "boom"}},
            started_at=datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 1, 2, 10, 4, 10, tzinfo=UTC),
        )

        admin = ExperimentMetricsRecalculationAdmin(ExperimentMetricsRecalculation, AdminSite())
        request = RequestFactory().post("/")
        request.user = self.user
        # A bare RequestFactory request has no message store; the success path calls messages.success.
        request.session = SessionStore()
        request._messages = FallbackStorage(request)  # type: ignore[attr-defined]
        with patch.object(admin, "has_change_permission", return_value=True):
            response = admin.retry_failures_view(request, str(prior.pk))

        # A metric-scoped trigger reuses the prior window, so only failed metrics recompute.
        new_run = (
            ExperimentMetricsRecalculation.objects.filter(experiment=exp)
            .exclude(pk=prior.pk)
            .order_by("-created_at")
            .first()
        )
        assert new_run is not None
        assert new_run.trigger == ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE
        assert str(new_run.pk) in response.url
        mock_start.assert_called_once()

    @patch("products.experiments.backend.admin.recalculation_panel.start_metrics_recalculation_workflow")
    def test_retry_failures_denied_without_change_permission(self, mock_start: MagicMock) -> None:
        exp = self._launched_experiment()
        prior = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            status=ExperimentMetricsRecalculation.Status.FAILED,
            total_metrics=1,
            metric_uuids=["m-named"],
            metric_errors={"m-named": {"message": "boom"}},
            started_at=datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 1, 2, 10, 4, 10, tzinfo=UTC),
        )

        admin = ExperimentMetricsRecalculationAdmin(ExperimentMetricsRecalculation, AdminSite())
        request = RequestFactory().post("/")
        request.user = self.user
        with patch.object(admin, "has_change_permission", return_value=False), pytest.raises(PermissionDenied):
            admin.retry_failures_view(request, str(prior.pk))

        assert not ExperimentMetricsRecalculation.objects.filter(experiment=exp).exclude(pk=prior.pk).exists()
        mock_start.assert_not_called()
