from dataclasses import replace
from datetime import datetime

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.experiments.backend.facade.contracts import ExperimentHealthReaderAccess
from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.health.condition_set_traffic import load_condition_set_traffic
from products.experiments.backend.health.context import HealthContext, load_health_context
from products.experiments.backend.health.exposure_columns import load_filters_without_column
from products.experiments.backend.health.exposure_gate import load_flag_history
from products.experiments.backend.health.exposure_inputs import ExposureInputs, load_exposure_inputs
from products.experiments.backend.health.latest_calculation import load_latest_calculation
from products.experiments.backend.health.metric_compiles import load_metric_compiles
from products.experiments.backend.health.pause_history import load_pause_history
from products.experiments.backend.health.primary_metric import load_primary_metric
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.setup_context import ProjectSetupFacts, build_project_setup_facts


@frozen
class HealthInputs:
    """What the staff view of the health checks shows: the context the checks read, the exposure query's answer that
    the exposure checks read, and facts about the project that no check reads yet but that explain a finding."""

    context: HealthContext
    exposures: ExposureInputs
    reader_access: ExperimentHealthReaderAccess
    # None when the experiment has no flag, or the flag has no version.
    flag_version: int | None
    # The flag's latest recorded call. None when the experiment has no flag, or the flag has no recorded call.
    flag_last_called_at: datetime | None
    project: ProjectSetupFacts


def load_experiment_health_context(
    *, team_id: int, experiment_id: int, reader_access: ExperimentHealthReaderAccess, user: User | None
) -> HealthContext:
    """The context that the checks of the health endpoint read: the experiment, its flag, its linked metrics, the
    compile of their queries and their latest calculation, the changes of the flag since launch and the flag's recent
    calls, as far as `reader_access` and `user`'s warehouse access allow."""
    return _health_context(_load_experiment(team_id, experiment_id), reader_access, user)


def load_experiment_health_inputs(
    *, team_id: int, experiment_id: int, reader_access: ExperimentHealthReaderAccess, user: User | None
) -> HealthInputs:
    experiment = _load_experiment(team_id, experiment_id)
    return HealthInputs(
        context=_health_context(experiment, reader_access, user),
        exposures=load_exposure_inputs(experiment, user=user, can_query_events=reader_access.can_query_events),
        reader_access=reader_access,
        flag_version=experiment.feature_flag.version if experiment.feature_flag_id else None,
        flag_last_called_at=experiment.feature_flag.last_called_at if experiment.feature_flag_id else None,
        project=build_project_setup_facts(
            experiment.team,
            can_query_events=reader_access.can_query_events,
            denied_event_properties=reader_access.denied_event_properties,
        ),
    )


def _load_experiment(team_id: int, experiment_id: int) -> Experiment:
    return (
        Experiment.objects.select_related("team", "feature_flag")
        .prefetch_related("experimenttosavedmetric_set__saved_metric")
        .get(id=experiment_id, team_id=team_id)
    )


def _health_context(
    experiment: Experiment, reader_access: ExperimentHealthReaderAccess, user: User | None
) -> HealthContext:
    flag_history = load_flag_history(experiment, reader_access=reader_access)
    context = load_health_context(experiment, flag_history=flag_history)
    traffic = load_condition_set_traffic(experiment, context, reader_access=reader_access)
    latest_calculation = load_latest_calculation(experiment)
    return replace(
        context,
        condition_set_traffic=traffic,
        pause_history=load_pause_history(experiment, reader_access=reader_access),
        primary_metric=load_primary_metric(experiment),
        metric_compiles=load_metric_compiles(experiment, user=user),
        latest_calculation=latest_calculation,
        exposure_filters_without_column=load_filters_without_column(experiment)
        if latest_calculation is not None
        and not latest_calculation.completed_count
        and any(failure.exposures_path == ExposuresPath.DIRECT_SCAN for failure in latest_calculation.failures)
        else None,
    )
