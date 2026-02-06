from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from posthog.schema import (
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    MaxExperimentMetricResult,
    MaxExperimentSummaryContext,
    MaxExperimentVariantResultBayesian,
    MaxExperimentVariantResultFrequentist,
)

from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag

from products.experiments.backend.experiment_summary_data_service import (
    ExperimentSummaryDataService,
    get_chance_to_win,
    get_default_metric_title,
    get_delta_from_interval,
    parse_metric_dict,
    transform_variant_for_max,
)
from products.experiments.backend.max_tools import ExperimentSummaryOutput, ExperimentSummaryTool

from ee.hogai.utils.types import AssistantState


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentSummaryToolHelpers(APIBaseTest):
    """Tests for the helper functions used by ExperimentSummaryTool"""

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
        """Test that chance_to_win is inverted when goal is decrease"""
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
        """Test that chance_to_win stays the same when goal is increase"""
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

    def test_get_default_metric_title_funnel_single_event(self):
        metric_dict = {
            "metric_type": "funnel",
            "series": [{"event": "purchase"}],
        }
        self.assertEqual(get_default_metric_title(metric_dict), "purchase conversion")

    def test_get_default_metric_title_funnel_multiple_events(self):
        metric_dict = {
            "metric_type": "funnel",
            "series": [
                {"event": "view_page"},
                {"event": "add_to_cart"},
                {"event": "purchase"},
            ],
        }
        self.assertEqual(get_default_metric_title(metric_dict), "view_page to purchase")

    def test_get_default_metric_title_mean(self):
        metric_dict = {
            "metric_type": "mean",
            "source": {"event": "revenue"},
        }
        self.assertEqual(get_default_metric_title(metric_dict), "Mean revenue")

    def test_get_default_metric_title_ratio(self):
        metric_dict = {"metric_type": "ratio"}
        self.assertEqual(get_default_metric_title(metric_dict), "Ratio metric")

    def test_get_default_metric_title_retention(self):
        metric_dict = {"metric_type": "retention"}
        self.assertEqual(get_default_metric_title(metric_dict), "Retention metric")


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentSummaryTool(ClickhouseTestMixin, APIBaseTest):
    """Integration tests for ExperimentSummaryTool"""

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
    async def test_experiment_not_found(self):
        """Test error when experiment doesn't exist"""
        tool = await ExperimentSummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(experiment_id=99999)

        self.assertIn("not found", result)
        self.assertEqual(artifact["error"], "fetch_failed")

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_experiment_not_started(self):
        """Test error when experiment hasn't started yet"""
        feature_flag = await self.acreate_feature_flag()
        experiment = await Experiment.objects.acreate(
            name="Not started experiment",
            team=self.team,
            feature_flag=feature_flag,
            start_date=None,  # Not started
            exposure_criteria=None,
        )

        tool = await ExperimentSummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        self.assertIn("has not been started", result)
        self.assertEqual(artifact["error"], "fetch_failed")

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_experiment_with_no_results(self):
        """Test when experiment has no metric results"""
        experiment = await self.acreate_experiment(with_metrics=False)

        tool = await ExperimentSummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        self.assertIn("No experiment results", result)
        self.assertEqual(artifact["error"], "no_results")

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_no_warning_when_recent(self):
        """Test that no warning is returned when data is fresh (within 1 minute threshold)"""
        data_service = ExperimentSummaryDataService(self.team)

        # 30 seconds difference - well within the 1 minute threshold
        frontend_refresh = "2020-01-10T11:59:00Z"
        backend_refresh = datetime(2020, 1, 10, 11, 59, 30, tzinfo=ZoneInfo("UTC"))

        warning = data_service.check_data_freshness(frontend_refresh, backend_refresh)
        self.assertIsNone(warning)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_warning_when_stale(self):
        """Test that warning is returned when data has changed significantly"""
        data_service = ExperimentSummaryDataService(self.team)

        frontend_refresh = "2020-01-10T10:00:00Z"
        backend_refresh = datetime(2020, 1, 10, 11, 30, tzinfo=ZoneInfo("UTC"))

        warning = data_service.check_data_freshness(frontend_refresh, backend_refresh)
        assert warning is not None
        self.assertIn("data has been updated", warning)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_warning_at_threshold_boundary(self):
        """Test that warning is returned when data difference is just over 1 minute threshold"""
        data_service = ExperimentSummaryDataService(self.team)

        # 61 seconds difference - just over the 1 minute (60 second) threshold
        frontend_refresh = "2020-01-10T11:58:00Z"
        backend_refresh = datetime(2020, 1, 10, 11, 59, 1, tzinfo=ZoneInfo("UTC"))

        warning = data_service.check_data_freshness(frontend_refresh, backend_refresh)
        assert warning is not None
        self.assertIn("data has been updated", warning)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_no_warning_at_threshold_boundary(self):
        """Test that no warning is returned when data difference is exactly at 1 minute threshold"""
        data_service = ExperimentSummaryDataService(self.team)

        # Exactly 60 seconds - at the threshold (not over), should NOT trigger warning
        frontend_refresh = "2020-01-10T11:58:00Z"
        backend_refresh = datetime(2020, 1, 10, 11, 59, 0, tzinfo=ZoneInfo("UTC"))

        warning = data_service.check_data_freshness(frontend_refresh, backend_refresh)
        self.assertIsNone(warning)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_check_data_freshness_handles_none_values(self):
        """Test that freshness check handles None values gracefully"""
        data_service = ExperimentSummaryDataService(self.team)

        self.assertIsNone(data_service.check_data_freshness(None, None))
        self.assertIsNone(data_service.check_data_freshness("2020-01-10T10:00:00Z", None))
        self.assertIsNone(data_service.check_data_freshness(None, datetime.now(ZoneInfo("UTC"))))

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_format_experiment_for_llm_bayesian(self):
        """Test formatting of experiment data for LLM with Bayesian stats"""
        tool = await ExperimentSummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

        context = MaxExperimentSummaryContext(
            experiment_id=1,
            experiment_name="Test Experiment",
            description="Testing new checkout flow",
            exposures={"control": 500.0, "test": 500.0},
            variants=["control", "test"],
            primary_metrics_results=[
                MaxExperimentMetricResult(
                    name="1. Conversion Rate",
                    goal="increase",
                    variant_results=[
                        MaxExperimentVariantResultBayesian(
                            key="test",
                            chance_to_win=0.85,
                            credible_interval=[0.05, 0.15],
                            delta=0.10,
                            significant=True,
                        ),
                    ],
                ),
            ],
            secondary_metrics_results=[],
            stats_method="bayesian",
        )

        formatted = tool._format_experiment_for_llm(context)

        self.assertIn("Statistical method: Bayesian", formatted)
        self.assertIn("Test Experiment", formatted)
        self.assertIn("Testing new checkout flow", formatted)
        self.assertIn("control: 500", formatted)
        self.assertIn("Chance to win: 85.0%", formatted)
        self.assertIn("credible interval", formatted.lower())

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_format_experiment_for_llm_frequentist(self):
        """Test formatting of experiment data for LLM with Frequentist stats"""
        tool = await ExperimentSummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

        context = MaxExperimentSummaryContext(
            experiment_id=1,
            experiment_name="Test Experiment",
            description=None,
            exposures={"control": 1000.0, "test": 1000.0},
            variants=["control", "test"],
            primary_metrics_results=[
                MaxExperimentMetricResult(
                    name="1. Revenue per User",
                    goal="increase",
                    variant_results=[
                        MaxExperimentVariantResultFrequentist(
                            key="test",
                            p_value=0.023,
                            confidence_interval=[0.02, 0.12],
                            delta=0.07,
                            significant=True,
                        ),
                    ],
                ),
            ],
            secondary_metrics_results=[],
            stats_method="frequentist",
        )

        formatted = tool._format_experiment_for_llm(context)

        self.assertIn("Statistical method: Frequentist", formatted)
        self.assertIn("P-value: 0.0230", formatted)
        self.assertIn("confidence interval", formatted.lower())

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_format_summary_for_user(self):
        """Test formatting of summary output for user display"""
        tool = await ExperimentSummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

        summary = ExperimentSummaryOutput(
            key_metrics=[
                "Test variant shows 10% improvement in conversion rate",
                "Result is statistically significant (p < 0.05)",
            ]
        )

        formatted = tool._format_summary_for_user(summary, "My Experiment")

        self.assertIn("My Experiment", formatted)
        self.assertIn("10% improvement", formatted)
        self.assertIn("statistically significant", formatted)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_freshness_warning_appears_in_tool_output(self):
        """Test that freshness warning is prepended to user message when data is stale"""
        experiment = await self.acreate_experiment(name="freshness-test", with_metrics=True)

        # Create tool with context containing an old frontend_last_refresh
        tool = await ExperimentSummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

        # Create mock results with recent backend refresh time
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
        # Backend refresh is 1 hour after frontend (way over threshold)
        mock_query_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        mock_exposure_result = MagicMock()
        mock_exposure_result.total_exposures = {"control": 500, "test": 500}
        mock_exposure_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        mock_summary = ExperimentSummaryOutput(key_metrics=["Test variant shows improvement"])

        # Mock context with old frontend refresh time (2 hours ago)
        mock_context: dict = {"experiment_results_summary": {"frontend_last_refresh": "2020-01-10T10:00:00Z"}}

        with (
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentQueryRunner"
            ) as mock_query_runner_class,
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentExposuresQueryRunner"
            ) as mock_exposure_runner_class,
            patch.object(tool, "_analyze_experiment", return_value=mock_summary),
            patch.object(tool._context_manager, "get_contextual_tools", return_value=mock_context),
        ):
            mock_query_runner_class.return_value.run.return_value = mock_query_result
            mock_exposure_runner_class.return_value.run.return_value = mock_exposure_result

            result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        # The freshness warning should be prepended to the result
        self.assertIn("**Note:** The experiment data has been updated", result)
        self.assertIn("60 minutes ago", result)
        # The actual summary should still be present
        self.assertIn("Experiment Summary", result)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_no_freshness_warning_when_frontend_timestamp_missing(self):
        """Test that no warning appears when frontend_last_refresh is not provided"""
        experiment = await self.acreate_experiment(name="no-timestamp-test", with_metrics=True)

        tool = await ExperimentSummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

        mock_query_result = MagicMock()
        mock_query_result.variant_results = [
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

        mock_exposure_result = MagicMock()
        mock_exposure_result.total_exposures = {"control": 500, "test": 500}
        mock_exposure_result.last_refresh = datetime(2020, 1, 10, 11, 0, tzinfo=ZoneInfo("UTC"))

        mock_summary = ExperimentSummaryOutput(key_metrics=["Test variant shows improvement"])

        # Mock context with no frontend_last_refresh
        mock_context: dict = {"experiment_results_summary": {}}

        with (
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentQueryRunner"
            ) as mock_query_runner_class,
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentExposuresQueryRunner"
            ) as mock_exposure_runner_class,
            patch.object(tool, "_analyze_experiment", return_value=mock_summary),
            patch.object(tool._context_manager, "get_contextual_tools", return_value=mock_context),
        ):
            mock_query_runner_class.return_value.run.return_value = mock_query_result
            mock_exposure_runner_class.return_value.run.return_value = mock_exposure_result

            result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        # No freshness warning should be present
        self.assertNotIn("**Note:**", result)
        # The actual summary should still be present
        self.assertIn("Experiment Summary", result)

    @freeze_time("2020-01-10T12:00:00Z")
    async def test_fetch_experiment_data_with_mocked_query_runners(self):
        """Test that fetch_experiment_data works with mocked query runners - exercises the query runner code path"""
        experiment = await self.acreate_experiment(name="query-runner-test", with_metrics=True)

        tool = await ExperimentSummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

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
                "products.experiments.backend.experiment_summary_data_service.ExperimentQueryRunner"
            ) as mock_query_runner_class,
            patch(
                "products.experiments.backend.experiment_summary_data_service.ExperimentExposuresQueryRunner"
            ) as mock_exposure_runner_class,
        ):
            mock_query_runner_class.return_value.run.return_value = mock_query_result
            mock_exposure_runner_class.return_value.run.return_value = mock_exposure_result

            data_service = ExperimentSummaryDataService(tool._team)
            context, last_refresh, pending_calculation = await data_service.fetch_experiment_data(experiment.id)

        self.assertEqual(context.experiment_id, experiment.id)
        self.assertEqual(context.experiment_name, "query-runner-test")
        self.assertEqual(len(context.primary_metrics_results), 1)
        self.assertEqual(context.exposures, {"control": 500.0, "test": 500.0})
        self.assertIsNotNone(last_refresh)
        self.assertFalse(pending_calculation)
