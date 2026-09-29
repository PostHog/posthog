from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from products.signals.backend.scout_harness.limits import MAX_RUN_NOTE_CHARS
from products.signals.backend.scout_harness.trial_evaluation_types import (
    EvaluationDocument,
    TrialComparisonReport,
    TrialEvaluationRequest,
    TrialEvaluationVariant,
)


class TrialComparisonVariant(EvaluationDocument):
    id: UUID
    label: str = Field(min_length=1, max_length=100)
    launch_ids: list[UUID] = Field(min_length=1, max_length=20)
    model: str = Field(min_length=1, max_length=200)
    reasoning_effort: str = Field(min_length=1, max_length=20)
    skill_body: str | None = Field(default=None, min_length=1, max_length=100_000)


class TrialComparisonRequest(EvaluationDocument):
    comparison_id: UUID
    baseline_variant_id: UUID
    variants: list[TrialComparisonVariant] = Field(min_length=1, max_length=10)
    note: str = Field(default="", max_length=MAX_RUN_NOTE_CHARS)

    def evaluation_request(self) -> TrialEvaluationRequest:
        return TrialEvaluationRequest(
            evaluation_id=self.comparison_id,
            baseline_variant_id=self.baseline_variant_id,
            rubric_source="saved",
            variants=[TrialEvaluationVariant(id=v.id, label=v.label, launch_ids=v.launch_ids) for v in self.variants],
        )


class TrialComparisonVariantResult(EvaluationDocument):
    id: UUID
    label: str
    launch_ids: list[UUID]
    model: str
    reasoning_effort: str
    skill_body_sha256: str


class TrialComparisonPlan(EvaluationDocument):
    version: Literal[1] = 1
    comparison_id: UUID
    team_id: int
    config_id: UUID
    user_id: int
    context_id: UUID
    skill_name: str
    skill_version: int
    variants: list[TrialComparisonVariantResult]
    created_at: datetime
    request: TrialComparisonRequest
    request_hash: str
    rubric_document: dict[str, JsonValue]
    judge_model: str
    judge_prompt_version: str


class TrialComparisonEvaluation(EvaluationDocument):
    request: TrialEvaluationRequest
    evaluation_id: UUID
    context_id: UUID
    status: str
    error: str | None
    report: TrialComparisonReport | None


class TrialComparisonResult(EvaluationDocument):
    comparison_id: UUID
    config_id: UUID
    context_id: UUID
    created_at: datetime
    baseline_variant_id: UUID
    rubric_revision: int
    variants: list[TrialComparisonVariantResult]
    status: Literal["not_started", "starting", "running", "judging", "completed", "failed", "unknown"]
    error: str | None
    evaluation: TrialComparisonEvaluation | None


class TrialComparisonHistory(EvaluationDocument):
    results: list[TrialComparisonResult]
    has_more: bool


class TrialComparisonProgress(EvaluationDocument):
    status: Literal["not_started", "starting", "running", "judging", "completed", "failed", "unknown"]
    error: str | None = None


class TrialComparisonHistoryEntry(EvaluationDocument):
    team_id: int
    config_id: UUID
    user_id: int
    skill_name: str
    skill_version: int
    summary: TrialComparisonResult


class TrialEvaluationReservation(EvaluationDocument):
    team_id: int
    evaluation_id: UUID
    config_id: UUID
    user_id: int
    kind: Literal["comparison", "evaluation"]
    request_hash: str
