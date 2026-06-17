"""Base class for all Replay Vision scanner types."""

from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field, create_model

from products.replay_vision.backend.temporal.scanners.prompt_env import render_prompt

if TYPE_CHECKING:
    from products.replay_vision.backend.temporal.types import EventTable


# Sited here rather than `temporal/types.py`: `types.py` imports from this module, so siting Segment in types.py would close the cycle.
class TextSegment(BaseModel, frozen=True):
    kind: Literal["text"] = "text"
    value: str


class ChipSegment(BaseModel, frozen=True):
    kind: Literal["chip"] = "chip"
    uuid: str
    timestamp_ms: int = Field(ge=0)


Segment = Annotated[TextSegment | ChipSegment, Field(discriminator="kind")]


# The side-mission calibration floor: templated into the prompt and enforced at emission.
MIN_SIGNAL_CONFIDENCE = 0.4


class SignalFinding(BaseModel, frozen=True):
    """Optional side-mission finding: a product issue worth surfacing as a PostHog Signal."""

    description: str = Field(
        description=(
            "Self-contained prose a reader with no session context can act on: what happened, where in the "
            "product, and the user impact — concrete, per the side-mission instructions. "
            "Plain prose, no `(event_uuid …)` citation markers."
        )
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Calibrated confidence that this is a real, actionable issue. Apply the calibration rules.",
    )


def _with_signal_field(base: type[BaseModel]) -> type[BaseModel]:
    """Extend an LLM response model with the optional side-mission `signal` field."""
    return create_model(
        f"{base.__name__}WithSignal",
        __base__=base,
        signal=(
            SignalFinding | None,
            Field(
                default=None,
                description=(
                    "Only when the session surfaced a clear, actionable product issue per the side mission; "
                    "null otherwise. Most sessions warrant null."
                ),
            ),
        ),
    )


class BaseScannerOutput(BaseModel, frozen=True):
    """Final output shape emitted as `$recording_observed` event properties (flattened with `scanner_output_*` keys)."""

    confidence: float = Field(
        ge=0,
        le=1,
        description="Calibrated confidence, 0.0 to 1.0 with one decimal. Apply the calibration rules from the system prompt.",
    )

    def to_event_properties(self) -> dict[str, Any]:
        """Flatten with `scanner_output_*` keys for the event; `scanner_type` is excluded (already a top-level property via the snapshot)."""
        return {f"scanner_output_{k}": v for k, v in self.model_dump(mode="json", exclude={"scanner_type"}).items()}


class BaseScanner(BaseModel, frozen=True):
    """Common shape for every concrete scanner; subclasses bind `scanner_type`, `prompt_template`, and `llm_response_schema`."""

    prompt: str
    emits_signals: bool = False

    # Per-scanner-type Jinja2 template under `prompts/`. Subclasses set this.
    prompt_template: ClassVar[str] = ""
    # Names of free-text fields on the LLM response that may contain `(event_uuid <uuid>)` citations.
    citation_fields: ClassVar[tuple[str, ...]] = ()
    # Persisted output class — subclasses override to stamp their `scanner_type` discriminator.
    output_cls: ClassVar[type["BaseScannerOutput"] | None] = None

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        """Pydantic class the LLM emits, passed to Gemini's `response_json_schema`."""
        raise NotImplementedError

    def llm_response_model(self) -> type[BaseModel]:
        """The model the LLM must emit: `llm_response_schema`, gaining the side-mission `signal` field when `emits_signals`."""
        return _with_signal_field(self.llm_response_schema) if self.emits_signals else self.llm_response_schema

    def prompt_context(self) -> dict[str, Any]:
        """Scanner-type-specific template variables. Subclasses override to inject their per-instance config."""
        return {}

    def finalize(self, llm_response: BaseModel) -> BaseScannerOutput:
        """Stamp `output_cls` (with its `scanner_type` discriminator) onto the validated LLM response."""
        if self.output_cls is None:
            raise NotImplementedError(f"{type(self).__name__} must set `output_cls`")
        return self.output_cls(**llm_response.model_dump())

    def validate_semantics(self, output: BaseScannerOutput) -> str | None:
        """Scanner-specific checks beyond Pydantic schema validation; return `None` when valid, otherwise an error string suitable to feed back into a re-prompt."""
        return None

    def build_prompt(
        self,
        *,
        team_name: str,
        events: "EventTable",
        url_mapping: dict[str, str] | None = None,
        window_mapping: dict[str, str] | None = None,
        session_metadata: dict[str, Any] | None = None,
    ) -> str:
        if not self.prompt_template:
            raise NotImplementedError(f"{type(self).__name__} must set `prompt_template`")
        return render_prompt(
            self.prompt_template,
            team_name=team_name,
            user_prompt=self.prompt,
            events=events,
            url_mapping=url_mapping or {},
            window_mapping=window_mapping or {},
            session_metadata=session_metadata or {},
            emits_signals=self.emits_signals,
            min_signal_confidence=MIN_SIGNAL_CONFIDENCE,
            **self.prompt_context(),
        )
