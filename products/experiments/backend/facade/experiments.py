"""Experiment reads: one experiment as the experiment API shows it, a page of the experiments list, and the reads of
the detail actions of the experiment API. Also the create, the update and the bulk tag change of the experiment API.

A read that the API must refuse, such as an unknown `order`, raises the `ValidationError` of Django REST framework,
with the message the API returns. A read that loads the experiment for a detail action raises `ExperimentNotFound`
when the project has no live experiment with the id.
"""

from collections.abc import Collection, Sequence
from dataclasses import fields
from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import User
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

from .api import create_experiment
from .contracts import (
    CreateExperimentInput,
    ExperimentBasic,
    ExperimentDetail,
    ExperimentFlag,
    ExperimentHandle,
    ExperimentHoldoutView,
    ExperimentListFilters,
    ExperimentRef,
    ExperimentSavedMetricLinkView,
    ExperimentTagChange,
    ExperimentTimeseriesResults,
    ExperimentUpdate,
    ExperimentUpdateTarget,
    ExperimentVelocityStats,
    FlagCleanupTarget,
    ListAccess,
)
from .warehouse_native_access import warehouse_native_connection_id


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


def _to_handle(experiment: Experiment) -> ExperimentHandle:
    return ExperimentHandle(
        id=experiment.id,
        team_id=experiment.team_id,
        created_by_id=experiment.created_by_id,
        feature_flag_id=experiment.feature_flag_id,
        feature_flag_created_by_id=experiment.feature_flag.created_by_id,
        holdout_id=experiment.holdout_id,
        flag_cleanup_task_id=experiment.flag_cleanup_task_id,
        warehouse_native_connection_id=warehouse_native_connection_id(experiment.exposure_criteria),
    )


def _to_ref(experiment: Experiment) -> ExperimentRef:
    return ExperimentRef(id=experiment.id, team_id=experiment.team_id, created_by_id=experiment.created_by_id)


def list_experiment_refs(*, team: Team, filters: ExperimentListFilters) -> list[ExperimentRef]:
    """Every experiment that the experiments list shows for the filters, across all of its pages, in the order of the
    list. Raises the `ValidationError` of Django REST framework for a filter that the list refuses."""
    return [_to_ref(experiment) for experiment in experiments.list_refs(team=team, filters=filters)]


def experiment_refs_among(*, team: Team, experiment_ids: Collection[int]) -> list[ExperimentRef]:
    """The live experiments of the project among `experiment_ids`, archived ones included, newest first."""
    return [_to_ref(experiment) for experiment in experiments.refs_among(team=team, experiment_ids=experiment_ids)]


def change_experiment_tags(
    *,
    team: Team,
    user: User,
    was_impersonated: bool,
    experiment_ids: Sequence[int],
    tag_action: str,
    tags: Sequence[str],
) -> list[ExperimentTagChange]:
    """Add, remove or set tags on the live experiments of the project among `experiment_ids`, in the order of
    `experiment_ids`.

    `tag_action` is `add`, `remove` or `set`. Each experiment whose tags change gets an activity log entry by `user`.
    Tags that no other object uses any more are deleted.
    """
    changes = experiments.change_tags(
        team=team,
        user=user,
        was_impersonated=was_impersonated,
        experiment_ids=experiment_ids,
        tag_action=tag_action,
        tags=tags,
    )
    return [ExperimentTagChange(id=change["id"], tags=tuple(change["tags"])) for change in changes]


def get_velocity_stats(*, team: Team) -> ExperimentVelocityStats:
    return ExperimentService(team=team, user=None).get_velocity_stats()


def get_experiment_handle(*, team: Team, experiment_id: int) -> ExperimentHandle | None:
    """The live experiment of the project with the id, or None when the project has no such experiment. One query."""
    experiment = experiments.get_handle(team=team, experiment_id=experiment_id)
    return None if experiment is None else _to_handle(experiment)


def linked_saved_metric_ids(*, experiment_id: int) -> list[int]:
    """The ids of the shared metrics that the experiment uses."""
    return experiments.linked_saved_metric_ids(experiment_id)


def get_flag_cleanup_target(*, team: Team, user: User, experiment_id: int) -> FlagCleanupTarget:
    experiment = experiments.get_for_action(team=team, experiment_id=experiment_id)
    target = ExperimentService(team=team, user=user).get_cleanup_repository_target(experiment)
    return FlagCleanupTarget(
        repository=target["repository"], source=target["source"], candidates=tuple(target["candidates"])
    )


def get_timeseries_results(
    *, team: Team, user: User, experiment_id: int, metric_uuid: str
) -> ExperimentTimeseriesResults:
    """Raises the `ValidationError` of Django REST framework for an experiment that has not started."""
    experiment = experiments.get_for_action(team=team, experiment_id=experiment_id)
    return ExperimentTimeseriesResults(
        **ExperimentService(team=team, user=user).get_timeseries_results(experiment, metric_uuid=metric_uuid)
    )


def assert_user_may_run_warehouse_native_sources(*, team: Team, user: User, experiment_id: int) -> None:
    """Raises the `ValidationError` of Django REST framework when `user` may not run the warehouse-native sources of
    the experiment, which a recalculation sends to the customer's warehouse with no user to check."""
    experiment = experiments.get_for_action(team=team, experiment_id=experiment_id)
    ExperimentService(team=team, user=user).assert_user_may_run_warehouse_native_sources(experiment)


def add_experiment(*, team: Team, user: User, experiment: CreateExperimentInput, tags: list[str] | None) -> int:
    """The id of a new experiment with the configuration of `experiment` and the tags, or no tags when `tags` is None.

    Raises `ExperimentValidationError` when the project has no holdout with `experiment.holdout_id`. The
    `ValidationError` of Django REST framework and the approval exceptions of the flag write pass through unchanged.
    """
    created = create_experiment(team=team, user=user, input_dto=experiment)
    if tags is not None:
        experiments.replace_tags(team=team, experiment_id=created.id, tags=tags)
    return created.id


def get_experiment_update_target(
    *, team: Team, experiment_id: int, include_deleted: bool
) -> ExperimentUpdateTarget | None:
    """The experiment of the project with the id, or None when the project has no such experiment. A deleted
    experiment counts only with `include_deleted`. One query."""
    experiment = experiments.get_update_target(team=team, experiment_id=experiment_id, include_deleted=include_deleted)
    if experiment is None:
        return None
    return ExperimentUpdateTarget(
        id=experiment.id,
        team_id=experiment.team_id,
        created_by_id=experiment.created_by_id,
        is_draft=experiment.is_draft,
        feature_flag_active=experiment.feature_flag.active,
        parameters=experiments.projected_parameters(experiment),
    )


def edit_experiment(
    *,
    team: Team,
    user: User,
    experiment_id: int,
    update: ExperimentUpdate,
    include_deleted: bool,
    serializer_context: dict[str, Any],
) -> None:
    """Write the fields of `update` onto the experiment of the project with the id.

    `serializer_context["request"]` is the HTTP request, which a write of the experiment's flag needs: an approval
    policy on the flag turns the write into a change request. Raises `ExperimentNotFound` when the project has no
    such experiment, where a deleted experiment counts only with `include_deleted`, and `ExperimentVersionConflict`
    when a stale update cannot merge. The approval exceptions and the `ValidationError` of Django REST framework pass
    through unchanged.
    """
    experiments.apply_update(
        team=team,
        user=user,
        experiment_id=experiment_id,
        update=update,
        include_deleted=include_deleted,
        serializer_context=serializer_context,
    )
