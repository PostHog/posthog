from dataclasses import replace

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.experiments.backend.facade.contracts import ExperimentHealthReaderAccess
from products.experiments.backend.health.condition_set_traffic import load_condition_set_traffic
from products.experiments.backend.health.context import HealthContext, load_health_context
from products.experiments.backend.health.exposure_gate import load_flag_history
from products.experiments.backend.health.exposure_inputs import ExposureInputs, load_exposure_inputs
from products.experiments.backend.health.pause_history import load_pause_history
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
    project: ProjectSetupFacts


def load_experiment_health_context(
    *, team_id: int, experiment_id: int, reader_access: ExperimentHealthReaderAccess
) -> HealthContext:
    """The context that the checks of the health endpoint read: the experiment, its flag, its linked metrics, the
    changes of the flag since launch and the flag's recent calls, as far as `reader_access` allows."""
    return _health_context(_load_experiment(team_id, experiment_id), reader_access)


def load_experiment_health_inputs(
    *, team_id: int, experiment_id: int, reader_access: ExperimentHealthReaderAccess, user: User | None
) -> HealthInputs:
    experiment = _load_experiment(team_id, experiment_id)
    return HealthInputs(
        context=_health_context(experiment, reader_access),
        exposures=load_exposure_inputs(experiment, user=user, can_query_events=reader_access.can_query_events),
        reader_access=reader_access,
        flag_version=experiment.feature_flag.version if experiment.feature_flag_id else None,
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


def _health_context(experiment: Experiment, reader_access: ExperimentHealthReaderAccess) -> HealthContext:
    flag_history = load_flag_history(experiment, reader_access=reader_access)
    context = load_health_context(experiment, flag_history=flag_history)
    traffic = load_condition_set_traffic(experiment, context, reader_access=reader_access)
    return replace(
        context,
        condition_set_traffic=traffic,
        pause_history=load_pause_history(experiment, reader_access=reader_access),
    )
