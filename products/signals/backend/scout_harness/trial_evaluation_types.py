from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from products.signals.backend.facade.rubrics import ScoutRubricReferenceContext
from products.signals.backend.rubrics_judging import (
    EvaluationDocument as EvaluationDocument,
    TrialCriterionAggregate as TrialCriterionAggregate,
    TrialCriterionEvidence as TrialCriterionEvidence,
    TrialCriterionVerdict as TrialCriterionVerdict,
    TrialEvaluationCriterion as TrialEvaluationCriterion,
    TrialEvidenceSource as TrialEvidenceSource,
    TrialJudgeVerdicts as TrialJudgeVerdicts,
    TrialVariantAggregate as TrialVariantAggregate,
)


class TrialEvaluationVariant(EvaluationDocument):
    id: UUID
    label: str = Field(min_length=1, max_length=100)
    launch_ids: list[UUID] = Field(min_length=1, max_length=20)


class TrialEvaluationRequest(EvaluationDocument):
    evaluation_id: UUID
    baseline_variant_id: UUID
    variants: list[TrialEvaluationVariant] = Field(min_length=1, max_length=10)
    rubric_source: Literal["mock", "saved"]


class TrialRunEvidence(EvaluationDocument):
    launch_id: UUID
    variant_id: UUID
    run_id: UUID | None
    task_id: UUID | None
    task_run_id: UUID | None
    execution_status: str
    exclusion_reason: str | None = None
    model: str
    runtime_adapter: Literal["claude", "codex"]
    service_tier: str | None = None
    reasoning_effort: str
    skill_body_sha256: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    sources: list[TrialEvidenceSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TrialEvaluationSnapshot(EvaluationDocument):
    version: Literal[1] = 1
    evaluation_id: UUID
    team_id: int
    config_id: UUID
    user_id: int
    context_id: UUID
    created_at: datetime
    request: TrialEvaluationRequest
    request_hash: str
    rubric_document: dict[str, JsonValue]
    rubric_reference_context: ScoutRubricReferenceContext | None = None
    rubric_reference_generation_id: str | None = None
    criteria: list[TrialEvaluationCriterion]
    judge_model: str
    judge_prompt_version: str
    runs: list[TrialRunEvidence]


class TrialRunJudgment(EvaluationDocument):
    launch_id: UUID
    variant_id: UUID
    status: Literal["judged", "excluded", "judge_error"]
    score: float | None = None
    coverage: float | None = None
    summary: str
    criteria: list[TrialCriterionVerdict] = Field(default_factory=list)
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class TrialComparisonOutcome(EvaluationDocument):
    status: Literal["winner", "tie", "inconclusive"]
    variant_ids: list[UUID] = Field(default_factory=list)
    summary: str


class TrialComparisonReport(EvaluationDocument):
    version: Literal[1] = 1
    evaluation_id: UUID
    context_id: UUID
    created_at: datetime
    completed_at: datetime
    summary: str
    outcome: TrialComparisonOutcome | None = None
    rubric_source: Literal["mock", "saved"]
    rubric_revision: int
    rubric_reference_context: ScoutRubricReferenceContext | None = None
    rubric_reference_generation_id: str | None = None
    criteria: list[TrialEvaluationCriterion]
    baseline_variant_id: UUID
    judge_model: str
    judge_prompt_version: str
    variants: list[TrialVariantAggregate]
    runs: list[TrialRunJudgment]
    evidence: list[TrialRunEvidence]
    limitations: list[str]
