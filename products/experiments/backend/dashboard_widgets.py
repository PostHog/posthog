"""The experiments reads behind the dashboard experiment widgets. Dashboards calls them through
`facade/dashboard_widgets.py`."""

import logging
from typing import Any

from django.db.models import QuerySet

from posthog.schema import ExperimentQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.facade.contracts import ExperimentResultsWidgetMetric, ExperimentResultsWidgetMetrics
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.metric_resolution import METRIC_BUILDERS, apply_saved_metric_overrides
from products.experiments.backend.models.experiment import Experiment, metric_display_rank

logger = logging.getLogger(__name__)


def _visible_to(access: UserAccessControl | None, queryset: QuerySet[Experiment]) -> QuerySet[Experiment]:
    return queryset if access is None else access.filter_queryset_by_access_level(queryset)


def list_widget_queryset(
    team: Team,
    access: UserAccessControl | None,
    *,
    status: str,
    order_by: str,
    descending: bool,
    created_by_id: int | None,
) -> QuerySet[Experiment]:
    # ExperimentService transitively imports the dashboard API, which loads the widget registry, which imports the
    # dashboard widgets that import this module. Deferring the import breaks that cycle.
    from products.experiments.backend.experiment_service import ExperimentService  # noqa: PLC0415

    order_prefix = "-" if descending else ""
    query_params: dict[str, Any] = {"status": status, "order": f"{order_prefix}{order_by}"}
    if created_by_id is not None:
        query_params["created_by_id"] = created_by_id

    base_queryset = Experiment.objects.filter(team=team).select_related("created_by", "feature_flag")
    service = ExperimentService(team=team, user=access.user if access is not None else None)
    queryset = service.filter_experiments_queryset(base_queryset, action="list", query_params=query_params)
    # Honor object-level experiment access controls, matching the REST list endpoint.
    return _visible_to(access, queryset)


def has_accessible_experiments(team: Team, access: UserAccessControl | None) -> bool:
    return _visible_to(access, Experiment.objects.filter(team=team, deleted=False)).exists()


def accessible_experiment(team: Team, access: UserAccessControl | None, experiment_id: int) -> Experiment | None:
    # Honor object-level experiment access controls, matching the REST endpoint. A user denied
    # access to a specific experiment must not see it (or its results) through the widget.
    queryset = Experiment.objects.filter(id=experiment_id, team=team, deleted=False).select_related("feature_flag")
    return _visible_to(access, queryset).first()


def _sort_by_ordered_uuids(metric_dicts: list[dict[str, Any]], ordered_uuids: list[str] | None) -> None:
    if not ordered_uuids:
        return
    rank = metric_display_rank(ordered_uuids)
    metric_dicts.sort(key=lambda metric: rank(metric.get("uuid", "")))


@frozen
class _MetricDicts:
    primary: list[dict[str, Any]]
    secondary: list[dict[str, Any]]


def _collect_metric_dicts(experiment: Experiment) -> _MetricDicts:
    """Inline metrics plus saved metrics, partitioned into primary and secondary in display order when known.

    The saved-metric link set is read once and split here so a widget render issues a single query for it.
    """
    primary: list[dict[str, Any]] = [dict(metric) for metric in (experiment.metrics or [])]
    secondary: list[dict[str, Any]] = [dict(metric) for metric in (experiment.metrics_secondary or [])]

    for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
        saved_query = link.saved_metric.query
        if not saved_query:
            continue
        metric_dict = {
            **apply_saved_metric_overrides(saved_query, link.metadata),
            "name": saved_query.get("name") or link.saved_metric.name,
        }
        # Links default to primary when untyped; an unrecognized type belongs to neither section.
        role = (link.metadata or {}).get("type", "primary")
        if role == "secondary":
            secondary.append(metric_dict)
        elif role == "primary":
            primary.append(metric_dict)

    _sort_by_ordered_uuids(primary, experiment.primary_metrics_ordered_uuids)
    _sort_by_ordered_uuids(secondary, experiment.secondary_metrics_ordered_uuids)

    return _MetricDicts(primary=primary, secondary=secondary)


def _compute_metric(
    team: Team, experiment: Experiment, metric_dict: dict[str, Any], index: int
) -> ExperimentResultsWidgetMetric:
    uuid = metric_dict.get("uuid")
    name = metric_dict.get("name") or f"Metric {index + 1}"

    metric_builder = METRIC_BUILDERS.get(metric_dict.get("metric_type", ""))
    if metric_dict.get("kind") != "ExperimentMetric" or metric_builder is None:
        return ExperimentResultsWidgetMetric(
            uuid=uuid, name=name, metric=None, result=None, error="Legacy metrics are not supported in this widget."
        )

    try:
        metric = metric_builder.model_validate(metric_dict)
        runner = ExperimentQueryRunner(
            query=ExperimentQuery(experiment_id=experiment.id, metric=metric),
            team=team,
        )
        response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        result_dict = response.model_dump(mode="json")
        # Strip per-variant session payloads and debug SQL — the widget only renders the scorecard.
        for key in ("clickhouse_sql", "hogql", "insight", "query_status"):
            result_dict.pop(key, None)
        return ExperimentResultsWidgetMetric(
            uuid=uuid, name=name, metric=metric.model_dump(mode="json"), result=result_dict, error=None
        )
    except Exception:
        logger.exception(
            "experiment_results_widget_metric_failed",
            extra={"experiment_id": experiment.id, "metric_uuid": uuid},
        )
        return ExperimentResultsWidgetMetric(
            uuid=uuid, name=name, metric=None, result=None, error="Could not compute results for this metric."
        )


def compute_metrics(
    team: Team, experiment: Experiment, *, max_metrics_per_section: int
) -> ExperimentResultsWidgetMetrics:
    metric_dicts = _collect_metric_dicts(experiment)
    with tags_context(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.pk):
        primary = tuple(
            _compute_metric(team, experiment, metric_dict, index)
            for index, metric_dict in enumerate(metric_dicts.primary[:max_metrics_per_section])
        )
        secondary = tuple(
            _compute_metric(team, experiment, metric_dict, index)
            for index, metric_dict in enumerate(metric_dicts.secondary[:max_metrics_per_section])
        )
    return ExperimentResultsWidgetMetrics(
        primary=primary,
        secondary=secondary,
        primary_total=len(metric_dicts.primary),
        secondary_total=len(metric_dicts.secondary),
    )
