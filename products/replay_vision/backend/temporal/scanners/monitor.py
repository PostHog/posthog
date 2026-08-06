"""Monitor scanner: detects whether a specific condition occurred during the session."""

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import (
    BaseScanner,
    BaseScannerOutput,
    Segment,
    confidence_field,
)

MonitorVerdict = Literal["yes", "no", "inconclusive"]

_VERDICT_DESCRIPTION = (
    "Did the condition described in the scanner intent occur during the session? "
    "`yes` if it did, `no` if it didn't, `inconclusive` only when the session genuinely does not provide enough signal to decide."
)
_REASONING_DESCRIPTION = "One paragraph grounding the verdict in concrete moments from the video and events."


class MonitorLlmResponse(BaseModel, frozen=True):
    """LLM-facing schema. Field order is load-bearing: `reasoning` first so the model works through the evidence
    before committing a `verdict`; `confidence` last. `scanner_type` is stamped by the workflow in `finalize`."""

    reasoning: str = Field(description=_REASONING_DESCRIPTION)
    verdict: MonitorVerdict = Field(description=_VERDICT_DESCRIPTION)
    confidence: float = confidence_field()


class MonitorOutput(BaseScannerOutput, frozen=True):
    """Persisted output: `reasoning` is plain prose; `reasoning_segments` is the same prose pre-split into render-ready text + chip segments."""

    scanner_type: Literal[ScannerType.MONITOR] = ScannerType.MONITOR
    verdict: MonitorVerdict = Field(description=_VERDICT_DESCRIPTION)
    reasoning: str = Field(description=_REASONING_DESCRIPTION)
    reasoning_segments: list[Segment] = Field(default_factory=list)


class MonitorScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.MONITOR] = ScannerType.MONITOR
    core_step_template: ClassVar[str] = "monitor_step.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("reasoning",)
    output_cls: ClassVar[type[BaseScannerOutput]] = MonitorOutput
    allow_inconclusive: bool = False

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return MonitorLlmResponse

    def prompt_context(self) -> dict[str, Any]:
        return {"allow_inconclusive": self.allow_inconclusive}

    def validate_semantics(self, output: BaseScannerOutput) -> str | None:
        if isinstance(output, MonitorOutput) and output.verdict == "inconclusive" and not self.allow_inconclusive:
            return (
                "Verdict is `inconclusive` but this scanner does not allow inconclusive verdicts; choose `yes` or `no`."
            )
        return None
