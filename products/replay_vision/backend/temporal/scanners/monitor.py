"""Monitor scanner: detects whether a specific condition occurred during the session."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import BaseScanner, BaseScannerOutput, Segment


class MonitorLlmResponse(BaseScannerOutput, frozen=True):
    """LLM-facing schema: the model decides these fields; `scanner_type` is stamped by the workflow in `finalize`."""

    verdict: bool = Field(description="Did the condition described in the scanner intent occur during the session?")
    reasoning: str = Field(
        description="One paragraph grounding the verdict in concrete moments from the video and events."
    )


class MonitorOutput(MonitorLlmResponse, frozen=True):
    """Persisted output: `reasoning` is plain prose; `reasoning_segments` is the same prose pre-split into render-ready text + chip segments."""

    scanner_type: Literal[ScannerType.MONITOR] = ScannerType.MONITOR
    reasoning_segments: list[Segment] = Field(default_factory=list)


class MonitorScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.MONITOR] = ScannerType.MONITOR
    prompt_template: ClassVar[str] = "monitor.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("reasoning",)
    output_cls: ClassVar[type[BaseScannerOutput]] = MonitorOutput

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return MonitorLlmResponse
