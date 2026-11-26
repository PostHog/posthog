"""The writes of the detail actions of the experiment API on one experiment: its lifecycle, its copies, its exposure
cohort and the backfill of a metric's daily results.

`request_context["request"]` is the HTTP request, which the feature flag writes need: an approval policy on the flag
turns the write into a change request. The approval exceptions and the `ValidationError` of Django REST framework pass
through unchanged. Each function raises `ExperimentNotFound` when the project has no live experiment with the id.
"""

from collections.abc import Mapping
from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import User

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.logic import experiments
from products.experiments.backend.models.experiment import Experiment

from .contracts import ExperimentRef, ExposureCohortCreated, TimeseriesRecalculationRequest


def _to_ref(experiment: Experiment) -> ExperimentRef:
    return ExperimentRef(id=experiment.id, team_id=experiment.team_id, created_by_id=experiment.created_by_id)


def _load(team: Team, experiment_id: int) -> Experiment:
    return experiments.get_for_action(team=team, experiment_id=experiment_id)


def launch_experiment(
    *, team: Team, user: User, experiment_id: int, request_context: Mapping[str, Any]
) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(service.launch_experiment(_load(team, experiment_id), request=request_context["request"]))


def archive_experiment(
    *,
    team: Team,
    user: User,
    experiment_id: int,
    disable_feature_flag: bool,
    can_write_feature_flag: bool,
    request_context: Mapping[str, Any],
) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(
        service.archive_experiment(
            _load(team, experiment_id),
            disable_feature_flag=disable_feature_flag,
            can_write_feature_flag=can_write_feature_flag,
            request=request_context["request"],
        )
    )


def unarchive_experiment(
    *, team: Team, user: User, experiment_id: int, can_write_feature_flag: bool, request_context: Mapping[str, Any]
) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(
        service.unarchive_experiment(
            _load(team, experiment_id),
            can_write_feature_flag=can_write_feature_flag,
            request=request_context["request"],
        )
    )


def end_experiment(
    *,
    team: Team,
    user: User,
    experiment_id: int,
    conclusion: str | None,
    conclusion_comment: str | None,
    open_cleanup_pr: bool,
    repository: str | None,
    set_repository_as_team_default: bool,
    request_context: Mapping[str, Any],
) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(
        service.end_experiment(
            _load(team, experiment_id),
            conclusion=conclusion,
            conclusion_comment=conclusion_comment,
            open_cleanup_pr=open_cleanup_pr,
            repository=repository,
            set_repository_as_team_default=set_repository_as_team_default,
            request=request_context["request"],
        )
    )


def ship_variant(
    *,
    team: Team,
    user: User,
    experiment_id: int,
    variant_key: str,
    release_to_everyone: bool,
    conclusion: str | None,
    conclusion_comment: str | None,
    open_cleanup_pr: bool,
    repository: str | None,
    set_repository_as_team_default: bool,
    request_context: Mapping[str, Any],
) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(
        service.ship_variant(
            _load(team, experiment_id),
            variant_key=variant_key,
            release_to_everyone=release_to_everyone,
            conclusion=conclusion,
            conclusion_comment=conclusion_comment,
            open_cleanup_pr=open_cleanup_pr,
            repository=repository,
            set_repository_as_team_default=set_repository_as_team_default,
            request=request_context["request"],
        )
    )


def pause_experiment(
    *, team: Team, user: User, experiment_id: int, request_context: Mapping[str, Any]
) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(service.pause_experiment(_load(team, experiment_id), request=request_context["request"]))


def resume_experiment(
    *, team: Team, user: User, experiment_id: int, request_context: Mapping[str, Any]
) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(service.resume_experiment(_load(team, experiment_id), request=request_context["request"]))


def freeze_exposure(*, team: Team, user: User, experiment_id: int, request_context: Mapping[str, Any]) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(service.freeze_exposure(_load(team, experiment_id), request=request_context["request"]))


def unfreeze_exposure(
    *, team: Team, user: User, experiment_id: int, request_context: Mapping[str, Any]
) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(service.unfreeze_exposure(_load(team, experiment_id), request=request_context["request"]))


def reset_experiment(
    *, team: Team, user: User, experiment_id: int, request_context: Mapping[str, Any]
) -> ExperimentRef:
    service = ExperimentService(team=team, user=user)
    return _to_ref(service.reset_experiment(_load(team, experiment_id), request=request_context["request"]))


def duplicate_experiment(
    *,
    team: Team,
    user: User,
    experiment_id: int,
    feature_flag_key: str | None,
    name: str | None,
    serializer_context: dict[str, Any],
) -> ExperimentRef:
    """A new draft with the configuration of the experiment."""
    service = ExperimentService(team=team, user=user)
    return _to_ref(
        service.duplicate_experiment(
            _load(team, experiment_id),
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context=serializer_context,
        )
    )


def copy_experiment_to_project(
    *,
    team: Team,
    user: User,
    experiment_id: int,
    target_team: Team,
    feature_flag_key: str | None,
    name: str | None,
    serializer_context: dict[str, Any],
) -> ExperimentRef:
    """A new draft in `target_team` with the configuration of the experiment. The caller checks that the user may
    create experiments in `target_team`."""
    service = ExperimentService(team=team, user=user)
    return _to_ref(
        service.copy_experiment_to_project(
            _load(team, experiment_id),
            target_team,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context=serializer_context,
        )
    )


def create_exposure_cohort(
    *, team: Team, user: User, experiment_id: int, serializer_context: dict[str, Any]
) -> ExposureCohortCreated:
    """A cohort of the people exposed to the experiment. `serializer_context` holds the `request` and the `team`
    that the cohort API renders the cohort with."""
    cohort = experiments.create_exposure_cohort(
        _load(team, experiment_id), team=team, user=user, serializer_context=serializer_context
    )
    return ExposureCohortCreated(cohort=cohort)


def request_timeseries_recalculation(
    *, team: Team, user: User, experiment_id: int, metric_uuid: str
) -> TimeseriesRecalculationRequest:
    """A backfill of the metric's daily results, after the check that `user` may run the warehouse-native sources of
    the experiment. The caller starts the workflow of a new backfill."""
    experiment = _load(team, experiment_id)
    service = ExperimentService(team=team, user=user)
    service.assert_user_may_run_warehouse_native_sources(experiment)
    return TimeseriesRecalculationRequest(
        **service.request_timeseries_recalculation(experiment, metric_uuid=metric_uuid)
    )
