from dataclasses import replace
from typing import Any

import pydantic

from posthog.models.user import User

from products.experiments.backend.facade.contracts import (
    ExperimentHealth,
    ExperimentHealthAnalysisSetup,
    ExperimentHealthExposureSetup,
    ExperimentHealthMultipleVariantHandling,
    ExperimentHealthReaderAccess,
    ExperimentHealthReleaseCondition,
    ExperimentHealthSetup,
    ExperimentHealthStatsMethod,
)
from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.health.condition_set_traffic import load_condition_set_traffic
from products.experiments.backend.health.context import HealthContext, flag_calls_readable, load_health_context
from products.experiments.backend.health.exposure_columns import load_filters_without_column
from products.experiments.backend.health.exposure_gate import load_flag_history
from products.experiments.backend.health.latest_calculation import load_latest_calculation
from products.experiments.backend.health.metric_compiles import load_metric_compiles
from products.experiments.backend.health.metric_windows import load_primary_metric_windows
from products.experiments.backend.health.pause_history import load_pause_history
from products.experiments.backend.health.primary_metric import load_primary_metric
from products.experiments.backend.health.registry import EXPERIMENT_HEALTH_CHECKS, evaluate, not_checked_health
from products.experiments.backend.health.skips import NOT_ON_FLAG_RULE
from products.experiments.backend.hogql_queries.cuped_config import activation_blocks_cuped, metric_supports_cuped
from products.experiments.backend.hogql_queries.utils import FrequentistSettings
from products.experiments.backend.metric_calculation.config import (
    ExperimentCalculationSettings,
    calculation_metric_name,
    team_experiments_configs,
)
from products.experiments.backend.metric_resolution import build_metric, get_metrics_for_calculation
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.feature_flags.backend.facade.filters import (
    condition_aggregation,
    condition_rollout_percentage,
    pinned_variant,
)


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
    team_config = _team_config(experiment)
    ctx = _health_context(experiment, team_config, reader_access, user)
    return replace(evaluate(ctx, EXPERIMENT_HEALTH_CHECKS), setup=_health_setup(experiment, ctx, team_config))


def _health_setup(
    experiment: Experiment, ctx: HealthContext, team_config: TeamExperimentsConfig
) -> ExperimentHealthSetup | None:
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
        analysis=_analysis_setup(experiment, team_config),
    )


def _analysis_setup(experiment: Experiment, team_config: TeamExperimentsConfig) -> ExperimentHealthAnalysisSetup:
    # The key version changes no field read here, and resolving it evaluates a feature flag.
    settings = ExperimentCalculationSettings.from_experiment(experiment, team_config=team_config, key_version=1)
    stats = settings.stats
    cuped = settings.cuped.enabled
    # The calculation takes the project default for a key that the experiment doesn't set, as
    # `resolve_experiment_cuped_config` and `resolve_frequentist_settings` decide. A False that the experiment sets
    # overrides a default of True.
    cuped_config = _stats_config_section(experiment, "cuped")
    frequentist_config = _stats_config_section(experiment, "frequentist")
    exposure_readable = "unparsed" not in settings.normalized_exposure
    return ExperimentHealthAnalysisSetup(
        stats_method=ExperimentHealthStatsMethod(settings.stats_method),
        confidence_level=1 - stats.alpha if isinstance(stats, FrequentistSettings) else stats.ci_level,
        sequential_testing=stats.sequential_testing_enabled if isinstance(stats, FrequentistSettings) else None,
        sequential_testing_from_project_default=isinstance(stats, FrequentistSettings)
        and "sequential_testing_enabled" not in frequentist_config,
        cuped=cuped,
        cuped_lookback_days=settings.cuped.lookback_days if cuped else None,
        cuped_from_project_default="enabled" not in cuped_config,
        cuped_lookback_days_from_project_default=cuped and cuped_config.get("lookback_days") is None,
        metrics_without_cuped_support=_metrics_without_cuped_support(experiment, settings) if cuped else (),
        # `settings.exposure` is None when the exposure criteria don't parse, and for a warehouse-native exposure, whose
        # query applies no test account filters.
        filters_test_accounts=settings.exposure.filter_test_accounts if settings.exposure is not None else None,
        test_account_filter_count=len(settings.test_account_filters),
        multiple_variant_handling=ExperimentHealthMultipleVariantHandling(
            settings.normalized_exposure["multiple_variant_handling"]
        )
        if exposure_readable
        else None,
        only_count_matured_users=settings.only_count_matured_users,
        baseline_variant=settings.baseline,
        excluded_variants=settings.excluded_variants,
    )


def _stats_config_section(experiment: Experiment, key: str) -> dict[str, Any]:
    stats_config = experiment.stats_config if isinstance(experiment.stats_config, dict) else {}
    section = stats_config.get(key)
    return section if isinstance(section, dict) else {}


def _metrics_without_cuped_support(experiment: Experiment, settings: ExperimentCalculationSettings) -> tuple[str, ...]:
    has_activation = settings.exposure is not None and settings.exposure.activation_config is not None
    names: dict[str, str] = {}
    for metric in get_metrics_for_calculation(experiment):
        try:
            parsed = build_metric(metric.definition)
        except pydantic.ValidationError:
            # The calculation of a metric that doesn't parse fails, and the metric checks report that failure.
            continue
        supports_cuped = metric_supports_cuped(parsed) and not activation_blocks_cuped(
            parsed, has_activation=has_activation
        )
        if not supports_cuped:
            calculation_config = settings.build_metric_config(
                metric_id=metric.uuid, role=metric.role, definition=metric.definition
            )
            names.setdefault(metric.uuid, calculation_metric_name(experiment, calculation_config))
    return tuple(names.values())


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


def _team_config(experiment: Experiment) -> TeamExperimentsConfig:
    return team_experiments_configs([experiment.team_id])[experiment.team_id]


def _health_context(
    experiment: Experiment,
    team_config: TeamExperimentsConfig,
    reader_access: ExperimentHealthReaderAccess,
    user: User | None,
) -> HealthContext:
    flag_history = load_flag_history(experiment, reader_access=reader_access)
    context = load_health_context(
        experiment,
        flag_history=flag_history,
        can_read_flag_history=reader_access.can_read_flag_history,
        can_read_flag_calls=flag_calls_readable(reader_access),
    )
    traffic = load_condition_set_traffic(experiment, context, reader_access=reader_access)
    latest_calculation = load_latest_calculation(experiment, team_config=team_config)
    return replace(
        context,
        condition_set_traffic=traffic,
        pause_history=load_pause_history(experiment, reader_access=reader_access),
        primary_metric=load_primary_metric(experiment, team_config=team_config),
        primary_metric_windows=load_primary_metric_windows(
            experiment, can_read_flag_history=reader_access.can_read_flag_history
        ),
        metric_compiles=load_metric_compiles(experiment, team_config=team_config, user=user),
        latest_calculation=latest_calculation,
        exposure_filters_without_column=load_filters_without_column(experiment)
        if latest_calculation is not None
        and not latest_calculation.completed_count
        and any(failure.exposures_path == ExposuresPath.DIRECT_SCAN for failure in latest_calculation.failures)
        else None,
    )
