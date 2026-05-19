"""Monitor lens: detects whether a specific condition occurred during the session."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import BaseLens, BaseLensOutput


class MonitorOutput(BaseLensOutput, frozen=True):
    lens_type: Literal[LensType.MONITOR] = LensType.MONITOR
    verdict: bool = Field(description="Did the condition described in the lens intent occur during the session?")
    reasoning: str = Field(
        description="One paragraph grounding the verdict in concrete moments from the video and events."
    )


class MonitorLens(BaseLens, frozen=True):
    lens_type: Literal[LensType.MONITOR] = LensType.MONITOR
    prompt_template: ClassVar[str] = "monitor.jinja"

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return MonitorOutput
