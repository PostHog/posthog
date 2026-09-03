from __future__ import annotations

from typing import Any, cast

from parameterized import parameterized
from posthoganalytics import Posthog

from products.posthog_ai.eval_harness.base import _SandboxedEvalRun
from products.posthog_ai.eval_harness.engines.types import CaseResult
from products.posthog_ai.eval_harness.one_shot import _OneShotEvalRun
from products.posthog_ai.eval_harness.trace_events import emit_evaluation_events, emit_trace_root

NAMESPACES = [(_SandboxedEvalRun.trace_namespace,), (_OneShotEvalRun.trace_namespace,)]


class _CapturingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def capture(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@parameterized.expand(NAMESPACES)
def test_evaluation_events_carry_the_run_namespace(namespace: str) -> None:
    client = _CapturingClient()
    result = CaseResult(input={"name": "case-1"}, output={}, scores={"a_scorer": 1.0})

    emit_evaluation_events(cast(Posthog, client), "exp-1", "my-suite", [result], namespace=namespace)

    properties = client.calls[0]["properties"]
    assert properties["$ai_experiment_name"] == f"{namespace}/my-suite"
    assert properties["$ai_eval_source"] == namespace


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
    )

    properties = client.calls[0]["properties"]
    assert properties["$ai_experiment_name"] == f"{namespace}/my-suite"


def test_the_two_run_kinds_label_themselves_differently() -> None:
    assert _SandboxedEvalRun.trace_namespace != _OneShotEvalRun.trace_namespace
