from collections.abc import Callable
from typing import TYPE_CHECKING

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

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment

if TYPE_CHECKING:
    from posthog.models import User

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
    # Use explicit JSON extraction rather than `properties.X = true`. The latter goes through
    # HogQL property type inference, which casts the property to Float64 if any event in the
    # table has stored this key as a number — silently dropping JSON-boolean events. The
    # JSONExtract* functions bypass the inference and read the JSON value directly.
    # The applicable guard excludes N/A evaluations (applicable=false) but keeps events
    # where the property isn't set at all (JSONExtractRaw returns '' for missing keys).
    applicable_filter = HogQLPropertyFilter(key="JSONExtractRaw(properties, '$ai_evaluation_applicable') != 'false'")
    return ExperimentRatioMetric(
        name="Eval pass rate",
        numerator=EventsNode(
            event="$ai_evaluation",
            properties=[
                _prompt_filter(prompt_name),
                HogQLPropertyFilter(key="JSONExtractBool(properties, '$ai_evaluation_result')"),
                applicable_filter,
            ],
        ),
        denominator=EventsNode(
            event="$ai_evaluation",
            properties=[
                _prompt_filter(prompt_name),
                applicable_filter,
            ],
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


def apply_metric_to_experiment(
    experiment: Experiment,
    template_name: str,
    prompt_name: str,
    *,
    user: "User",
    replace: bool = False,
) -> Experiment:
    new_metric = build_template(template_name, prompt_name).model_dump(exclude_none=True)

    if replace:
        next_metrics = [new_metric]
    else:
        next_metrics = [*(experiment.metrics or []), new_metric]

    service = ExperimentService(team=experiment.team, user=user)
    # The templates hardcode known LLM event names, so the typo-guard validation in
    # update_experiment adds no value but rejects the common case of attaching a
    # metric before any matching event has been ingested.
    return service.update_experiment(experiment, {"metrics": next_metrics}, allow_unknown_events=True)
