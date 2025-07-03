from ee.hogai.tool import MaxTool
from pydantic import BaseModel, Field
from typing import Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage


# Define your tool's arguments schema
class ExperimentResultsSummaryArgs(BaseModel):
    experiment_id: str = Field(description="The ID of the experiment to summarize")
    results_data: str = Field(description="The formatted experiment results data to analyze")


class ExperimentResultsSummaryTool(MaxTool):
    name: str = "experiment_results_summary"
    description: str = "Summarize the results of an experiment"
    args_schema: type[BaseModel] = ExperimentResultsSummaryArgs
    thinking_message: str = "Analyzing experiment"
    root_system_prompt_template: str = """
Instructions:
- If there is a significant winner, mention the variant, win probability, lift, and what this means for the experiment.
- If not, mention how long the experiment has been running, how much time is left, and whether the results are trending toward significance or if more data is needed.
- Comment on the relative performance of the variants, even if not significant, and mention the credible intervals and p-value if relevant.
- Do NOT speculate or invent results that are not in the data.
- Write as a product analyst would, not as an AI. Use clear, professional language.
Examples:
- "After 14 days, the test variant is leading with a 95% probability of being the best, showing a 12% lift over control. This result is statistically significant and suggests the test variant is outperforming the baseline."
- "The experiment has been running for 8 days with no significant difference between variants. More data is needed to draw a conclusion."
- "Control and test variants are performing similarly so far, with the test variant showing a slight, but not significant, improvement. Credible intervals overlap and the p-value is above the significance threshold."
"""

    def _run_impl(self, experiment_id: str, results_data: str) -> tuple[str, Any]:
        try:
            system_content = self.root_system_prompt_template

            user_content = f"""
Please analyze the following experiment results and provide a comprehensive summary:

Experiment ID: {experiment_id}

{results_data}

Focus on key metrics, statistical significance, and actionable insights for the product team.
"""

            messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

            result = self._model.invoke(messages)
            content = result.content

            return content, None  # Return tuple of (content, artifact)
        except Exception as e:
            return f"Error generating experiment summary: {str(e)}", None

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0.3, streaming=True)
