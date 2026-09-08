"""Public subscription capabilities exposed to presentation and other products."""

from __future__ import annotations

from collections.abc import Mapping

from products.subscriptions.backend.logic import recommendations, research
from products.tasks.backend.facade.staged_evidence import CompletedMCPCallEvidence

from .contracts import (
    PublicResearchResult,
    RecommendationCitation,
    RecommendationDegradation,
    RecommendationGenerationHandle,
    RecommendationGenerationInput,
    RecommendationGenerationState,
    RecommendationResult,
)


def start_recommendation_generation(input: RecommendationGenerationInput) -> RecommendationGenerationHandle:
    return recommendations.start_recommendation_generation(input)


def read_recommendation_generation(
    input: RecommendationGenerationInput, handle: RecommendationGenerationHandle
) -> RecommendationGenerationState:
    return recommendations.read_recommendation_generation(input, handle)


def parse_recommendation_result(
    raw_result: dict[str, object],
    *,
    allowed_citation_ids: set[str],
    citation_metadata: Mapping[str, RecommendationCitation] | None = None,
    degradations: tuple[RecommendationDegradation, ...] = (),
    measurement_calls: tuple[CompletedMCPCallEvidence, ...] = (),
) -> RecommendationResult:
    return recommendations.parse_recommendation_result(
        raw_result,
        allowed_citation_ids=allowed_citation_ids,
        citation_metadata=citation_metadata,
        degradations=degradations,
        measurement_calls=measurement_calls,
    )


def run_public_research(query: str) -> PublicResearchResult:
    return research.run_public_research(query)
