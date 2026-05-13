from typing import TYPE_CHECKING

from posthog.schema import (
    EventPropertyFilter,
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentRatioMetric,
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
            properties=[
                _prompt_filter(prompt_name),
                EventPropertyFilter(
                    key="$ai_evaluation_result",
                    operator=PropertyOperator.EXACT,
                    value=1,
                ),
            ],
        ),
        denominator=EventsNode(
            event="$ai_evaluation",
            properties=[_prompt_filter(prompt_name)],
        ),
    )


_TEMPLATES = {
    "cost": build_cost_metric,
    "latency": build_latency_metric,
    "eval_pass_rate": build_eval_pass_rate_metric,
}

TEMPLATE_NAMES = tuple(_TEMPLATES)


def build_template(name: str, prompt_name: str) -> LLMMetric:
    if name not in _TEMPLATES:
        raise ValueError(f"Unknown LLM metric template: {name!r}. Known: {sorted(_TEMPLATES)}")
    return _TEMPLATES[name](prompt_name)


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
    return service.update_experiment(experiment, {"metrics": next_metrics})
