from collections.abc import Callable

from posthog.schema import (
    EventPropertyFilter,
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricGoal,
    ExperimentMetricMathType,
    ExperimentRatioMetric,
    HogQLPropertyFilter,
    PropertyOperator,
)

from products.ai_observability.backend.facade.contracts import EVALUATION_GRADED_MARKER, EVALUATION_PASSED_MARKER

LLMMetric = ExperimentMeanMetric | ExperimentRatioMetric


def _prompt_filter(prompt_name: str) -> EventPropertyFilter:
    return EventPropertyFilter(
        key="$ai_prompt_name",
        operator=PropertyOperator.EXACT,
        value=prompt_name,
    )


def build_cost_metric(prompt_name: str) -> ExperimentMeanMetric:
    return ExperimentMeanMetric(
        name="Cost",
        goal=ExperimentMetricGoal.DECREASE,
        source=EventsNode(
            event="$ai_generation",
            math=ExperimentMetricMathType.SUM,
            math_property="$ai_total_cost_usd",
            properties=[_prompt_filter(prompt_name)],
        ),
    )


def build_latency_metric(prompt_name: str) -> ExperimentMeanMetric:
    return ExperimentMeanMetric(
        name="Latency",
        goal=ExperimentMetricGoal.DECREASE,
        source=EventsNode(
            event="$ai_generation",
            math=ExperimentMetricMathType.SUM,
            math_property="$ai_latency",
            properties=[_prompt_filter(prompt_name)],
        ),
    )


def build_eval_pass_rate_metric(prompt_name: str) -> ExperimentRatioMetric:
    return ExperimentRatioMetric(
        name="Eval pass rate",
        numerator=EventsNode(
            event="$ai_evaluation",
            properties=[_prompt_filter(prompt_name), HogQLPropertyFilter(key=EVALUATION_PASSED_MARKER)],
        ),
        denominator=EventsNode(
            event="$ai_evaluation",
            properties=[_prompt_filter(prompt_name), HogQLPropertyFilter(key=EVALUATION_GRADED_MARKER)],
        ),
    )


_TEMPLATES: dict[str, Callable[[str], LLMMetric]] = {
    "cost": build_cost_metric,
    "latency": build_latency_metric,
    "eval_pass_rate": build_eval_pass_rate_metric,
}

_TEMPLATE_METADATA: dict[str, dict[str, str]] = {
    "cost": {
        "label": "Cost",
        "description": "Compares LLM cost per user across prompt versions.",
    },
    "latency": {
        "label": "Latency",
        "description": "Compares LLM response time per user across prompt versions.",
    },
    "eval_pass_rate": {
        "label": "Eval pass rate",
        "description": "Compares the share of evaluations that pass across prompt versions.",
    },
}

TEMPLATE_NAMES = tuple(_TEMPLATES)


def build_template(name: str, prompt_name: str) -> LLMMetric:
    if name not in _TEMPLATES:
        raise ValueError(f"Unknown LLM metric template: {name!r}. Known: {sorted(_TEMPLATES)}")
    return _TEMPLATES[name](prompt_name)


def list_templates() -> list[dict[str, str]]:
    return [{"key": name, **_TEMPLATE_METADATA[name]} for name in _TEMPLATES]
