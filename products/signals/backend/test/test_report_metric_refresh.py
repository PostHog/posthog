from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.schema import ChartDisplayType

from posthog.constants import AvailableFeature

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.product_analytics.backend.facade.contracts import TrendsQueryRunResult
from products.signals.backend.models import SignalReport
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy
from products.signals.backend.report_metric_refresh import (
    MAX_METRIC_SERIES_POINTS,
    MetricMeasurement,
    _persist_metric_snapshot,
    longitudinal_values,
    measure_metric,
    refresh_report_metric_snapshots,
    whole_window_value,
)
from products.signals.backend.serializers import SignalReportMetricRefreshRequestSerializer
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query

_MEASURE = "products.signals.backend.report_metric_refresh.measure_metric"


def _metric(
    *,
    metric_id: str = "affected-users",
    kind: str = "affected_users",
    role: str = "primary",
    event: str = "$exception",
    value: float | None = 17,
    value_at: str | None = "2026-08-29T12:00:00Z",
) -> dict:
    series = [{"kind": "EventsNode", "event": event, "math": "dau" if kind == "affected_users" else "total"}]
    return {
        "metric_id": metric_id,
        "title": "Affected users" if kind == "affected_users" else "Occurrences",
        "kind": kind,
        "role": role,
        "value": value,
        "value_at": value_at,
        "value_format": "count",
        "unit": "users",
        "query": trends_metric_query(series=series, date_from="-14d"),
        "caption": None,
        "comparison": None,
    }


def _measurement(value: float = 21, *, measured_at: datetime | None = None) -> MetricMeasurement:
    return MetricMeasurement(value=value, measured_at=measured_at or timezone.now(), series=[1.0, 2.0, 3.0])


class TestReportMetricRefreshRequestValidation(SimpleTestCase):
    def test_rejects_more_than_one_page_of_ids(self) -> None:
        serializer = SignalReportMetricRefreshRequestSerializer(
            data={"report_ids": [f"00000000-0000-4000-8000-{i:012d}" for i in range(21)]}
        )
        assert not serializer.is_valid()
        assert serializer.errors["report_ids"][0].code == "max_length"


class TestReportMetricRefreshApi(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/reports/refresh_metrics/"

    def _report(self, **kwargs) -> SignalReport:
        defaults = {
            "team": self.team,
            "status": SignalReport.Status.READY,
            "title": "Impact report",
            "summary": "A point-in-time description",
            "metrics": [_metric()],
        }
        defaults.update(kwargs)
        return SignalReport.objects.create(**defaults)

    def _refresh(self, *reports: SignalReport):
        return self.client.post(self._url(), {"report_ids": [str(report.id) for report in reports]}, format="json")

    def test_refresh_replaces_only_the_numbers_and_returns_snapshots(self) -> None:
        report = self._report()
        before = SignalReport.objects.get(id=report.id)
        measured_at = timezone.now().replace(microsecond=0)

        with patch(_MEASURE, return_value=_measurement(21, measured_at=measured_at)) as measure:
            response = self._refresh(report)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert measure.call_count == 1
        [row] = response.json()["reports"]
        assert row["id"] == str(report.id)
        assert row["metrics"][0]["value"] == 21.0
        assert row["metrics"][0]["series"] == [1.0, 2.0, 3.0]
        assert "query" not in row["metrics"][0]
        assert "comparison" not in row["metrics"][0]

        after = SignalReport.objects.get(id=report.id)
        assert after.metrics[0]["value"] == 21.0
        assert after.metrics[0]["value_at"] == measured_at.isoformat()
        assert after.metrics[0]["query"] == before.metrics[0]["query"]
        assert (after.title, after.summary, after.updated_at) == (before.title, before.summary, before.updated_at)

    def test_fresh_snapshot_is_served_without_a_query(self) -> None:
        recent = (timezone.now() - timedelta(minutes=1)).isoformat()
        report = self._report(metrics=[_metric(value_at=recent)])

        with patch(_MEASURE) as measure:
            response = self._refresh(report)

        assert response.status_code == status.HTTP_200_OK
        measure.assert_not_called()
        assert response.json()["reports"][0]["metrics"][0]["value"] == 17.0

    def test_row_metrics_refresh_before_supporting_metrics_when_the_budget_runs_out(self) -> None:
        first = self._report(
            metrics=[
                _metric(metric_id="occurrences", kind="occurrences", role="supporting"),
                _metric(metric_id="affected-users", role="supporting"),
            ]
        )
        second = self._report(metrics=[_metric(metric_id="primary", kind="occurrences", role="primary")])

        with (
            patch("products.signals.backend.report_metric_refresh.MAX_REPORT_METRIC_SOURCE_RUNS_PER_REQUEST", 4),
            patch(_MEASURE, return_value=_measurement(5)) as measure,
        ):
            response = self._refresh(first, second)

        assert response.status_code == status.HTTP_200_OK
        assert measure.call_count == 2
        refreshed = {
            (row["id"], metric["metric_id"]): metric["value"]
            for row in response.json()["reports"]
            for metric in row["metrics"]
        }
        assert refreshed[(str(first.id), "affected-users")] == 5.0
        assert refreshed[(str(second.id), "primary")] == 5.0
        assert refreshed[(str(first.id), "occurrences")] == 17.0

    @parameterized.expand(
        [
            ("query_failure", RuntimeError("clickhouse down")),
            ("invalid_count", _measurement(2.5)),
        ]
    )
    def test_a_failed_or_invalid_measurement_keeps_the_previous_snapshot(self, _name: str, outcome: object) -> None:
        report = self._report()
        kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}

        with patch(_MEASURE, **kwargs):
            response = self._refresh(report)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["reports"][0]["metrics"][0]["value"] == 17.0
        assert SignalReport.objects.get(id=report.id).metrics[0]["value"] == 17

    def test_property_restricted_member_cannot_trigger_a_shared_refresh(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        property_definition = PropertyDefinition.objects.create(
            team=self.team, name="secret_plan", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=property_definition,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        report = self._report()

        with patch(_MEASURE) as measure:
            response = self._refresh(report)

        assert response.status_code == status.HTTP_200_OK
        measure.assert_not_called()
        assert response.json()["reports"][0]["metrics"][0]["value"] is None
        assert SignalReport.objects.get(id=report.id).metrics[0]["value"] == 17

    def test_an_edit_landing_during_the_refresh_is_what_the_response_returns(self) -> None:
        report = self._report()
        edited = [_metric(event="$pageview", value=5, value_at="2026-08-30T12:00:00Z")]

        def edit_then_measure(*args, **kwargs) -> MetricMeasurement:
            SignalReport.objects.filter(id=report.id).update(metrics=edited)
            return _measurement(21)

        with patch(_MEASURE, side_effect=edit_then_measure):
            response = self._refresh(report)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert SignalReport.objects.get(id=report.id).metrics == edited
        [row] = response.json()["reports"]
        assert row["metrics"][0]["value"] == 5.0

    def test_reports_that_are_not_current_are_left_out(self) -> None:
        archived = self._report(status=SignalReport.Status.SUPPRESSED)
        current = self._report()

        with patch(_MEASURE, return_value=_measurement(3)):
            response = self._refresh(archived, current)

        assert [row["id"] for row in response.json()["reports"]] == [str(current.id)]

    def test_a_metric_refreshed_earlier_in_the_call_does_not_block_the_next_one(self) -> None:
        report = self._report(
            metrics=[_metric(), _metric(metric_id="occurrences", kind="occurrences", role="supporting")]
        )

        with patch(_MEASURE, return_value=_measurement(4)):
            self._refresh(report)

        assert [metric["value"] for metric in SignalReport.objects.get(id=report.id).metrics] == [4.0, 4.0]

    def test_personal_api_key_refresh_enters_query_service_protection(self) -> None:
        report = self._report()
        key = self.create_personal_api_key_with_scopes(["task:read", "query:read", "event_definition:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        with patch(
            "products.product_analytics.backend.hogql_queries.trends.trends_query_runner.TrendsQueryRunner"
        ) as runner_type:
            runner_type.return_value.run.return_value = type(
                "Response",
                (),
                {"results": [{"aggregated_value": 21, "data": [19, 20, 21]}], "last_refresh": timezone.now()},
            )()
            response = self._refresh(report)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert runner_type.return_value.is_query_service is True


class TestPersistMetricSnapshot(APIBaseTest):
    def _report(self) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", metrics=[_metric()]
        )

    def test_concurrent_edit_wins_over_a_measurement_of_the_old_definition(self) -> None:
        report = self._report()
        edited = [_metric(event="$pageview")]
        SignalReport.objects.filter(id=report.id).update(metrics=edited)

        result = _persist_metric_snapshot(
            team_id=self.team.id,
            report_id=str(report.id),
            expected_metrics=[_metric()],
            metric_id="affected-users",
            measurement=_measurement(99),
        )

        assert result is None
        assert SignalReport.objects.get(id=report.id).metrics == edited

    def test_older_cached_measurement_does_not_replace_a_newer_snapshot(self) -> None:
        report = self._report()

        result = _persist_metric_snapshot(
            team_id=self.team.id,
            report_id=str(report.id),
            expected_metrics=report.metrics,
            metric_id="affected-users",
            measurement=_measurement(99, measured_at=datetime(2026, 8, 29, 11, 0, tzinfo=UTC)),
        )

        assert result is None
        assert SignalReport.objects.get(id=report.id).metrics[0]["value"] == 17

    def test_naive_saved_timestamp_is_compared_as_utc(self) -> None:
        report = self._report()
        metrics = [{**report.metrics[0], "value_at": "2026-08-30T12:00:00"}]
        SignalReport.objects.filter(id=report.id).update(metrics=metrics)

        result = _persist_metric_snapshot(
            team_id=self.team.id,
            report_id=str(report.id),
            expected_metrics=metrics,
            metric_id="affected-users",
            measurement=_measurement(99, measured_at=datetime(2026, 8, 29, 11, 0, tzinfo=UTC)),
        )

        assert result is None
        assert SignalReport.objects.get(id=report.id).metrics[0]["value"] == 17


class TestRefreshSkipsUnreadableSnapshots(APIBaseTest):
    def test_policy_gate_is_applied_per_metric(self) -> None:
        report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="t", summary="s", metrics=[_metric()]
        )
        policy = ReportMetricAccessPolicy(request=None, team=self.team)

        with patch(_MEASURE) as measure:
            summary = refresh_report_metric_snapshots(team=self.team, reports=[report], policy=policy)

        measure.assert_not_called()
        assert (summary.refreshed, summary.skipped, summary.failed) == (0, 1, 0)


class TestReportMetricQueryShapes(APIBaseTest):
    def test_uses_the_aggregate_for_the_value_and_trailing_buckets_for_the_series(self) -> None:
        measured_at = timezone.now()
        query = _metric(event="metric-refresh-event")["query"]
        with patch(
            "products.signals.backend.report_metric_refresh.run_cached_trends_query",
            side_effect=[
                TrendsQueryRunResult(results=[{"aggregated_value": 2.0}], last_refresh=measured_at),
                TrendsQueryRunResult(results=[{"data": list(range(17))}], last_refresh=measured_at),
            ],
        ) as run_query:
            value, refreshed_at = whole_window_value(query, self.team)
            series = longitudinal_values(query, self.team)

        assert value == 2
        assert refreshed_at == measured_at
        assert len(series) == MAX_METRIC_SERIES_POINTS
        assert series == [float(value) for value in range(3, 17)]
        assert run_query.call_args_list[0].kwargs["query"]["trendsFilter"]["display"] == ChartDisplayType.BOLD_NUMBER
        assert run_query.call_args_list[1].kwargs["query"]["trendsFilter"]["display"] == ChartDisplayType.ACTIONS_BAR

    def test_passes_the_snapshot_cache_age_to_both_shapes(self) -> None:
        response = TrendsQueryRunResult(results=[{"aggregated_value": 2.0}], last_refresh=timezone.now())
        with patch(
            "products.signals.backend.report_metric_refresh.run_cached_trends_query", return_value=response
        ) as run_query:
            whole_window_value(_metric()["query"], self.team)

        assert run_query.call_args.kwargs["cache_age_seconds"] == 15 * 60

    def test_skips_the_strip_when_the_deadline_passes_after_the_headline(self) -> None:
        measured_at = timezone.now()
        with (
            patch(
                "products.signals.backend.report_metric_refresh.whole_window_value",
                return_value=(2.0, measured_at),
            ),
            patch("products.signals.backend.report_metric_refresh.time.monotonic", return_value=10.0),
            patch("products.signals.backend.report_metric_refresh.longitudinal_values") as strip,
        ):
            measurement = measure_metric(_metric()["query"], self.team, deadline=10.0, include_series=True)

        assert measurement.series is None
        strip.assert_not_called()

    def test_multiple_source_series_spend_source_run_budget(self) -> None:
        multi_source = _metric()
        multi_source["kind"] = "custom"
        multi_source["query"] = trends_metric_query(
            series=[{"kind": "EventsNode", "event": f"event-{index}", "math": "total"} for index in range(3)],
            date_from="-14d",
        )
        multi_source["query"]["source"]["trendsFilter"] = {"formula": "A+B+C"}
        report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="t",
            summary="s",
            metrics=[multi_source, _metric(metric_id="second")],
        )
        policy = type("ReadablePolicy", (), {"may_read_snapshot": lambda self, metric: True})()

        with (
            patch("products.signals.backend.report_metric_refresh.MAX_REPORT_METRIC_SOURCE_RUNS_PER_REQUEST", 3),
            patch(_MEASURE, return_value=_measurement()) as measure,
        ):
            summary = refresh_report_metric_snapshots(team=self.team, reports=[report], policy=policy)

        assert measure.call_count == 1
        assert (summary.refreshed, summary.skipped) == (1, 1)
        saved = SignalReport.objects.get(id=report.id).metrics
        assert saved[0]["value"] == 17
        assert saved[1]["value"] == 21
