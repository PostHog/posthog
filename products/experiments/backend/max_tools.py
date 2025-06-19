from ee.hogai.tool import MaxTool
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

# Define your tool's arguments schema
class ExperimentResultsSummaryArgs(BaseModel):
    experiment_id: str = Field(description="The ID of the experiment to summarize")

class ExperimentResultsSummaryTool(MaxTool):
    name: str = "experiment_results_summary"
    description: str = "Summarize the results of an experiment"
    args_schema: Type[BaseModel] = ExperimentResultsSummaryArgs

    def _run(self, experiment_id: str) -> str:
        # tool implementation goes here :D
        return f"Summarized results for experiment {experiment_id}"
