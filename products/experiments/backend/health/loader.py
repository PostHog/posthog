from dataclasses import replace
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.experiments.backend.facade.contracts import (
    ExperimentHealth,
    ExperimentHealthReaderAccess,
    ExperimentHealthReleaseCondition,
    ExperimentHealthSetup,
)
from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.health.condition_set_traffic import (
    load_condition_set_traffic,
    scan_reads_denied_property,
)
from products.experiments.backend.health.context import HealthContext, load_health_context
from products.experiments.backend.health.exposure_columns import load_filters_without_column
from products.experiments.backend.health.exposure_gate import load_flag_history
from products.experiments.backend.health.exposure_inputs import ExposureInputs, load_exposure_inputs
from products.experiments.backend.health.latest_calculation import load_latest_calculation
from products.experiments.backend.health.metric_compiles import load_metric_compiles
from products.experiments.backend.health.metric_windows import load_primary_metric_windows
from products.experiments.backend.health.pause_history import load_pause_history
from products.experiments.backend.health.primary_metric import load_primary_metric
from products.experiments.backend.health.registry import EXPERIMENT_HEALTH_CHECKS, evaluate
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.setup_context import ProjectSetupFacts, build_project_setup_facts
from products.feature_flags.backend.facade.filters import condition_aggregation, condition_rollout_percentage


@frozen
class HealthInputs:
    """What the staff view of the health checks shows: the context the checks read, the exposure query's answer that
    the exposure checks read, and facts about the project that no check reads yet but that explain a finding."""

    context: HealthContext
    exposures: ExposureInputs
    reader_access: ExperimentHealthReaderAccess
    # Whether the flag call scan reads a property that the reader is denied, so the scan didn't run.
    scan_reads_denied_property: bool
    # None when the experiment has no flag, or the flag has no version.
    flag_version: int | None
    project: ProjectSetupFacts


def evaluate_experiment_health(
    *, team_id: int, experiment_id: int, reader_access: ExperimentHealthReaderAccess, user: User | None
) -> ExperimentHealth:
    """The health endpoint's checks and the flag's setup. The checks read the experiment, its flag, its linked
    metrics, the compile of their queries and their latest calculation, the changes of the flag since launch and the
    flag's recent calls, as far as `reader_access` and `user`'s warehouse access allow."""
    experiment = _load_experiment(team_id, experiment_id)
    health = evaluate(_health_context(experiment, reader_access, user), EXPERIMENT_HEALTH_CHECKS)
    return replace(health, setup=_health_setup(experiment))


def load_experiment_health_inputs(
    *, team_id: int, experiment_id: int, reader_access: ExperimentHealthReaderAccess, user: User | None
) -> HealthInputs:
    experiment = _load_experiment(team_id, experiment_id)
    return HealthInputs(
        context=_health_context(experiment, reader_access, user),
        exposures=load_exposure_inputs(
            experiment,
            user=user,
            can_query_events=reader_access.can_query_events,
            can_read_flag_history=reader_access.can_read_flag_history,
        ),
        reader_access=reader_access,
        scan_reads_denied_property=scan_reads_denied_property(reader_access, experiment),
        flag_version=experiment.feature_flag.version if experiment.feature_flag_id else None,
        project=build_project_setup_facts(
            experiment.team,
            can_query_events=reader_access.can_query_events,
            denied_event_properties=reader_access.denied_event_properties,
        ),
    )


def _health_setup(experiment: Experiment) -> ExperimentHealthSetup | None:
    # django-stubs types the id as int, but an unsaved instance can carry None.
    feature_flag_id: int | None = experiment.feature_flag_id
    if feature_flag_id is None:
        return None
    flag = experiment.feature_flag
    conditions = flag.conditions if isinstance(flag.conditions, list) else []
    # The sets as stored, not the users they reach: the checks judge what the configuration does.
    # A null column means the model default, which the flag service applies too.
    return ExperimentHealthSetup(
        release_conditions=tuple(
            _release_condition(condition, flag.aggregation_group_type_index)
            for condition in conditions
            if isinstance(condition, dict)
        ),
        early_exit=flag.early_exit,
        bucketing_identifier=flag.bucketing_identifier or "distinct_id",
        aggregation_group_type_index=flag.aggregation_group_type_index,
        evaluation_runtime=flag.evaluation_runtime or "all",
        evaluation_contexts=tuple(sorted(flag.evaluation_tag_names or ())),
        ensure_experience_continuity=bool(flag.ensure_experience_continuity),
    )


def _release_condition(condition: dict[str, Any], flag_aggregation: int | None) -> ExperimentHealthReleaseCondition:
    properties = condition.get("properties")
    return ExperimentHealthReleaseCondition(
        rollout_percentage=float(condition_rollout_percentage(condition)),
        property_count=len(properties) if isinstance(properties, list) else 0,
        aggregation_group_type_index=condition_aggregation(condition, flag_aggregation),
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
    context = load_health_context(
        experiment, flag_history=flag_history, can_read_flag_history=reader_access.can_read_flag_history
    )
    traffic = load_condition_set_traffic(experiment, context, reader_access=reader_access)
    latest_calculation = load_latest_calculation(experiment)
    return replace(
        context,
        condition_set_traffic=traffic,
        pause_history=load_pause_history(experiment, reader_access=reader_access),
        primary_metric=load_primary_metric(experiment),
        primary_metric_windows=load_primary_metric_windows(
            experiment, can_read_flag_history=reader_access.can_read_flag_history
        ),
        metric_compiles=load_metric_compiles(experiment, user=user),
        latest_calculation=latest_calculation,
        exposure_filters_without_column=load_filters_without_column(experiment)
        if latest_calculation is not None
        and not latest_calculation.completed_count
        and any(failure.exposures_path == ExposuresPath.DIRECT_SCAN for failure in latest_calculation.failures)
        else None,
    )
