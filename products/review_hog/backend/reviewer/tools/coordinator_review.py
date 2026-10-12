"""The coordinator variant of a Standard turn: one sandbox session runs every review unit as a sub-agent.

Each unit is the main review or one lens part, with the prompt its own session would get. The prompts
reach the sandbox as session files, because the coordinator cannot copy that much text into its
sub-agent messages in reasonable time.
"""

from typing import Literal

from pydantic import BaseModel, Field

from posthog.dataclasses import frozen

from products.review_hog.backend.reviewer.models.single_agent_review import SingleAgentFinding
from products.review_hog.backend.reviewer.tools.single_agent_review import SINGLE_AGENT_PROMPT_PATH, load_prompt_file

COORDINATOR_PROMPT_FILE = SINGLE_AGENT_PROMPT_PATH / "coordinator.md"
TASK_MESSAGE = (
    "Read the file `<path of {file_name}>` in full ({lines} lines, {chars} characters; read it in parts when one"
    " read cannot hold all of it). It is your complete task. Follow it exactly and reply with only the JSON object"
    " it asks for."
)


@frozen
class CoordinatorUnit:
    """One sub-agent, keyed like the separate session that would run the same review unit."""

    task_name: str
    pass_number: int
    chunk_id: int
    source: str
    prompt: str

    @property
    def file_name(self) -> str:
        return f"{self.task_name}.prompt.md"

    def task_line(self) -> str:
        message = TASK_MESSAGE.format(
            file_name=self.file_name, lines=self.prompt.count("\n") + 1, chars=len(self.prompt)
        )
        return f'   - task name `{self.task_name}`, message: "{message}"'


class CoordinatorResult(BaseModel):
    task: str
    status: Literal["ok", "failed"]
    findings: list[SingleAgentFinding] = Field(default_factory=list)


class CoordinatorReview(BaseModel):
    """The coordinator's answer: one result per sub-agent, with its findings copied unchanged."""

    results: list[CoordinatorResult]

    def findings_by_task(self) -> dict[str, list[SingleAgentFinding]]:
        """The findings of every sub-agent that finished, by task name."""
        return {result.task: result.findings for result in self.results if result.status == "ok"}


def coordinator_prompt(units: list[CoordinatorUnit], *, model: str, reasoning_effort: str) -> str:
    return (
        load_prompt_file(COORDINATOR_PROMPT_FILE)
        .replace("<<MODEL>>", model)
        .replace("<<EFFORT>>", reasoning_effort)
        .replace("<<TASKS>>", "\n".join(unit.task_line() for unit in units))
    )
