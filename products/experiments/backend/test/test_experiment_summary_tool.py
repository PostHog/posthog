from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import (
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    MaxExperimentVariantResultBayesian,
    MaxExperimentVariantResultFrequentist,
)

from posthog.hogql.constants import LimitContext

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.feature_flag.feature_flag import FeatureFlag

from products.experiments.backend.experiment_summary_data_service import (
    ExperimentSummaryDataService,
    get_chance_to_win,
    get_delta_from_interval,
    parse_metric_dict,
    transform_variant_for_max,
)
from products.experiments.backend.metric_utils import get_default_metric_title
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentSummaryToolHelpers(APIBaseTest):
    def test_parse_metric_dict_funnel(self):
        metric_dict = {
            "metric_type": "funnel",
            "series": [{"event": "purchase"}],
        }
        result = parse_metric_dict(metric_dict)
        assert result is not None
        self.assertEqual(result.metric_type, "funnel")

    def test_parse_metric_dict_mean(self):
        metric_dict = {
            "metric_type": "mean",
            "source": {"kind": "EventsNode", "event": "purchase"},
        }
        result = parse_metric_dict(metric_dict)
        assert result is not None
        self.assertEqual(result.metric_type, "mean")

    def test_parse_metric_dict_unknown(self):
        metric_dict = {"metric_type": "unknown"}
        result = parse_metric_dict(metric_dict)
        self.assertIsNone(result)

    def test_get_delta_from_interval(self):
        # Normal case
        self.assertEqual(get_delta_from_interval([0.1, 0.3]), 0.2)

        # Empty/None cases
        self.assertIsNone(get_delta_from_interval(None))
        self.assertIsNone(get_delta_from_interval([]))
        self.assertIsNone(get_delta_from_interval([0.1]))

    def test_get_chance_to_win_increase_goal(self):
        # When goal is increase, chance_to_win stays the same
        self.assertEqual(get_chance_to_win(0.85, "increase"), 0.85)
        self.assertEqual(get_chance_to_win(0.15, "increase"), 0.15)

    def test_get_chance_to_win_decrease_goal(self):
        # When goal is decrease, chance_to_win is inverted (1 - chance_to_win)
        # Use "almost" to avoid "0.15000000000000002 != 0.15"
        result1 = get_chance_to_win(0.85, "decrease")
        result2 = get_chance_to_win(0.15, "decrease")
        assert result1 is not None
        assert result2 is not None
        self.assertAlmostEqual(result1, 0.15)
        self.assertAlmostEqual(result2, 0.85)

    def test_get_chance_to_win_no_goal(self):
        # When goal is None, chance_to_win stays the same
        self.assertEqual(get_chance_to_win(0.85, None), 0.85)

    def test_get_chance_to_win_none_value(self):
        # When chance_to_win is None, return None regardless of goal
        self.assertIsNone(get_chance_to_win(None, "increase"))
        self.assertIsNone(get_chance_to_win(None, "decrease"))
        self.assertIsNone(get_chance_to_win(None, None))

    def test_transform_variant_for_max_bayesian(self):
        variant = ExperimentVariantResultBayesian(
            key="test",
            method="bayesian",
            chance_to_win=0.85,
            credible_interval=[0.1, 0.3],
            significant=True,
            number_of_samples=100,
            sum=50,
            sum_squares=2500,
        )
        result = transform_variant_for_max(variant, "bayesian")
        assert isinstance(result, MaxExperimentVariantResultBayesian)
        self.assertEqual(result.key, "test")
        self.assertEqual(result.chance_to_win, 0.85)
        self.assertEqual(result.credible_interval, [0.1, 0.3])
        self.assertEqual(result.delta, 0.2)  # (0.1 + 0.3) / 2
        self.assertTrue(result.significant)

    def test_transform_variant_for_max_frequentist(self):
        variant = ExperimentVariantResultFrequentist(
            key="test",
            method="frequentist",
            p_value=0.03,
            confidence_interval=[-0.1, 0.5],
            significant=True,
            number_of_samples=100,
            sum=50,
            sum_squares=2500,
        )
        result = transform_variant_for_max(variant, "frequentist")
        assert isinstance(result, MaxExperimentVariantResultFrequentist)
        self.assertEqual(result.key, "test")
        self.assertEqual(result.p_value, 0.03)
        self.assertEqual(result.confidence_interval, [-0.1, 0.5])
        self.assertEqual(result.delta, 0.2)  # (-0.1 + 0.5) / 2
        self.assertTrue(result.significant)

    def test_transform_variant_for_max_bayesian_with_decrease_goal(self):
        variant = ExperimentVariantResultBayesian(
            key="test",
            method="bayesian",
            chance_to_win=0.85,
            credible_interval=[0.1, 0.3],
            significant=True,
            number_of_samples=100,
            sum=50,
            sum_squares=2500,
        )
        result = transform_variant_for_max(variant, "bayesian", goal="decrease")
        assert isinstance(result, MaxExperimentVariantResultBayesian)
        self.assertEqual(result.key, "test")
        # chance_to_win should be inverted: 1 - 0.85 = 0.15
        assert result.chance_to_win is not None
        self.assertAlmostEqual(result.chance_to_win, 0.15)
        self.assertEqual(result.credible_interval, [0.1, 0.3])
        self.assertEqual(result.delta, 0.2)
        self.assertTrue(result.significant)

    def test_transform_variant_for_max_bayesian_with_increase_goal(self):
        variant = ExperimentVariantResultBayesian(
            key="test",
            method="bayesian",
            chance_to_win=0.85,
            credible_interval=[0.1, 0.3],
            significant=True,
            number_of_samples=100,
            sum=50,
            sum_squares=2500,
        )
        result = transform_variant_for_max(variant, "bayesian", goal="increase")
        assert isinstance(result, MaxExperimentVariantResultBayesian)
        self.assertEqual(result.chance_to_win, 0.85)

    @parameterized.expand(
        [
            ("funnel_single", {"metric_type": "funnel", "series": [{"event": "purchase"}]}, "purchase conversion"),
            (
                "funnel_multi",
                {
                    "metric_type": "funnel",
                    "series": [{"event": "view_page"}, {"event": "add_to_cart"}, {"event": "purchase"}],
                },
                "view_page to purchase",
            ),
            ("mean", {"metric_type": "mean", "source": {"event": "revenue"}}, "Mean revenue"),
            ("ratio_no_events", {"metric_type": "ratio"}, "Event / Event"),
            (
                "ratio_with_events",
                {
                    "metric_type": "ratio",
                    "numerator": {"kind": "EventsNode", "event": "$pageview"},
                    "denominator": {"kind": "EventsNode", "event": "experiment timeseries viewed"},
                },
                "$pageview / experiment timeseries viewed",
            ),
            ("retention_no_events", {"metric_type": "retention"}, "Event / Event"),
            (
                "retention_with_events",
                {
                    "metric_type": "retention",
                    "start_event": {"kind": "EventsNode", "event": "$pageview"},
                    "completion_event": {"kind": "EventsNode", "event": "purchase"},
                },
                "$pageview / purchase",
            ),
        ]
    )
    def test_get_default_metric_title(self, _name, metric_dict, expected):
        self.assertEqual(get_default_metric_title(metric_dict), expected)


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentSummaryDataService(ClickhouseTestMixin, APIBaseTest):
    async def acreate_feature_flag(self, key="test-experiment"):
        return await FeatureFlag.objects.acreate(
            name=f"Test experiment flag: {key}",
            key=key,
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
            created_by=self.user,
        )

    async def acreate_experiment(self, name="test-experiment", feature_flag=None, with_metrics=True):
        if feature_flag is None:
            feature_flag = await self.acreate_feature_flag(name)

        metrics = []
        if with_metrics:
            metrics = [
                {
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "purchase"}],
                    "name": "Purchase conversion",
                }
            ]

        return await Experiment.objects.acreate(
            name=name,
            team=self.team,
            feature_flag=feature_flag,
            start_date=timezone.now() - timedelta(days=7),
            end_date=timezone.now() + timedelta(days=7),
            exposure_criteria=None,
            metrics=metrics,
            metrics_secondary=[],
        )

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_no_warning_when_recent(self):
        data_service = ExperimentSummaryDataService(self.team)

        # 30 seconds difference - well within the 1 minute threshold
        frontend_refresh = "2020-01-10T11:59:00Z"
        backend_refresh = datetime(2020, 1, 10, 11, 59, 30, tzinfo=ZoneInfo("UTC"))

        warning = data_service.check_data_freshness(frontend_refresh, backend_refresh)
        self.assertIsNone(warning)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_warning_when_stale(self):
        data_service = ExperimentSummaryDataService(self.team)

        frontend_refresh = "2020-01-10T10:00:00Z"
        backend_refresh = datetime(2020, 1, 10, 11, 30, tzinfo=ZoneInfo("UTC"))

        warning = data_service.check_data_freshness(frontend_refresh, backend_refresh)
        assert warning is not None
        self.assertIn("data has been updated", warning)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_warning_at_threshold_boundary(self):
        data_service = ExperimentSummaryDataService(self.team)

        # 61 seconds difference - just over the 1 minute (60 second) threshold
        frontend_refresh = "2020-01-10T11:58:00Z"
        backend_refresh = datetime(2020, 1, 10, 11, 59, 1, tzinfo=ZoneInfo("UTC"))

        warning = data_service.check_data_freshness(frontend_refresh, backend_refresh)
        assert warning is not None
        self.assertIn("data has been updated", warning)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_no_warning_at_threshold_boundary(self):
        data_service = ExperimentSummaryDataService(self.team)

        # Exactly 60 seconds - at the threshold (not over), should NOT trigger warning
        frontend_refresh = "2020-01-10T11:58:00Z"
        backend_refresh = datetime(2020, 1, 10, 11, 59, 0, tzinfo=ZoneInfo("UTC"))

        warning = data_service.check_data_freshness(frontend_refresh, backend_refresh)
        self.assertIsNone(warning)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_handles_none_values(self):
        data_service = ExperimentSummaryDataService(self.team)

        self.assertIsNone(data_service.check_data_freshness(None, None))
        self.assertIsNone(data_service.check_data_freshness("2020-01-10T10:00:00Z", None))
        self.assertIsNone(data_service.check_data_freshness(None, datetime.now(ZoneInfo("UTC"))))

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_fetch_experiment_data_with_mocked_query_runners(self):
        experiment = await self.acreate_experiment(name="query-runner-test", with_metrics=True)

        # Create mock query result
        mock_query_result = MagicMock()
        mock_query_result.variant_results = [
            ExperimentVariantResultBayesian(
                key="control",
                method="bayesian",
                chance_to_win=0.15,
                credible_interval=[-0.05, 0.05],
                significant=False,
                number_of_samples=100,
                sum=50,
                sum_squares=2500,
            ),
            ExperimentVariantResultBayesian(
                key="test",
                method="bayesian",
                chance_to_win=0.85,
                credible_interval=[0.05, 0.15],
                significant=True,
                number_of_samples=100,
                sum=60,
                sum_squares=3600,
            ),
        ]
        mock_query_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        # Create mock exposure result
        mock_exposure_result = MagicMock()
        mock_exposure_result.total_exposures = {"control": 500, "test": 500}
        mock_exposure_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        with (
            patch(
                "products.experiments.backend.experiment_summary_data_service.posthoganalytics.feature_enabled",
                return_value=False,
            ),
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentQueryRunner"
            ) as mock_query_runner_class,
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentExposuresQueryRunner"
            ) as mock_exposure_runner_class,
        ):
            mock_query_runner_class.return_value.run.return_value = mock_query_result
            mock_exposure_runner_class.return_value.run.return_value = mock_exposure_result

            data_service = ExperimentSummaryDataService(self.team)
            context, last_refresh, pending_calculation = await data_service.fetch_experiment_data(experiment.id)

        self.assertEqual(context.experiment_id, experiment.id)
        self.assertEqual(context.experiment_name, "query-runner-test")
        self.assertEqual(len(context.primary_metrics_results), 1)
        self.assertEqual(context.exposures, {"control": 500.0, "test": 500.0})
        self.assertIsNotNone(last_refresh)
        self.assertFalse(pending_calculation)
        self.assertEqual(mock_query_runner_class.call_args.kwargs["limit_context"], LimitContext.QUERY_ASYNC)
        self.assertEqual(mock_exposure_runner_class.call_args.kwargs["limit_context"], LimitContext.QUERY_ASYNC)
        self.assertEqual(
            mock_query_runner_class.return_value.run.call_args.kwargs["execution_mode"],
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
        )
        self.assertEqual(
            mock_exposure_runner_class.return_value.run.call_args.kwargs["execution_mode"],
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
        )

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_fetch_experiment_data_uses_sync_execution_when_rollout_flag_enabled(self):
        experiment = await self.acreate_experiment(name="query-runner-sync-test", with_metrics=True)

        mock_query_result = MagicMock()
        mock_query_result.variant_results = []
        mock_query_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        mock_exposure_result = MagicMock()
        mock_exposure_result.total_exposures = {"control": 500, "test": 500}
        mock_exposure_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        with (
            patch(
                "products.experiments.backend.experiment_summary_data_service.posthoganalytics.feature_enabled",
                return_value=True,
            ),
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentQueryRunner"
            ) as mock_query_runner_class,
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentExposuresQueryRunner"
            ) as mock_exposure_runner_class,
        ):
            mock_query_runner_class.return_value.run.return_value = mock_query_result
            mock_exposure_runner_class.return_value.run.return_value = mock_exposure_result

            data_service = ExperimentSummaryDataService(self.team)
            await data_service.fetch_experiment_data(experiment.id)

        self.assertEqual(
            mock_query_runner_class.return_value.run.call_args.kwargs["execution_mode"],
            ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        )
        self.assertEqual(
            mock_exposure_runner_class.return_value.run.call_args.kwargs["execution_mode"],
            ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
        )

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_fetch_experiment_data_executes_queries_on_cold_cache(self):
        """
        On a cold cache, queries must execute synchronously rather than
        returning a CacheMissResponse. Previously the data service used
        RECENT_CACHE_CALCULATE_ASYNC_IF_STALE which returned immediately
        on cache miss, giving the AI zero results and causing hallucinations.
        """
        experiment = await self.acreate_experiment(name="cold-cache-test", with_metrics=False)
        experiment.metrics = [
            {
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "purchase"},
                "name": "Purchase value",
            }
        ]
        await experiment.asave(update_fields=["metrics"])

        data_service = ExperimentSummaryDataService(self.team)
        context, last_refresh, pending_calculation = await data_service.fetch_experiment_data(experiment.id)

        self.assertFalse(pending_calculation)
        self.assertIsNotNone(last_refresh)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_fetch_experiment_data_includes_saved_metrics(self):
        experiment = await self.acreate_experiment(name="saved-metrics-test", with_metrics=False)

        # Create saved metrics and link them via ExperimentToSavedMetric
        primary_saved = await ExperimentSavedMetric.objects.acreate(
            team=self.team,
            name="Team Growth NSM",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "funnel",
                "series": [{"kind": "EventsNode", "event": "first team event ingested"}],
                "uuid": "primary-saved-uuid",
            },
        )
        secondary_saved = await ExperimentSavedMetric.objects.acreate(
            team=self.team,
            name="Onboarding Completion",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "funnel",
                "series": [{"kind": "EventsNode", "event": "onboarding completed"}],
                "uuid": "secondary-saved-uuid",
            },
        )
        await ExperimentToSavedMetric.objects.acreate(
            experiment=experiment, saved_metric=primary_saved, metadata={"type": "primary"}
        )
        await ExperimentToSavedMetric.objects.acreate(
            experiment=experiment, saved_metric=secondary_saved, metadata={"type": "secondary"}
        )

        mock_query_result = MagicMock()
        mock_query_result.variant_results = [
            ExperimentVariantResultBayesian(
                key="control",
                method="bayesian",
                chance_to_win=0.4,
                credible_interval=[-0.05, 0.05],
                significant=False,
                number_of_samples=100,
                sum=50,
                sum_squares=2500,
            ),
            ExperimentVariantResultBayesian(
                key="test",
                method="bayesian",
                chance_to_win=0.6,
                credible_interval=[-0.02, 0.08],
                significant=False,
                number_of_samples=100,
                sum=55,
                sum_squares=3025,
            ),
        ]
        mock_query_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        mock_exposure_result = MagicMock()
        mock_exposure_result.total_exposures = {"control": 500, "test": 500}
        mock_exposure_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        with (
            patch(
                "products.experiments.backend.experiment_summary_data_service.posthoganalytics.feature_enabled",
                return_value=False,
            ),
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentQueryRunner"
            ) as mock_query_runner_class,
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentExposuresQueryRunner"
            ) as mock_exposure_runner_class,
        ):
            mock_query_runner_class.return_value.run.return_value = mock_query_result
            mock_exposure_runner_class.return_value.run.return_value = mock_exposure_result

            data_service = ExperimentSummaryDataService(self.team)
            context, _, _ = await data_service.fetch_experiment_data(experiment.id)

        self.assertEqual(len(context.primary_metrics_results), 1)
        self.assertEqual(len(context.secondary_metrics_results), 1)

        # Verify the saved metric queries were actually passed to the query runner
        query_runner_calls = mock_query_runner_class.call_args_list
        self.assertEqual(len(query_runner_calls), 2)
        metrics_queried = [call.kwargs["query"].metric.metric_type for call in query_runner_calls]
        self.assertEqual(metrics_queried, ["funnel", "funnel"])

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_fetch_experiment_data_combines_inline_and_saved_metrics(self):
        experiment = await self.acreate_experiment(name="mixed-metrics-test", with_metrics=True)
        # experiment.metrics already has 1 inline primary metric from acreate_experiment

        # Add 1 inline secondary
        experiment.metrics_secondary = [
            {
                "metric_type": "funnel",
                "series": [{"kind": "EventsNode", "event": "signup"}],
                "name": "Signup conversion",
            }
        ]
        await experiment.asave(update_fields=["metrics_secondary"])

        # Add 1 saved primary + 1 saved secondary
        saved_primary = await ExperimentSavedMetric.objects.acreate(
            team=self.team,
            name="Saved Primary",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "revenue"},
                "uuid": "saved-primary-uuid",
            },
        )
        saved_secondary = await ExperimentSavedMetric.objects.acreate(
            team=self.team,
            name="Saved Secondary",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "funnel",
                "series": [{"kind": "EventsNode", "event": "activation"}],
                "uuid": "saved-secondary-uuid",
            },
        )
        await ExperimentToSavedMetric.objects.acreate(
            experiment=experiment, saved_metric=saved_primary, metadata={"type": "primary"}
        )
        await ExperimentToSavedMetric.objects.acreate(
            experiment=experiment, saved_metric=saved_secondary, metadata={"type": "secondary"}
        )

        mock_query_result = MagicMock()
        mock_query_result.variant_results = [
            ExperimentVariantResultBayesian(
                key="control",
                method="bayesian",
                chance_to_win=0.5,
                credible_interval=[-0.03, 0.03],
                significant=False,
                number_of_samples=100,
                sum=50,
                sum_squares=2500,
            ),
            ExperimentVariantResultBayesian(
                key="test",
                method="bayesian",
                chance_to_win=0.5,
                credible_interval=[-0.03, 0.03],
                significant=False,
                number_of_samples=100,
                sum=50,
                sum_squares=2500,
            ),
        ]
        mock_query_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        mock_exposure_result = MagicMock()
        mock_exposure_result.total_exposures = {"control": 500, "test": 500}
        mock_exposure_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        with (
            patch(
                "products.experiments.backend.experiment_summary_data_service.posthoganalytics.feature_enabled",
                return_value=False,
            ),
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentQueryRunner"
            ) as mock_query_runner_class,
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentExposuresQueryRunner"
            ) as mock_exposure_runner_class,
        ):
            mock_query_runner_class.return_value.run.return_value = mock_query_result
            mock_exposure_runner_class.return_value.run.return_value = mock_exposure_result

            data_service = ExperimentSummaryDataService(self.team)
            context, _, _ = await data_service.fetch_experiment_data(experiment.id)

        # 1 inline primary + 1 saved primary = 2
        self.assertEqual(len(context.primary_metrics_results), 2)
        # 1 inline secondary + 1 saved secondary = 2
        self.assertEqual(len(context.secondary_metrics_results), 2)

        # Verify all 4 metrics were passed to the query runner (2 primary + 2 secondary)
        query_runner_calls = mock_query_runner_class.call_args_list
        self.assertEqual(len(query_runner_calls), 4)
        metrics_queried = [call.kwargs["query"].metric.metric_type for call in query_runner_calls]
        # Inline funnel primary, saved mean primary, inline funnel secondary, saved funnel secondary
        self.assertEqual(metrics_queried, ["funnel", "mean", "funnel", "funnel"])
