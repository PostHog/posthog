"""Base class for all Replay Vision lens types."""

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from products.replay_vision.backend.temporal.types import EventTable

_PROMPT_TEMPLATE = """\
You are applying a configured lens to a recorded user session of {team_name}.

The video is the rasterized recording: 8x playback speed with inactive periods skipped. The events table below lists the analytics events captured during the session, in chronological order. Use both to ground your answer.

<lens_intent>
{user_prompt}
</lens_intent>

<task>
{task_instruction}
</task>

<events>
{events_json}
</events>
"""


class BaseLensOutput(BaseModel, frozen=True):
    """Final output shape emitted as `$recording_observed` event properties (flattened with `lens_output_*` keys)."""

    confidence: float = Field(
        ge=0,
        le=1,
        description="Your confidence in this answer, 0 to 1. 0.5 means uncertain; 1.0 means absolutely sure.",
    )

    def to_event_properties(self) -> dict[str, Any]:
        """Flatten with `lens_output_*` keys for the `$recording_observed` event.

        `lens_type` is excluded because it's already a top-level event property via the snapshot.
        """
        return {f"lens_output_{k}": v for k, v in self.model_dump(mode="json", exclude={"lens_type"}).items()}


class BaseLens(BaseModel, frozen=True):
    """Common shape for every concrete lens; subclasses bind a `Literal` `lens_type` discriminator and override `task_instruction` + `llm_response_schema`."""

    prompt: str
    emits_signals: bool = False

    def task_instruction(self) -> str:
        """Lens-type-specific guidance — describes what to put in each output field."""
        raise NotImplementedError

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        """Pydantic class the LLM emits, passed to Gemini's `response_json_schema`."""
        raise NotImplementedError

    def finalize(self, llm_response: BaseModel) -> BaseLensOutput:
        """Build the final `BaseLensOutput` from the validated LLM response; default returns it unchanged."""
        if not isinstance(llm_response, BaseLensOutput):
            raise TypeError(f"Expected BaseLensOutput, got {type(llm_response).__name__}")
        return llm_response

    def validate_semantics(self, output: BaseLensOutput) -> str | None:
        """Lens-specific checks beyond Pydantic schema validation; return `None` when valid, otherwise an error string suitable to feed back into a re-prompt."""
        return None

    def build_prompt(self, *, team_name: str, events: "EventTable") -> str:
        return _PROMPT_TEMPLATE.format(
            team_name=team_name,
            user_prompt=self.prompt,
            task_instruction=self.task_instruction(),
            events_json=_render_events(events),
        )


def _render_events(events: "EventTable") -> str:
    if not events.rows:
        return "(no events captured during the session)"
    # Compact separators: Gemini parses fine without whitespace, and indent=2 burns thousands of prompt tokens.
    rendered = json.dumps([dict(zip(events.columns, row)) for row in events.rows], separators=(",", ":"), default=str)
    # Escape `<` so a hostile event value can't forge the `</events>` closing tag and break out of the data block.
    return rendered.replace("<", "\\u003c")
