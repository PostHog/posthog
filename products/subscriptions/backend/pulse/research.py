"""Server-owned public research topics for proactive subscriptions."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, cast

PublicResearchTopic = Literal[
    "product_analytics_market_trends",
    "product_analytics_competitors",
    "b2b_saas_benchmarks",
    "consumer_product_benchmarks",
    "onboarding_best_practices",
    "activation_best_practices",
    "retention_best_practices",
    "experimentation_best_practices",
    "analytics_instrumentation_best_practices",
    "pricing_best_practices",
]

PUBLIC_RESEARCH_TOPIC_QUERIES: Final[Mapping[PublicResearchTopic, str]] = MappingProxyType(
    {
        "product_analytics_market_trends": "current product analytics market trends",
        "product_analytics_competitors": "product analytics competitor landscape",
        "b2b_saas_benchmarks": "B2B SaaS product adoption benchmarks",
        "consumer_product_benchmarks": "consumer digital product engagement benchmarks",
        "onboarding_best_practices": "software product onboarding best practices",
        "activation_best_practices": "software product activation best practices",
        "retention_best_practices": "software product retention best practices",
        "experimentation_best_practices": "product experimentation best practices",
        "analytics_instrumentation_best_practices": "product analytics instrumentation best practices",
        "pricing_best_practices": "software product pricing best practices",
    }
)
PUBLIC_RESEARCH_TOPICS: Final[tuple[PublicResearchTopic, ...]] = tuple(PUBLIC_RESEARCH_TOPIC_QUERIES)


class PublicResearchValidationError(ValueError):
    pass


def public_research_query_for_topic(topic: str) -> str:
    """Resolve one fixed query without sending model-authored text to the provider."""
    try:
        return PUBLIC_RESEARCH_TOPIC_QUERIES[cast(PublicResearchTopic, topic)]
    except KeyError as error:
        raise PublicResearchValidationError("Public research topic is invalid") from error
