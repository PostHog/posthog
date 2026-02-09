from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.schema import (
    MaxExperimentMetricResult,
    MaxExperimentVariantResultBayesian,
    MaxExperimentVariantResultFrequentist,
)

from posthog.models import Experiment, FeatureFlag

from products.experiments.backend.max_tools import CreateExperimentTool, ExperimentSummaryTool

from ee.hogai.utils.types import AssistantState


class TestCreateExperimentTool(APIBaseTest):
    def _create_tool(self) -> CreateExperimentTool:
        return CreateExperimentTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            context={},
            config={},
        )

    async def _create_multivariate_flag(
        self,
        key: str,
        name: str | None = None,
        variants: list[dict] | None = None,
    ) -> FeatureFlag:
        if variants is None:
            variants = [
                {"key": "control", "name": "Control", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ]
        return await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key=key,
            name=name or f"Flag for {key}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {"variants": variants},
            },
        )

    async def test_create_experiment_minimal(self):
        await self._create_multivariate_flag(key="test-experiment-flag", name="Test Experiment Flag")
        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Test Experiment",
            feature_flag_key="test-experiment-flag",
        )

        assert "Successfully created" in result
        assert artifact is not None
        assert artifact["experiment_name"] == "Test Experiment"
        assert artifact["feature_flag_key"] == "test-experiment-flag"
        assert "/experiments/" in artifact["url"]
        assert artifact["type"] == "product"

        experiment = await Experiment.objects.select_related("feature_flag").aget(
            name="Test Experiment", team=self.team
        )
        assert experiment.description == ""
        assert experiment.type == "product"
        assert experiment.start_date is None  # Draft
        assert experiment.feature_flag.key == "test-experiment-flag"

    async def test_create_experiment_with_description(self):
        await self._create_multivariate_flag(key="checkout-test", name="Checkout Test Flag")
        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Checkout Experiment",
            feature_flag_key="checkout-test",
            description="Testing new checkout flow to improve conversion rates",
        )

        assert "Successfully created" in result

        experiment = await Experiment.objects.aget(name="Checkout Experiment", team=self.team)
        assert experiment.description == "Testing new checkout flow to improve conversion rates"

    async def test_create_experiment_web_type(self):
        await self._create_multivariate_flag(key="homepage-redesign", name="Homepage Redesign Flag")
        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Homepage Redesign",
            feature_flag_key="homepage-redesign",
            type="web",
        )

        assert "Successfully created" in result
        assert artifact is not None
        assert artifact["type"] == "web"

        experiment = await Experiment.objects.aget(name="Homepage Redesign", team=self.team)
        assert experiment.type == "web"

    async def test_create_experiment_duplicate_name(self):
        flag = await self._create_multivariate_flag(key="existing-flag")
        await Experiment.objects.acreate(
            team=self.team,
            created_by=self.user,
            name="Existing Experiment",
            feature_flag=flag,
        )

        await self._create_multivariate_flag(key="another-flag")
        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Existing Experiment",
            feature_flag_key="another-flag",
        )

        assert "Failed to create" in result
        assert "already exists" in result
        assert artifact is not None
        assert artifact.get("error") is not None

    async def test_create_experiment_with_existing_flag(self):
        await self._create_multivariate_flag(key="existing-flag", name="Existing Flag")
        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="New Experiment",
            feature_flag_key="existing-flag",
        )

        assert "Successfully created" in result
        assert artifact is not None

        experiment = await Experiment.objects.select_related("feature_flag").aget(name="New Experiment", team=self.team)
        assert experiment.feature_flag.key == "existing-flag"

    async def test_create_experiment_flag_already_used(self):
        flag = await self._create_multivariate_flag(key="used-flag")
        await Experiment.objects.acreate(
            team=self.team,
            created_by=self.user,
            name="First Experiment",
            feature_flag=flag,
        )

        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Second Experiment",
            feature_flag_key="used-flag",
        )

        assert "Failed to create" in result
        assert "already used by experiment" in result
        assert artifact is not None
        assert artifact.get("error") is not None

    async def test_create_experiment_default_parameters(self):
        await self._create_multivariate_flag(key="param-test", name="Param Test Flag")
        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Parameter Test",
            feature_flag_key="param-test",
        )

        assert "Successfully created" in result

        experiment = await Experiment.objects.aget(name="Parameter Test", team=self.team)
        assert experiment.parameters is not None
        assert experiment.parameters["feature_flag_variants"] == [
            {"key": "control", "name": "Control", "rollout_percentage": 50},
            {"key": "test", "name": "Test", "rollout_percentage": 50},
        ]
        assert experiment.parameters["minimum_detectable_effect"] == 30
        assert experiment.metrics == []
        assert experiment.metrics_secondary == []

    async def test_create_experiment_missing_flag(self):
        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Test Experiment",
            feature_flag_key="non-existent-flag",
        )

        assert "Failed to create" in result
        assert "does not exist" in result
        assert artifact is not None
        assert artifact.get("error") is not None

    async def test_create_experiment_flag_without_variants(self):
        await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key="no-variants-flag",
            name="No Variants Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Test Experiment",
            feature_flag_key="no-variants-flag",
        )

        assert "Failed to create" in result
        assert "must have multivariate variants" in result
        assert artifact is not None
        assert artifact.get("error") is not None

    async def test_create_experiment_flag_with_one_variant(self):
        await self._create_multivariate_flag(
            key="one-variant-flag",
            name="One Variant Flag",
            variants=[{"key": "only_one", "name": "Only Variant", "rollout_percentage": 100}],
        )

        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Test Experiment",
            feature_flag_key="one-variant-flag",
        )

        assert "Failed to create" in result
        assert "at least 2 variants" in result
        assert artifact is not None
        assert artifact.get("error") is not None

    async def test_create_experiment_uses_flag_variants(self):
        await self._create_multivariate_flag(
            key="custom-variants-flag",
            name="Custom Variants Flag",
            variants=[
                {"key": "control", "name": "Control", "rollout_percentage": 33},
                {"key": "variant_b", "name": "Variant B", "rollout_percentage": 33},
                {"key": "variant_c", "name": "Variant C", "rollout_percentage": 34},
            ],
        )

        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Custom Variants Test",
            feature_flag_key="custom-variants-flag",
        )

        assert "Successfully created" in result

        experiment = await Experiment.objects.aget(name="Custom Variants Test", team=self.team)
        assert experiment.parameters is not None
        assert len(experiment.parameters["feature_flag_variants"]) == 3
        assert experiment.parameters["feature_flag_variants"][0]["key"] == "control"
        assert experiment.parameters["feature_flag_variants"][0]["name"] == "Control"
        assert experiment.parameters["feature_flag_variants"][0]["rollout_percentage"] == 33
        assert experiment.parameters["feature_flag_variants"][1]["key"] == "variant_b"
        assert experiment.parameters["feature_flag_variants"][2]["key"] == "variant_c"

    async def test_create_experiment_flag_without_control_variant(self):
        await self._create_multivariate_flag(
            key="no-control-flag",
            name="No Control Flag",
            variants=[
                {"key": "baseline", "name": "Baseline", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ],
        )

        tool = self._create_tool()

        result, artifact = await tool._arun_impl(
            name="Test Experiment",
            feature_flag_key="no-control-flag",
        )

        assert "Failed to create" in result
        assert "must have 'control' as the first variant" in result
        assert "Found 'baseline' instead" in result
        assert artifact is not None
        assert artifact.get("error") is not None


class TestExperimentSummaryTool(APIBaseTest):
    def _create_tool(self, context: dict) -> ExperimentSummaryTool:
        context_manager = MagicMock()
        context_manager.get_contextual_tools.return_value = {"experiment_results_summary": context}

        return ExperimentSummaryTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            context_manager=context_manager,
            config={},
        )

    async def _create_multivariate_flag(
        self,
        key: str = "test-flag",
        variants: list[dict] | None = None,
    ) -> FeatureFlag:
        if variants is None:
            variants = [
                {"key": "control", "name": "Control", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ]
        return await FeatureFlag.objects.acreate(
            team=self.team,
            created_by=self.user,
            key=key,
            name=f"Flag for {key}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {"variants": variants},
            },
        )

    async def _create_experiment(
        self,
        name: str = "Test Experiment",
        description: str | None = None,
        flag_key: str = "test-flag",
        flag_variants: list[dict] | None = None,
        stats_config: dict | None = None,
    ) -> Experiment:
        flag = await self._create_multivariate_flag(key=flag_key, variants=flag_variants)
        return await Experiment.objects.acreate(
            team=self.team,
            created_by=self.user,
            name=name,
            description=description or "",
            feature_flag=flag,
            stats_config=stats_config,
        )

    def _build_context(
        self,
        experiment_id: int,
        exposures: dict[str, float] | None = None,
        primary_metrics: list[MaxExperimentMetricResult] | None = None,
        secondary_metrics: list[MaxExperimentMetricResult] | None = None,
    ) -> dict:
        return {
            "experiment_id": experiment_id,
            "exposures": exposures,
            "primary_metrics_results": [m.model_dump() for m in primary_metrics] if primary_metrics else [],
            "secondary_metrics_results": [m.model_dump() for m in secondary_metrics] if secondary_metrics else [],
        }

    async def test_returns_formatted_experiment_data(self):
        experiment = await self._create_experiment(
            name="Pricing Test",
            description="Testing new pricing page",
            flag_key="pricing-test",
        )
        context = self._build_context(experiment_id=experiment.id)
        tool = self._create_tool(context)

        result, artifact = await tool._arun_impl()

        assert "## Experiment: Pricing Test" in result
        assert "**Statistical Method:** Bayesian" in result
        assert "**Hypothesis:** Testing new pricing page" in result
        assert artifact["experiment_name"] == "Pricing Test"
        assert artifact["stats_method"] == "bayesian"

    async def test_returns_exposure_data(self):
        experiment = await self._create_experiment(flag_key="exposure-test")
        context = self._build_context(
            experiment_id=experiment.id,
            exposures={"control": 5000.0, "test": 5000.0},
        )
        tool = self._create_tool(context)

        result, artifact = await tool._arun_impl()

        assert "### Exposures" in result
        assert "**Total:** 10000" in result
        assert "control: 5000 (50.0%)" in result
        assert "test: 5000 (50.0%)" in result

    async def test_warns_on_multiple_exposures(self):
        experiment = await self._create_experiment(flag_key="multiple-exposure-test")
        context = self._build_context(
            experiment_id=experiment.id,
            exposures={"control": 4500.0, "test": 4500.0, "$multiple": 100.0},
        )
        tool = self._create_tool(context)

        result, artifact = await tool._arun_impl()

        assert "$multiple: 100 (1.1%)" in result
        assert "**Warning:** Users exposed to multiple variants detected" in result

    async def test_returns_bayesian_metrics(self):
        experiment = await self._create_experiment(flag_key="bayesian-metrics-test")
        primary_metrics = [
            MaxExperimentMetricResult(
                name="Conversion Rate",
                goal="increase",
                variant_results=[
                    MaxExperimentVariantResultBayesian(
                        key="control",
                        chance_to_win=0.25,
                        credible_interval=[0.08, 0.12],
                        delta=0.0,
                        significant=False,
                    ),
                    MaxExperimentVariantResultBayesian(
                        key="test",
                        chance_to_win=0.75,
                        credible_interval=[0.10, 0.15],
                        delta=0.25,
                        significant=True,
                    ),
                ],
            )
        ]
        context = self._build_context(experiment_id=experiment.id, primary_metrics=primary_metrics)
        tool = self._create_tool(context)

        result, artifact = await tool._arun_impl()

        assert "### Primary Metrics" in result
        assert "**Metric: Conversion Rate**" in result
        assert "Goal: Increase" in result
        assert "Chance to win: 75.0%" in result
        assert "95% credible interval: 10.0% - 15.0%" in result
        assert "Delta (effect size): 25.0%" in result
        assert "Significant: Yes" in result
        assert artifact["has_results"] is True

    async def test_returns_frequentist_metrics(self):
        experiment = await self._create_experiment(
            flag_key="frequentist-metrics-test",
            stats_config={"method": "frequentist"},
        )
        primary_metrics = [
            MaxExperimentMetricResult(
                name="Click Rate",
                goal="increase",
                variant_results=[
                    MaxExperimentVariantResultFrequentist(
                        key="control",
                        p_value=None,
                        confidence_interval=[0.05, 0.08],
                        delta=0.0,
                        significant=False,
                    ),
                    MaxExperimentVariantResultFrequentist(
                        key="test",
                        p_value=0.023,
                        confidence_interval=[0.07, 0.11],
                        delta=0.30,
                        significant=True,
                    ),
                ],
            )
        ]
        context = self._build_context(experiment_id=experiment.id, primary_metrics=primary_metrics)
        tool = self._create_tool(context)

        result, artifact = await tool._arun_impl()

        assert "### Primary Metrics" in result
        assert "**Metric: Click Rate**" in result
        assert "P-value: 0.0230" in result
        assert "95% confidence interval: 7.0% - 11.0%" in result
        assert "Significant: Yes" in result
        assert artifact["stats_method"] == "frequentist"

    async def test_handles_no_metrics_results(self):
        experiment = await self._create_experiment(flag_key="no-metrics-test")
        context = self._build_context(experiment_id=experiment.id)
        tool = self._create_tool(context)

        result, artifact = await tool._arun_impl()

        assert "**No metrics results available yet.**" in result
        assert artifact["has_results"] is False

    async def test_returns_secondary_metrics(self):
        experiment = await self._create_experiment(flag_key="secondary-metrics-test")
        secondary_metrics = [
            MaxExperimentMetricResult(
                name="Session Duration",
                goal="increase",
                variant_results=[
                    MaxExperimentVariantResultBayesian(
                        key="control",
                        chance_to_win=0.40,
                        delta=0.0,
                        significant=False,
                    ),
                    MaxExperimentVariantResultBayesian(
                        key="test",
                        chance_to_win=0.60,
                        delta=0.15,
                        significant=False,
                    ),
                ],
            )
        ]
        context = self._build_context(experiment_id=experiment.id, secondary_metrics=secondary_metrics)
        tool = self._create_tool(context)

        result, artifact = await tool._arun_impl()

        assert "### Secondary Metrics" in result
        assert "**Metric: Session Duration**" in result

    async def test_handles_missing_experiment_id(self):
        tool = self._create_tool({})

        result, artifact = await tool._arun_impl()

        assert "No experiment specified" in result
        assert artifact["error"] == "invalid_context"

    async def test_handles_nonexistent_experiment(self):
        context = self._build_context(experiment_id=99999)
        tool = self._create_tool(context)

        result, artifact = await tool._arun_impl()

        assert "not found" in result
        assert artifact["error"] == "not_found"

    async def test_returns_variants_in_artifact(self):
        experiment = await self._create_experiment(
            flag_key="variants-test",
            flag_variants=[
                {"key": "control", "name": "Control", "rollout_percentage": 33},
                {"key": "test-a", "name": "Test A", "rollout_percentage": 33},
                {"key": "test-b", "name": "Test B", "rollout_percentage": 34},
            ],
        )
        context = self._build_context(experiment_id=experiment.id)
        tool = self._create_tool(context)

        result, artifact = await tool._arun_impl()

        assert artifact["variants"] == ["control", "test-a", "test-b"]
        assert "**Variants:** control, test-a, test-b" in result

    async def test_agent_initiated_with_experiment_id_argument(self):
        experiment = await self._create_experiment(
            name="Agent Discovered Experiment",
            description="Found via search",
            flag_key="agent-test",
        )
        # Empty context (no frontend registration)
        tool = self._create_tool({})

        mock_context = MagicMock()
        mock_context.experiment_id = experiment.id
        mock_context.experiment_name = experiment.name
        mock_context.exposures = {"control": 500.0, "test": 500.0}
        mock_context.primary_metrics_results = [
            MaxExperimentMetricResult(
                name="Conversion",
                goal="increase",
                variant_results=[
                    MaxExperimentVariantResultBayesian(key="control", chance_to_win=0.3, delta=0.0, significant=False),
                    MaxExperimentVariantResultBayesian(key="test", chance_to_win=0.7, delta=0.1, significant=False),
                ],
            )
        ]
        mock_context.secondary_metrics_results = []
        mock_context.stats_method = "bayesian"
        mock_context.variants = ["control", "test"]

        with patch(
            "products.experiments.backend.experiment_summary_data_service.ExperimentSummaryDataService"
        ) as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.fetch_experiment_data = AsyncMock(return_value=(mock_context, None, False))

            result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        assert "## Experiment: Agent Discovered Experiment" in result
        assert artifact["experiment_name"] == "Agent Discovered Experiment"
        assert artifact["has_results"] is True

    async def test_context_experiment_id_takes_priority_over_argument(self):
        experiment = await self._create_experiment(
            name="Context Experiment",
            flag_key="priority-test",
        )
        context = self._build_context(experiment_id=experiment.id)
        tool = self._create_tool(context)

        # Pass a different experiment_id as argument - context should win
        result, artifact = await tool._arun_impl(experiment_id=99999)

        assert artifact["experiment_name"] == "Context Experiment"
