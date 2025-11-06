"""
MaxTool for AI-powered experiment summary.
"""

from typing import Any

from pydantic import BaseModel, Field

from posthog.schema import MaxExperimentSummaryContext

from posthog.exceptions_capture import capture_exception

from products.enterprise.backend.hogai.llm import MaxChatOpenAI
from products.enterprise.backend.hogai.tool import MaxTool

from .prompts import EXPERIMENT_SUMMARY_BAYESIAN_PROMPT, EXPERIMENT_SUMMARY_FREQUENTIST_PROMPT

MAX_METRICS_TO_SUMMARIZE = 3


class ExperimentSummaryArgs(BaseModel):
    """
    Analyze experiment results to generate an executive summary with key insights and recommendations.
    All experiment data and results are automatically provided from context.
    """


class ExperimentSummaryOutput(BaseModel):
    """Structured output for experiment summary"""

    key_metrics: list[str] = Field(description="Summary of key metric performance", max_length=3)


EXPERIMENT_SUMMARY_TOOL_DESCRIPTION = """
Use this tool to analyze experiment results and generate an executive summary with key insights and recommendations.
The tool processes experiment data including metrics, statistical significance, and variant performance to provide actionable insights.
It works with both Bayesian and Frequentist statistical methods and automatically adapts to the experiment's configuration.

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
            ).with_structured_output(ExperimentSummaryOutput)

            formatted_prompt = prompt_template.replace("{{{experiment_data}}}", formatted_data)
            analysis_result = await llm.ainvoke([{"role": "system", "content": formatted_prompt}])

            if isinstance(analysis_result, dict):
                return ExperimentSummaryOutput(**analysis_result)
            return analysis_result

        except Exception as e:
            capture_exception(
                e, {"team_id": self._team.id, "user_id": self._user.id, "experiment_id": context.experiment_id}
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

        if not context.metrics_results:
            return "\n".join(lines)

        lines.append("\nResults:")

        for metric in context.metrics_results[:MAX_METRICS_TO_SUMMARIZE]:
            lines.append(f"\nMetric: {metric.name}")

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

                    lines.append(f"    Significant: {'Yes' if variant.significant else 'No'}")
                else:
                    if hasattr(variant, "p_value") and variant.p_value is not None:
                        lines.append(f"    P-value: {variant.p_value:.4f}")

                    if hasattr(variant, "confidence_interval") and variant.confidence_interval:
                        ci_low, ci_high = variant.confidence_interval[:2]
                        lines.append(f"    95% confidence interval: {ci_low:.1%} - {ci_high:.1%}")

                    lines.append(f"    Significant: {'Yes' if variant.significant else 'No'}")

        return "\n".join(lines)

    def _format_summary_for_user(self, summary: ExperimentSummaryOutput, experiment_name: str) -> str:
        """Format the structured summary into a user-friendly message."""
        lines = []
        lines.append(f"✅ **Experiment Summary: '{experiment_name}'**")

        if summary.key_metrics:
            lines.append("\n**📊 Key Metrics:**")
            for metric in summary.key_metrics:
                lines.append(f"• {metric}")

        return "\n".join(lines)

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        try:
            try:
                validated_context = MaxExperimentSummaryContext(**self.context)
            except Exception as e:
                error_details = str(e)
                error_context = {
                    "error": "invalid_context",
                    "details": error_details,
                }

                if hasattr(e, "__cause__") and e.__cause__:
                    error_context["validation_cause"] = str(e.__cause__)

                capture_exception(
                    e,
                    {
                        "team_id": self._team.id,
                        "user_id": self._user.id,
                        "context_keys": list(self.context.keys()) if isinstance(self.context, dict) else None,
                        "experiment_id": self.context.get("experiment_id") if isinstance(self.context, dict) else None,
                    },
                )

                return f"❌ Invalid experiment context: {error_details}", error_context

            if not validated_context.metrics_results:
                return "❌ No experiment results to analyze", {
                    "error": "no_results",
                    "details": "No metrics results provided in context",
                }

            summary_result = await self._analyze_experiment(validated_context)
            user_message = self._format_summary_for_user(summary_result, validated_context.experiment_name)

            return user_message, {
                "experiment_id": validated_context.experiment_id,
                "experiment_name": validated_context.experiment_name,
                "summary": summary_result.model_dump(),
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Failed to summarize experiment: {str(e)}", {"error": "summary_failed", "details": str(e)}
