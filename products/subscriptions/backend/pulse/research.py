"""Bounded, server-owned public research primitives for proactive subscriptions."""

from string import Formatter
from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen

PublicResearchTopic = Literal[
    "market_trends",
    "competitor_landscape",
    "industry_benchmarks",
    "product_best_practices",
]

PUBLIC_RESEARCH_TOPICS = frozenset(
    {
        "market_trends",
        "competitor_landscape",
        "industry_benchmarks",
        "product_best_practices",
    }
)
_TEMPLATE_FIELDS = frozenset({"subject_name", "canonical_domain", "topic"})


class PublicResearchValidationError(ValueError):
    pass


@frozen
class PublicResearchRequest:
    """The only model-facing research input: a fixed topic and reviewed catalog UUID."""

    topic: PublicResearchTopic
    public_subject_id: UUID


def render_public_research_query(*, topic: str, subject_name: str, canonical_domain: str, template: str) -> str:
    """Render a reviewed catalog template without accepting any model-authored prose."""
    if topic not in PUBLIC_RESEARCH_TOPICS:
        raise PublicResearchValidationError("Public research topic is not reviewed")
    if not subject_name or not canonical_domain or not template:
        raise PublicResearchValidationError("Public research catalog record is incomplete")
    fields = {field_name for _, field_name, _, _ in Formatter().parse(template) if field_name}
    if fields - _TEMPLATE_FIELDS:
        raise PublicResearchValidationError("Public research template contains an unapproved field")
    try:
        query = template.format(
            subject_name=subject_name,
            canonical_domain=canonical_domain,
            topic=topic,
        )
    except (KeyError, ValueError) as exc:
        raise PublicResearchValidationError("Public research template is invalid") from exc
    normalized = " ".join(query.split())
    if not normalized or len(normalized) > 512:
        raise PublicResearchValidationError("Public research query is invalid or exceeds its budget")
    return normalized
