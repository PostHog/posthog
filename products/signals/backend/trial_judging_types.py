from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EvaluationDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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


class TrialEvidenceFile(EvaluationDocument):
    id: str = Field(min_length=1, max_length=100)
    kind: Literal["instructions", "context", "summary", "report", "memory", "trace"]
    filename: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*\.(txt|jsonl)$", max_length=120)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


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
    files: list[TrialEvidenceFile] = Field(default_factory=list)
    sources: list[TrialEvidenceSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TrialCriterionEvidence(EvaluationDocument):
    source_id: str = Field(max_length=100)
    quote: str = Field(min_length=1, max_length=1000)


class TrialCriterionVerdict(EvaluationDocument):
    criterion_id: str = Field(max_length=100)
    verdict: Literal["pass", "fail", "unknown", "not_applicable"]
    reason: str = Field(min_length=1, max_length=2000)
    confidence: Literal["low", "medium", "high"]
    evidence: list[TrialCriterionEvidence] = Field(max_length=6)


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
