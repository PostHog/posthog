from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from products.signals.backend.facade.rubrics import ScoutRubricReferenceContext
from products.signals.backend.scout_harness.limits import MAX_TRIAL_REPEATS, MAX_TRIAL_VARIANTS
from products.signals.backend.trial_judging_types import (
    EvaluationDocument as EvaluationDocument,
    TrialCriterionEvidence as TrialCriterionEvidence,
    TrialCriterionVerdict as TrialCriterionVerdict,
    TrialEvaluationCriterion as TrialEvaluationCriterion,
    TrialEvidenceFile as TrialEvidenceFile,
    TrialEvidenceSource as TrialEvidenceSource,
    TrialJudgeVerdicts as TrialJudgeVerdicts,
    TrialRunEvidence as TrialRunEvidence,
    TrialRunJudgment as TrialRunJudgment,
)


class TrialEvaluationVariant(EvaluationDocument):
    id: UUID
    label: str = Field(min_length=1, max_length=100)
    launch_ids: list[UUID] = Field(min_length=1, max_length=MAX_TRIAL_REPEATS)


class TrialEvaluationRequest(EvaluationDocument):
    evaluation_id: UUID
    baseline_variant_id: UUID
    variants: list[TrialEvaluationVariant] = Field(min_length=1, max_length=MAX_TRIAL_VARIANTS)
    rubric_source: Literal["saved"]


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
    rubric_reference_context: ScoutRubricReferenceContext
    rubric_reference_generation_id: str
    criteria: list[TrialEvaluationCriterion]
    judge_model: str
    judge_prompt_version: str
    runs: list[TrialRunEvidence]


class TrialCriterionAggregate(EvaluationDocument):
    criterion_id: str
    passed: int
    failed: int
    unknown: int
    not_applicable: int
    pass_rate: float | None
    coverage: float | None
    baseline_delta: float | None = None


class TrialVariantAggregate(EvaluationDocument):
    variant_id: UUID
    label: str
    is_baseline: bool
    total_runs: int
    judged_runs: int
    excluded_runs: int
    judge_errors: int
    score: float | None
    coverage: float | None
    baseline_delta: float | None = None
    criteria: list[TrialCriterionAggregate]


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
    rubric_source: Literal["saved"]
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
