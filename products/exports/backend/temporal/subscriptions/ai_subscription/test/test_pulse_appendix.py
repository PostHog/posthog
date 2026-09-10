from products.exports.backend.temporal.subscriptions.ai_subscription.activities import _render_recommendations_appendix
from products.subscriptions.backend.facade.contracts import Recommendation, RecommendationCitation
from products.subscriptions.backend.facade.proactive import RecommendationAppendixDTO


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
