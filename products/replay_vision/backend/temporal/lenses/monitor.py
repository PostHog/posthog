"""Monitor lens: detects whether a specific condition occurred during the session."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import BaseLens, BaseLensOutput


class MonitorLlmResponse(BaseLensOutput, frozen=True):
    """LLM-facing schema: the model decides these fields; `lens_type` is stamped by the workflow in `finalize`."""

    verdict: bool = Field(description="Did the condition described in the lens intent occur during the session?")
    reasoning: str = Field(
        description="One paragraph grounding the verdict in concrete moments from the video and events."
    )


class MonitorOutput(MonitorLlmResponse, frozen=True):
    """Persisted output: adds the discriminator for the `AnyLensOutput` union."""

    lens_type: Literal[LensType.MONITOR] = LensType.MONITOR


class MonitorLens(BaseLens, frozen=True):
    lens_type: Literal[LensType.MONITOR] = LensType.MONITOR
    prompt: str
    prompt_template: ClassVar[str] = "monitor.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("reasoning",)
    output_cls: ClassVar[type[BaseLensOutput]] = MonitorOutput

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return MonitorLlmResponse
