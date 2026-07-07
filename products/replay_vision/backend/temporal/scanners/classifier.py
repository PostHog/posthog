"""Classifier scanner: assigns one or more tags from a fixed vocabulary, optionally plus freeform tags."""

import typing
from functools import cached_property
from typing import Any, ClassVar, Literal, cast

from pydantic import BaseModel, Field, create_model, field_validator

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.tags import slugify_tag
from products.replay_vision.backend.temporal.scanners.base import (
    BaseScanner,
    BaseScannerOutput,
    Segment,
    confidence_field,
)

_MAX_FREEFORM_TAGS = 5


class ClassifierOutput(BaseScannerOutput, frozen=True):
    scanner_type: Literal[ScannerType.CLASSIFIER] = ScannerType.CLASSIFIER
    tags: list[str] = Field(description="Subset of the scanner's configured tag vocabulary.")
    tags_freeform: list[str] = Field(
        default_factory=list,
        description=(
            "Open-text tags emitted by the LLM when the scanner has `allow_freeform_tags=True`; lowercase, deduped."
        ),
    )
    reasoning: str = Field(description="One paragraph grounding the tag choice in concrete moments.")
    reasoning_segments: list[Segment] = Field(default_factory=list)

    @field_validator("tags_freeform", mode="after")
    @classmethod
    def _normalize_freeform(cls, value: list[str]) -> list[str]:
        # Lowercase + snake-case + order-preserving dedup so the unbounded freeform space stays consistent.
        return list(dict.fromkeys(slug for tag in value if (slug := slugify_tag(tag))))


class ClassifierScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.CLASSIFIER] = ScannerType.CLASSIFIER
    core_step_template: ClassVar[str] = "classifier_step.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("reasoning",)
    output_cls: ClassVar[type[BaseScannerOutput]] = ClassifierOutput
    tags: list[str] = Field(min_length=1, description="Fixed vocabulary the model picks from.")
    multi_label: bool = True
    allow_freeform_tags: bool = Field(
        default=False,
        description=f"When true, the LLM may emit up to {_MAX_FREEFORM_TAGS} freeform tags alongside the fixed picks.",
    )

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        # Pin the vocabulary as a `Literal` enum and `multi_label=False` as `max_length=1` so Gemini fails invalid tags at parse time.
        tag_literal = typing.Literal[tuple(self.tags)]  # type: ignore[valid-type]
        # Field order is load-bearing: reasoning first (reason before tagging), confidence last.
        fields: dict[str, Any] = {
            "reasoning": (str, Field(description="One paragraph grounding the tag choice in concrete moments.")),
            "tags": (
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
        }
        if self.allow_freeform_tags:
            fields["tags_freeform"] = (
                list[str],
                Field(
                    default_factory=list,
                    max_length=_MAX_FREEFORM_TAGS,
                    description=(
                        f"Up to {_MAX_FREEFORM_TAGS} short lowercase snake_case identifiers, ONLY for concepts no "
                        "fixed-vocabulary tag covers. Never paraphrase or restate a fixed tag here. Skip when nothing "
                        "meaningful applies."
                    ),
                ),
            )
        fields["confidence"] = (float, confidence_field())
        return create_model("ClassifierLlmResponse", **fields)

    @cached_property
    def _fixed_vocab_slugs(self) -> frozenset[str]:
        """Slug-normalized fixed-vocab tags; cached so per-observation finalize doesn't re-walk the regex."""
        return frozenset(slugify_tag(t) for t in self.tags)

    def finalize(self, llm_response: BaseModel) -> BaseScannerOutput:
        # Base maps the dynamic `Literal`-typed response onto the static `ClassifierOutput` (its validator lowercases
        # and dedups freeform). Then strip freeform tags that overlap the fixed vocab — same slug normalization both sides.
        output = cast(ClassifierOutput, super().finalize(llm_response))
        kept = [t for t in output.tags_freeform if t not in self._fixed_vocab_slugs]
        if kept != output.tags_freeform:
            output = output.model_copy(update={"tags_freeform": kept})
        return output

    def prompt_context(self) -> dict[str, Any]:
        return {
            "vocabulary": ", ".join(repr(t) for t in self.tags),
            "multi_label": self.multi_label,
            "allow_freeform_tags": self.allow_freeform_tags,
            "max_freeform_tags": _MAX_FREEFORM_TAGS,
        }

    def validate_semantics(self, output: BaseScannerOutput) -> str | None:
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
        if not self.allow_freeform_tags and output.tags_freeform:
            return f"allow_freeform_tags=False but received freeform tags {output.tags_freeform!r}"
        if len(output.tags_freeform) > _MAX_FREEFORM_TAGS:
            return f"Too many freeform tags: {len(output.tags_freeform)} > {_MAX_FREEFORM_TAGS}"
        return None
