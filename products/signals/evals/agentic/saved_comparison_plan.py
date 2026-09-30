from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from products.signals.evals.agentic.saved_case import SavedFile, SavedModel, SavedScoutCase

if TYPE_CHECKING:
    from products.signals.backend.scout_harness.trial_comparison_types import TrialComparisonRequest


class SavedComparisonVariant(SavedModel):
    label: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    reasoning_effort: str = Field(min_length=1, max_length=20)
    repeats: int = Field(default=1, ge=1, le=20)
    instructions: SavedFile | None = None

    @field_validator("label", "model", "reasoning_effort", mode="before")
    @classmethod
    def strip_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    def instruction_body(self, directory: Path) -> str | None:
        if self.instructions is None:
            return None
        body = self.instructions.resolve(directory).read_text(encoding="utf-8")
        if not body.strip() or len(body) > 100_000:
            raise ValueError("Variant instructions must contain 1–100,000 characters of nonempty UTF-8 text")
        return body


class SavedComparison(SavedModel):
    skill_name: str = Field(min_length=1, max_length=64)
    variants: tuple[SavedComparisonVariant, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_variants(self) -> Self:
        labels = [variant.label.strip() for variant in self.variants]
        if any(not label for label in labels) or len(set(labels)) != len(labels):
            raise ValueError("Variant labels must be nonempty and unique")
        if self.launch_count > 20:
            raise ValueError("The online comparison supports at most 20 runs per scout")
        return self

    @property
    def launch_count(self) -> int:
        return sum(variant.repeats for variant in self.variants)

    def run_note(self, saved: SavedScoutCase, target_cutoff: datetime) -> str:
        if saved.skill_name != self.skill_name:
            raise ValueError("The comparison scout does not match the saved case")
        note = saved.to_scout_case(target_cutoff).run_note or ""
        delta = saved._delta(target_cutoff)
        if delta.total_seconds():
            mapping = (
                f"Saved data shifted from cutoff {saved.manifest.source_cutoff.isoformat()} "
                f"to {target_cutoff.isoformat()} ({delta.total_seconds()} seconds)."
            )
            note = f"{mapping}\n{note}".strip()
        if len(note) > 1_000:
            raise ValueError("The comparison note and saved date mapping exceed 1,000 characters")
        return note

    def request(self, directory: Path, saved: SavedScoutCase, *, target_cutoff: datetime) -> TrialComparisonRequest:
        note = self.run_note(saved, target_cutoff)
        bodies = [variant.instruction_body(directory) for variant in self.variants]
        from products.signals.backend.scout_harness.trial_comparison_types import (  # noqa: PLC0415 — keep CLI validation Django-free
            TrialComparisonRequest,
            TrialComparisonVariant,
        )

        variants = [
            TrialComparisonVariant(
                id=uuid4(),
                label=variant.label,
                launch_ids=[uuid4() for _ in range(variant.repeats)],
                model=variant.model,
                reasoning_effort=variant.reasoning_effort,
                skill_body=body,
            )
            for variant, body in zip(self.variants, bodies, strict=True)
        ]
        return TrialComparisonRequest(
            comparison_id=uuid4(),
            baseline_variant_id=variants[0].id,
            variants=variants,
            note=note,
        )


class SavedComparisonPlan(SavedModel):
    schema_version: Literal[1] = 1
    comparisons: tuple[SavedComparison, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_scouts(self) -> Self:
        names = [comparison.skill_name for comparison in self.comparisons]
        if len(set(names)) != len(names):
            raise ValueError("Each scout must have one comparison per batch")
        return self

    def validate_inputs(
        self,
        directory: Path,
        cases: tuple[SavedScoutCase, ...],
        max_sandboxes: int,
        *,
        target_cutoff: datetime | None = None,
    ) -> None:
        sources = {case.skill_name: case for case in cases}
        if len(sources) != len(cases):
            raise ValueError("Each scout must have one prepared saved case")
        for comparison in self.comparisons:
            if comparison.skill_name not in sources:
                raise ValueError(f"No saved case supplies scout {comparison.skill_name}")
            if comparison.launch_count > max_sandboxes:
                raise ValueError("Online variants run in parallel; increase --max-sandboxes or reduce repeats/variants")
            for variant in comparison.variants:
                variant.instruction_body(directory)
            if target_cutoff is not None:
                comparison.run_note(sources[comparison.skill_name], target_cutoff)
