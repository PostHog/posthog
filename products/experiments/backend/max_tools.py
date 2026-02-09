from datetime import UTC, datetime
from textwrap import dedent
from typing import Any, Literal

from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.schema import MaxExperimentSummaryContext

from posthog.models import Experiment, FeatureFlag
from posthog.session_recordings.session_recording_api import list_recordings_from_query
from posthog.session_recordings.utils import filter_from_params_to_query
from posthog.sync import database_sync_to_async

from ee.hogai.tool import MaxTool

CREATE_EXPERIMENT_TOOL_DESCRIPTION = dedent("""
    Use this tool to create A/B test experiments that measure the impact of changes.

    # When to use
    - The user wants to create a new A/B test or experiment
    - The user wants to test variants of a feature with controlled measurement
    - The user wants to set up a controlled experiment to measure impact

    # Prerequisites
    **IMPORTANT**: Before creating an experiment, you must first create a multivariate feature flag
    using the `create_feature_flag` tool with at least two variants (control and test).
    The first variant MUST be named "control".

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
        - The flag must have at least 2 variants
        - The first variant MUST be named "control"
        - The flag cannot already be used by another experiment

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
        # Validate inputs
        if not name or not name.strip():
            return "Experiment name cannot be empty", {"error": "invalid_name"}

        if not feature_flag_key or not feature_flag_key.strip():
            return "Feature flag key cannot be empty", {"error": "invalid_flag_key"}

        @database_sync_to_async
        def create_experiment() -> Experiment:
            # Check if experiment with this name already exists
            existing_experiment = Experiment.objects.filter(team=self._team, name=name, deleted=False).first()
            if existing_experiment:
                raise ValueError(f"An experiment with name '{name}' already exists")

            try:
                feature_flag = FeatureFlag.objects.get(team=self._team, key=feature_flag_key, deleted=False)
            except FeatureFlag.DoesNotExist:
                raise ValueError(f"Feature flag '{feature_flag_key}' does not exist")

            # Validate that the flag has multivariate variants
            multivariate = feature_flag.filters.get("multivariate")
            if not multivariate or not multivariate.get("variants"):
                raise ValueError(
                    f"Feature flag '{feature_flag_key}' must have multivariate variants to be used in an experiment. "
                    f"Create the flag with variants first using the create_feature_flag tool."
                )

            variants = multivariate["variants"]
            if len(variants) < 2:
                raise ValueError(
                    f"Feature flag '{feature_flag_key}' must have at least 2 variants for an experiment (e.g., control and test)"
                )

            # Validate that the first variant is "control" - required for experiment statistics
            if variants[0].get("key") != "control":
                raise ValueError(
                    f"Feature flag '{feature_flag_key}' must have 'control' as the first variant. "
                    f"Found '{variants[0].get('key')}' instead. Please update the feature flag variants."
                )

            # If flag already exists and is already used by another experiment, raise error
            existing_experiment_with_flag = Experiment.objects.filter(feature_flag=feature_flag, deleted=False).first()
            if existing_experiment_with_flag:
                raise ValueError(
                    f"Feature flag '{feature_flag_key}' is already used by experiment '{existing_experiment_with_flag.name}'"
                )

            # Use the actual variants from the feature flag
            feature_flag_variants = [
                {
                    "key": variant["key"],
                    "name": variant.get("name", variant["key"]),
                    "rollout_percentage": variant["rollout_percentage"],
                }
                for variant in variants
            ]

            # Create the experiment as a draft (no start_date)
            experiment = Experiment.objects.create(
                team=self._team,
                created_by=self._user,
                name=name,
                description=description or "",
                type=type,
                feature_flag=feature_flag,
                filters={},  # Empty filters for draft
                parameters={
                    "feature_flag_variants": feature_flag_variants,
                    "minimum_detectable_effect": 30,
                },
                metrics=[],
                metrics_secondary=[],
            )

            return experiment

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
        except ValueError as e:
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
    """
    Retrieve experiment results data for analysis.
    All experiment data and results are automatically provided from context.
    """


class ExperimentSummaryTool(MaxTool):
    name: str = "experiment_results_summary"
    description: str = EXPERIMENT_SUMMARY_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ExperimentSummaryArgs

    def get_required_resource_access(self):
        return [("experiment", "viewer")]

    def _format_experiment_data(self, context: MaxExperimentSummaryContext) -> str:
        """Format experiment data for the agent to analyze."""
        lines = []

        lines.append(f"## Experiment: {context.experiment_name}")
        lines.append(f"**ID:** {context.experiment_id}")
        lines.append(f"**Statistical Method:** {context.stats_method.title()}")

        if context.description:
            lines.append(f"**Hypothesis:** {context.description}")

        if context.variants:
            lines.append(f"\n**Variants:** {', '.join(context.variants)}")

        if context.exposures:
            exposures = context.exposures
            lines.append("\n### Exposures")
            total = sum(exposures.values())
            lines.append(f"**Total:** {int(total)}")

            for variant_key, count in exposures.items():
                if variant_key == "$multiple":
                    continue
                percentage = (count / total * 100) if total > 0 else 0
                lines.append(f"- {variant_key}: {int(count)} ({percentage:.1f}%)")

            if "$multiple" in exposures:
                multiple_count = exposures.get("$multiple", 0)
                multiple_pct = (multiple_count / total * 100) if total > 0 else 0
                lines.append(f"- $multiple: {int(multiple_count)} ({multiple_pct:.1f}%)")
                if multiple_pct > 0.5:
                    lines.append("**Warning:** Users exposed to multiple variants detected")

        if not context.primary_metrics_results and not context.secondary_metrics_results:
            lines.append("\n**No metrics results available yet.**")
            return "\n".join(lines)

        def format_metrics_section(metrics: list, section_name: str) -> None:
            """Helper to format a section of metrics (primary or secondary)."""
            if not metrics:
                return

            lines.append(f"\n### {section_name}")
            for metric in metrics[:10]:  # Limit to 10 metrics per section
                lines.append(f"\n**Metric: {metric.name}**")
                if metric.goal and metric.goal.value:
                    lines.append(f"Goal: {metric.goal.value.title()}")

                if not metric.variant_results:
                    continue

                for variant in metric.variant_results:
                    lines.append(f"\n*{variant.key}:*")

                    if context.stats_method == "bayesian":
                        if hasattr(variant, "chance_to_win") and variant.chance_to_win is not None:
                            lines.append(f"  - Chance to win: {variant.chance_to_win:.1%}")

                        if hasattr(variant, "credible_interval") and variant.credible_interval:
                            ci_low, ci_high = variant.credible_interval[:2]
                            lines.append(f"  - 95% credible interval: {ci_low:.1%} - {ci_high:.1%}")

                        if hasattr(variant, "delta") and variant.delta is not None:
                            lines.append(f"  - Delta (effect size): {variant.delta:.1%}")

                        lines.append(f"  - Significant: {'Yes' if variant.significant else 'No'}")
                    else:
                        if hasattr(variant, "p_value") and variant.p_value is not None:
                            lines.append(f"  - P-value: {variant.p_value:.4f}")

                        if hasattr(variant, "confidence_interval") and variant.confidence_interval:
                            ci_low, ci_high = variant.confidence_interval[:2]
                            lines.append(f"  - 95% confidence interval: {ci_low:.1%} - {ci_high:.1%}")

                        if hasattr(variant, "delta") and variant.delta is not None:
                            lines.append(f"  - Delta (effect size): {variant.delta:.1%}")

                        lines.append(f"  - Significant: {'Yes' if variant.significant else 'No'}")

        format_metrics_section(context.primary_metrics_results, "Primary Metrics")
        format_metrics_section(context.secondary_metrics_results, "Secondary Metrics")

        return "\n".join(lines)

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        try:
            try:
                validated_context = MaxExperimentSummaryContext(**self.context)
            except Exception as e:
                error_details = str(e)
                error_context: dict[str, Any] = {
                    "error": "invalid_context",
                    "details": error_details,
                }

                if hasattr(e, "__cause__") and e.__cause__:
                    error_context["validation_cause"] = str(e.__cause__)

                capture_exception(
                    e,
                    properties={
                        "team_id": self._team.id,
                        "user_id": self._user.id,
                        "context_keys": list(self.context.keys()) if isinstance(self.context, dict) else None,
                        "experiment_id": self.context.get("experiment_id") if isinstance(self.context, dict) else None,
                    },
                )

                return f"Invalid experiment context: {error_details}", error_context

            formatted_data = self._format_experiment_data(validated_context)

            return formatted_data, {
                "experiment_id": validated_context.experiment_id,
                "experiment_name": validated_context.experiment_name,
                "stats_method": validated_context.stats_method,
                "variants": validated_context.variants,
                "has_results": bool(
                    validated_context.primary_metrics_results or validated_context.secondary_metrics_results
                ),
            }

        except Exception as e:
            capture_exception(
                e,
                properties={
                    "team_id": self._team.id,
                    "user_id": self._user.id,
                    "experiment_id": self.context.get("experiment_id") if isinstance(self.context, dict) else None,
                },
            )
            return f"❌ Failed to summarize experiment: {str(e)}", {"error": "summary_failed", "details": str(e)}


# Session Replay Summary Tool


class SessionReplaySummaryArgs(BaseModel):
    """
    Analyze session replay patterns for an experiment to understand user behavior across variants.
    """

    experiment_id: int = Field(description="The ID of the experiment to analyze session replays for")


class SessionReplaySummaryOutput(BaseModel):
    """Structured output for session replay summary"""

    experiment_id: int = Field(description="ID of the experiment")
    experiment_name: str = Field(default="", description="Name of the experiment")
    behavioral_patterns: list[str] = Field(
        default_factory=list,
        description="Key behavioral patterns observed across experiment variants",
        max_length=20,
    )
    recording_counts: dict[str, int] = Field(
        default_factory=dict, description="Number of recordings available per variant"
    )
    total_recordings: int = Field(default=0, description="Total number of recordings across all variants")
    variants: list[str] = Field(default_factory=list, description="List of variant keys")
    date_range: dict[str, str | None] = Field(default_factory=dict, description="Experiment date range")
    variant_insights: dict[str, list[str]] = Field(default_factory=dict, description="Specific insights per variant")
    warning: str | None = Field(default=None, description="Warning about data quality or availability")
    error: str | None = Field(default=None, description="Error code if something went wrong")


SESSION_REPLAY_SUMMARY_TOOL_DESCRIPTION = """
Use this tool to analyze session replay patterns across experiment variants to understand user behavior differences.
The tool provides recording counts per variant and context for Max to analyze actual session recordings.

This tool is useful when:
- Understanding how users interact with different experiment variants
- Identifying usability issues or confusion in specific variants
- Comparing user behavior patterns between control and test variants
- Getting qualitative insights to complement quantitative experiment results

**Important:** This tool provides the context and recording counts. Use the filter_session_recordings tool to actually fetch and analyze the recordings for each variant.

# Examples

<example>
User: How are users behaving in my experiment?
Assistant: I'll analyze session replay patterns across your experiment variants.
*Uses experiment_session_replays_summary tool*
Assistant: I found 299 total recordings across your variants. Let me analyze them...

<reasoning>
The assistant used experiment_session_replays_summary to get recording counts and filters for the experiment variants.
</reasoning>
</example>
""".strip()


class SessionReplaySummaryTool(MaxTool):
    name: str = "experiment_session_replays_summary"
    description: str = SESSION_REPLAY_SUMMARY_TOOL_DESCRIPTION
    context_prompt_template: str = "Analyzes session replay patterns in experiment variants."

    args_schema: type[BaseModel] = SessionReplaySummaryArgs

    def get_required_resource_access(self):
        return [("experiment", "viewer")]

    async def _arun_impl(
        self,
        experiment_id: int,
    ) -> tuple[str, dict[str, Any]]:
        try:
            # Fetch experiment
            @database_sync_to_async
            def get_experiment():
                try:
                    return Experiment.objects.select_related("team", "feature_flag").get(
                        id=experiment_id, team=self._team
                    )
                except Experiment.DoesNotExist:
                    raise ValueError(f"Experiment {experiment_id} not found")

            experiment = await get_experiment()

            if not experiment.start_date:
                output = SessionReplaySummaryOutput(
                    experiment_id=experiment_id,
                    experiment_name=experiment.name,
                    error="not_started",
                )
                return "❌ Experiment has not started yet. No session replays available.", output.model_dump()

            # Get variants from feature flag
            feature_flag = experiment.feature_flag
            multivariate = feature_flag.filters.get("multivariate", {})
            variants = multivariate.get("variants", [])
            variant_keys = [v["key"] for v in variants]

            if not variant_keys:
                output = SessionReplaySummaryOutput(
                    experiment_id=experiment_id,
                    experiment_name=experiment.name,
                    error="no_variants",
                )
                return "❌ No variants configured for this experiment.", output.model_dump()

            # Count recordings per variant
            recording_counts = {}
            for variant_key in variant_keys:
                # Build recording filters for this variant
                filters = self._build_experiment_recording_filters(experiment, variant_key)

                # Convert to RecordingsQuery and count
                try:
                    query = filter_from_params_to_query(filters)
                    query.limit = 100

                    @database_sync_to_async
                    def count_recordings(q):
                        recordings, has_more, _, _ = list_recordings_from_query(query=q, user=None, team=self._team)
                        # If has_more, there are 100+ recordings
                        return len(recordings) if not has_more else 100

                    count = await count_recordings(query)
                    recording_counts[variant_key] = count
                except Exception as e:
                    capture_exception(
                        e,
                        properties={
                            "team_id": self._team.id,
                            "experiment_id": experiment_id,
                            "variant_key": variant_key,
                        },
                    )
                    recording_counts[variant_key] = 0

            total_recordings = sum(recording_counts.values())

            if total_recordings == 0:
                output = SessionReplaySummaryOutput(
                    experiment_id=experiment_id,
                    experiment_name=experiment.name,
                    recording_counts=recording_counts,
                    variants=variant_keys,
                    error="no_recordings",
                )
                return (
                    f"❌ No session recordings found for experiment '{experiment.name}'. "
                    "Make sure session replay is enabled and users have been exposed to the experiment.",
                    output.model_dump(),
                )

            # Build response
            behavioral_patterns = [
                f"Experiment '{experiment.name}' has {total_recordings} total session recordings across {len(variant_keys)} variants",
                "To analyze user behavior, use the filter_session_recordings tool with the filters for each variant",
                "Compare behavior patterns between variants to understand the impact of your changes",
            ]

            # Add variant-specific guidance
            for variant_key, count in recording_counts.items():
                if count > 0:
                    behavioral_patterns.append(f"Variant '{variant_key}': {count} recordings available for analysis")

            user_message = self._format_summary_for_user(
                experiment_name=experiment.name,
                recording_counts=recording_counts,
                total_recordings=total_recordings,
            )

            output = SessionReplaySummaryOutput(
                experiment_id=experiment_id,
                experiment_name=experiment.name,
                behavioral_patterns=behavioral_patterns,
                recording_counts=recording_counts,
                total_recordings=total_recordings,
                variants=variant_keys,
                date_range={
                    "start": experiment.start_date.isoformat() if experiment.start_date else None,
                    "end": experiment.end_date.isoformat() if experiment.end_date else None,
                },
            )

            return user_message, output.model_dump()

        except ValueError as e:
            return f"❌ {str(e)}", {"error": "validation_error", "details": str(e)}
        except Exception as e:
            capture_exception(
                e,
                properties={
                    "team_id": self._team.id,
                    "user_id": self._user.id,
                    "experiment_id": experiment_id,
                },
            )
            return f"❌ Failed to analyze session replays: {str(e)}", {
                "error": "analysis_failed",
                "details": str(e),
            }

    def _build_experiment_recording_filters(self, experiment: Experiment, variant_key: str) -> dict[str, Any]:
        """
        Build recording filters for experiment variant.

        Replicates frontend getViewRecordingFilters() logic from experiments/utils.ts
        """
        feature_flag_key = experiment.feature_flag.key

        # Build filter structure matching RecordingUniversalFilters
        return {
            "date_from": experiment.start_date.isoformat() if experiment.start_date else None,
            "date_to": experiment.end_date.isoformat() if experiment.end_date else datetime.now(UTC).isoformat(),
            "events": [
                {
                    "id": "$feature_flag_called",
                    "type": "events",
                    "properties": [
                        {
                            "key": "$feature_flag",
                            "value": [feature_flag_key],
                            "operator": "exact",
                            "type": "event",
                        },
                        {
                            "key": f"$feature/{feature_flag_key}",
                            "value": [variant_key],
                            "operator": "exact",
                            "type": "event",
                        },
                    ],
                }
            ],
        }

    def _format_summary_for_user(
        self, experiment_name: str, recording_counts: dict[str, int], total_recordings: int
    ) -> str:
        """Format the session replay summary for user display"""
        lines = [
            f"📹 Session Replay Summary for '{experiment_name}'",
            "",
            f"Total recordings: {total_recordings}",
            "",
            "Recordings by variant:",
        ]

        for variant_key, count in recording_counts.items():
            percentage = (count / total_recordings * 100) if total_recordings > 0 else 0
            lines.append(f"  • {variant_key}: {count} ({percentage:.1f}%)")

        lines.extend(
            [
                "",
                "💡 To analyze user behavior patterns:",
                "  1. I can help you filter and view specific recordings",
                "  2. Compare behavior differences between variants",
                "  3. Identify usability issues or unexpected user journeys",
                "",
                "What would you like to explore?",
            ]
        )

        return "\n".join(lines)
