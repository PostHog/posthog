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

from products.ai_observability.backend.facade.api import get_evaluation_pass_filters

LLMMetric = ExperimentMeanMetric | ExperimentRatioMetric


def _prompt_filter(prompt_name: str) -> EventPropertyFilter:
    return EventPropertyFilter(
        key="$ai_prompt_name",
        operator=PropertyOperator.EXACT,
        value=prompt_name,
    )


def build_cost_metric(prompt_name: str, team_id: int) -> ExperimentMeanMetric:
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


def build_latency_metric(prompt_name: str, team_id: int) -> ExperimentMeanMetric:
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


def build_eval_pass_rate_metric(prompt_name: str, team_id: int) -> ExperimentRatioMetric:
    # Graded by each evaluation's output config, the same rules the evaluation UI and reports apply.
    filters = get_evaluation_pass_filters(team_id)
    return ExperimentRatioMetric(
        name="Eval pass rate",
        numerator=EventsNode(
            event="$ai_evaluation",
            properties=[_prompt_filter(prompt_name), HogQLPropertyFilter(key=filters.passed)],
        ),
        denominator=EventsNode(
            event="$ai_evaluation",
            properties=[_prompt_filter(prompt_name), HogQLPropertyFilter(key=filters.graded)],
        ),
    )


_TEMPLATES: dict[str, Callable[[str, int], LLMMetric]] = {
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


def build_template(name: str, prompt_name: str, team_id: int) -> LLMMetric:
    if name not in _TEMPLATES:
        raise ValueError(f"Unknown LLM metric template: {name!r}. Known: {sorted(_TEMPLATES)}")
    return _TEMPLATES[name](prompt_name, team_id)


def list_templates() -> list[dict[str, str]]:
    return [{"key": name, **_TEMPLATE_METADATA[name]} for name in _TEMPLATES]
