from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

from parameterized import parameterized
from posthoganalytics import Posthog

from products.posthog_ai.eval_harness.acp_log import GenerationDescriptor, ParsedLog, SpanDescriptor
from products.posthog_ai.eval_harness.base import _SandboxedEvalRun
from products.posthog_ai.eval_harness.one_shot import _OneShotEvalRun
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.posthog_ai.eval_harness.scorers.tracing import (
    TracedClients,
    TracedScorer,
    _build_posthog_kwargs,
    _scorer_context,
)
from products.posthog_ai.eval_harness.trace_events import RunMetadata, emit_trace_events, emit_trace_root

NAMESPACES = [(_SandboxedEvalRun.trace_namespace,), (_OneShotEvalRun.trace_namespace,)]
RUN_METADATA: RunMetadata = {"agent_model": "claude-test", "trials": 3, "git_sha": "abc123", "git_dirty": False}


class _CapturingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def capture(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@parameterized.expand(NAMESPACES)
def test_trace_root_carries_the_run_namespace(namespace: str) -> None:
    client = _CapturingClient()

    emit_trace_root(
        cast(Posthog, client),
        trace_id="trace-1",
        experiment_id="exp-1",
        experiment_name="my-suite",
        case_name="case-1",
        namespace=namespace,
        prompt="hello",
        duration=1.0,
        first_timestamp="",
        run_metadata=RUN_METADATA,
    )

    properties = client.calls[0]["properties"]
    assert properties["$ai_experiment_name"] == f"{namespace}/my-suite"


def _trace_root_properties(run_metadata: RunMetadata) -> dict[str, Any]:
    client = _CapturingClient()
    emit_trace_root(
        cast(Posthog, client),
        trace_id="trace-1",
        experiment_id="exp-1",
        experiment_name="my-suite",
        case_name="case-1",
        namespace="ns",
        run_metadata=run_metadata,
        prompt="hello",
        duration=1.0,
        first_timestamp="",
    )
    return client.calls[0]["properties"]


def _parsed_event_properties(event: str) -> Callable[[RunMetadata], dict[str, Any]]:
    def properties(run_metadata: RunMetadata) -> dict[str, Any]:
        client = _CapturingClient()
        parsed = ParsedLog(
            generations=[GenerationDescriptor()],
            spans=[SpanDescriptor(span_id="span-1", span_name="tool")],
        )
        emit_trace_events(
            cast(Posthog, client),
            "trace-1",
            "exp-1",
            "my-suite",
            "case-1",
            parsed,
            namespace="ns",
            run_metadata=run_metadata,
        )
        return next(call["properties"] for call in client.calls if call["event"] == event)

    return properties


class _StubScorer:
    def _name(self) -> str:
        return "stub"


def _scorer_span_properties(run_metadata: RunMetadata) -> dict[str, Any]:
    client = _CapturingClient()
    scorer = TracedScorer(
        cast(Scorer, _StubScorer()),
        cast(TracedClients, None),
        {"experiment_id": "exp-1", "experiment_name": "ns/my-suite", "run_metadata": run_metadata},
        {},
        posthog_client=cast(Posthog, client),
        agent_trace_id_lookup={"case-1": "trace-1"},
    )
    scorer._emit_scorer_span("case-1", Score(name="stub", score=1.0))
    return client.calls[0]["properties"]


def _judge_generation_properties(run_metadata: RunMetadata) -> dict[str, Any]:
    token = _scorer_context.set(
        {
            "trace_id": "trace-1",
            "experiment_id": "exp-1",
            "experiment_name": "ns/my-suite",
            "run_metadata": run_metadata,
        }
    )
    try:
        return _build_posthog_kwargs()["posthog_properties"]
    finally:
        _scorer_context.reset(token)


@parameterized.expand(
    [
        ("trace_root", _trace_root_properties),
        ("agent_generation", _parsed_event_properties("$ai_generation")),
        ("agent_span", _parsed_event_properties("$ai_span")),
        ("scorer_span", _scorer_span_properties),
        ("judge_generation", _judge_generation_properties),
    ]
)
def test_every_event_carries_the_run_metadata(
    _name: str, event_properties: Callable[[RunMetadata], dict[str, Any]]
) -> None:
    properties = event_properties(RUN_METADATA)

    assert {key: properties[key] for key in RUN_METADATA} == RUN_METADATA


def test_the_two_run_kinds_label_themselves_differently() -> None:
    assert _SandboxedEvalRun.trace_namespace != _OneShotEvalRun.trace_namespace


def test_repeated_case_scores_link_to_their_own_trial_traces() -> None:
    class _TrialScorer(Scorer):
        def _name(self) -> str:
            return "stub"

        def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
            return Score(name="stub", score=1.0)

    client = _CapturingClient()
    scorer_traces: dict[tuple[str, str], str] = {}
    scorer = TracedScorer(
        _TrialScorer(),
        cast(TracedClients, None),
        {"experiment_id": "exp-1", "experiment_name": "ns/my-suite", "run_metadata": RUN_METADATA},
        scorer_traces,
        posthog_client=cast(Posthog, client),
        agent_trace_id_lookup={"trial-1": "agent-1", "trial-2": "agent-2"},
    )
    for index in (1, 2):
        trial_id = f"trial-{index}"
        metadata = {"trial_id": trial_id, "trace_id": f"agent-{index}"}
        asyncio.run(scorer.eval_async({}, input={"name": "same-case"}, metadata=metadata))
    assert [call["properties"]["$ai_trace_id"] for call in client.calls] == [
        "agent-1",
        "agent-2",
    ]
    assert len({call["properties"]["$ai_span_id"] for call in client.calls}) == 2
