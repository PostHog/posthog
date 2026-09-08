from products.exports.backend.temporal.subscriptions.ai_subscription.activities import (
    _recommendation_memory_context_content,
    _render_recommendations_appendix,
)
from products.subscriptions.backend.facade.contracts import Recommendation, RecommendationCitation
from products.subscriptions.backend.facade.proactive import RecommendationAppendixDTO, RecommendationMemoryDTO


def test_pulse_appendix_is_bounded_and_deterministic() -> None:
    recommendation = Recommendation(
        kind="investigation",
        title="Check activation",
        rationale="Activation fell",
        target="activation",
        why_now="This week",
        confidence=0.8,
        effort="small",
        metric_name="activation rate",
        metric_direction="increase",
        expected_metric_movement="5%",
        citation_ids=("report",),
        semantic_key="key",
    )
    appendix = RecommendationAppendixDTO(
        status="completed",
        recommendations=(recommendation,) * 4,
        citations=(RecommendationCitation(id="report", title="Subscription report"),),
    )

    rendered = _render_recommendations_appendix(appendix)

    assert rendered.startswith("## Recommendations")
    assert rendered.count("### Check activation") == 3
    assert "Sources: Subscription report" in rendered


def test_recommendation_memory_context_includes_a_non_citable_outcome_summary() -> None:
    item = RecommendationMemoryDTO(
        semantic_key="key",
        title="Check activation",
        created_at="2026-09-08T10:30:00+00:00",
        outcome_status="improved",
        outcome_summary="Metric movement after adoption: activation increased by 2 (the expected direction).",
    )

    assert _recommendation_memory_context_content(item) == (
        "Previously recommended at 2026-09-08T10:30:00+00:00: Check activation. "
        "Do not repeat this exact idea. "
        "Metric movement after adoption: activation increased by 2 (the expected direction)."
    )
