"""
Actors query for a funnel experiment metric: the people behind one funnel step and variant.
"""

import uuid
from typing import TYPE_CHECKING

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelMetric,
    ExperimentWarehouseNativeExposureConfig,
)

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError

from posthog.clickhouse.query_tagging import Product, tag_queries

from products.experiments.backend.hogql_queries.experiment_funnel_actors_query_builder import (
    ExperimentFunnelActorsQueryBuilder,
)
from products.experiments.backend.hogql_queries.experiment_query_builder import (
    get_exposure_config_params_for_builder,
    resolve_exposure_config_for_builder,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import resolve_filter_test_accounts
from products.experiments.backend.metric_utils import get_default_metric_title

if TYPE_CHECKING:
    from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner


def build_experiment_actors_query(runner: "ExperimentQueryRunner") -> ast.SelectQuery:
    """
    Actors query for a funnel metric. It includes exposure as step 0, so it applies
    the same temporal filtering as the main experiment query, and its counts match
    the funnel chart. It returns the individual users for one step and variant,
    optionally with matched recordings, instead of aggregate statistics.
    """
    if runner.actors_query is None:
        raise ValidationError("actors_query must be set before calling to_actors_query()")

    if not isinstance(runner.metric, ExperimentFunnelMetric):
        raise ValidationError("Actors query only supported for funnel experiment metrics")

    funnel_step = runner.actors_query.funnelStep
    if funnel_step is None:
        raise ValidationError("funnelStep is required for experiment actors query")

    num_metric_steps = len(runner.metric.series)

    # funnelStep=-1 is a valid drop-off: "exposed but never reached the first metric step".
    # step_reached is 0-indexed with exposure as step 0, so the WHERE clause resolves it to
    # step_reached == 0, which selects the exposed users who did not validly enter the funnel.
    if funnel_step < 0:
        max_drop_off = -(num_metric_steps + 1)
        if funnel_step < max_drop_off:
            raise ValidationError(
                f"Invalid drop-off step {funnel_step} for experiment with {num_metric_steps} metric steps. "
                f"Valid drop-off steps: -1 (exposed, did not reach first metric step) to {max_drop_off}."
            )

    if funnel_step > num_metric_steps:
        raise ValidationError(
            f"Invalid conversion step {funnel_step} for experiment with {num_metric_steps} metric steps. "
            f"Valid conversion steps: 0 (exposure step) to {num_metric_steps}."
        )

    exposure_config: ExperimentEventExposureConfig | ActionsNode
    activation_config: ExperimentEventExposureConfig | ActionsNode | None = None
    if runner.actors_query.exposureConfig is not None:
        override = runner.actors_query.exposureConfig
        if isinstance(override, ExperimentWarehouseNativeExposureConfig):
            raise ExposedHogQLError("Warehouse-native sources cannot be calculated yet.")
        # An explicit override replaces the whole exposure definition, including any
        # stored activation event.
        exposure_config = resolve_exposure_config_for_builder(override, runner.team, runner.experiment.start_date)
    else:
        # Same resolution as the main experiment query, so the actor list matches the counts.
        exposure_params = get_exposure_config_params_for_builder(
            runner.experiment.exposure_criteria, runner.team, runner.experiment.start_date
        )
        exposure_config = exposure_params.exposure_config
        activation_config = exposure_params.activation_config

    if runner.actors_query.multipleVariantHandling is not None:
        multiple_variant_handling = runner.actors_query.multipleVariantHandling
    else:
        multiple_variant_handling = runner.multiple_variant_handling

    if runner.actors_query.featureFlagKey:
        feature_flag_key = runner.actors_query.featureFlagKey
    else:
        feature_flag_key = runner.feature_flag_key

    funnel_step_breakdown_raw = runner.actors_query.funnelStepBreakdown
    if funnel_step_breakdown_raw is None:
        funnel_step_breakdown: str | int | float = ""
    elif isinstance(funnel_step_breakdown_raw, list):
        funnel_step_breakdown = funnel_step_breakdown_raw[0] if funnel_step_breakdown_raw else ""
    else:
        funnel_step_breakdown = funnel_step_breakdown_raw

    metric_name = runner.metric.name or get_default_metric_title(runner.metric.model_dump())
    tag_queries(
        product=Product.EXPERIMENTS,
        experiment_query_surface="actors",
        # No sub-queries here, but tag for a consistent group id per top-level query.
        experiment_query_group_id=uuid.uuid4(),
        experiment_exposures_path="direct_scan",
        experiment_metric_events_path="not_applicable",
        experiment_id=runner.experiment.id,
        experiment_name=runner.experiment.name,
        experiment_feature_flag_key=feature_flag_key,
        experiment_metric_uuid=runner.metric.uuid,
        experiment_metric_name=metric_name,
        experiment_actors_query_step=funnel_step,
        experiment_actors_query_variant=str(funnel_step_breakdown) if funnel_step_breakdown else "",
        experiment_actors_query_includes_recordings=runner.actors_query.includeRecordings or False,
    )

    builder = ExperimentFunnelActorsQueryBuilder(
        team=runner.team,
        feature_flag_key=feature_flag_key,
        exposure_config=exposure_config,
        filter_test_accounts=resolve_filter_test_accounts(runner.experiment.exposure_criteria),
        multiple_variant_handling=multiple_variant_handling,
        variants=runner.variants,
        date_range_query=runner.date_range_query,
        entity_key=runner.entity_key,
        metric=runner.metric,
        funnel_step=funnel_step,
        funnel_step_breakdown=funnel_step_breakdown,
        include_recordings=runner.actors_query.includeRecordings or False,
        activation_config=activation_config,
    )

    # Step 0 is the exposure step: return everyone exposed to the variant,
    # without funnel evaluation.
    if funnel_step == 0:
        return builder.build_exposure_actors_query()

    return builder.build_actors_query()
