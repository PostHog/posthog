from datetime import UTC, datetime
from typing import Any, Literal

from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.schema import MaxExperimentSummaryContext

from posthog.models import Experiment, FeatureFlag
from posthog.session_recordings.session_recording_api import list_recordings_from_query
from posthog.session_recordings.utils import filter_from_params_to_query
from posthog.sync import database_sync_to_async

from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .experiment_summary_data_service import ExperimentSummaryDataService
from .prompts import EXPERIMENT_SUMMARY_BAYESIAN_PROMPT, EXPERIMENT_SUMMARY_FREQUENTIST_PROMPT


class CreateExperimentArgs(BaseModel):
    name: str = Field(description="Experiment name - should clearly describe what is being tested")
    feature_flag_key: str = Field(
        description="Feature flag key (letters, numbers, hyphens, underscores only). Will create a new flag if it doesn't exist."
    )
    description: str | None = Field(
        default=None,
        description="Detailed description of the experiment hypothesis, what changes are being tested, and expected outcomes",
    )
    type: Literal["product", "web"] = Field(
        default="product",
        description="Experiment type: 'product' for backend/API changes, 'web' for frontend UI changes",
    )


class CreateExperimentTool(MaxTool):
    name: Literal["create_experiment"] = "create_experiment"
    description: str = """
Create a new A/B test experiment in the current project.

Experiments allow you to test changes with a controlled rollout and measure their impact.

Use this tool when the user wants to:
- Create a new A/B test experiment
- Set up a controlled experiment to test changes
- Test variants of a feature with users

Examples:
- "Create an experiment to test the new checkout flow"
- "Set up an A/B test for our pricing page redesign"
- "Create an experiment called 'homepage-cta-test' to test different call-to-action buttons

**IMPORTANT**: You must first find or create a multivariate feature flag using `create_feature_flag`, with at least two variants (control and test)."
    """.strip()
    context_prompt_template: str = "Creates a new A/B test experiment in the project"
    args_schema: type[BaseModel] = CreateExperimentArgs

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


class ExperimentSummaryArgs(BaseModel):
    """
    Analyze experiment results to generate an executive summary with key insights and recommendations.
    The tool fetches experiment data directly from the backend using the experiment ID.
    """

    experiment_id: int = Field(description="The ID of the experiment to summarize")


class ExperimentSummaryOutput(BaseModel):
    """Structured output for experiment summary"""

    key_metrics: list[str] = Field(description="Summary of key metric performance", max_length=20)
    freshness_warning: str | None = Field(default=None, description="Warning if data has been updated since page load")


EXPERIMENT_SUMMARY_TOOL_DESCRIPTION = """
Use this tool to analyze experiment results and generate an executive summary with key insights and recommendations.
The tool processes experiment data including metrics, statistical significance, and variant performance to provide actionable insights.
It works with both Bayesian and Frequentist statistical methods and automatically adapts to the experiment's configuration.

**Important:** When presenting results to the user, include any data freshness notices from the tool output. These notices inform the user if the data has been updated since they loaded the page.

# Examples of when to use the experiment_results_summary tool

<example>
User: Can you summarize the results of my experiment?
Assistant: I'll analyze your experiment results and provide a summary with key insights.
*Uses experiment_results_summary tool*
Assistant: Based on the analysis of your experiment results...

<reasoning>
The assistant used the experiment_results_summary tool because:
1. The user is asking for a summary of experiment results
2. The tool can analyze the statistical data and provide actionable insights
</reasoning>
</example>

<example>
User: What are the key takeaways from this A/B test?
Assistant: Let me analyze the experiment results to identify the key takeaways.
*Uses experiment_results_summary tool*
Assistant: The key takeaways from your A/B test are...

<reasoning>
The assistant used the experiment_results_summary tool because:
1. The user wants to understand the main findings from their experiment
2. The tool can extract and summarize the most important metrics and outcomes
</reasoning>
</example>
""".strip()


class ExperimentSummaryTool(MaxTool):
    name: str = "experiment_results_summary"
    description: str = EXPERIMENT_SUMMARY_TOOL_DESCRIPTION
    context_prompt_template: str = "Analyzes experiment results and generates executive summaries with key insights."

    args_schema: type[BaseModel] = ExperimentSummaryArgs

    def get_required_resource_access(self):
        return [("experiment", "viewer")]

    def _data_service(self) -> "ExperimentSummaryDataService":
        return ExperimentSummaryDataService(self._team)

    async def _analyze_experiment(self, context: MaxExperimentSummaryContext) -> ExperimentSummaryOutput:
        """Analyze experiment and generate summary."""
        try:
            if context.stats_method not in ("bayesian", "frequentist"):
                raise ValueError(f"Unsupported statistical method: {context.stats_method}")

            prompt_template = (
                EXPERIMENT_SUMMARY_BAYESIAN_PROMPT
                if context.stats_method == "bayesian"
                else EXPERIMENT_SUMMARY_FREQUENTIST_PROMPT
            )

            formatted_data = self._format_experiment_for_llm(context)

            llm = MaxChatOpenAI(
                user=self._user,
                team=self._team,
                model="gpt-4.1",
                temperature=0.1,
                billable=True,
            ).with_structured_output(ExperimentSummaryOutput)

            formatted_prompt = prompt_template.replace("{{{experiment_data}}}", formatted_data)

            analysis_result = await llm.ainvoke([{"role": "system", "content": formatted_prompt}])

            if isinstance(analysis_result, dict):
                return ExperimentSummaryOutput(**analysis_result)
            return analysis_result

        except Exception as e:
            capture_exception(
                e,
                properties={"team_id": self._team.id, "user_id": self._user.id, "experiment_id": context.experiment_id},
            )
            return ExperimentSummaryOutput(key_metrics=[f"Analysis failed: {str(e)}"])

    def _format_experiment_for_llm(self, context: MaxExperimentSummaryContext) -> str:
        """Format experiment data for LLM consumption."""
        lines = []

        lines.append(f"Statistical method: {context.stats_method.title()}")
        lines.append(f"Experiment: {context.experiment_name}")

        if context.description:
            lines.append(f"Hypothesis: {context.description}")

        if context.variants:
            lines.append(f"\nVariants: {', '.join(context.variants)}")

        if context.exposures:
            exposures = context.exposures
            lines.append("\nExposures:")
            total = sum(exposures.values())
            lines.append(f"  Total: {int(total)}")

            for variant_key, count in exposures.items():
                if variant_key == "$multiple":
                    continue
                percentage = (count / total * 100) if total > 0 else 0
                lines.append(f"  {variant_key}: {int(count)} ({percentage:.1f}%)")

            if "$multiple" in exposures:
                multiple_count = exposures.get("$multiple", 0)
                lines.append(f"  $multiple: {int(multiple_count)} ({multiple_count / total * 100:.1f}%)")
                lines.append("  [Quality Warning: Users exposed to multiple variants detected]")

        if not context.primary_metrics_results and not context.secondary_metrics_results:
            return "\n".join(lines)

        lines.append("\nResults:")

        def format_metrics_section(metrics: list, section_name: str) -> None:
            """Helper to format a section of metrics (primary or secondary)."""
            if not metrics:
                return

            lines.append(f"\n{section_name}:")
            for metric in metrics:
                lines.append(f"\nMetric: {metric.name}")
                if metric.goal:
                    # Handle enum and string goal representations
                    goal_str = metric.goal.value if hasattr(metric.goal, "value") else str(metric.goal)
                    lines.append(f"  Goal: {goal_str.title()}")

                if not metric.variant_results:
                    continue

                for variant in metric.variant_results:
                    lines.append(f"  {variant.key}:")

                    if context.stats_method == "bayesian":
                        if hasattr(variant, "chance_to_win") and variant.chance_to_win is not None:
                            lines.append(f"    Chance to win: {variant.chance_to_win:.1%}")

                        if hasattr(variant, "credible_interval") and variant.credible_interval:
                            ci_low, ci_high = variant.credible_interval[:2]
                            lines.append(f"    95% credible interval: {ci_low:.1%} - {ci_high:.1%}")

                        if hasattr(variant, "delta") and variant.delta is not None:
                            lines.append(f"    Delta (effect size): {variant.delta:.1%}")

                        lines.append(f"    Significant: {'Yes' if variant.significant else 'No'}")
                    else:
                        if hasattr(variant, "p_value") and variant.p_value is not None:
                            lines.append(f"    P-value: {variant.p_value:.4f}")

                        if hasattr(variant, "confidence_interval") and variant.confidence_interval:
                            ci_low, ci_high = variant.confidence_interval[:2]
                            lines.append(f"    95% confidence interval: {ci_low:.1%} - {ci_high:.1%}")

                        if hasattr(variant, "delta") and variant.delta is not None:
                            lines.append(f"    Delta (effect size): {variant.delta:.1%}")

                        lines.append(f"    Significant: {'Yes' if variant.significant else 'No'}")

        format_metrics_section(context.primary_metrics_results[:10], "Primary Metrics")
        format_metrics_section(context.secondary_metrics_results[:10], "Secondary Metrics")

        return "\n".join(lines)

    def _format_summary_for_user(self, summary: ExperimentSummaryOutput, experiment_name: str) -> str:
        """Format the structured summary into a user-friendly message."""
        lines = []

        if summary.freshness_warning:
            lines.append("[IMPORTANT: Include this data freshness notice when presenting results to the user]")
            lines.append(summary.freshness_warning)
            lines.append("[End of notice]")
            lines.append("")

        lines.append(f"✅ **Experiment Summary: '{experiment_name}'**")

        if summary.key_metrics:
            lines.append("\n**📊 Key Metrics:**")
            for metric in summary.key_metrics:
                lines.append(f"• {metric}")

        return "\n".join(lines)

    async def _arun_impl(
        self,
        experiment_id: int,
    ) -> tuple[str, dict[str, Any]]:
        # Get frontend_last_refresh from the tool's registered context (set by frontend)
        frontend_last_refresh = self.context.get("frontend_last_refresh")

        try:
            # Fetch experiment data from the backend
            try:
                data_service = self._data_service()
                context, backend_last_refresh, pending_calculation = await data_service.fetch_experiment_data(
                    experiment_id
                )
            except ValueError as e:
                return f"❌ {str(e)}", {"error": "fetch_failed", "details": str(e)}

            if pending_calculation:
                return "⏳ Experiment results are still computing. Please try again in a minute.", {
                    "error": "results_pending",
                    "experiment_id": experiment_id,
                }

            if not context.primary_metrics_results and not context.secondary_metrics_results:
                return "❌ No experiment results to analyze. The experiment may not have collected enough data yet.", {
                    "error": "no_results",
                    "experiment_id": experiment_id,
                }

            # Analyze the experiment
            summary_result = await self._analyze_experiment(context)

            # Add freshness warning if applicable
            freshness_warning = self._data_service().check_data_freshness(frontend_last_refresh, backend_last_refresh)
            if freshness_warning:
                summary_result.freshness_warning = freshness_warning

            user_message = self._format_summary_for_user(summary_result, context.experiment_name)

            return user_message, {
                "experiment_id": context.experiment_id,
                "experiment_name": context.experiment_name,
                "summary": summary_result.model_dump(),
                "data_refreshed_at": backend_last_refresh.isoformat() if backend_last_refresh else None,
                "freshness_warning": freshness_warning,
            }

        except Exception as e:
            capture_exception(
                e,
                properties={
                    "team_id": self._team.id,
                    "user_id": self._user.id,
                    "experiment_id": experiment_id,
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
