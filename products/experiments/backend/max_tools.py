"""
MaxTool for AI-powered experiment summary.
"""

from typing import Any

from pydantic import BaseModel, Field

from posthog.exceptions_capture import capture_exception

from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .prompts import EXPERIMENT_SUMMARY_SYSTEM_PROMPT


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

    async def _analyze_experiment(self, experiment_data: dict[str, Any]) -> ExperimentSummaryOutput:
        """
        Analyze experiment data using LLM to generate summary and insights.
        """
        try:
            # Format the data for LLM analysis
            formatted_data = self._format_experiment_for_llm(experiment_data)

            # Initialize LLM with structured output
            llm = MaxChatOpenAI(
                user=self._user,
                team=self._team,
                model="gpt-4.1",
                temperature=0.1,  # Low temperature for consistent analysis
            ).with_structured_output(ExperimentSummaryOutput)

            # Create the analysis prompt
            formatted_prompt = EXPERIMENT_SUMMARY_SYSTEM_PROMPT.replace("{{{experiment_data}}}", formatted_data)

            # Generate analysis with structured output
            analysis_result = await llm.ainvoke([{"role": "system", "content": formatted_prompt}])

            if isinstance(analysis_result, dict):
                return ExperimentSummaryOutput(**analysis_result)
            return analysis_result

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})

            # Return error state
            return ExperimentSummaryOutput(key_metrics=[f"Analysis failed: {str(e)}"])

    def _format_experiment_for_llm(self, experiment_data: dict[str, Any]) -> str:
        """
        Format experiment data into a structured string for LLM analysis.
        """
        lines = []

        # Basic experiment info
        lines.append(f"Experiment: {experiment_data.get('name', 'Unknown')}")

        if experiment_data.get("hypothesis"):
            lines.append(f"Hypothesis: {experiment_data.get('hypothesis')}")

        if experiment_data.get("description"):
            lines.append(f"Description: {experiment_data.get('description')}")

        # Variants info
        variants = experiment_data.get("variants", [])
        if variants:
            lines.append(f"\nVariants: {', '.join(v.get('key', '') for v in variants)}")

        # Results data
        results = experiment_data.get("results", [])
        if results:
            lines.append("\nResults:")
            for result in results[:3]:  # Limit to first 3 metrics
                metric_name = result.get("metric_name", "Unknown metric")
                lines.append(f"\nMetric: {metric_name}")

                if result.get("variants"):
                    for variant in result["variants"]:
                        key = variant.get("key", "unknown")
                        count = variant.get("count", 0)
                        exposure = variant.get("exposure", 0)
                        conversion_rate = variant.get("conversion_rate")

                        lines.append(f"  {key}:")
                        if conversion_rate is not None:
                            lines.append(f"    Conversion: {conversion_rate:.2%}")
                        else:
                            lines.append(f"    Count: {count}, Exposure: {exposure}")

                # Statistical significance
                if result.get("significant"):
                    lines.append(f"  Significant: Yes (p={result.get('p_value', 'N/A')})")
                else:
                    lines.append(f"  Significant: No")

                if result.get("winner"):
                    lines.append(f"  Winner: {result['winner']}")

        # Conclusion if set
        if experiment_data.get("conclusion"):
            lines.append(f"\nConclusion: {experiment_data['conclusion']}")

        if experiment_data.get("conclusion_comment"):
            lines.append(f"Comment: {experiment_data['conclusion_comment']}")

        return "\n".join(lines)

    def _format_summary_for_user(self, summary: ExperimentSummaryOutput, experiment_name: str) -> str:
        """Format the structured summary into a user-friendly message."""
        lines = []

        # Header
        lines.append(f"✅ **Experiment Summary: '{experiment_name}'**")

        # Key metrics
        if summary.key_metrics:
            lines.append("\n**📊 Key Metrics:**")
            for metric in summary.key_metrics:
                lines.append(f"• {metric}")

        return "\n".join(lines)

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        """
        Generate experiment summary from provided context.
        """
        try:
            # Get experiment data from context
            experiment_id = self.context.get("experiment_id")
            experiment_name = self.context.get("experiment_name", "Unknown Experiment")
            experiment_data = {
                "name": experiment_name,
                "hypothesis": self.context.get("hypothesis"),
                "description": self.context.get("description"),
                "variants": self.context.get("variants", []),
                "results": self.context.get("results", []),
                "conclusion": self.context.get("conclusion"),
                "conclusion_comment": self.context.get("conclusion_comment"),
            }

            if not experiment_id:
                return "❌ No experiment data provided", {
                    "error": "no_experiment_data",
                    "details": "Experiment information not found in context",
                }

            # Analyze the experiment
            summary_result = await self._analyze_experiment(experiment_data)

            # Format the summary as a user-friendly message
            user_message = self._format_summary_for_user(summary_result, experiment_name)

            return user_message, {
                "experiment_id": experiment_id,
                "experiment_name": experiment_name,
                "summary": summary_result.model_dump(),
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Failed to summarize experiment: {str(e)}", {"error": "summary_failed", "details": str(e)}
