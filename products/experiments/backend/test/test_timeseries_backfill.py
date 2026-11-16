import datetime
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ExperimentQueryResponse, ExperimentStatsBaseValidated, ExperimentVariantResultFrequentist

from posthog.models import Organization, Team, User

from products.experiments.backend.metric_calculation.config import get_metric_calculation_config
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentTimeseriesRecalculation,
)
from products.experiments.backend.timeseries_backfill import backfill_experiment_timeseries
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@pytest.mark.django_db
class TestBackfillExperimentTimeseries(BaseTest):
    def test_backfill_processes_all_days_and_creates_correct_records(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team", timezone="America/New_York")
        user = User.objects.create(email="test@example.com")

        flag = FeatureFlag.objects.create(team=team, key="test-flag", created_by=user)
        metric_data = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "uuid": "test-metric-uuid",
            "source": {"kind": "EventsNode", "event": "test_event"},
        }
        experiment = Experiment.objects.create(
            name="Test Experiment",
            team=team,
            feature_flag=flag,
            start_date=datetime.datetime(2024, 12, 25, 10, 0, 0, tzinfo=ZoneInfo("UTC")),
            end_date=datetime.datetime(2024, 12, 27, 10, 0, 0, tzinfo=ZoneInfo("UTC")),
            metrics=[metric_data],
        )
        calculation_config = get_metric_calculation_config(experiment, "test-metric-uuid")
        assert calculation_config is not None

        recalculation_request = ExperimentTimeseriesRecalculation.objects.create(
            team=team,
            experiment=experiment,
            metric=metric_data,
            fingerprint=calculation_config.calculation_key(),
            status=ExperimentTimeseriesRecalculation.Status.PENDING,
        )

        mock_result = ExperimentQueryResponse(
            baseline=ExperimentStatsBaseValidated(key="control", number_of_samples=100, sum=1000, sum_squares=10000),
            variant_results=[
                ExperimentVariantResultFrequentist(
                    key="test", number_of_samples=110, sum=1100, sum_squares=11000, significant=False
                )
            ],
        )

        with patch("products.experiments.backend.timeseries_backfill.ExperimentQueryRunner") as mock_query_runner_class:
            mock_query_runner = MagicMock()
            mock_query_runner.calculation_config = calculation_config
            mock_query_runner._calculate.return_value = mock_result
            mock_query_runner_class.return_value = mock_query_runner

            result = backfill_experiment_timeseries(str(recalculation_request.id))

        recalculation_request.refresh_from_db()
        assert recalculation_request.status == ExperimentTimeseriesRecalculation.Status.COMPLETED
        assert recalculation_request.last_successful_date == datetime.date(2024, 12, 27)

        metric_results = ExperimentMetricResult.objects.filter(
            experiment=experiment, metric_uuid="test-metric-uuid"
        ).order_by("query_to")

        assert len(metric_results) == 3

        # NYC is UTC-5 in December, so end-of-day boundaries are shifted
        expected_dates_utc = [
            datetime.datetime(2024, 12, 26, 5, 0, 0, tzinfo=ZoneInfo("UTC")),  # End of Dec 25 in EST
            datetime.datetime(2024, 12, 27, 5, 0, 0, tzinfo=ZoneInfo("UTC")),  # End of Dec 26 in EST
            datetime.datetime(2024, 12, 28, 5, 0, 0, tzinfo=ZoneInfo("UTC")),  # End of Dec 27 in EST
        ]

        for i, metric_result in enumerate(metric_results):
            assert metric_result.query_to == expected_dates_utc[i]
            assert metric_result.query_from == experiment.start_date
            assert metric_result.status == ExperimentMetricResult.Status.COMPLETED
            assert metric_result.result == mock_result.model_dump()
            assert metric_result.display_key == calculation_config.legacy_key()

        assert result["recalculation_id"] == str(recalculation_request.id)
        assert result["experiment_id"] == experiment.id
        assert result["metric_uuid"] == "test-metric-uuid"
        assert result["days_processed"] == 3
        assert result["start_date"] == "2024-12-25"
        assert result["end_date"] == "2024-12-27"

    def test_backfill_until_caps_running_experiment_at_given_date(self):
        # A running experiment (no end_date) otherwise backfills through the real today —
        # demo seeding passes its simulated clock so days without data are never queried.
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team", timezone="UTC")
        user = User.objects.create(email="test-cap@example.com")

        flag = FeatureFlag.objects.create(team=team, key="test-cap-flag", created_by=user)
        experiment = Experiment.objects.create(
            name="Running Experiment",
            team=team,
            feature_flag=flag,
            start_date=datetime.datetime(2024, 10, 25, 10, 0, 0, tzinfo=ZoneInfo("UTC")),
            end_date=None,
        )

        recalculation_request = ExperimentTimeseriesRecalculation.objects.create(
            team=team,
            experiment=experiment,
            metric={
                "metric_type": "mean",
                "uuid": "test-metric-uuid",
                "source": {"kind": "EventsNode", "event": "test_event"},
            },
            fingerprint="test-fingerprint",
            status=ExperimentTimeseriesRecalculation.Status.PENDING,
        )

        experiment.metrics = [recalculation_request.metric]
        experiment.save()
        calculation_config = get_metric_calculation_config(experiment, "test-metric-uuid")
        assert calculation_config is not None
        recalculation_request.fingerprint = calculation_config.calculation_key()
        recalculation_request.save()

        mock_result = ExperimentQueryResponse(
            baseline=ExperimentStatsBaseValidated(key="control", number_of_samples=100, sum=1000, sum_squares=10000),
            variant_results=[],
        )

        with patch("products.experiments.backend.timeseries_backfill.ExperimentQueryRunner") as mock_query_runner_class:
            mock_query_runner = MagicMock()
            mock_query_runner.calculation_config = calculation_config
            mock_query_runner._calculate.return_value = mock_result
            mock_query_runner_class.return_value = mock_query_runner

            result = backfill_experiment_timeseries(
                str(recalculation_request.id), backfill_until=datetime.date(2024, 10, 27)
            )

        assert result["days_processed"] == 3
        assert result["end_date"] == "2024-10-27"
        recalculation_request.refresh_from_db()
        assert recalculation_request.status == ExperimentTimeseriesRecalculation.Status.COMPLETED
        assert recalculation_request.last_successful_date == datetime.date(2024, 10, 27)

    @parameterized.expand(
        [
            ("before_start", 1),
            ("before_query", 1),
            ("between_days", 1),
            ("superseded_during_query", 1),
            ("superseded_then_query_fails", 1),
            ("between_days", 2),
            ("unchanged", 2),
        ]
    )
    def test_settings_drift_and_supersession_do_not_write_mislabeled_results(
        self, moment: str, key_version: int
    ) -> None:
        # A version 2 request runs on a worker whose new operations use version 1. It keeps its own key version.
        metric = {"uuid": "m1", "metric_type": "mean", "source": {"kind": "EventsNode", "event": "$pageview"}}
        flag = FeatureFlag.objects.create(team=self.team, key="drift-flag", created_by=self.user)
        experiment = Experiment.objects.create(
            team=self.team,
            feature_flag=flag,
            metrics=[metric],
            start_date=datetime.datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
            end_date=datetime.datetime(2024, 1, 3, tzinfo=ZoneInfo("UTC")),
        )
        config = get_metric_calculation_config(experiment, "m1")
        assert config is not None
        key = config.key_for_version(key_version)
        request = ExperimentTimeseriesRecalculation.objects.create(
            team=self.team, experiment=experiment, metric=metric, fingerprint=key
        )
        result = ExperimentQueryResponse(
            baseline=ExperimentStatsBaseValidated(key="control", number_of_samples=100, sum=1000, sum_squares=10000),
            variant_results=[],
        )

        def change_settings() -> None:
            # Both key versions hash the stats method.
            experiment.stats_config = {"method": "frequentist"}
            experiment.save()

        def calculate() -> ExperimentQueryResponse:
            if moment == "between_days":
                change_settings()
            if moment.startswith("superseded"):
                ExperimentTimeseriesRecalculation.objects.filter(id=request.id).update(status="canceled")
            if moment == "superseded_then_query_fails":
                raise RuntimeError("query failed")
            return result

        def runner(**kwargs):
            if moment == "before_query":
                change_settings()
            mock = MagicMock()
            mock.calculation_config = get_metric_calculation_config(Experiment.objects.get(id=experiment.id), "m1")
            mock._calculate.side_effect = calculate
            return mock

        if moment == "before_start":
            change_settings()
        with patch("products.experiments.backend.timeseries_backfill.ExperimentQueryRunner", side_effect=runner):
            if moment == "superseded_then_query_fails":
                with pytest.raises(RuntimeError):
                    backfill_experiment_timeseries(str(request.id))
                output = {"days_processed": 0}
            else:
                output = backfill_experiment_timeseries(str(request.id))
            # A Temporal retry of the activity must not start a canceled request again.
            retried = backfill_experiment_timeseries(str(request.id)) if moment != "unchanged" else None
        request.refresh_from_db()
        assert request.status == ("completed" if moment == "unchanged" else "canceled")
        if retried is not None:
            assert retried["days_processed"] == 0
        written_days = {"between_days": 1, "unchanged": 3}.get(moment, 0)
        assert output["days_processed"] == written_days
        rows = ExperimentMetricResult.objects.filter(experiment=experiment)
        assert rows.count() == written_days
        assert {(row.fingerprint, row.display_key) for row in rows} <= {(key, config.legacy_key())}
