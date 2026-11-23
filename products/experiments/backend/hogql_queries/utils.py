import math
from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Optional, TypeVar

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQuantileMetric,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentStatsBase,
    ExperimentStatsBaseValidated,
    ExperimentStatsValidationFailure,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    HogQLQueryModifiers,
)

from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client.escape import substitute_params_for_display
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.experiments.backend.hogql_queries import CONTROL_VARIANT_KEY
from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig, get_cuped_config
from products.experiments.stats.bayesian.method import BayesianConfig, BayesianMethod
from products.experiments.stats.bayesian.tests import BayesianResult
from products.experiments.stats.frequentist.method import (
    DEFAULT_SEQUENTIAL_TUNING_PARAMETER,
    FrequentistConfig,
    FrequentistMethod,
    TestType,
)
from products.experiments.stats.frequentist.tests import TestResult
from products.experiments.stats.shared.cuped import CupedCovariate, cuped_adjust
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import (
    ProportionStatistic,
    QuantileBounds,
    QuantileStatistic,
    RatioStatistic,
    SampleMeanStatistic,
    StatisticError,
    choose_quantile_bounds,
    quantile_grid_levels,
)
from products.experiments.stats.shared.utils import validate_statistic_inputs

if TYPE_CHECKING:
    from products.experiments.stats.shared.statistics import RelativeEffectBaseline

logger = structlog.get_logger(__name__)

V = TypeVar("V", bound=ExperimentStatsBase)

AnyExperimentMetric = (
    ExperimentMeanMetric
    | ExperimentFunnelMetric
    | ExperimentRatioMetric
    | ExperimentRetentionMetric
    | ExperimentQuantileMetric
)


def get_experiment_query_debug(
    experiment_query_ast: ast.SelectQuery,
    team: Team,
    *,
    user: Optional[User] = None,
    bypass_warehouse_access_control: bool = False,
    modifiers: HogQLQueryModifiers | None = None,
) -> tuple[str, str]:
    """
    Return (hogql, clickhouse_sql) for debugging.

    `user` and `bypass_warehouse_access_control` must match the execution step, because
    resolving the query here also applies warehouse access control.
    """
    executor = HogQLQueryExecutor(
        query=experiment_query_ast,
        team=team,
        user=user,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
        modifiers=create_default_modifiers_for_team(team, modifiers),
    )
    clickhouse_sql_with_params, clickhouse_context_with_values = executor.generate_clickhouse_sql()
    clickhouse_sql = substitute_params_for_display(clickhouse_sql_with_params, clickhouse_context_with_values.values)
    assert executor.hogql is not None
    return (executor.hogql, clickhouse_sql)


def _parse_enum_config(value: Any, enum_class: type[Enum], default: Any) -> Any:
    try:
        if isinstance(value, str):
            return enum_class[value]
        elif isinstance(value, enum_class):
            return value
        return default
    except (KeyError, TypeError):
        return default


def _validate_numeric_range(value: Any, min_val: float, max_val: float, default: float) -> float:
    try:
        float_value = float(value)
        if min_val <= float_value <= max_val:
            return float_value
        return default
    except (TypeError, ValueError):
        return default


def sanitize_non_finite(value: Any) -> Any:
    """Replace non-finite floats (inf/-inf/nan) with None, recursively.

    Stats can overflow to infinity (e.g. delta-method variance with a near-zero
    denominator). json.dumps emits those as the nonstandard `Infinity`/`NaN`
    tokens, and Postgres rejects them in jsonb columns, so apply this to result
    dicts at the storage boundary. None matches the schema because the affected
    fields (confidence intervals etc.) are already nullable.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: sanitize_non_finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_non_finite(v) for v in value]
    return value


StatsMethod = Literal["bayesian", "frequentist"]


def resolve_stats_method(stats_config: dict | None) -> StatsMethod:
    """The statistics method an experiment's results use. A missing or unknown method is Bayesian."""
    method = stats_config.get("method") if isinstance(stats_config, dict) else None
    return "frequentist" if method == "frequentist" else "bayesian"


def get_experiment_stats_method(experiment) -> StatsMethod:
    return resolve_stats_method(experiment.stats_config)


def split_baseline_and_test_variants(
    variants: list[V],
    baseline_key: str = CONTROL_VARIANT_KEY,
) -> tuple[V, list[V]]:
    control_variants = [variant for variant in variants if variant.key == baseline_key]
    if not control_variants:
        # The baseline has no exposures early in an experiment. Raise a validation
        # error so that the user sees a message instead of a server error.
        raise ValidationError(
            f"No exposures for the '{baseline_key}' variant yet. Results can be calculated once it has data.",
            code="no_data",
        )
    if len(control_variants) > 1:
        raise ValueError("Multiple control variants found")
    control_variant = control_variants[0]
    test_variants = [variant for variant in variants if variant.key != baseline_key]

    return control_variant, test_variants


# Maps the SELECT aliases of the experiment query builders to
# ExperimentStatsBase field names. Aliases not registered here are ignored, so
# a new SELECT column without an entry in this map is silently dropped.
_ALIAS_TO_STATS_FIELD: dict[str, str] = {
    "variant": "key",
    "num_users": "number_of_samples",
    "total_sum": "sum",
    "total_sum_of_squares": "sum_squares",
    "step_counts": "step_counts",
    "denominator_sum": "denominator_sum",
    "denominator_sum_squares": "denominator_sum_squares",
    "numerator_denominator_sum_product": "numerator_denominator_sum_product",
    "covariate_sum": "covariate_sum",
    "covariate_sum_squares": "covariate_sum_squares",
    "covariate_sum_product": "covariate_sum_product",
    "quantile_grid": "quantile_grid",
}


def get_variant_result(
    row: tuple,
    columns: list[str],
    alias_to_field: dict[str, str] = _ALIAS_TO_STATS_FIELD,
) -> tuple[tuple[str, ...] | None, ExperimentStatsBase]:
    """
    Parse one result row into (breakdown_tuple, stats).

    Fields are matched by the column aliases declared in each SELECT
    (`count(...) AS num_users`, `breakdown_value_1`, ...), not by position.
    The breakdown tuple is None when the row has no `breakdown_value_N` columns.
    """
    row_dict = dict(zip(columns, row))

    breakdown_keys = sorted(
        (k for k in columns if k.startswith("breakdown_value_")),
        key=lambda k: int(k.removeprefix("breakdown_value_")),
    )
    breakdown_tuple = tuple(str(row_dict[k]) for k in breakdown_keys) or None

    base_stats: dict[str, Any] = {
        field: row_dict[alias] for alias, field in alias_to_field.items() if alias in row_dict
    }

    return breakdown_tuple, ExperimentStatsBase(**base_stats)


def get_variant_results(
    rows: list[tuple],
    columns: list[str],
) -> list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]:
    return [get_variant_result(row, columns) for row in rows]


def get_overall_variant_results(
    rows: list[tuple],
    columns: list[str],
) -> list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]:
    """
    Parse the rows of a query with breakdowns into stats that add up to the overall stats of each variant.

    The quantiles of the breakdowns do not give the quantile of the whole variant, so a quantile query returns
    an overall_<alias> column for each stat that does not add up, and that column replaces <alias>. The stats
    of other metrics add up as they are.
    """
    alias_to_field = {
        (f"overall_{alias}" if f"overall_{alias}" in columns else alias): field
        for alias, field in _ALIAS_TO_STATS_FIELD.items()
    }
    return [get_variant_result(row, columns, alias_to_field) for row in rows]


def aggregate_variants_across_breakdowns(
    variants: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]],
) -> list[ExperimentStatsBase]:
    """
    Sum each variant's stats over all breakdown combinations to get the overall stats per variant.

    The stats must come from get_overall_variant_results, because quantiles do not add up.
    """
    from collections import defaultdict

    variants_by_key: dict[str, list[ExperimentStatsBase]] = defaultdict(list)
    for _, variant in variants:
        variants_by_key[variant.key].append(variant)

    aggregated_variants = []

    for key, variant_list in variants_by_key.items():
        aggregated_stats: dict[str, Any] = {
            "key": key,
            "number_of_samples": sum(v.number_of_samples for v in variant_list),
            "sum": sum(v.sum for v in variant_list),
            "sum_squares": sum(v.sum_squares for v in variant_list),
        }

        if variant_list[0].step_counts is not None:
            aggregated_stats["step_counts"] = [
                sum(step_values) for step_values in zip(*[v.step_counts for v in variant_list if v.step_counts])
            ]

        if variant_list[0].denominator_sum is not None:
            aggregated_stats.update(
                {
                    "denominator_sum": sum(v.denominator_sum for v in variant_list if v.denominator_sum is not None),
                    "denominator_sum_squares": sum(
                        v.denominator_sum_squares for v in variant_list if v.denominator_sum_squares is not None
                    ),
                    "numerator_denominator_sum_product": sum(
                        v.numerator_denominator_sum_product
                        for v in variant_list
                        if v.numerator_denominator_sum_product is not None
                    ),
                }
            )

        if variant_list[0].covariate_sum is not None:
            aggregated_stats.update(
                {
                    "covariate_sum": sum(v.covariate_sum for v in variant_list if v.covariate_sum is not None),
                    "covariate_sum_squares": sum(
                        v.covariate_sum_squares for v in variant_list if v.covariate_sum_squares is not None
                    ),
                    "covariate_sum_product": sum(
                        v.covariate_sum_product for v in variant_list if v.covariate_sum_product is not None
                    ),
                }
            )

        if any(v.quantile_grid is not None for v in variant_list):
            # Each row of a variant holds the same grid of the whole variant, but a breakdown without events
            # holds an empty grid.
            aggregated_stats["quantile_grid"] = next((v.quantile_grid for v in variant_list if v.quantile_grid), [])

        aggregated_variants.append(ExperimentStatsBase(**aggregated_stats))

    return aggregated_variants


@frozen
class VariantQuantile:
    quantile: float
    bounds: QuantileBounds


def read_variant_quantile(quantile_level: float, quantile_grid: list[float] | None, n: int) -> VariantQuantile | None:
    """
    Read the quantile and the chosen bounds from the quantile_grid array of a variant with n events.

    The array holds the quantile, then Y_L and Y_U for each n* in the grid, in the order of
    quantile_query_levels(). Returns None when the variant has no events, or when Y_L == Y_U
    for every eligible n* (too many tied values).
    """
    levels = quantile_grid_levels(quantile_level)
    if n <= 0 or not quantile_grid or len(quantile_grid) != 1 + 2 * len(levels):
        return None
    grid_bounds = [
        QuantileBounds(n_star=level.n_star, lower=quantile_grid[1 + 2 * j], upper=quantile_grid[2 + 2 * j])
        for j, level in enumerate(levels)
    ]
    chosen = choose_quantile_bounds(n, grid_bounds)
    if chosen is None:
        return None
    return VariantQuantile(quantile=quantile_grid[0], bounds=chosen)


def quantile_statistic(
    metric: ExperimentQuantileMetric, variant: ExperimentStatsBase | ExperimentStatsBaseValidated
) -> QuantileStatistic | None:
    """The QuantileStatistic of a variant, or None when its bounds are unavailable or its sums are inconsistent."""
    n_events = int(variant.denominator_sum or 0)
    variant_quantile = read_variant_quantile(metric.quantile, variant.quantile_grid, n_events)
    if variant_quantile is None:
        return None
    try:
        return QuantileStatistic(
            nu=metric.quantile,
            n=n_events,
            n_clusters=variant.number_of_samples,
            quantile=variant_quantile.quantile,
            quantile_lower=variant_quantile.bounds.lower,
            quantile_upper=variant_quantile.bounds.upper,
            n_star=variant_quantile.bounds.n_star,
            s_sum=variant.sum,
            s_sum_squares=variant.sum_squares,
            n_sum=variant.denominator_sum or 0.0,
            n_sum_squares=variant.denominator_sum_squares or 0.0,
            s_n_sum_of_products=variant.numerator_denominator_sum_product or 0.0,
        )
    except StatisticError:
        return None


def validate_variant_result(
    variant_result: ExperimentStatsBase,
    metric: AnyExperimentMetric,
    is_baseline=False,
    difference_type: DifferenceType = DifferenceType.RELATIVE,
) -> ExperimentStatsBaseValidated:
    validation_failures = []

    if variant_result.number_of_samples < 50:
        validation_failures.append(ExperimentStatsValidationFailure.NOT_ENOUGH_EXPOSURES)

    if isinstance(metric, (ExperimentFunnelMetric | ExperimentRetentionMetric)) and variant_result.sum < 5:
        validation_failures.append(ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA)

    # A zero denominator makes the ratio undefined, so no statistical result can be computed
    if isinstance(metric, ExperimentRatioMetric) and not variant_result.denominator_sum:
        validation_failures.append(ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA)

    if isinstance(metric, ExperimentQuantileMetric):
        quantile_stat = quantile_statistic(metric, variant_result)
        # The statistical tests refuse these quantiles, so flag them here to show why the variant has no inference.
        if quantile_stat is None or validate_statistic_inputs(quantile_stat):
            validation_failures.append(ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA)
        # sum holds the count of events at or below the quantile, so the baseline check reads the quantile instead.
        # Only a relative difference divides by the baseline, so an absolute difference accepts a zero quantile.
        elif is_baseline and difference_type == DifferenceType.RELATIVE and quantile_stat.quantile == 0:
            validation_failures.append(ExperimentStatsValidationFailure.BASELINE_MEAN_IS_ZERO)
    elif is_baseline and variant_result.sum == 0:
        validation_failures.append(ExperimentStatsValidationFailure.BASELINE_MEAN_IS_ZERO)

    validated_result = ExperimentStatsBaseValidated(
        key=variant_result.key,
        number_of_samples=variant_result.number_of_samples,
        sum=variant_result.sum,
        sum_squares=variant_result.sum_squares,
        validation_failures=validation_failures,
    )

    if hasattr(variant_result, "step_counts") and variant_result.step_counts is not None:
        validated_result.step_counts = variant_result.step_counts

    if hasattr(variant_result, "denominator_sum") and variant_result.denominator_sum is not None:
        validated_result.denominator_sum = variant_result.denominator_sum
        validated_result.denominator_sum_squares = variant_result.denominator_sum_squares
        validated_result.numerator_denominator_sum_product = variant_result.numerator_denominator_sum_product

    if variant_result.quantile_grid is not None:
        validated_result.quantile_grid = variant_result.quantile_grid

    if hasattr(variant_result, "covariate_sum") and variant_result.covariate_sum is not None:
        validated_result.covariate_sum = variant_result.covariate_sum
        validated_result.covariate_sum_squares = variant_result.covariate_sum_squares
        validated_result.covariate_sum_product = variant_result.covariate_sum_product

    return validated_result


def metric_variant_to_statistic(
    metric: AnyExperimentMetric,
    variant: ExperimentStatsBaseValidated,
) -> SampleMeanStatistic | ProportionStatistic | RatioStatistic | QuantileStatistic:
    if isinstance(metric, ExperimentMeanMetric):
        # A thresholded mean is a binary "did the user reach N" outcome, so it must be
        # analyzed as a proportion (Bernoulli), not a continuous mean (Gaussian).
        # The query builder emits total_sum as the count of users who crossed.
        if metric.threshold is not None:
            return ProportionStatistic(
                n=variant.number_of_samples,
                sum=int(variant.sum),
            )
        return SampleMeanStatistic(
            n=variant.number_of_samples,
            sum=variant.sum,
            sum_squares=variant.sum_squares,
        )
    elif isinstance(metric, (ExperimentRatioMetric, ExperimentRetentionMetric)):
        # Model retention as a ratio so that the variance includes the uncertainty
        # in both the numerator and the denominator.
        # Retention numerator: users who completed (0 or 1 per user).
        numerator_stat = SampleMeanStatistic(
            n=variant.number_of_samples,
            sum=variant.sum,
            sum_squares=variant.sum_squares,
        )
        # Retention denominator: each user who started contributes 1.
        denominator_stat = SampleMeanStatistic(
            n=variant.number_of_samples,
            sum=variant.denominator_sum or 0.0,
            sum_squares=variant.denominator_sum_squares or 0.0,
        )
        return RatioStatistic(
            n=variant.number_of_samples,
            m_statistic=numerator_stat,
            d_statistic=denominator_stat,
            m_d_sum_of_products=variant.numerator_denominator_sum_product or 0.0,
        )
    elif isinstance(metric, ExperimentQuantileMetric):
        quantile_stat = quantile_statistic(metric, variant)
        if quantile_stat is None:
            raise StatisticError("Quantile bounds are unavailable - no events or too many tied values")
        errors = validate_statistic_inputs(quantile_stat)
        if errors:
            raise StatisticError("; ".join(errors))
        return quantile_stat
    else:
        # ExperimentFunnelMetric case
        return ProportionStatistic(
            n=variant.number_of_samples,
            sum=int(variant.sum),
        )


def metric_variant_to_cuped_data(variant: ExperimentStatsBaseValidated) -> CupedCovariate:
    return CupedCovariate(
        pre_statistic=SampleMeanStatistic(
            n=variant.number_of_samples,
            sum=variant.covariate_sum or 0.0,
            sum_squares=variant.covariate_sum_squares or 0.0,
        ),
        sum_of_cross_products=variant.covariate_sum_product or 0.0,
    )


def _copy_cuped_fields(
    result: ExperimentVariantResultFrequentist | ExperimentVariantResultBayesian,
    variant: ExperimentStatsBaseValidated,
) -> None:
    if variant.covariate_sum is None:
        return

    result.covariate_sum = variant.covariate_sum
    result.covariate_sum_squares = variant.covariate_sum_squares
    result.covariate_sum_product = variant.covariate_sum_product


ExperimentStatistic = SampleMeanStatistic | ProportionStatistic | RatioStatistic | QuantileStatistic


@frozen
class CupedAdjustment:
    test_stat: ExperimentStatistic
    control_stat: ExperimentStatistic
    relative_effect_baseline: RelativeEffectBaseline | None


def _apply_cuped_adjustment_if_enabled(
    metric: AnyExperimentMetric,
    cuped_config: CupedQueryConfig,
    test_stat: ExperimentStatistic,
    control_stat: ExperimentStatistic,
    test_variant: ExperimentStatsBaseValidated,
    control_variant: ExperimentStatsBaseValidated,
) -> CupedAdjustment:
    unadjusted = CupedAdjustment(test_stat=test_stat, control_stat=control_stat, relative_effect_baseline=None)

    if not cuped_config.enabled:
        return unadjusted

    if not isinstance(metric, (ExperimentMeanMetric, ExperimentFunnelMetric)):
        return unadjusted

    # cuped_adjust supports SampleMeanStatistic and ProportionStatistic, but not RatioStatistic.
    if not isinstance(test_stat, (SampleMeanStatistic, ProportionStatistic)) or not isinstance(
        control_stat, (SampleMeanStatistic, ProportionStatistic)
    ):
        return unadjusted

    cuped_result = cuped_adjust(
        test_stat,
        control_stat,
        metric_variant_to_cuped_data(test_variant),
        metric_variant_to_cuped_data(control_variant),
    )

    # With theta = 0 CUPED adjusts nothing, but the adjusted statistics still carry the variance floor. The floor
    # turns a treatment arm without spread into a decisive result, where the unadjusted test rejects it.
    if cuped_result.theta == 0.0:
        return unadjusted

    return CupedAdjustment(
        test_stat=cuped_result.treatment_adjusted,
        control_stat=cuped_result.control_adjusted,
        relative_effect_baseline=cuped_result.relative_effect_baseline,
    )


def _log_statistics_skipped(variant: ExperimentStatsBaseValidated, error: StatisticError) -> None:
    logger.info(
        "experiment_statistics_skipped",
        variant_key=variant.key,
        number_of_samples=variant.number_of_samples,
        reason=str(error),
    )


@frozen
class ValidatedVariants:
    control: ExperimentStatsBaseValidated
    tests: tuple[ExperimentStatsBaseValidated, ...]
    control_stat: ExperimentStatistic | None


def _validate_variants(
    metric: AnyExperimentMetric,
    control_variant: ExperimentStatsBase,
    test_variants: list[ExperimentStatsBase],
    difference_type: DifferenceType,
) -> ValidatedVariants:
    control = validate_variant_result(control_variant, metric, is_baseline=True, difference_type=difference_type)
    tests = tuple(
        validate_variant_result(test_variant, metric, difference_type=difference_type) for test_variant in test_variants
    )
    control_stat = None
    if not control.validation_failures:
        try:
            control_stat = metric_variant_to_statistic(metric, control)
        except StatisticError as e:
            _log_statistics_skipped(control, e)
    return ValidatedVariants(control=control, tests=tests, control_stat=control_stat)


VariantResultT = TypeVar("VariantResultT", ExperimentVariantResultFrequentist, ExperimentVariantResultBayesian)


def _variant_result(result_cls: type[VariantResultT], variant: ExperimentStatsBaseValidated) -> VariantResultT:
    result = result_cls(
        key=variant.key,
        number_of_samples=variant.number_of_samples,
        sum=variant.sum,
        sum_squares=variant.sum_squares,
        step_counts=variant.step_counts,
        validation_failures=variant.validation_failures,
    )
    if variant.denominator_sum is not None:
        result.denominator_sum = variant.denominator_sum
        result.denominator_sum_squares = variant.denominator_sum_squares
        result.numerator_denominator_sum_product = variant.numerator_denominator_sum_product
    result.quantile_grid = variant.quantile_grid
    _copy_cuped_fields(result, variant)
    return result


TestResultT = TypeVar("TestResultT", TestResult, BayesianResult)


def _run_variant_test(
    run_test: Callable[..., TestResultT],
    metric: AnyExperimentMetric,
    cuped_config: CupedQueryConfig,
    test_variant: ExperimentStatsBaseValidated,
    variants: ValidatedVariants,
) -> TestResultT | None:
    """Runs the test of one variant against the control, with CUPED where it applies. Returns None when either
    side has no valid statistic, and logs why when the statistics are invalid."""
    if variants.control_stat is None or test_variant.validation_failures:
        return None
    try:
        test_stat = metric_variant_to_statistic(metric, test_variant)
        cuped_adjustment = _apply_cuped_adjustment_if_enabled(
            metric,
            cuped_config,
            test_stat,
            variants.control_stat,
            test_variant,
            variants.control,
        )
        return run_test(
            cuped_adjustment.test_stat,
            cuped_adjustment.control_stat,
            relative_effect_baseline=cuped_adjustment.relative_effect_baseline,
        )
    except StatisticError as e:
        _log_statistics_skipped(test_variant, e)
        return None


def _resolve_sequential_settings(
    frequentist_config: dict,
    team_default_enabled: bool,
    team_default_tuning_parameter: int | None,
) -> tuple[bool, float]:
    """Resolve sequential testing settings using precedence: experiment > team default > hardcoded.

    Mirrors the CUPED resolution pattern: an experiment value of `False` deliberately
    overrides a team default of `True` (explicit opt-out wins).
    """
    if "sequential_testing_enabled" in frequentist_config:
        enabled = bool(frequentist_config["sequential_testing_enabled"])
    else:
        enabled = team_default_enabled

    team_fallback = (
        _validate_numeric_range(team_default_tuning_parameter, 1, 1_000_000_000, DEFAULT_SEQUENTIAL_TUNING_PARAMETER)
        if team_default_tuning_parameter is not None
        else DEFAULT_SEQUENTIAL_TUNING_PARAMETER
    )
    tuning_parameter = _validate_numeric_range(
        frequentist_config.get("sequential_tuning_parameter", team_fallback),
        1,
        1_000_000_000,
        team_fallback,
    )
    return enabled, tuning_parameter


@frozen
class BayesianSettings:
    """What the Bayesian test reads from an experiment's stats config, with defaults applied."""

    ci_level: float
    difference_type: DifferenceType


@frozen
class FrequentistSettings:
    """What the frequentist test reads from an experiment's stats config, with the team's sequential
    testing defaults and the product defaults applied."""

    alpha: float
    difference_type: DifferenceType
    sequential_testing_enabled: bool
    sequential_tuning_parameter: float


def _method_config(stats_config: dict | None, method: StatsMethod) -> dict:
    method_config = stats_config.get(method) if isinstance(stats_config, dict) else None
    return method_config if isinstance(method_config, dict) else {}


def resolve_bayesian_settings(stats_config: dict | None) -> BayesianSettings:
    bayesian_config = _method_config(stats_config, "bayesian")
    return BayesianSettings(
        ci_level=_validate_numeric_range(bayesian_config.get("ci_level", 0.95), 0.0, 1.0, 0.95),
        difference_type=_parse_enum_config(
            bayesian_config.get("difference_type", "RELATIVE"), DifferenceType, DifferenceType.RELATIVE
        ),
    )


def resolve_frequentist_settings(
    stats_config: dict | None,
    *,
    team_default_sequential_testing_enabled: bool,
    team_default_sequential_tuning_parameter: int | None,
) -> FrequentistSettings:
    frequentist_config = _method_config(stats_config, "frequentist")
    sequential_testing_enabled, sequential_tuning_parameter = _resolve_sequential_settings(
        frequentist_config,
        team_default_enabled=team_default_sequential_testing_enabled,
        team_default_tuning_parameter=team_default_sequential_tuning_parameter,
    )
    return FrequentistSettings(
        alpha=_validate_numeric_range(frequentist_config.get("alpha", 0.05), 0.0, 1.0, 0.05),
        difference_type=_parse_enum_config(
            frequentist_config.get("difference_type", "RELATIVE"), DifferenceType, DifferenceType.RELATIVE
        ),
        sequential_testing_enabled=sequential_testing_enabled,
        sequential_tuning_parameter=sequential_tuning_parameter,
    )


def get_frequentist_experiment_result(
    metric: AnyExperimentMetric,
    control_variant: ExperimentStatsBase,
    test_variants: list[ExperimentStatsBase],
    stats_config: dict | None = None,
    cuped_config: CupedQueryConfig | None = None,
    team_default_sequential_testing_enabled: bool = False,
    team_default_sequential_tuning_parameter: int | None = None,
) -> ExperimentQueryResponse:
    resolved_cuped_config = cuped_config or get_cuped_config(stats_config, metric)
    settings = resolve_frequentist_settings(
        stats_config,
        team_default_sequential_testing_enabled=team_default_sequential_testing_enabled,
        team_default_sequential_tuning_parameter=team_default_sequential_tuning_parameter,
    )

    config = FrequentistConfig(
        alpha=settings.alpha,
        test_type=TestType.TWO_SIDED,
        difference_type=settings.difference_type,
        sequential_testing_enabled=settings.sequential_testing_enabled,
        sequential_tuning_parameter=settings.sequential_tuning_parameter,
    )
    method = FrequentistMethod(config)

    validated = _validate_variants(metric, control_variant, test_variants, settings.difference_type)
    variants: list[ExperimentVariantResultFrequentist] = []
    for test_variant in validated.tests:
        variant_result = _variant_result(ExperimentVariantResultFrequentist, test_variant)
        result = _run_variant_test(method.run_test, metric, resolved_cuped_config, test_variant, validated)
        if result is not None:
            variant_result.p_value = result.p_value
            variant_result.confidence_interval = [result.confidence_interval[0], result.confidence_interval[1]]
            variant_result.significant = result.is_significant
        variants.append(variant_result)

    return ExperimentQueryResponse(baseline=validated.control, variant_results=variants)


def get_bayesian_experiment_result(
    metric: AnyExperimentMetric,
    control_variant: ExperimentStatsBase,
    test_variants: list[ExperimentStatsBase],
    stats_config: dict | None = None,
    cuped_config: CupedQueryConfig | None = None,
) -> ExperimentQueryResponse:
    resolved_cuped_config = cuped_config or get_cuped_config(stats_config, metric)
    settings = resolve_bayesian_settings(stats_config)

    config = BayesianConfig(ci_level=settings.ci_level, difference_type=settings.difference_type)
    method = BayesianMethod(config)

    validated = _validate_variants(metric, control_variant, test_variants, settings.difference_type)
    variants: list[ExperimentVariantResultBayesian] = []
    for test_variant in validated.tests:
        variant_result = _variant_result(ExperimentVariantResultBayesian, test_variant)
        result = _run_variant_test(method.run_test, metric, resolved_cuped_config, test_variant, validated)
        if result is not None:
            variant_result.chance_to_win = result.chance_to_win
            variant_result.credible_interval = [result.credible_interval[0], result.credible_interval[1]]
            variant_result.significant = result.is_decisive
        variants.append(variant_result)

    return ExperimentQueryResponse(baseline=validated.control, variant_results=variants)
