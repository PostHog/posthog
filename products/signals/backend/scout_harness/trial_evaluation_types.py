from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class EvaluationDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TrialEvaluationVariant(EvaluationDocument):
    id: UUID
    label: str = Field(min_length=1, max_length=100)
    launch_ids: list[UUID] = Field(min_length=1, max_length=20)


class TrialEvaluationRequest(EvaluationDocument):
    evaluation_id: UUID
    baseline_variant_id: UUID
    variants: list[TrialEvaluationVariant] = Field(min_length=1, max_length=10)
    rubric_source: Literal["mock"]


class TrialEvaluationCriterion(EvaluationDocument):
    id: str
    title: str
    description: str
    pass_condition: str
    applicability: str


class TrialEvidenceSource(EvaluationDocument):
    id: str
    kind: Literal["instructions", "context", "summary", "report", "memory", "trace"]
    text: str


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
    criteria: list[TrialEvaluationCriterion]
    judge_model: str
    judge_prompt_version: str
    runs: list[TrialRunEvidence]


class TrialCriterionEvidence(EvaluationDocument):
    source_id: str = Field(max_length=100)
    quote: str = Field(min_length=1, max_length=1000)


class TrialCriterionVerdict(EvaluationDocument):
    criterion_id: str = Field(max_length=100)
    verdict: Literal["pass", "fail", "unknown", "not_applicable"]
    reason: str = Field(min_length=1, max_length=2000)
    confidence: Literal["low", "medium", "high"]
    evidence: list[TrialCriterionEvidence] = Field(default_factory=list, max_length=6)


class TrialJudgeVerdicts(EvaluationDocument):
    summary: str = Field(min_length=1, max_length=2000)
    criteria: list[TrialCriterionVerdict] = Field(min_length=1, max_length=30)


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


class TrialComparisonReport(EvaluationDocument):
    version: Literal[1] = 1
    evaluation_id: UUID
    context_id: UUID
    created_at: datetime
    completed_at: datetime
    summary: str
    rubric_source: Literal["mock"]
    rubric_revision: int
    criteria: list[TrialEvaluationCriterion]
    baseline_variant_id: UUID
    judge_model: str
    judge_prompt_version: str
    variants: list[TrialVariantAggregate]
    runs: list[TrialRunJudgment]
    evidence: list[TrialRunEvidence]
    limitations: list[str]
