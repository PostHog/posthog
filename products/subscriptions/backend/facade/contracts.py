"""Stable, framework-free contracts for proactive subscriptions."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen

from products.tasks.backend.facade.staged_evidence import CompletedMCPCallEvidence
from products.tasks.backend.facade.staged_execution import StagedRepositoryBinding as StagedRepositoryBinding

RecommendationKind = Literal["product_change", "experiment", "instrumentation", "investigation"]
RecommendationEffort = Literal["small", "medium", "large"]
RecommendationStatus = Literal["pending", "completed", "failed"]


@frozen
class RecommendationContext:
    id: str
    content: str
    citable: bool = True


@frozen
class RecommendationCitation:
    id: str
    title: str
    url: str | None = None


@frozen
class Recommendation:
    kind: RecommendationKind
    title: str
    rationale: str
    target: str
    why_now: str
    confidence: float
    effort: RecommendationEffort
    metric_name: str
    metric_direction: str
    expected_metric_movement: str
    citation_ids: tuple[str, ...]
    semantic_key: str
    measurement_call_id: str | None = None


@frozen
class RecommendationDegradation:
    code: str
    detail: str | None = None


@frozen
class RecommendationResult:
    recommendations: tuple[Recommendation, ...]
    citations: tuple[RecommendationCitation, ...]
    degradations: tuple[RecommendationDegradation, ...] = ()
    completed_mcp_calls: tuple[CompletedMCPCallEvidence, ...] = ()


@frozen
class RecommendationGenerationInput:
    team_id: int
    subscription_id: int
    delivery_id: UUID
    actor_id: int
    idempotency_key: str
    report_markdown: str
    prompt: str
    contexts: tuple[RecommendationContext, ...]
    public_web_research: bool
    create_draft_pr: bool = False
    repository_name: str | None = None
    repository_integration_id: int | None = None
    repository: StagedRepositoryBinding | None = None


@frozen
class RecommendationGenerationHandle:
    staged_run_id: UUID
    task_id: UUID
    analysis_run_id: UUID


@frozen
class RecommendationGenerationState:
    status: RecommendationStatus
    result: RecommendationResult | None = None
    failure_code: str | None = None


@frozen
class PublicResearchCitation:
    id: str
    url: str
    title: str
    excerpt: str


@frozen
class PublicResearchResult:
    citations: tuple[PublicResearchCitation, ...]
    degradation: str | None = None
