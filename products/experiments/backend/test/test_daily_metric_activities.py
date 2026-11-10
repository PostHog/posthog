from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import time_machine
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import EventsNode, ExperimentMeanMetric

from posthog.models.team.extensions import get_or_create_team_extension
from posthog.temporal.experiments.activities import (
    _calculate_experiment_regular_metric_sync,
    _calculate_experiment_saved_metric_sync,
)
from posthog.temporal.experiments.models import TIMESERIES_METRIC_MAX_ATTEMPTS

from products.experiments.backend.facade.enums import ExperimentResultConfigurationStatus
from products.experiments.backend.facade.timeseries import metric_calculation_keys
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from products.experiments.backend.metric_calculation.config import get_metric_calculation_config
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

# A recalculation of the experiment can hold the daily window under its own fingerprint. The daily write must take
# that row over instead of failing on the (experiment, metric_uuid, query_to) unique constraint.
_WINDOW_HOLDERS = [("free_window", None), ("window_held_by_another_fingerprint", "recalculation-fingerprint")]


_ACTIVITY_FOR_KIND = {
    "regular": _calculate_experiment_regular_metric_sync,
    "saved": _calculate_experiment_saved_metric_sync,
}


@override_settings(IN_UNIT_TESTING=True)
class TestDailyMetricActivities(ExperimentQueryRunnerBaseTest):
    def _queued_key(self, experiment: Experiment, metric_uuid: str) -> str:
        calculation_config = get_metric_calculation_config(experiment, metric_uuid)
        assert calculation_config is not None
        return calculation_config.calculation_key()

    @contextmanager
    def _mocked_runner(self, experiment: Experiment, metric_uuid: str) -> Iterator[MagicMock]:
        # The activity compares the key of the runner's settings with the queued key before it runs the query.
        with patch("posthog.temporal.experiments.activities.ExperimentQueryRunner") as mock_runner_class:
            mock_runner_class.return_value.calculation_config = get_metric_calculation_config(experiment, metric_uuid)
            yield mock_runner_class

    def _hold_window(self, experiment_id: int, metric_uuid: str, query_to: datetime, fingerprint: str | None) -> None:
        if fingerprint is not None:
            ExperimentMetricResult.objects.create(
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                fingerprint=fingerprint,
                query_from=datetime.fromisoformat("2020-01-01T00:00:00+00:00"),
                query_to=query_to,
                status=ExperimentMetricResult.Status.COMPLETED,
                result={"stale": True},
            )

    @parameterized.expand(_WINDOW_HOLDERS)
    @time_machine.travel("2020-01-10T12:00:00Z", tick=False)
    def test_regular_metric_activity_pins_runner_to_stored_query_to(self, _name: str, holder: str | None):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1, 0, 0, 0),
            end_date=datetime(2020, 1, 5, 0, 0, 0),
        )
        metric = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase"))
        metric_dict = metric.model_dump(mode="json")
        experiment.metrics = [metric_dict]
        experiment.save()
        expected_query_to = datetime.fromisoformat("2020-01-05T00:00:00+00:00")
        self._hold_window(experiment.id, metric_dict["uuid"], expected_query_to, holder)

        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            self._mocked_runner(experiment, metric_dict["uuid"]) as mock_runner_class,
        ):
            mock_runner_class.return_value.run.return_value.model_dump.return_value = {"variant_results": []}

            activity_result = _calculate_experiment_regular_metric_sync.func(  # type: ignore[attr-defined]
                experiment.id, metric_dict["uuid"], self._queued_key(experiment, metric_dict["uuid"])
            )

        self.assertTrue(activity_result.success, msg=activity_result.error_message)
        mock_runner_class.assert_called_once()
        assert mock_runner_class.call_args.kwargs["as_of"] == expected_query_to
        result_row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid=metric_dict["uuid"])
        assert result_row.query_to == expected_query_to
        assert (result_row.fingerprint, result_row.display_key, result_row.result) == (
            self._queued_key(experiment, metric_dict["uuid"]),
            self._queued_key(experiment, metric_dict["uuid"]),
            {"variant_results": []},
        )

    @parameterized.expand(_WINDOW_HOLDERS)
    @time_machine.travel("2020-01-10T12:00:00Z", tick=False)
    def test_saved_metric_activity_pins_runner_to_stored_query_to(self, _name: str, holder: str | None):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1, 0, 0, 0),
            end_date=datetime(2020, 1, 5, 0, 0, 0),
        )
        metric = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase"))
        metric_dict = metric.model_dump(mode="json")
        expected_query_to = datetime.fromisoformat("2020-01-05T00:00:00+00:00")

        saved_metric = ExperimentSavedMetric.objects.create(
            name="test saved metric",
            team=self.team,
            query=metric_dict,
            created_by=self.user,
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment,
            saved_metric=saved_metric,
            metadata={"type": "primary"},
        )
        self._hold_window(experiment.id, metric_dict["uuid"], expected_query_to, holder)

        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            self._mocked_runner(experiment, metric_dict["uuid"]) as mock_runner_class,
        ):
            mock_runner_class.return_value.run.return_value.model_dump.return_value = {"variant_results": []}

            activity_result = _calculate_experiment_saved_metric_sync.func(  # type: ignore[attr-defined]
                experiment.id, metric_dict["uuid"], self._queued_key(experiment, metric_dict["uuid"])
            )

        self.assertTrue(activity_result.success, msg=activity_result.error_message)
        mock_runner_class.assert_called_once()
        assert mock_runner_class.call_args.kwargs["as_of"] == expected_query_to
        result_row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid=metric_dict["uuid"])
        assert result_row.query_to == expected_query_to
        assert (result_row.fingerprint, result_row.display_key, result_row.result) == (
            self._queued_key(experiment, metric_dict["uuid"]),
            self._queued_key(experiment, metric_dict["uuid"]),
            {"variant_results": []},
        )

    @parameterized.expand(
        [
            (f"{kind}_{change}", kind, key_version, change)
            for kind in ("regular", "saved")
            for key_version, change in ((1, "stats_method"), (2, "team_cuped_default"), (2, None))
        ]
    )
    @time_machine.travel("2020-01-10T12:00:00Z", tick=False)
    def test_activity_stores_a_result_only_under_the_key_the_runner_computes(
        self, _name: str, kind: str, key_version: int, change: str | None
    ) -> None:
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1, 0, 0, 0),
            end_date=datetime(2020, 1, 5, 0, 0, 0),
        )
        metric_dict = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase")).model_dump(
            mode="json"
        )
        if kind == "regular":
            experiment.metrics = [metric_dict]
            experiment.save()
        else:
            ExperimentToSavedMetric.objects.create(
                experiment=experiment,
                saved_metric=ExperimentSavedMetric.objects.create(
                    name="saved", team=self.team, query=metric_dict, created_by=self.user
                ),
                metadata={"type": "primary"},
            )
        settings_a = get_metric_calculation_config(experiment, metric_dict["uuid"])
        assert settings_a is not None
        queued_key = settings_a.key_for_version(key_version)
        team_config = get_or_create_team_extension(self.team, TeamExperimentsConfig)

        def apply_settings(*, changed: bool) -> None:
            if change == "stats_method":
                experiment.stats_config = {"method": "frequentist"} if changed else None
                experiment.save()
            elif change == "team_cuped_default":
                team_config.default_cuped_enabled = changed
                team_config.save()

        apply_settings(changed=True)
        significant_result = MagicMock()
        significant_result.model_dump.return_value = {
            "variant_results": [{"key": "test", "significant": True, "chance_to_win": 0.99}]
        }
        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            patch.object(ExperimentQueryRunner, "run", return_value=significant_result),
            patch("posthog.temporal.experiments.utils.produce_internal_event") as mock_produce,
        ):
            activity_result = _ACTIVITY_FOR_KIND[kind].func(experiment.id, metric_dict["uuid"], queued_key)  # type: ignore[attr-defined]

        rows = ExperimentMetricResult.objects.filter(experiment=experiment, metric_uuid=metric_dict["uuid"])
        if change is None:
            assert (activity_result.success, activity_result.skipped) == (True, False)
            assert [(row.fingerprint, row.display_key) for row in rows] == [(queued_key, settings_a.legacy_key())]
            mock_produce.assert_called_once()
            return

        assert (activity_result.success, activity_result.skipped) == (False, True)
        assert not rows.exists()
        mock_produce.assert_not_called()

        apply_settings(changed=False)
        experiment.refresh_from_db()
        calculation_config = get_metric_calculation_config(experiment, metric_dict["uuid"])
        assert calculation_config is not None and calculation_config.key_for_version(key_version) == queued_key
        timeseries = MetricResultStore(experiment_id=experiment.id).timeseries(
            calculation_config, timezone=ZoneInfo("UTC")
        )
        assert ExperimentResultConfigurationStatus.CURRENT not in timeseries.configuration_by_day.values()

    @time_machine.travel("2020-01-10T12:00:00Z", tick=False)
    def test_saved_metric_activity_computes_the_link_of_the_queued_key(self) -> None:
        # Two links can carry one saved metric with different breakdowns, and discovery queues each under its own key.
        experiment = self.create_experiment(
            feature_flag=self.create_feature_flag(),
            start_date=datetime(2020, 1, 1, 0, 0, 0),
            end_date=datetime(2020, 1, 5, 0, 0, 0),
        )
        metric_dict = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase")).model_dump(
            mode="json"
        )
        saved_metric = ExperimentSavedMetric.objects.create(
            name="saved", team=self.team, query=metric_dict, created_by=self.user
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment, saved_metric=saved_metric, metadata={"type": "primary"}
        )
        broken_down = ExperimentToSavedMetric.objects.create(
            experiment=experiment,
            saved_metric=saved_metric,
            metadata={"type": "secondary", "breakdowns": [{"property": "$browser", "type": "event"}]},
        )
        queued_key = metric_calculation_keys(experiment.id, team_id=self.team.id).saved[broken_down.id]
        computed = MagicMock()
        computed.model_dump.return_value = {"variant_results": []}

        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            patch.object(ExperimentQueryRunner, "run", return_value=computed),
        ):
            activity_result = _calculate_experiment_saved_metric_sync.func(  # type: ignore[attr-defined]
                experiment.id, metric_dict["uuid"], queued_key
            )

        assert (activity_result.success, activity_result.skipped) == (True, False)
        assert list(
            ExperimentMetricResult.objects.filter(experiment=experiment).values_list("fingerprint", flat=True)
        ) == [queued_key]

    @time_machine.travel("2020-01-10T12:00:00Z", tick=False)
    def test_regular_metric_activity_returns_permanent_failure_on_validation_error(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1, 0, 0, 0),
            end_date=datetime(2020, 1, 5, 0, 0, 0),
        )
        metric = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase"))
        metric_dict = metric.model_dump(mode="json")
        experiment.metrics = [metric_dict]
        experiment.save()

        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            self._mocked_runner(experiment, metric_dict["uuid"]) as mock_runner_class,
            patch("posthog.temporal.experiments.activities.capture_experiment_metric_error_event") as mock_event,
        ):
            mock_runner_class.return_value.run.side_effect = ValidationError("compound expressions not supported")

            activity_result = _calculate_experiment_regular_metric_sync.func(  # type: ignore[attr-defined]
                experiment.id, metric_dict["uuid"], self._queued_key(experiment, metric_dict["uuid"])
            )

        self.assertFalse(activity_result.success)
        result_row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid=metric_dict["uuid"])
        assert result_row.status == ExperimentMetricResult.Status.FAILED
        mock_event.assert_called_once()

    @time_machine.travel("2020-01-10T12:00:00Z", tick=False)
    def test_saved_metric_activity_returns_permanent_failure_on_validation_error(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1, 0, 0, 0),
            end_date=datetime(2020, 1, 5, 0, 0, 0),
        )
        metric = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase"))
        metric_dict = metric.model_dump(mode="json")

        saved_metric = ExperimentSavedMetric.objects.create(
            name="test saved metric",
            team=self.team,
            query=metric_dict,
            created_by=self.user,
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment,
            saved_metric=saved_metric,
            metadata={"type": "primary"},
        )

        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            self._mocked_runner(experiment, metric_dict["uuid"]) as mock_runner_class,
            patch("posthog.temporal.experiments.activities.capture_experiment_metric_error_event") as mock_event,
        ):
            mock_runner_class.return_value.run.side_effect = ValidationError("compound expressions not supported")

            activity_result = _calculate_experiment_saved_metric_sync.func(  # type: ignore[attr-defined]
                experiment.id, metric_dict["uuid"], self._queued_key(experiment, metric_dict["uuid"])
            )

        self.assertFalse(activity_result.success)
        result_row = ExperimentMetricResult.objects.get(experiment=experiment, metric_uuid=metric_dict["uuid"])
        assert result_row.status == ExperimentMetricResult.Status.FAILED
        mock_event.assert_called_once()

    @time_machine.travel("2020-01-10T12:00:00Z", tick=False)
    def test_regular_metric_activity_still_raises_transient_errors(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1, 0, 0, 0),
            end_date=datetime(2020, 1, 5, 0, 0, 0),
        )
        metric = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase"))
        metric_dict = metric.model_dump(mode="json")
        experiment.metrics = [metric_dict]
        experiment.save()

        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            self._mocked_runner(experiment, metric_dict["uuid"]) as mock_runner_class,
            patch("posthog.temporal.experiments.activities.capture_experiment_metric_error_event") as mock_event,
        ):
            mock_runner_class.return_value.run.side_effect = Exception("transient query failure")

            with self.assertRaises(Exception):
                _calculate_experiment_regular_metric_sync.func(  # type: ignore[attr-defined]
                    experiment.id, metric_dict["uuid"], self._queued_key(experiment, metric_dict["uuid"]), attempt=1
                )
            mock_event.assert_not_called()

            with self.assertRaises(Exception):
                _calculate_experiment_regular_metric_sync.func(  # type: ignore[attr-defined]
                    experiment.id,
                    metric_dict["uuid"],
                    self._queued_key(experiment, metric_dict["uuid"]),
                    attempt=TIMESERIES_METRIC_MAX_ATTEMPTS,
                )
            mock_event.assert_called_once()

    @time_machine.travel("2020-01-10T12:00:00Z", tick=False)
    def test_saved_metric_activity_still_raises_transient_errors(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1, 0, 0, 0),
            end_date=datetime(2020, 1, 5, 0, 0, 0),
        )
        metric = ExperimentMeanMetric(uuid=str(uuid4()), source=EventsNode(event="purchase"))
        metric_dict = metric.model_dump(mode="json")

        saved_metric = ExperimentSavedMetric.objects.create(
            name="test saved metric",
            team=self.team,
            query=metric_dict,
            created_by=self.user,
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment,
            saved_metric=saved_metric,
            metadata={"type": "primary"},
        )

        with (
            patch("posthog.temporal.experiments.activities.close_old_connections"),
            self._mocked_runner(experiment, metric_dict["uuid"]) as mock_runner_class,
            patch("posthog.temporal.experiments.activities.capture_experiment_metric_error_event") as mock_event,
        ):
            mock_runner_class.return_value.run.side_effect = Exception("transient query failure")

            with self.assertRaises(Exception):
                _calculate_experiment_saved_metric_sync.func(  # type: ignore[attr-defined]
                    experiment.id, metric_dict["uuid"], self._queued_key(experiment, metric_dict["uuid"]), attempt=1
                )
            mock_event.assert_not_called()

            with self.assertRaises(Exception):
                _calculate_experiment_saved_metric_sync.func(  # type: ignore[attr-defined]
                    experiment.id,
                    metric_dict["uuid"],
                    self._queued_key(experiment, metric_dict["uuid"]),
                    attempt=TIMESERIES_METRIC_MAX_ATTEMPTS,
                )
            mock_event.assert_called_once()
