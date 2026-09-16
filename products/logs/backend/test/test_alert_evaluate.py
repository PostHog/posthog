from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts.backend.models import WIPAlert, WIPAlertConfiguration
from products.logs.backend.alert_check_query import BatchedBucketedResult, BucketedCount
from products.logs.backend.alert_source_cycle import evaluate_logs_batch
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent

_MODULE = "products.logs.backend.alert_source_cycle"
_LOGS_OWNED_FIELDS = ("state", "consecutive_failures", "next_check_at", "last_notified_at", "snooze_until")


class TestLogsAlertEvaluation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 16, 10, tzinfo=UTC)

    def _configuration(self, **overrides) -> WIPAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "API errors",
            "source_kind": WIPAlertConfiguration.SourceKind.LOGS,
            "source_config": {},
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "check_interval_minutes": 10,
            "next_check_at": self.cutoff - timedelta(minutes=1),
        }
        defaults.update(overrides)
        with team_scope(self.team.id):
            return WIPAlertConfiguration.objects.create(**defaults)

    def _run(self, *configurations: WIPAlertConfiguration):
        breaching = {str(c.id): [BucketedCount(timestamp=self.cutoff, count=500)] for c in configurations}
        with (
            patch(f"{_MODULE}.fetch_live_logs_checkpoint", return_value=None),
            patch(f"{_MODULE}.BatchedAlertCheckQuery") as query,
        ):
            query.return_value.execute_rolling_checks.return_value = BatchedBucketedResult(
                per_alert=breaching, query_duration_ms=1
            )
            slot = (configurations[0].next_check_at or self.cutoff).replace(second=0, microsecond=0).isoformat()
            with team_scope(self.team.id):
                return evaluate_logs_batch(self.team.id, slot, self.cutoff), query

    def test_a_breaching_configuration_fires_and_records_its_own_state(self) -> None:
        configuration = self._configuration()

        previews, _ = self._run(configuration)

        assert [t.notification for preview in previews for t in preview.transitions] == ["fire"]
        with team_scope(self.team.id):
            alert = WIPAlert.objects.get(configuration=configuration, grouping_key="")
            configuration.refresh_from_db()
        assert alert.state == WIPAlert.State.FIRING
        assert alert.last_notified_at is not None
        # The schedule advanced, so the next tick does not rediscover this configuration.
        assert configuration.next_check_at is not None
        assert configuration.next_check_at > self.cutoff

    def test_the_logs_product_rows_are_never_written(self) -> None:
        legacy = LogsAlertConfiguration.objects.create(
            team=self.team,
            name="API errors",
            threshold_count=10,
            threshold_operator="above",
            window_minutes=5,
            filters={},
            next_check_at=self.cutoff - timedelta(minutes=1),
        )
        before = LogsAlertConfiguration.objects.values(*_LOGS_OWNED_FIELDS).get(id=legacy.id)

        self._run(self._configuration(legacy_configuration_id=legacy.id))

        # The logs fleet evaluates this same alert on its own queue. Writing its rows here would
        # transition an alert twice and notify a person twice for one breach.
        assert LogsAlertConfiguration.objects.values(*_LOGS_OWNED_FIELDS).get(id=legacy.id) == before
        assert not LogsAlertEvent.objects.filter(alert=legacy).exists()

    @parameterized.expand([("single_period", 1, 5), ("three_periods", 3, 25)])
    def test_the_scanned_range_covers_every_rolling_window(
        self, _name: str, evaluation_periods: int, expected_lookback_minutes: int
    ) -> None:
        configuration = self._configuration(evaluation_periods=evaluation_periods, check_interval_minutes=10)

        _, query = self._run(configuration)

        kwargs = query.call_args.kwargs
        assert kwargs["date_to"] - kwargs["date_from"] == timedelta(minutes=expected_lookback_minutes)

    def test_the_evaluation_key_comes_from_the_tick_occasion_not_the_clock(self) -> None:
        configuration = self._configuration(next_check_at=None)

        previews, _ = self._run(configuration)

        assert [p.evaluation_key for p in previews] == [f"{configuration.id}:window:{self.cutoff.isoformat()}"]
