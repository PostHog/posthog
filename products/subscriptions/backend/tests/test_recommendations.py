from __future__ import annotations

from uuid import uuid4

import pytest

from products.subscriptions.backend.facade.recommendations import (
    RecommendationCitation,
    RecommendationContext,
    RecommendationDegradation,
    RecommendationGenerationInput,
    parse_recommendation_result,
    read_recommendation_generation,
    start_recommendation_generation,
)
from products.tasks.backend.facade.staged_evidence import CompletedMCPCallEvidence
from products.tasks.backend.facade.staged_execution import StagedTaskResult


def _recommendation(*, citation_ids: list[str]) -> dict[str, object]:
    return {
        "kind": "investigation",
        "title": "Investigate checkout drop-off",
        "rationale": "Checkout completion fell after the release.",
        "target": "checkout completion",
        "why_now": "The weekly report shows a new decline.",
        "confidence": 0.8,
        "effort": "small",
        "metric_name": "Checkout completion",
        "metric_direction": "increase",
        "expected_metric_movement": "Increase completed checkouts.",
        "citation_ids": citation_ids,
    }


def test_parse_recommendation_result_keeps_grounded_recommendations() -> None:
    result = parse_recommendation_result(
        {"recommendations": [_recommendation(citation_ids=["report"])]},
        allowed_citation_ids={"report"},
    )

    assert len(result.recommendations) == 1
    assert result.recommendations[0].citation_ids == ("report",)
    assert result.recommendations[0].semantic_key
    assert result.citations[0].id == "report"


def test_parse_recommendation_result_drops_only_invented_citations() -> None:
    result = parse_recommendation_result(
        {
            "recommendations": [
                _recommendation(citation_ids=["report"]),
                _recommendation(citation_ids=["invented"]),
            ]
        },
        allowed_citation_ids={"report"},
    )

    assert len(result.recommendations) == 1
    assert result.recommendations[0].citation_ids == ("report",)


def test_parse_recommendation_result_ignores_model_supplied_research_degradation() -> None:
    result = parse_recommendation_result(
        {"recommendations": [], "degradations": [{"code": "unavailable"}]},
        allowed_citation_ids={"report"},
    )

    assert result.degradations == ()


def test_parse_recommendation_result_rejects_more_than_three_recommendations() -> None:
    with pytest.raises(ValueError, match="at most three"):
        parse_recommendation_result(
            {"recommendations": [_recommendation(citation_ids=["report"]) for _ in range(4)]},
            allowed_citation_ids={"report"},
        )


def test_parse_recommendation_result_rejects_an_oversized_text_field() -> None:
    recommendation = _recommendation(citation_ids=["report"])
    recommendation["title"] = "x" * 301

    with pytest.raises(ValueError, match="title"):
        parse_recommendation_result({"recommendations": [recommendation]}, allowed_citation_ids={"report"})


def test_start_recommendation_generation_uses_the_fixed_pulse_analysis_posture(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_input = None

    def create(input):
        nonlocal captured_input
        captured_input = input
        return type("Created", (), {"staged_run_id": uuid4(), "task_id": uuid4(), "analysis_run_id": uuid4()})()

    monkeypatch.setattr("products.subscriptions.backend.facade.recommendations.create_staged_task", create)
    delivery_id = uuid4()

    handle = start_recommendation_generation(
        RecommendationGenerationInput(
            team_id=17,
            subscription_id=23,
            delivery_id=delivery_id,
            actor_id=29,
            idempotency_key="delivery-23",
            report_markdown="Checkout completion declined.",
            prompt="Find the most useful next step.",
            contexts=(),
            public_web_research=True,
        )
    )

    assert handle.staged_run_id
    assert captured_input.caller_id == delivery_id
    assert captured_input.origin_product == "pulse_subscription"
    assert captured_input.analysis_manifest.mcp_scope_preset == "pulse_analysis"
    assert captured_input.analysis_manifest.network_egress == "posthog_mcp_only"
    assert captured_input.analysis_manifest.disabled_tools == ("Bash", "WebFetch", "WebSearch", "Write", "Edit")
    assert "degradations" not in captured_input.output_schema["properties"]


def test_start_recommendation_generation_omits_the_research_tool_when_opted_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_input = None

    def create(input):
        nonlocal captured_input
        captured_input = input
        return type("Created", (), {"staged_run_id": uuid4(), "task_id": uuid4(), "analysis_run_id": uuid4()})()

    monkeypatch.setattr("products.subscriptions.backend.facade.recommendations.create_staged_task", create)

    start_recommendation_generation(
        RecommendationGenerationInput(
            team_id=17,
            subscription_id=23,
            delivery_id=uuid4(),
            actor_id=29,
            idempotency_key="delivery-23-no-research",
            report_markdown="Checkout completion declined.",
            prompt="Find the most useful next step.",
            contexts=(),
            public_web_research=False,
        )
    )

    assert captured_input.analysis_manifest.mcp_scope_preset == "pulse_analysis_no_research"


@pytest.mark.parametrize(
    "contexts",
    [
        (RecommendationContext(id="report", content="Not allowed."),),
        (RecommendationContext(id="same", content="One."), RecommendationContext(id="same", content="Two.")),
    ],
)
def test_start_recommendation_generation_rejects_ambiguous_context_evidence(
    contexts: tuple[RecommendationContext, ...],
) -> None:
    with pytest.raises(ValueError, match="context"):
        start_recommendation_generation(
            RecommendationGenerationInput(
                team_id=17,
                subscription_id=23,
                delivery_id=uuid4(),
                actor_id=29,
                idempotency_key="delivery-23",
                report_markdown="Checkout completion declined.",
                prompt="Find the most useful next step.",
                contexts=contexts,
                public_web_research=False,
            )
        )


def test_read_recommendation_generation_accepts_only_bound_completed_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "products.subscriptions.backend.facade.recommendations.read_staged_task_result",
        lambda **_: StagedTaskResult(
            status="completed",
            output={"recommendations": [_recommendation(citation_ids=["mcp:call-1"])]},
            completed_mcp_call_ids=("mcp:call-1",),
            completed_mcp_calls=(
                CompletedMCPCallEvidence(
                    citation_id="mcp:call-1",
                    tool_name="insight-query",
                    result={"value": 12},
                ),
            ),
        ),
    )
    input = RecommendationGenerationInput(
        team_id=17,
        subscription_id=23,
        delivery_id=uuid4(),
        actor_id=29,
        idempotency_key="delivery-23",
        report_markdown="Checkout completion declined.",
        prompt="Find the most useful next step.",
        contexts=(),
        public_web_research=False,
    )

    state = read_recommendation_generation(
        input,
        type("Handle", (), {"staged_run_id": uuid4(), "task_id": uuid4(), "analysis_run_id": uuid4()})(),
    )

    assert state.status == "completed"
    assert state.result is not None
    assert state.result.recommendations[0].citation_ids == ("mcp:call-1",)
    assert state.result.citations == (RecommendationCitation(id="mcp:call-1", title="PostHog MCP: insight-query"),)


def test_read_recommendation_generation_uses_completed_research_degradation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "products.subscriptions.backend.facade.recommendations.read_staged_task_result",
        lambda **_: StagedTaskResult(
            status="completed",
            output={"recommendations": [], "degradations": [{"code": "not_configured"}]},
            completed_mcp_calls=(
                CompletedMCPCallEvidence(
                    citation_id="mcp:insight-1",
                    tool_name="insight-query",
                    result={"degradation": "unavailable"},
                ),
                CompletedMCPCallEvidence(
                    citation_id="mcp:research-1",
                    tool_name="pulse-research-search",
                    result={"degradation": "busy"},
                ),
            ),
        ),
    )
    input = RecommendationGenerationInput(
        team_id=17,
        subscription_id=23,
        delivery_id=uuid4(),
        actor_id=29,
        idempotency_key="delivery-23",
        report_markdown="Checkout completion declined.",
        prompt="Find the most useful next step.",
        contexts=(),
        public_web_research=True,
    )

    state = read_recommendation_generation(
        input,
        type("Handle", (), {"staged_run_id": uuid4(), "task_id": uuid4(), "analysis_run_id": uuid4()})(),
    )

    assert state.result is not None
    assert state.result.degradations == (RecommendationDegradation(code="busy"),)


def test_read_recommendation_generation_accepts_only_completed_research_web_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "products.subscriptions.backend.facade.recommendations.read_staged_task_result",
        lambda **_: StagedTaskResult(
            status="completed",
            output={
                "recommendations": [
                    _recommendation(citation_ids=["web:real"]),
                    _recommendation(citation_ids=["web:invented"]),
                ]
            },
            completed_mcp_call_ids=("mcp:research-1",),
            completed_mcp_calls=(
                CompletedMCPCallEvidence(
                    citation_id="mcp:research-1",
                    tool_name="pulse-research-search",
                    result={"citations": [{"id": "web:real", "title": "Example", "url": "https://example.com"}]},
                ),
            ),
        ),
    )
    input = RecommendationGenerationInput(
        team_id=17,
        subscription_id=23,
        delivery_id=uuid4(),
        actor_id=29,
        idempotency_key="delivery-23",
        report_markdown="Checkout completion declined.",
        prompt="Find the most useful next step.",
        contexts=(),
        public_web_research=True,
    )

    state = read_recommendation_generation(
        input,
        type("Handle", (), {"staged_run_id": uuid4(), "task_id": uuid4(), "analysis_run_id": uuid4()})(),
    )

    assert state.status == "completed"
    assert state.result is not None
    assert [recommendation.citation_ids for recommendation in state.result.recommendations] == [("web:real",)]
    assert state.result.citations == (
        RecommendationCitation(
            id="web:real",
            title="Example",
            url="https://example.com",
        ),
    )
