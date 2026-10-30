"""Experiments reads for the dashboard experiment widgets.

Each function takes the viewer's access control, or None outside request context, and leaves out the experiments
that the viewer cannot see, the same as the experiments API.
"""

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend import dashboard_widgets
from products.experiments.backend.experiment_creator import to_experiment_creator
from products.experiments.backend.facade.contracts import (
    ExperimentListWidgetPage,
    ExperimentListWidgetRow,
    ExperimentResultsWidget,
    ExperimentResultsWidgetMetrics,
)
from products.experiments.backend.models.experiment import Experiment

__all__ = [
    "experiment_results_widget",
    "experiments_list_widget_page",
    "has_accessible_experiments",
]


def _list_widget_row(experiment: Experiment) -> ExperimentListWidgetRow:
    return ExperimentListWidgetRow(
        id=experiment.id,
        name=experiment.name,
        status=experiment.status_label,
        conclusion=experiment.conclusion,
        start_date=experiment.start_date,
        end_date=experiment.end_date,
        created_at=experiment.created_at,
        feature_flag_key=experiment.feature_flag.key,
        created_by=to_experiment_creator(experiment.created_by) if experiment.created_by else None,
    )


def experiments_list_widget_page(
    team: Team,
    access: UserAccessControl | None,
    *,
    status: str,
    order_by: str,
    descending: bool,
    created_by_id: int | None,
    limit: int,
) -> ExperimentListWidgetPage:
    """The first `limit` experiments that the experiments list shows for these filters and this order.

    `status` and `order_by` take the values of the experiments list API.
    """
    queryset = dashboard_widgets.list_widget_queryset(
        team,
        access,
        status=status,
        order=f"{'-' if descending else ''}{order_by}",
        created_by_id=created_by_id,
    )
    experiments = list(queryset[: limit + 1])
    return ExperimentListWidgetPage(
        rows=tuple(_list_widget_row(experiment) for experiment in experiments[:limit]),
        has_more=len(experiments) > limit,
    )


def has_accessible_experiments(team: Team, access: UserAccessControl | None) -> bool:
    """True when the team has an experiment that is not deleted and that the viewer can see."""
    return dashboard_widgets.has_accessible_experiments(team, access)


def experiment_results_widget(
    team: Team, access: UserAccessControl | None, *, experiment_id: int, max_metrics_per_section: int
) -> ExperimentResultsWidget | None:
    """The experiment with the results of its first `max_metrics_per_section` primary and secondary metrics.

    Each metric runs an experiment query, from the cache when it is recent. None when the experiment does not exist,
    is deleted, belongs to another team, or the viewer cannot see it.
    """
    experiment = dashboard_widgets.accessible_experiment(team, access, experiment_id)
    if experiment is None:
        return None

    metrics = None
    if experiment.start_date is not None:
        primary_metric_dicts, secondary_metric_dicts = dashboard_widgets.collect_metric_dicts(experiment)
        with tags_context(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.pk):
            primary = tuple(
                dashboard_widgets.compute_metric(team, experiment, metric_dict, index)
                for index, metric_dict in enumerate(primary_metric_dicts[:max_metrics_per_section])
            )
            secondary = tuple(
                dashboard_widgets.compute_metric(team, experiment, metric_dict, index)
                for index, metric_dict in enumerate(secondary_metric_dicts[:max_metrics_per_section])
            )
        metrics = ExperimentResultsWidgetMetrics(
            primary=primary,
            secondary=secondary,
            primary_total=len(primary_metric_dicts),
            secondary_total=len(secondary_metric_dicts),
        )

    return ExperimentResultsWidget(
        id=experiment.id,
        name=experiment.name,
        status=experiment.status_label,
        start_date=experiment.start_date,
        end_date=experiment.end_date,
        feature_flag_key=experiment.feature_flag.key,
        metrics=metrics,
    )
