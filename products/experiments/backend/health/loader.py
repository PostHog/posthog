from dataclasses import replace
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.experiments.backend.facade.contracts import (
    ExperimentHealth,
    ExperimentHealthAnalysisSetup,
    ExperimentHealthExposureSetup,
    ExperimentHealthReaderAccess,
    ExperimentHealthReleaseCondition,
    ExperimentHealthSetup,
)
from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.health.condition_set_traffic import load_condition_set_traffic
from products.experiments.backend.health.context import HealthContext, flag_calls_readable, load_health_context
from products.experiments.backend.health.exposure_columns import load_filters_without_column
from products.experiments.backend.health.exposure_gate import load_flag_history
from products.experiments.backend.health.exposure_inputs import ExposureInputs, load_exposure_inputs
from products.experiments.backend.health.latest_calculation import load_latest_calculation
from products.experiments.backend.health.metric_compiles import load_metric_compiles
from products.experiments.backend.health.metric_windows import load_primary_metric_windows
from products.experiments.backend.health.pause_history import load_pause_history
from products.experiments.backend.health.primary_metric import load_primary_metric
from products.experiments.backend.health.registry import EXPERIMENT_HEALTH_CHECKS, evaluate, not_checked_health
from products.experiments.backend.health.skips import NOT_ON_FLAG_RULE
from products.experiments.backend.hogql_queries.utils import FrequentistSettings
from products.experiments.backend.metric_calculation.config import ExperimentCalculationSettings
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.setup_context import ProjectSetupFacts, build_project_setup_facts
from products.feature_flags.backend.facade.filters import (
    condition_aggregation,
    condition_rollout_percentage,
    pinned_variant,
)


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


def evaluate_experiment_health(
    *, team_id: int, experiment_id: int, reader_access: ExperimentHealthReaderAccess, user: User | None
) -> ExperimentHealth:
    """The health endpoint's checks and the flag's setup. The checks read the experiment, its flag, its linked
    metrics, the compile of their queries and their latest calculation, the changes of the flag since launch and the
    flag's recent calls, as far as `reader_access` and `user`'s warehouse access allow."""
    experiment = _load_experiment(team_id, experiment_id)
    if experiment.is_rule_linked:
        # The checks and the setup read the release conditions and the variants of a v1 flag, and none reads a
        # feature flag rule yet.
        return not_checked_health(EXPERIMENT_HEALTH_CHECKS, NOT_ON_FLAG_RULE)
    ctx = _health_context(experiment, reader_access, user)
    return replace(evaluate(ctx, EXPERIMENT_HEALTH_CHECKS), setup=_health_setup(experiment, ctx))


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
        flag_version=experiment.feature_flag.version if experiment.feature_flag_id else None,
        project=build_project_setup_facts(
            experiment.team,
            can_query_events=reader_access.can_query_events,
            denied_event_properties=reader_access.denied_event_properties,
        ),
    )


def _health_setup(experiment: Experiment, ctx: HealthContext) -> ExperimentHealthSetup | None:
    if ctx.flag is None:
        return None
    flag = experiment.feature_flag
    conditions = flag.conditions if isinstance(flag.conditions, list) else []
    variant_keys = {variant.key for variant in ctx.flag.variants if variant.key}
    reachable_numbers = {condition.number for condition in ctx.flag.reachable_conditions}
    # `reachable_conditions` doesn't model a request without a device ID, which skips the sets that need the bucketing
    # hash. On a flag that buckets by device ID, such a request can reach a set that it calls unreachable.
    reach_known = flag.bucketing_identifier != "device_id"
    exposure_events = ctx.exposure_events
    # The sets as stored, not the users they reach: the checks judge what the configuration does.
    # A null column means the model default, which the flag service applies too.
    return ExperimentHealthSetup(
        release_conditions=tuple(
            _release_condition(
                condition,
                flag.aggregation_group_type_index,
                variant_keys,
                reachable=number in reachable_numbers if reach_known else None,
            )
            for number, condition in enumerate(conditions, start=1)
            if isinstance(condition, dict)
        ),
        early_exit=flag.early_exit,
        bucketing_identifier=flag.bucketing_identifier or "distinct_id",
        aggregation_group_type_index=flag.aggregation_group_type_index,
        evaluation_runtime=flag.evaluation_runtime or "all",
        evaluation_contexts=tuple(sorted(flag.evaluation_tag_names or ())),
        ensure_experience_continuity=bool(flag.ensure_experience_continuity),
        exposure=ExperimentHealthExposureSetup(
            event=exposure_events.custom_event,
            action=exposure_events.action,
            activation=exposure_events.activation,
        )
        if exposure_events
        else None,
        analysis=_analysis_setup(experiment),
    )


def _analysis_setup(experiment: Experiment) -> ExperimentHealthAnalysisSetup:
    # The key version changes no field read here, and resolving it evaluates a feature flag.
    settings = ExperimentCalculationSettings.from_experiment(experiment, key_version=1)
    stats = settings.stats
    stats_config = experiment.stats_config if isinstance(experiment.stats_config, dict) else {}
    exposure_readable = "unparsed" not in settings.normalized_exposure
    # A missing key falls back to the project default, as `resolve_experiment_cuped_config` and
    # `resolve_frequentist_settings` decide. An experiment that sets False overrides a default of True.
    cuped_config = stats_config.get("cuped")
    frequentist_config = stats_config.get("frequentist")
    return ExperimentHealthAnalysisSetup(
        stats_method=settings.stats_method,
        confidence_level=1 - stats.alpha if isinstance(stats, FrequentistSettings) else stats.ci_level,
        sequential_testing=stats.sequential_testing_enabled if isinstance(stats, FrequentistSettings) else None,
        sequential_testing_from_project_default=isinstance(stats, FrequentistSettings)
        and not (isinstance(frequentist_config, dict) and "sequential_testing_enabled" in frequentist_config),
        cuped=settings.cuped.enabled,
        cuped_lookback_days=settings.cuped.lookback_days if settings.cuped.enabled else None,
        cuped_from_project_default=not (isinstance(cuped_config, dict) and "enabled" in cuped_config),
        filters_test_accounts=bool(settings.normalized_exposure["filter_test_accounts"]) if exposure_readable else None,
        test_account_filter_count=len(settings.test_account_filters),
        multiple_variant_handling=settings.normalized_exposure["multiple_variant_handling"]
        if exposure_readable
        else None,
        only_count_matured_users=settings.only_count_matured_users,
        baseline_variant=settings.baseline,
        excluded_variants=settings.excluded_variants,
    )


def _release_condition(
    condition: dict[str, Any], flag_aggregation: int | None, variant_keys: set[str], *, reachable: bool | None
) -> ExperimentHealthReleaseCondition:
    properties = condition.get("properties")
    return ExperimentHealthReleaseCondition(
        rollout_percentage=float(condition_rollout_percentage(condition)),
        property_count=len(properties) if isinstance(properties, list) else 0,
        aggregation_group_type_index=condition_aggregation(condition, flag_aggregation),
        variant=pinned_variant(condition, variant_keys),
        reachable=reachable,
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
        experiment,
        flag_history=flag_history,
        can_read_flag_history=reader_access.can_read_flag_history,
        can_read_flag_calls=flag_calls_readable(reader_access),
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
