"""Generate a `ChartSpec` from a result-set summary using an LLM with structured output.

This is the "AI-as-presentation-layer" half of the gen-UI charts idea: the model never invents data,
it only decides how to present the rows it is handed. Mirrors the structured-output mechanics of
`ee/hogai/chat_agent/schema_generator/nodes.py` without coupling to the assistant graph, so it can be
unit-tested in isolation.
"""

from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import BaseModel

from posthog.models import Team, User

from ee.hogai.chat_agent.schema_generator.parsers import parse_pydantic_structured_output
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.utils.helpers import dereference_schema

from .prompts import CHART_SPEC_HUMAN_PROMPT, CHART_SPEC_SYSTEM_PROMPT
from .schema import ChartSpec


class ChartSpecGeneratorOutput(BaseModel):
    chart: ChartSpec


def generate_chart_spec_schema() -> dict:
    """Build the function-call schema handed to the model — a fully dereferenced ChartSpec under `chart`."""
    return {
        "name": "output_chart_spec",
        "description": "Outputs a chart specification describing how to present the given data.",
        "parameters": {
            "type": "object",
            "properties": {"chart": dereference_schema(ChartSpec.model_json_schema())},
            "additionalProperties": False,
            "required": ["chart"],
        },
    }


CHART_SPEC_SCHEMA = generate_chart_spec_schema()


class ChartSpecGenerator:
    def __init__(self, team: Team, user: User) -> None:
        self._team = team
        self._user = user

    @property
    def _model(self) -> Runnable:
        return MaxChatOpenAI(
            model="gpt-5.2",
            temperature=0.3,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            max_tokens=8192,
            billable=True,
            output_version="responses/v1",
            use_responses_api=True,
            reasoning={"effort": "none"},
            model_kwargs={"prompt_cache_key": f"team_{self._team.id}"},
        ).with_structured_output(
            CHART_SPEC_SCHEMA,
            method="json_schema",
            include_raw=False,
        )

    def _parse_output(self, output: dict) -> ChartSpec:
        return parse_pydantic_structured_output(ChartSpecGeneratorOutput)(output).chart

    async def agenerate(
        self, data_summary: str, instruction: str, config: Optional[RunnableConfig] = None
    ) -> ChartSpec:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", CHART_SPEC_SYSTEM_PROMPT),
                ("human", CHART_SPEC_HUMAN_PROMPT),
            ],
            template_format="mustache",
        )
        chain = prompt | self._model | self._parse_output
        return await chain.ainvoke({"data_summary": data_summary, "instruction": instruction}, config)
