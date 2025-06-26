from ee.hogai.tool import MaxTool
from pydantic import BaseModel, Field


# Define your tool's arguments schema
class ExperimentResultsSummaryArgs(BaseModel):
    experiment_id: str = Field(description="The ID of the experiment to summarize")


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

    def _run(self, experiment_id: str) -> str:
        # tool implementation goes here :D
        return f"Summarized results for experiment {experiment_id}"
