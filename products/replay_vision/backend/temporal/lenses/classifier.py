"""Classifier lens: assigns one or more tags from a fixed vocabulary."""

import typing
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, create_model

from products.replay_vision.backend.models.replay_lens import LensType
from products.replay_vision.backend.temporal.lenses.base import BaseLens, BaseLensOutput


class ClassifierOutput(BaseLensOutput, frozen=True):
    lens_type: Literal[LensType.CLASSIFIER] = LensType.CLASSIFIER
    tags: list[str] = Field(description="Subset of the lens's configured tag vocabulary.")
    reasoning: str = Field(description="One paragraph grounding the tag choice in concrete moments.")


class ClassifierLens(BaseLens, frozen=True):
    lens_type: Literal[LensType.CLASSIFIER] = LensType.CLASSIFIER
    prompt: str
    prompt_template: ClassVar[str] = "classifier.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("reasoning",)
    output_cls: ClassVar[type[BaseLensOutput]] = ClassifierOutput
    tags: list[str] = Field(min_length=1, description="Fixed vocabulary the model picks from.")
    multi_label: bool = True

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        # Pin the vocabulary as a `Literal` enum and `multi_label=False` as `max_length=1` so Gemini fails invalid tags at parse time.
        tag_literal = typing.Literal[tuple(self.tags)]  # type: ignore[valid-type]
        return create_model(
            "ClassifierLlmResponse",
            __base__=BaseLensOutput,
            tags=(
                list[tag_literal],  # type: ignore[valid-type]
                Field(
                    min_length=1,
                    max_length=None if self.multi_label else 1,
                    description=(
                        "Subset of the configured tag vocabulary."
                        if self.multi_label
                        else "The single tag from the configured vocabulary that best fits."
                    ),
                ),
            ),
            reasoning=(str, Field(description="One paragraph grounding the tag choice in concrete moments.")),
        )

    def finalize(self, llm_response: BaseModel) -> BaseLensOutput:
        # Cast the dynamic `Literal`-typed response to the static `ClassifierOutput` for downstream consumers.
        return ClassifierOutput(
            confidence=llm_response.confidence,  # type: ignore[attr-defined]
            tags=list(llm_response.tags),  # type: ignore[attr-defined]
            reasoning=llm_response.reasoning,  # type: ignore[attr-defined]
        )

    def prompt_context(self) -> dict[str, Any]:
        return {
            "vocabulary": ", ".join(repr(t) for t in self.tags),
            "multi_label": self.multi_label,
        }

    def validate_semantics(self, output: BaseLensOutput) -> str | None:
        # Defense in depth — `llm_response_schema` already enforces these at parse time, but `ClassifierOutput`'s `list[str]` doesn't.
        if not isinstance(output, ClassifierOutput):
            return f"Expected ClassifierOutput, got {type(output).__name__}"
        if not output.tags:
            return "tags must not be empty"
        configured = set(self.tags)
        unknown = [t for t in output.tags if t not in configured]
        if unknown:
            return f"Tags {unknown!r} are not in the configured vocabulary {self.tags!r}"
        if not self.multi_label and len(output.tags) != 1:
            return f"multi_label=False requires exactly one tag; got {len(output.tags)}"
        return None
