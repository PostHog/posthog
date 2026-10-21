from collections.abc import Callable
from typing import Any, Literal

from django.db import transaction
from django.db.models import QuerySet

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
from products.ai_observability.backend.facade.contracts import EvaluationPassFilters
from products.experiments.backend.metric_calculation.config import ExperimentCalculationSettings, stamp_calculation_keys
from products.experiments.backend.models.experiment import Experiment

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
    return _eval_pass_rate_metric(prompt_name, get_evaluation_pass_filters(team_id))


def _eval_pass_rate_metric(prompt_name: str, filters: EvaluationPassFilters) -> ExperimentRatioMetric:
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


_LEGACY_RESULT = "JSONExtractBool(properties, '$ai_evaluation_result')"
_LEGACY_APPLICABLE = "JSONExtractRaw(properties, '$ai_evaluation_applicable') != 'false'"
_LEGACY_BOOLEAN = "JSONExtractString(properties, '$ai_evaluation_result_type') IN ('', 'boolean')"


def eval_pass_rate_sources(metric: LLMMetric) -> dict[str, Any]:
    """The numerator and denominator the template wrote, kept in prompt_metadata so a rebuild can tell them apart
    from sources the experiment's owner edited."""
    return metric.model_dump(mode="json", exclude_none=True, include={"numerator", "denominator"})


def _legacy_eval_pass_rate_sources(prompt_name: str) -> list[dict[str, Any]]:
    # The two shapes the template wrote before it recorded its sources in prompt_metadata.
    prompt_filter = _prompt_filter(prompt_name).model_dump(mode="json", exclude_none=True)

    def source(*keys: str) -> dict[str, Any]:
        hogql = [{"key": key, "type": "hogql"} for key in keys]
        return {"kind": "EventsNode", "event": "$ai_evaluation", "properties": [prompt_filter, *hogql]}

    return [
        {"numerator": source(_LEGACY_RESULT, _LEGACY_APPLICABLE), "denominator": source(_LEGACY_APPLICABLE)},
        {
            "numerator": source(_LEGACY_RESULT, _LEGACY_APPLICABLE, _LEGACY_BOOLEAN),
            "denominator": source(_LEGACY_APPLICABLE, _LEGACY_BOOLEAN),
        },
    ]


def _eval_pass_rate_experiments() -> QuerySet[Experiment]:
    # An ended experiment keeps the result it concluded with.
    return Experiment.objects.filter(
        parameters__prompt_metadata__templates__contains=["eval_pass_rate"], end_date__isnull=True
    ).exclude(deleted=True)


def rebuild_eval_pass_rate_metrics(team_id: int, *, dry_run: bool = False) -> int:
    """Rebuild the eval pass rate metrics of the team's prompt experiments from the current evaluation output
    configs. Only a metric whose sources are still exactly what the template wrote is rebuilt. Returns the number of
    experiments that changed."""
    experiment_ids = list(_eval_pass_rate_experiments().filter(team_id=team_id).values_list("id", flat=True))
    changed = 0
    for experiment_id in experiment_ids:
        # Locked and versioned like ExperimentService updates, so a concurrent edit is not lost and an older tab
        # gets a version conflict instead of writing the previous filters back. Eligibility and the evaluation
        # rules are read under the lock, so an experiment that ended meanwhile is skipped and a delayed rebuild
        # cannot write older rules over a newer one.
        with transaction.atomic():
            experiment = (
                _eval_pass_rate_experiments()
                .select_for_update(of=("self",))
                .select_related("team")
                .filter(team_id=team_id, pk=experiment_id)
                .first()
            )
            if experiment is None:
                continue
            updates = _rebuilt_eval_pass_rate_fields(experiment, get_evaluation_pass_filters(team_id))
            if updates is None:
                continue
            changed += 1
            if dry_run:
                continue
            for field, value in updates.items():
                setattr(experiment, field, value)
            experiment.version = (experiment.version or 0) + 1
            experiment.save(update_fields=[*updates, "version", "updated_at"])
    return changed


def _rebuilt_eval_pass_rate_fields(experiment: Experiment, filters: EvaluationPassFilters) -> dict[str, Any] | None:
    prompt_metadata = (experiment.parameters or {}).get("prompt_metadata") or {}
    prompt_name = prompt_metadata.get("name")
    if not isinstance(prompt_name, str):
        return None
    sources = eval_pass_rate_sources(_eval_pass_rate_metric(prompt_name, filters))
    written = [*_legacy_eval_pass_rate_sources(prompt_name), prompt_metadata.get("eval_pass_rate_sources")]
    updates: dict[str, Any] = {}
    settings: ExperimentCalculationSettings | None = None
    sections: tuple[tuple[str, Literal["primary", "secondary"]], ...] = (
        ("metrics", "primary"),
        ("metrics_secondary", "secondary"),
    )
    for field, role in sections:
        metrics = getattr(experiment, field) or []
        rebuilt = []
        for metric in metrics:
            current = {side: metric.get(side) for side in ("numerator", "denominator")}
            if metric.get("metric_type") == "ratio" and current in written and current != sources:
                settings = settings or ExperimentCalculationSettings.from_experiment(experiment)
                metric = stamp_calculation_keys([{**metric, **sources}], role, settings)[0]
            rebuilt.append(metric)
        if rebuilt != metrics:
            updates[field] = rebuilt
    if not updates:
        return None
    updates["parameters"] = {
        **(experiment.parameters or {}),
        "prompt_metadata": {**prompt_metadata, "eval_pass_rate_sources": sources},
    }
    return updates
