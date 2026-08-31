from textwrap import dedent
from typing import Any, Literal

from posthoganalytics import capture_exception
from pydantic import BaseModel, Field
from rest_framework.exceptions import ValidationError

from posthog.event_usage import EventSource
from posthog.sync import database_sync_to_async

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.experiment_summary_data_service import ExperimentSummaryDataService
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag, experiment_eligibility_error

from ee.hogai.context.experiment.context import ExperimentContext
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolAccessDeniedError

CREATE_EXPERIMENT_TOOL_DESCRIPTION = dedent("""
    Use this tool to create A/B test experiments that measure the impact of changes.

    # When to use
    - The user wants to create a new A/B test or experiment
    - The user wants to test variants of a feature with controlled measurement
    - The user wants to set up a controlled experiment to measure impact

    # Prerequisites
    **IMPORTANT**: Before creating an experiment, you must first create a multivariate feature flag
    using the `create_feature_flag` tool with 2 to 20 variants (conventionally control and test).
    The baseline defaults to the variant named "control" when present, else the first variant.

    # Experiment Types
    - **product**: For backend/API changes, server-side experiments
    - **web**: For frontend UI changes, client-side experiments

    # Workflow
    1. Create a multivariate feature flag with `create_feature_flag` (variants: control + test)
    2. Create the experiment with this tool, linking it to the feature flag
    3. Configure metrics in the PostHog UI
    4. Launch the experiment when ready
    """).strip()


class CreateExperimentToolArgs(BaseModel):
    name: str = Field(
        description=dedent("""
        The experiment name - should clearly describe what is being tested.

        Examples:
        - "Pricing Page Redesign Test"
        - "New Checkout Flow Experiment"
        - "Homepage CTA Button A/B Test"
        """).strip()
    )
    feature_flag_key: str = Field(
        description=dedent("""
        The key of an existing multivariate feature flag to use for this experiment.

        Requirements:
        - The flag must already exist (create it first with create_feature_flag)
        - The flag must have multivariate variants defined
        - The flag must have 2 to 20 variants
        - The flag cannot already be used by another experiment

        The baseline defaults to the variant keyed "control" when present, else the first variant.

        Example: "pricing-page-experiment"
        """).strip()
    )
    description: str | None = Field(
        default=None,
        description=dedent("""
        Optional detailed description of the experiment.

        Should include:
        - The hypothesis being tested
        - What changes are being made in each variant
        - Expected outcomes or success criteria

        Example: "Testing whether a simplified checkout flow increases conversion rates.
        Control shows existing 3-step checkout, test shows new 1-page checkout."
        """).strip(),
    )
    type: Literal["product", "web"] = Field(
        default="product",
        description=dedent("""
        The experiment type:
        - "product": For backend/API changes, server-side experiments (default)
        - "web": For frontend UI changes, client-side experiments
        """).strip(),
    )


class CreateExperimentTool(MaxTool):
    name: Literal["create_experiment"] = "create_experiment"
    description: str = CREATE_EXPERIMENT_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateExperimentToolArgs

    def get_required_resource_access(self):
        return [("experiment", "editor")]

    async def _arun_impl(
        self,
        name: str,
        feature_flag_key: str,
        description: str | None = None,
        type: Literal["product", "web"] = "product",
    ) -> tuple[str, dict[str, Any] | None]:
        if not name or not name.strip():
            return "Experiment name cannot be empty", {"error": "invalid_name"}

        if not feature_flag_key or not feature_flag_key.strip():
            return "Feature flag key cannot be empty", {"error": "invalid_flag_key"}

        @database_sync_to_async
        def create_experiment() -> Experiment:
            existing_experiment = Experiment.objects.filter(team=self._team, name=name, deleted=False).first()
            if existing_experiment:
                raise ValueError(f"An experiment with name '{name}' already exists")

            try:
                feature_flag = FeatureFlag.objects.get(team=self._team, key=feature_flag_key)
            except FeatureFlag.DoesNotExist:
                raise ValueError(f"Feature flag '{feature_flag_key}' does not exist")

            eligibility_error = experiment_eligibility_error(feature_flag.variants)
            if eligibility_error:
                raise ValueError(
                    f"Feature flag '{feature_flag_key}' cannot back an experiment: {eligibility_error}. "
                    f"Update the flag's variants, or create a new flag with the create_feature_flag tool."
                )

            existing_experiment_with_flag = Experiment.objects.filter(feature_flag=feature_flag, deleted=False).first()
            if existing_experiment_with_flag:
                raise ValueError(
                    f"Feature flag '{feature_flag_key}' is already used by experiment '{existing_experiment_with_flag.name}'"
                )

            # The flag already exists with valid variants, so the experiment links to it as-is —
            # no flag config to send. (create_experiment reuses the existing flag unchanged.)
            service = ExperimentService(team=self._team, user=self._user)
            return service.create_experiment(
                name=name,
                feature_flag_key=feature_flag_key,
                description=description or "",
                type=type,
                running_time_calculation={
                    "minimum_detectable_effect": 30,
                },
                event_source=EventSource.POSTHOG_AI,
            )

        try:
            experiment = await create_experiment()
            experiment_url = f"/project/{self._team.project_id}/experiments/{experiment.id}"

            return (
                f"Successfully created experiment '{name}'. "
                f"The experiment is in draft mode - you can configure metrics and launch it at {experiment_url}",
                {
                    "experiment_id": experiment.id,
                    "experiment_name": experiment.name,
                    "feature_flag_key": feature_flag_key,
                    "type": type,
                    "url": experiment_url,
                },
            )
        except (ValueError, ValidationError) as e:
            return f"Failed to create experiment: {str(e)}", {"error": str(e)}
        except Exception as e:
            capture_exception(e)
            return f"Failed to create experiment: {str(e)}", {"error": "creation_failed"}


EXPERIMENT_SUMMARY_TOOL_DESCRIPTION = dedent("""
    Use this tool to retrieve experiment results data for analysis.

    # When to use
    - The user wants to understand their experiment results
    - The user asks about A/B test performance or metrics
    - The user wants to know if their experiment is statistically significant
    - The user asks for insights or recommendations based on experiment data

    # What this tool returns
    Returns formatted experiment data including:
    - Experiment metadata (name, description, variants)
    - Exposure data (sample sizes per variant)
    - Primary and secondary metrics results with statistical measures
    - For Bayesian experiments: chance to win, credible intervals, significance
    - For Frequentist experiments: p-values, confidence intervals, significance

    # Data interpretation
    The data returned includes all information needed to analyze the experiment:
    - **Exposures**: Sample size per variant, quality warnings for multiple exposures
    - **Metrics**: Each metric shows results per variant with statistical measures
    - **Significance**: Whether results are statistically significant
    - **Effect size (delta)**: The percentage change from control

    # Important notes
    - Analyze each metric separately - different metrics may favor different variants
    - Consider sample size when interpreting results
    - Check for setup issues like users exposed to multiple variants
    """).strip()


class ExperimentSummaryArgs(BaseModel):
    experiment_id: int | None = Field(
        default=None,
        description="The ID of the experiment to summarize. Not needed when the user is viewing an experiment (taken from context).",
    )


class ExperimentSummaryTool(MaxTool):
    name: str = "experiment_results_summary"
    description: str = EXPERIMENT_SUMMARY_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ExperimentSummaryArgs

    def get_required_resource_access(self):
        return [("experiment", "viewer")]

    async def _arun_impl(self, experiment_id: int | None = None) -> tuple[str, dict[str, Any]]:
        """Retrieve experiment data and format it for the agent."""

        try:
            context = self.context

            resolved_experiment_id = context.get("experiment_id") or experiment_id

            if resolved_experiment_id is None:
                return "No experiment specified. Please provide an experiment_id.", {"error": "invalid_context"}

            resolved_experiment_id = int(resolved_experiment_id)

            return await self._fetch_and_format(resolved_experiment_id)

        except MaxToolAccessDeniedError:
            raise
        except Exception as e:
            capture_exception(
                e,
                properties={
                    "team_id": self._team.id,
                    "user_id": self._user.id,
                    "experiment_id": self.context.get("experiment_id") if isinstance(self.context, dict) else None,
                },
            )
            return f"Failed to summarize experiment: {str(e)}", {"error": "summary_failed", "details": str(e)}

    async def _fetch_and_format(self, experiment_id: int) -> tuple[str, dict[str, Any]]:
        """Fetch experiment data from query runners and format it."""
        experiment_context = ExperimentContext(team=self._team, experiment_id=experiment_id)
        experiment = await experiment_context.aget_experiment()
        if experiment is None:
            return f"Experiment {experiment_id} not found", {"error": "not_found"}

        # Before the metric queries run, so a denied user costs no ClickHouse work
        await self.check_object_access(experiment, "viewer", resource="experiment", action="read")

        data_service = ExperimentSummaryDataService(self._team, self._user)

        try:
            summary_data = await data_service.fetch_experiment_data(experiment_id)
        except ValueError as e:
            return str(e), {"error": "not_found"}

        summary_context = summary_data.context

        formatted_data = await experiment_context.format_experiment_results_data(
            experiment,
            exposures=summary_context.exposures,
            primary_metrics_results=summary_context.primary_metrics_results,
            secondary_metrics_results=summary_context.secondary_metrics_results,
        )

        if summary_data.pending_calculation:
            formatted_data += "\n\n**Note:** Some metrics are still being calculated. Results may be incomplete."

        if summary_data.omitted_metric_count:
            formatted_data += (
                f"\n\n**Note:** {summary_data.omitted_metric_count} metrics were omitted from this summary."
            )

        return self._build_result(
            experiment,
            formatted_data,
            summary_context.primary_metrics_results,
            summary_context.secondary_metrics_results,
        )

    def _build_result(
        self,
        experiment: Experiment,
        formatted_data: str,
        primary_metrics: list,
        secondary_metrics: list,
    ) -> tuple[str, dict[str, Any]]:
        """Build the final result tuple with artifact metadata."""
        stats_method = get_experiment_stats_method(experiment)
        variants = [v.get("key") for v in experiment.feature_flag.variants if v.get("key")]

        return formatted_data, {
            "experiment_id": experiment.id,
            "experiment_name": experiment.name,
            "stats_method": stats_method,
            "variants": variants,
            "has_results": bool(primary_metrics or secondary_metrics),
        }
