"""Experiment reads: one experiment as the experiment API shows it, and a page of the experiments list.

A read that the API must refuse, such as an unknown `order`, raises the `ValidationError` of Django REST framework,
with the message the API returns.
"""

from dataclasses import fields
from typing import Any

from posthog.models.team.team import Team
from posthog.paging import Page, PageRequest

from products.experiments.backend.experiment_creator import to_experiment_creator
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.logic import experiments
from products.experiments.backend.metric_resolution import (
    METRIC_BUILDERS,
    apply_saved_metric_overrides,
    saved_metric_links,
)
from products.experiments.backend.metric_utils import refresh_action_names_in_metric
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentToSavedMetric,
    experiment_has_legacy_metrics,
)

from .contracts import (
    ExperimentBasic,
    ExperimentDetail,
    ExperimentFlag,
    ExperimentHoldoutView,
    ExperimentListFilters,
    ExperimentSavedMetricLinkView,
    ListAccess,
)


def _to_experiment_flag(experiment: Experiment) -> ExperimentFlag:
    flag = experiment.feature_flag
    return ExperimentFlag(
        id=flag.id,
        team_id=flag.team_id,
        name=flag.name,
        key=flag.key,
        filters=flag.filters,
        deleted=flag.deleted,
        active=flag.active,
        ensure_experience_continuity=flag.ensure_experience_continuity,
        version=flag.version,
        evaluation_runtime=flag.evaluation_runtime,
        bucketing_identifier=flag.bucketing_identifier,
        evaluation_contexts=tuple(context.evaluation_context.name for context in flag.flag_evaluation_contexts.all()),
    )


def _to_holdout(experiment: Experiment) -> ExperimentHoldoutView | None:
    holdout = experiment.holdout
    if holdout is None:
        return None
    return ExperimentHoldoutView(
        id=holdout.id,
        name=holdout.name,
        description=holdout.description,
        filters=holdout.filters,
        created_by=to_experiment_creator(holdout.created_by) if holdout.created_by else None,
        created_at=holdout.created_at,
        updated_at=holdout.updated_at,
    )


def _to_experiment_basic(experiment: Experiment, *, is_legacy: bool) -> ExperimentBasic:
    return ExperimentBasic(
        id=experiment.id,
        team_id=experiment.team_id,
        name=experiment.name,
        description=experiment.description,
        start_date=experiment.start_date,
        end_date=experiment.end_date,
        feature_flag_key=experiment.get_feature_flag_key(),
        feature_flag=_to_experiment_flag(experiment),
        holdout=_to_holdout(experiment),
        exposure_cohort_id=experiment.exposure_cohort_id,
        parameters=experiments.projected_parameters(experiment),
        running_time_calculation=experiment.running_time_calculation,
        excluded_variants=None if experiment.excluded_variants is None else tuple(experiment.excluded_variants),
        archived=experiment.archived,
        deleted=experiment.deleted,
        created_by_id=experiment.created_by_id,
        created_by=to_experiment_creator(experiment.created_by) if experiment.created_by else None,
        created_at=experiment.created_at,
        updated_at=experiment.updated_at,
        type=experiment.type,
        conclusion=experiment.conclusion,
        conclusion_comment=experiment.conclusion_comment,
        status=experiment.status_label,
        is_legacy=is_legacy,
        tags=tuple(tagged_item.tag.name for tagged_item in getattr(experiment, "prefetched_tags", ())),
    )


def _with_current_action_names(metrics: list[dict[str, Any]] | None, team: Team) -> list[dict[str, Any]] | None:
    if metrics is None:
        return None
    return [refresh_action_names_in_metric(metric, team) or metric for metric in metrics]


def _to_saved_metric_link(
    link: ExperimentToSavedMetric, team: Team, calculation_key: str | None
) -> ExperimentSavedMetricLinkView:
    query = refresh_action_names_in_metric(link.saved_metric.query, team)
    effective_query = None
    if query:
        if calculation_key is not None:
            # The frontend reads the timeseries rows by this fingerprint. The key hashes the stored query, so it
            # does not depend on the refreshed action names.
            query = {**query, "fingerprint": calculation_key}
        if query.get("kind") == "ExperimentMetric" and query.get("metric_type") in METRIC_BUILDERS:
            effective_query = apply_saved_metric_overrides(query, link.metadata)
    return ExperimentSavedMetricLinkView(
        id=link.id,
        experiment_id=link.experiment_id,
        saved_metric_id=link.saved_metric_id,
        name=link.saved_metric.name,
        metadata=link.metadata,
        query=query,
        effective_query=effective_query,
        created_at=link.created_at,
    )


def _to_saved_metric_links(experiment: Experiment) -> tuple[ExperimentSavedMetricLinkView, ...]:
    links = saved_metric_links(experiment)
    # The calculation keys read the team's experiment settings, so an experiment without shared metrics skips them.
    calculation_keys = ExperimentService.saved_metric_calculation_keys(experiment) if links else {}
    return tuple(_to_saved_metric_link(link, experiment.team, calculation_keys.get(link.id)) for link in links)


def _to_experiment_detail(experiment: Experiment) -> ExperimentDetail:
    basic = _to_experiment_basic(experiment, is_legacy=experiment_has_legacy_metrics(experiment))
    return ExperimentDetail(
        **{field.name: getattr(basic, field.name) for field in fields(basic)},
        feature_flag_rule_id=experiment.feature_flag_rule_id,
        holdout_id=experiment.holdout_id,
        filters=experiment.filters,
        secondary_metrics=experiment.secondary_metrics,
        metrics=_with_current_action_names(experiment.metrics, experiment.team),
        metrics_secondary=_with_current_action_names(experiment.metrics_secondary, experiment.team),
        saved_metrics=_to_saved_metric_links(experiment),
        exposure_criteria=experiment.exposure_criteria,
        stats_config=experiment.stats_config,
        scheduling_config=experiment.scheduling_config,
        primary_metrics_ordered_uuids=experiment.primary_metrics_ordered_uuids,
        secondary_metrics_ordered_uuids=experiment.secondary_metrics_ordered_uuids,
        only_count_matured_users=experiment.only_count_matured_users,
        version=experiment.version,
        flag_cleanup_task_id=experiment.flag_cleanup_task_id,
        repository=experiment.repository,
        can_freeze_exposure=experiment.can_freeze_exposure,
        resolved_exposure_event=experiments.resolved_exposure_event(experiment),
    )


def get_experiment(*, team: Team, experiment_id: int, include_deleted: bool = False) -> ExperimentDetail | None:
    """The experiment of the project with the id, or None when the project has no such experiment.

    A deleted experiment counts only with `include_deleted`.
    """
    experiment = experiments.get_detail(team=team, experiment_id=experiment_id, include_deleted=include_deleted)
    return None if experiment is None else _to_experiment_detail(experiment)


def list_experiments(
    *, team: Team, filters: ExperimentListFilters, access: ListAccess | None, page: PageRequest
) -> Page[ExperimentBasic]:
    """One page of the project's experiments that are not deleted and pass the filters and `access`, newest first
    unless `filters.order` names another order."""
    return experiments.list_page(team=team, filters=filters, access=access, page=page).map(
        # The list computes is_legacy in SQL, because it does not read the metric columns.
        lambda experiment: _to_experiment_basic(experiment, is_legacy=experiment.is_legacy_annotation)  # type: ignore[attr-defined]
    )
