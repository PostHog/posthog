"""Base class for all Replay Vision lens types."""

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from products.replay_vision.backend.temporal.lenses.prompt_env import render_prompt

if TYPE_CHECKING:
    from products.replay_vision.backend.temporal.types import EventTable


class BaseLensOutput(BaseModel, frozen=True):
    """Final output shape emitted as `$recording_observed` event properties (flattened with `lens_output_*` keys)."""

    confidence: float = Field(
        ge=0,
        le=1,
        description="Your confidence in this answer, 0 to 1. 0.5 means uncertain; 1.0 means absolutely sure.",
    )

    def to_event_properties(self) -> dict[str, Any]:
        """Flatten with `lens_output_*` keys for the event; `lens_type` is excluded (already a top-level property via the snapshot)."""
        return {f"lens_output_{k}": v for k, v in self.model_dump(mode="json", exclude={"lens_type"}).items()}


class BaseLens(BaseModel, frozen=True):
    """Common shape for every concrete lens; subclasses bind a `Literal` `lens_type` discriminator, a `prompt_template`, and an `llm_response_schema`."""

    prompt: str
    emits_signals: bool = False

    # Per-lens-type Jinja2 template under `prompts/`. Subclasses set this.
    prompt_template: ClassVar[str] = ""

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        """Pydantic class the LLM emits, passed to Gemini's `response_json_schema`."""
        raise NotImplementedError

    def prompt_context(self) -> dict[str, Any]:
        """Lens-type-specific template variables. Subclasses override to inject their per-instance config."""
        return {}

    def finalize(self, llm_response: BaseModel) -> BaseLensOutput:
        """Build the final `BaseLensOutput` from the validated LLM response; default returns it unchanged."""
        if not isinstance(llm_response, BaseLensOutput):
            raise TypeError(f"Expected BaseLensOutput, got {type(llm_response).__name__}")
        return llm_response

    def validate_semantics(self, output: BaseLensOutput) -> str | None:
        """Lens-specific checks beyond Pydantic schema validation; return `None` when valid, otherwise an error string suitable to feed back into a re-prompt."""
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
            **self.prompt_context(),
        )
