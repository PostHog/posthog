"""Base class for all Replay Vision scanner types."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from products.replay_vision.backend.temporal.scanners.prompt_env import render_prompt

# `(t 123)` / `(t 123, t 456)` citation markers the model leaks into the plain-text signal description despite the
# prompt forbidding them. Matched leniently (whitespace, comma-joined times) so the strip catches every variant.
_SIGNAL_TIMESTAMP_MARKER_RE = re.compile(r"\s*\(\s*t\s*\d+(?:\s*,\s*t?\s*\d+)*\s*\)")


# Sited here rather than `temporal/types.py`: `types.py` imports from this module, so siting Segment in types.py would close the cycle.
class TextSegment(BaseModel, frozen=True):
    kind: Literal["text"] = "text"
    value: str


class ChipSegment(BaseModel, frozen=True):
    kind: Literal["chip"] = "chip"
    # Recording-relative position (ms) the player seeks to; from a `(t <sec>)` citation.
    timestamp_ms: int = Field(ge=0)


Segment = Annotated[TextSegment | ChipSegment, Field(discriminator="kind")]


# The side-mission calibration floor: templated into the prompt and enforced at emission.
MIN_SIGNAL_CONFIDENCE = 0.4

# Stable step names the producer (`mission_steps`) and consumers (`assemble`) key on.
STEP_CORE = "core"
STEP_SIGNALS = "signals"


class SignalFinding(BaseModel, frozen=True):
    """Optional side-mission finding: a bug, crash, or design flaw the recording itself reveals. See the side-mission prompt block."""

    problem_type: Literal["bug", "crash", "design_flaw", "ux_friction"] = Field(
        description="The kind of issue: `bug`, `crash`, `design_flaw`, or `ux_friction`."
    )
    start_time: int = Field(
        ge=0,
        description=(
            "When the issue starts in the recording, in seconds — copy the whole-number `REC_T` value shown in the "
            "video footer at that moment (`REC_T` is seconds since the recording started)."
        ),
    )
    end_time: int = Field(
        ge=0, description="When the issue ends in the recording, in seconds — the `REC_T` value from the footer."
    )
    url: str = Field(
        description="The page the issue happened on — copy the `URL:` value shown in the video footer at that moment."
    )
    description: str = Field(
        description=(
            "Actionable prose a reader with no session context can act on. Lead with what you saw on screen that "
            "reveals the issue — the visual detail the events don't capture (e.g. a spinner overlapping a button, an "
            "error toast that flashed off-screen, a layout shift, visible hesitation). Then say what happened, where "
            "in the product, and the user impact. Quote exact on-screen labels and button text when visible. Plain "
            "prose with no timestamp references — no `(t …)` markers, no `REC_T`, no 'at N seconds', no event IDs; "
            "the timing lives in `start_time`/`end_time`."
        )
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Calibrated confidence that this is a real, actionable issue. Apply the calibration rules.",
    )

    @field_validator("description", mode="after")
    @classmethod
    def _strip_timestamp_markers(cls, value: str) -> str:
        # The model leaks `(t 123)` markers into this embedded, free-text-searchable field despite the prompt — strip
        # them so the timing stays only in start_time/end_time and the prose reads cleanly. Collapse any double space
        # the removal (or the model) leaves so the prose stays clean.
        return re.sub(r"\s{2,}", " ", _SIGNAL_TIMESTAMP_MARKER_RE.sub("", value)).strip()


class SignalsResponse(BaseModel, frozen=True):
    """The signals side-mission turn's structured output — one entry per video-only issue, usually empty."""

    signals: list[SignalFinding] = Field(
        default_factory=list,
        description=(
            "Findings from the side mission — one entry per distinct bug, crash, or design flaw the recording "
            "reveals. Usually empty: most sessions show nothing video-only. List each issue separately."
        ),
    )


@dataclass(frozen=True)
class MissionStep:
    """One structured turn in a scanner's conversation: an instruction, the schema the model must answer with,
    and how its result feeds the final output.

    `required` steps abort the scan when they can't be satisfied; non-required steps (facets, signals) are
    best-effort and simply contribute nothing on failure. `validate` runs an extra semantic check on the parsed
    response and, when it returns an error string, triggers the same re-prompt path as a schema failure.
    """

    name: str
    instruction: str
    response_model: type[BaseModel]
    required: bool = True
    validate: Callable[[BaseModel], str | None] | None = field(default=None)


_CONFIDENCE_DESCRIPTION = (
    "Calibrated confidence, 0.0 to 1.0 with one decimal. Apply the calibration rules from the system prompt."
)


def confidence_field() -> Any:
    """`confidence` field for LLM-response schemas. Declared explicitly (and last) so the model writes its
    reasoning/answer before committing a confidence — reason-before-answer, not confidence-first."""
    return Field(ge=0, le=1, description=_CONFIDENCE_DESCRIPTION)


class BaseScannerOutput(BaseModel, frozen=True):
    """Final output shape emitted as `$recording_observed` event properties (flattened with `scanner_output_*` keys)."""

    confidence: float = confidence_field()

    def to_event_properties(self) -> dict[str, Any]:
        """Flatten with `scanner_output_*` keys for the event; `scanner_type` is excluded (already a top-level property via the snapshot)."""
        return {f"scanner_output_{k}": v for k, v in self.model_dump(mode="json", exclude={"scanner_type"}).items()}


class BaseScanner(BaseModel, frozen=True):
    """Common shape for every concrete scanner; subclasses bind `scanner_type`, `core_step_template`, and `llm_response_schema`.

    A scan is a multi-turn conversation over the cached video: a shared `preamble` (sent/cached once) followed by
    the ordered `mission_steps` — one structured turn each. Most scanners have a single `core` step; the summarizer
    splits into `summary` then `facets`; the signals side mission, when enabled, is always the final turn.
    """

    prompt: str
    emits_signals: bool = False

    # Shared opening turn (footer, events tool, calibration, session metadata), rendered once and cached with the video.
    preamble_template: ClassVar[str] = "preamble.jinja"
    # Per-scanner-type instruction for the `core` step. Subclasses set this (the summarizer overrides `core_steps`).
    core_step_template: ClassVar[str] = ""
    # Names of free-text output fields that may contain `(t <sec>)` citations.
    citation_fields: ClassVar[tuple[str, ...]] = ()
    # Persisted output class — subclasses override to stamp their `scanner_type` discriminator.
    output_cls: ClassVar[type["BaseScannerOutput"] | None] = None

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        """Pydantic class the `core` step emits, passed to Gemini's `response_json_schema`."""
        raise NotImplementedError

    def prompt_context(self) -> dict[str, Any]:
        """Scanner-type-specific template variables. Subclasses override to inject their per-instance config."""
        return {}

    def preamble(
        self,
        *,
        team_name: str,
        session_metadata: dict[str, Any] | None = None,
        moment: dict[str, Any] | None = None,
    ) -> str:
        """The conversation's shared opening: framing, footer, events tool, calibration, and session metadata."""
        return render_prompt(
            self.preamble_template,
            team_name=team_name,
            session_metadata=session_metadata or {},
            moment=moment,
        )

    def core_steps(self) -> list[MissionStep]:
        """The task turn(s) that produce this scanner's primary output. Default: one `core` step."""
        if not self.core_step_template:
            raise NotImplementedError(f"{type(self).__name__} must set `core_step_template`")
        instruction = render_prompt(self.core_step_template, user_prompt=self.prompt, **self.prompt_context())
        return [
            MissionStep(
                name=STEP_CORE,
                instruction=instruction,
                response_model=self.llm_response_schema,
                validate=self._validate_core,
            )
        ]

    def mission_steps(self) -> list[MissionStep]:
        """The full ordered turn list: the core task, then the signals side mission when enabled."""
        steps = self.core_steps()
        if self.emits_signals:
            steps.append(self._signals_step())
        return steps

    def _signals_step(self) -> MissionStep:
        instruction = render_prompt("signals_step.jinja", min_signal_confidence=MIN_SIGNAL_CONFIDENCE)
        # Best-effort: a side-mission failure must not sink the whole scan.
        return MissionStep(name=STEP_SIGNALS, instruction=instruction, response_model=SignalsResponse, required=False)

    def _validate_core(self, parsed: BaseModel) -> str | None:
        """Run the scanner's semantic checks against a finalized version of the core response."""
        return self.validate_semantics(self.finalize(parsed))

    def assemble(self, step_outputs: dict[str, BaseModel]) -> tuple["BaseScannerOutput", list[SignalFinding]]:
        """Merge the per-turn outputs into the final persisted output and the side-mission findings."""
        finalized = self.finalize(step_outputs[STEP_CORE])
        return finalized, self._extract_signals(step_outputs)

    @staticmethod
    def _extract_signals(step_outputs: dict[str, BaseModel]) -> list[SignalFinding]:
        """Pull the side-mission findings out of the (optional) signals turn."""
        return list(getattr(step_outputs.get(STEP_SIGNALS), "signals", []))

    def finalize(self, llm_response: BaseModel) -> "BaseScannerOutput":
        """Stamp `output_cls` (with its `scanner_type` discriminator) onto the validated LLM response."""
        if self.output_cls is None:
            raise NotImplementedError(f"{type(self).__name__} must set `output_cls`")
        return self.output_cls(**llm_response.model_dump())

    def validate_semantics(self, output: "BaseScannerOutput") -> str | None:
        """Scanner-specific checks beyond Pydantic schema validation; return `None` when valid, otherwise an error string suitable to feed back into a re-prompt."""
        return None
