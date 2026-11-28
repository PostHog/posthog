from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from pydantic.dataclasses import dataclass

from .enums import InvestigationHypothesisStatus, InvestigationStage

Text = Annotated[str, Field(max_length=10000)]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Cell = Annotated[str, Field(max_length=2000)] | Annotated[float, Field(allow_inf_nan=False)] | bool | None


class InvestigationEvidence(BaseModel):
    id: Identifier
    reference: int = Field(gt=0)
    title: str = Field(max_length=200)
    kind: Literal["query", "link"]
    sql: Text
    url: str = Field(max_length=2000)
    note: Text


class InvestigationHypothesis(BaseModel):
    id: Identifier
    title: str = Field(max_length=500)
    status: InvestigationHypothesisStatus
    reasoning: Text
    evidenceIds: list[Identifier] = Field(max_length=12)


class InvestigationEvidenceResult(BaseModel):
    evidenceId: Identifier
    title: str = Field(max_length=200)
    sql: Text
    columns: list[Annotated[str, Field(max_length=500)]] = Field(max_length=20)
    rows: list[Annotated[list[Cell], Field(max_length=20)]] = Field(max_length=50)
    truncated: bool
    error: Annotated[str, Field(max_length=2000)] | None


class InvestigationRun(BaseModel):
    id: Identifier
    at: datetime
    conclusion: Text
    results: list[InvestigationEvidenceResult] = Field(max_length=12)


class InvestigationDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    question: str = Field(max_length=500)
    status: InvestigationStage
    context: Text
    checks: list[Literal["definition", "maturity", "tracking", "population"]] = Field(max_length=4)
    evidence: list[InvestigationEvidence] = Field(max_length=12)
    nextEvidenceNumber: int = Field(gt=0)
    hypotheses: list[InvestigationHypothesis] = Field(max_length=12)
    conclusion: Text
    decision: Text
    followUp: str = Field(max_length=2000)
    runs: list[InvestigationRun] = Field(max_length=10)
    baselineId: Identifier | None
    example: bool


@dataclass(frozen=True, kw_only=True)
class InvestigationSummary:
    id: UUID
    question: str
    status: InvestigationStage
    revision: int
    evidence_count: int
    run_count: int
    updated_at: datetime
    created_at: datetime
    created_by: int | None


@dataclass(frozen=True, kw_only=True)
class SavedInvestigation(InvestigationSummary):
    document: dict[str, JsonValue]


class InvestigationNotFound(Exception):
    pass


class InvestigationConflict(Exception):
    pass
