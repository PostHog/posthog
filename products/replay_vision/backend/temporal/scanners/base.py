"""Base class for all Replay Vision scanner types."""

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from products.replay_vision.backend.temporal.scanners.prompt_env import render_prompt

if TYPE_CHECKING:
    from products.replay_vision.backend.temporal.types import EventTable


class BaseScannerOutput(BaseModel, frozen=True):
    """Final output shape emitted as `$recording_observed` event properties (flattened with `scanner_output_*` keys)."""

    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Calibrated confidence, 0.0 to 1.0 with one decimal; use the full range — most answers fall in 0.6-0.9. "
            "Ask: could a reasonable alternative answer be defended on the same evidence? If yes, cap at 0.7. "
            "Reserve 0.9+ for unambiguous evidence with no plausible alternative. "
            "1.0 should be exceedingly rare — pick 0.95 instead."
        ),
    )

    def to_event_properties(self) -> dict[str, Any]:
        """Flatten with `scanner_output_*` keys for the event; `scanner_type` is excluded (already a top-level property via the snapshot)."""
        return {f"scanner_output_{k}": v for k, v in self.model_dump(mode="json", exclude={"scanner_type"}).items()}


class BaseScanner(BaseModel, frozen=True):
    """Common shape for every concrete scanner; subclasses bind `scanner_type`, `prompt_template`, and `llm_response_schema`."""

    emits_signals: bool = False

    # Per-scanner-type Jinja2 template under `prompts/`. Subclasses set this.
    prompt_template: ClassVar[str] = ""
    # Names of free-text fields on the LLM response that may contain `(event_id <hash>)` citations.
    citation_fields: ClassVar[tuple[str, ...]] = ()
    # Persisted output class — subclasses override to stamp their `scanner_type` discriminator.
    output_cls: ClassVar[type["BaseScannerOutput"] | None] = None

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        """Pydantic class the LLM emits, passed to Gemini's `response_json_schema`."""
        raise NotImplementedError

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
            # `prompt` lives on the four scanners that accept it; the indexer doesn't declare one.
            user_prompt=getattr(self, "prompt", None),
            events=events,
            url_mapping=url_mapping or {},
            window_mapping=window_mapping or {},
            session_metadata=session_metadata or {},
            **self.prompt_context(),
        )
