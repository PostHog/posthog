"""
MaxTool for AI-powered experiment summary.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.schema import ExperimentMaxBayesianContext, ExperimentMaxFrequentistContext

from posthog.exceptions_capture import capture_exception

from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .prompts import EXPERIMENT_SUMMARY_BAYESIAN_PROMPT, EXPERIMENT_SUMMARY_FREQUENTIST_PROMPT


class ExperimentSummaryArgs(BaseModel):
    """
    Analyze experiment results to generate an executive summary with key insights and recommendations.
    All experiment data and results are automatically provided from context.
    """


class ExperimentSummaryOutput(BaseModel):
    """Structured output for experiment summary"""

    key_metrics: list[str] = Field(description="Summary of key metric performance", max_length=3)


class ExperimentSummaryTool(MaxTool):
    name: str = "experiment_results_summary"
    description: str = "Generate an executive summary of experiment results with key insights and recommendations"
    thinking_message: str = "Analyzing your experiment results"
    context_prompt_template: str = (
        "You have access to an experiment summary tool that can analyze experiment results and generate executive summaries. "
        "When users ask about summarizing experiments, understanding experiment outcomes, or getting recommendations from experiment results, "
        "use the experiment_results_summary tool. Experiment data includes: {experiment_name}, {hypothesis}, {results}"
    )

    args_schema: type[BaseModel] = ExperimentSummaryArgs

    def _extract_experiment_results(self) -> tuple[dict[str, Any], str]:
        if not hasattr(self, "context") or not self.context:
            # Return empty data - will be handled by caller
            return {}, "bayesian"

        experiment_data = {
            "name": self.context.get("experiment_name", "Unknown Experiment"),
            "hypothesis": self.context.get("hypothesis"),
            "description": self.context.get("description"),
            "variants": self.context.get("variants", []),
            "conclusion": self.context.get("conclusion"),
            "conclusion_comment": self.context.get("conclusion_comment"),
        }

        statistical_method = self.context.get("statistical_method", "bayesian")
        raw_results = self.context.get("results", [])
        validated_results = []

        for result in raw_results:
            if not result:
                continue

            metric_result = {"metric_name": result.get("metric_name", "Unknown metric"), "variants": []}

            raw_variants = result.get("variants", [])
            for variant in raw_variants:
                try:
                    if statistical_method == "bayesian":
                        validated_variant = ExperimentMaxBayesianContext.model_validate(variant)
                        metric_result["variants"].append(validated_variant.model_dump())
                    else:
                        validated_variant_freq = ExperimentMaxFrequentistContext.model_validate(variant)
                        metric_result["variants"].append(validated_variant_freq.model_dump())
                except Exception as e:
                    capture_exception(
                        e,
                        {
                            "team_id": self._team.id,
                            "user_id": self._user.id,
                            "validation_error": str(e),
                            "variant_data": variant,
                            "statistical_method": statistical_method,
                        },
                    )
                    continue

            if metric_result["variants"]:
                validated_results.append(metric_result)

        experiment_data["results"] = validated_results
        return experiment_data, statistical_method

    async def _analyze_experiment(
        self, experiment_data: dict[str, Any], statistical_method: str
    ) -> ExperimentSummaryOutput:
        try:
            method: Literal["bayesian", "frequentist"] = (
                statistical_method if statistical_method in ["bayesian", "frequentist"] else "bayesian"
            )

            if method == "frequentist":
                prompt_template = EXPERIMENT_SUMMARY_FREQUENTIST_PROMPT
            else:
                prompt_template = EXPERIMENT_SUMMARY_BAYESIAN_PROMPT

            formatted_data = self._format_experiment_for_llm(experiment_data, method)

            llm = MaxChatOpenAI(
                user=self._user,
                team=self._team,
                model="gpt-4.1",
                temperature=0.1,  # Low temperature for consistent analysis
            ).with_structured_output(ExperimentSummaryOutput)

            formatted_prompt = prompt_template.replace("{{{experiment_data}}}", formatted_data)
            analysis_result = await llm.ainvoke([{"role": "system", "content": formatted_prompt}])

            if isinstance(analysis_result, dict):
                return ExperimentSummaryOutput(**analysis_result)
            return analysis_result

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})

            return ExperimentSummaryOutput(key_metrics=[f"Analysis failed: {str(e)}"])

    def _format_experiment_for_llm(
        self, experiment_data: dict[str, Any], method: Literal["bayesian", "frequentist"]
    ) -> str:
        lines = []

        lines.append(f"Statistical method: {method.title()}")
        lines.append(f"Experiment: {experiment_data.get('name', 'Unknown')}")

        if experiment_data.get("hypothesis"):
            lines.append(f"Hypothesis: {experiment_data.get('hypothesis')}")

        if experiment_data.get("description"):
            lines.append(f"Description: {experiment_data.get('description')}")

        variants = experiment_data.get("variants", [])
        if variants:
            lines.append(f"\nVariants: {', '.join(v.get('key', '') for v in variants)}")

        results = experiment_data.get("results", [])
        if results:
            lines.append("\nResults:")
            for result in results[:3]:  # Limit to first 3 metrics
                metric_name = result.get("metric_name", "Unknown metric")
                lines.append(f"\nMetric: {metric_name}")

                if result.get("variants"):
                    for variant in result["variants"]:
                        key = variant.get("key", "unknown")
                        lines.append(f"  {key}:")

                        if method == "bayesian":
                            chance_to_win = variant.get("chance_to_win")
                            credible_interval = variant.get("credible_interval", [])
                            significant = variant.get("significant", False)

                            if chance_to_win is not None:
                                lines.append(f"    Chance to win: {chance_to_win:.1%}")

                            if credible_interval:
                                ci_low, ci_high = credible_interval[:2]
                                lines.append(f"    95% credible interval: {ci_low:.1%} - {ci_high:.1%}")

                            lines.append(f"    Significant: {'Yes' if significant else 'No'}")

                        else:
                            p_value = variant.get("p_value")
                            confidence_interval = variant.get("confidence_interval", [])
                            significant = variant.get("significant", False)

                            if p_value is not None:
                                lines.append(f"    P-value: {p_value:.4f}")

                            if confidence_interval:
                                ci_low, ci_high = confidence_interval[:2]
                                lines.append(f"    95% confidence interval: {ci_low:.1%} - {ci_high:.1%}")

                            lines.append(f"    Significant: {'Yes' if significant else 'No'}")

        if experiment_data.get("conclusion"):
            lines.append(f"\nConclusion: {experiment_data['conclusion']}")

        if experiment_data.get("conclusion_comment"):
            lines.append(f"Comment: {experiment_data['conclusion_comment']}")

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
            experiment_id = self.context.get("experiment_id")
            if not experiment_id:
                return "❌ No experiment data provided", {
                    "error": "no_experiment_data",
                    "details": "Experiment information not found in context",
                }

            experiment_data, statistical_method = self._extract_experiment_results()

            if not experiment_data.get("results"):
                return "❌ No valid experiment results to analyze", {
                    "error": "no_valid_results",
                    "details": "No properly formatted experiment results found in context",
                }

            summary_result = await self._analyze_experiment(experiment_data, statistical_method)

            experiment_name = experiment_data.get("name", "Unknown Experiment")
            user_message = self._format_summary_for_user(summary_result, experiment_name)

            return user_message, {
                "experiment_id": experiment_id,
                "experiment_name": experiment_name,
                "summary": summary_result.model_dump(),
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Failed to summarize experiment: {str(e)}", {"error": "summary_failed", "details": str(e)}
