from typing import cast

from posthog.schema import ActionsNode, ExperimentEventExposureConfig, ExperimentFunnelMetric, MultipleVariantHandling

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team

from products.experiments.backend.hogql_queries.base_query_utils import funnel_steps_to_filter
from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder


class ExperimentFunnelActorsQueryBuilder:
    """
    Builds the actors query for experiment funnels with exposure filtering.

    Reuses the exposure and funnel fragment builders for exposure filtering and funnel
    steps. The actors query has a different output contract from the aggregate experiment
    results, so the actor selection and filtering live here.

    Query structure:
    1. exposures CTE: First exposure per entity (same as main query)
    2. metric_events CTE: All metric events (funnel steps 1-N)
    3. entity_metrics CTE: Funnel evaluation with exposure as step 0
    4. actors query: Filter to specific step and variant, return person details
    """

    def __init__(
        self,
        team: Team,
        feature_flag_key: str,
        exposure_config: ExperimentEventExposureConfig | ActionsNode,
        filter_test_accounts: bool,
        multiple_variant_handling: MultipleVariantHandling,
        variants: list[str],
        date_range_query: QueryDateRange,
        entity_key: str,
        metric: ExperimentFunnelMetric,
        funnel_step: int,
        funnel_step_breakdown: str | int | float,
        include_recordings: bool,
        activation_config: ExperimentEventExposureConfig | ActionsNode | None = None,
    ):
        self.team = team
        self.metric = metric
        self.date_range_query = date_range_query
        self.entity_key = entity_key
        self.funnel_step = funnel_step
        self.funnel_step_breakdown = funnel_step_breakdown
        self.include_recordings = include_recordings

        # The funnel fragment builder reads shared metric and exposure state through an
        # ExperimentQueryBuilder, so keep one here instead of re-deriving that state.
        self._query_builder = ExperimentQueryBuilder(
            team=team,
            feature_flag_key=feature_flag_key,
            exposure_config=exposure_config,
            filter_test_accounts=filter_test_accounts,
            multiple_variant_handling=multiple_variant_handling,
            variants=variants,
            date_range_query=date_range_query,
            entity_key=entity_key,
            metric=metric,
            activation_config=activation_config,
        )

    def build_actors_query(self) -> ast.SelectQuery:
        """
        Returns persons who:
        - Were exposed to the specified variant
        - Completed the specified funnel step (or dropped off at that step)
        - Only considers events that occurred AFTER their first exposure
        """
        query = self._build_base_query_with_ctes()
        query = self._add_actors_selection(query)
        query = self._add_actors_where_clause(query)

        # Order by entity_id so that results are deterministic.
        query.order_by = [ast.OrderExpr(expr=ast.Field(chain=["entity_id"]))]

        return query

    def build_exposure_actors_query(self) -> ast.SelectQuery:
        """
        Build actors query for the exposure step (funnel step 0).

        Unlike the metric-step actors query, this needs no funnel evaluation: the
        exposure bar counts everyone who was exposed to a variant, so we select
        straight from the exposures CTE. Recordings, when requested, point at the
        first exposure event.
        """
        exposure_select_query = self._query_builder._exposure_query_builder().select_query()

        query = cast(
            ast.SelectQuery,
            parse_select(
                "WITH exposures AS ({exposure_query}) SELECT * FROM exposures",
                placeholders={"exposure_query": exposure_select_query},
            ),
        )

        select_exprs: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["entity_id"])),
            ast.Alias(alias="variant", expr=ast.Field(chain=["variant"])),
        ]

        if self.include_recordings:
            # Mirror the (timestamp, uuid, $session_id, $window_id) tuple shape the
            # actors runner expects, sourced from the first exposure event.
            select_exprs.append(
                ast.Alias(
                    alias="matching_events",
                    expr=parse_expr("array(tuple(first_exposure_time, exposure_event_uuid, exposure_session_id, ''))"),
                )
            )

        query.select = select_exprs
        query.where = self._build_variant_filter()
        query.order_by = [ast.OrderExpr(expr=ast.Field(chain=["actor_id"]))]

        return query

    def _build_base_query_with_ctes(self) -> ast.SelectQuery:
        """
        Build query with exposures, metric_events, and entity_metrics CTEs.

        This mirrors the main experiment query structure but focuses on
        individual users rather than aggregate statistics.
        """
        exposure_select_query = self._query_builder._exposure_query_builder().select_query()
        metric_events_cte = self._build_metric_events_cte()
        entity_metrics_cte = self._build_entity_metrics_cte()

        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            WITH
                exposures AS ({exposure_query}),
                metric_events AS ({metric_events_query}),
                entity_metrics AS ({entity_metrics_query})

            SELECT * FROM entity_metrics
            """,
                placeholders={
                    "exposure_query": exposure_select_query,
                    "metric_events_query": metric_events_cte,
                    "entity_metrics_query": entity_metrics_cte,
                },
            ),
        )

        return query

    def _build_metric_events_cte(self) -> ast.SelectQuery:
        """
        Build the metric_events CTE with all funnel step events.

        Includes step_0 (exposure), step_1, step_2, ... (metric events)
        """
        assert isinstance(self.metric, ExperimentFunnelMetric), "metric must be ExperimentFunnelMetric"

        date_from = self.date_range_query.date_from_as_hogql()
        date_to = self.date_range_query.date_to_as_hogql()
        funnel_steps_filter = funnel_steps_to_filter(self.team, self.metric.series)
        exposure_predicate = self._query_builder._exposure_query_builder().build_exposure_step_event_predicate()

        query = cast(
            ast.SelectQuery,
            parse_select(
                """
            SELECT
                {entity_key} AS entity_id,
                timestamp,
                uuid,
                properties.$session_id AS session_id,
                1 * ({exposure_predicate}) AS step_0
            FROM events
            WHERE timestamp >= {date_from}
                AND timestamp <= {date_to}
                AND ({exposure_predicate} OR {funnel_steps_filter})
            """,
                placeholders={
                    "entity_key": parse_expr(self.entity_key),
                    "exposure_predicate": exposure_predicate,
                    "funnel_steps_filter": funnel_steps_filter,
                    "date_from": date_from,
                    "date_to": date_to,
                },
            ),
        )

        # The SELECT above already defines step_0, so take only the metric step columns.
        all_step_columns = self._query_builder._funnel_query_builder().build_funnel_step_columns()
        step_columns = all_step_columns[1:]
        query.select.extend(step_columns)

        return query

    def _build_entity_metrics_cte(self) -> ast.SelectQuery:
        """
        Build entity_metrics CTE with funnel evaluation.

        Uses aggregate_funnel_array UDF with exposure as step 0.
        Includes matched_events_array for recording support.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric), "metric must be ExperimentFunnelMetric"

        # An unordered funnel needs the temporal filter. Activation mode needs it for
        # ordered funnels too, matching the main funnel query: step_0 rows are plain
        # activation-event matches, so events before the qualifying activation must be excluded.
        is_unordered = self.metric.funnel_order_type == "unordered"
        is_activation_mode = self._query_builder.context.activation_config is not None
        temporal_filter = (
            "AND metric_events.timestamp >= exposures.first_exposure_time" if is_unordered or is_activation_mode else ""
        )

        if self.metric.conversion_window is not None and self.metric.conversion_window_unit is not None:
            from products.experiments.backend.hogql_queries.base_query_utils import conversion_window_to_seconds

            conversion_window_seconds = conversion_window_to_seconds(
                self.metric.conversion_window, self.metric.conversion_window_unit
            )
        else:
            # Without a conversion window, all events count. 3 years is large enough to act as no limit.
            conversion_window_seconds = 3 * 365 * 24 * 60 * 60

        num_steps = len(self.metric.series) + 1  # +1 for exposure
        funnel_order_type = self.metric.funnel_order_type or "ordered"

        step_conditions = [f"{i + 1} * metric_events.step_{i}" for i in range(num_steps)]
        step_conditions_str = ", ".join(step_conditions)

        if self.include_recordings:
            recordings_fields = """
                groupArray(tuple(metric_events.timestamp, metric_events.uuid, metric_events.session_id, '')) as user_events,
                mapFromArrays(arrayMap(x -> x.2, user_events), user_events) as user_events_map,
                arraySort(x -> -x.1,
                    aggregate_funnel_array(
                        {num_steps},
                        {conversion_window_seconds},
                        'first_touch',
                        '{funnel_order_type}',
                        array(array('')),
                        [],
                        arraySort(t -> t.1, groupArray(tuple(
                            toFloat(metric_events.timestamp),
                            metric_events.uuid,
                            array(''),
                            arrayFilter(x -> x > 0, [{step_conditions_str}])
                        )))
                    )
                )[1] as af_tuple,
                af_tuple.1 as step_reached,
                af_tuple.4 as matched_event_uuids_array_array,
                arrayMap(matched_event_uuids_array -> arrayMap(event_uuid -> user_events_map[event_uuid], arrayDistinct(matched_event_uuids_array)), matched_event_uuids_array_array) as matched_events_array
            """.format(
                num_steps=num_steps,
                conversion_window_seconds=conversion_window_seconds,
                funnel_order_type=funnel_order_type,
                step_conditions_str=step_conditions_str,
            )
        else:
            from products.experiments.backend.hogql_queries.base_query_utils import funnel_evaluation_expr

            funnel_agg_expr = funnel_evaluation_expr(
                self.team,
                self.metric,
                events_alias="metric_events",
                include_exposure=True,
            )
            recordings_fields = ""

        # recordings_fields and temporal_filter are built internally from validated values. The
        # semgrep rule in .semgrep/rules/security/hogql-no-fstring.yaml exempts them.
        query = cast(
            ast.SelectQuery,
            parse_select(
                f"""
            SELECT
                exposures.entity_id AS entity_id,
                exposures.variant AS variant,
                exposures.exposure_event_uuid AS exposure_event_uuid
                {("," + recordings_fields) if recordings_fields else ""}
            FROM exposures
            LEFT JOIN metric_events
                ON exposures.entity_id = metric_events.entity_id
                {temporal_filter}
            GROUP BY
                exposures.entity_id,
                exposures.variant,
                exposures.exposure_event_uuid
            """
            ),
        )

        # funnel_evaluation_expr returns tuple(step_reached, ...), so element 1 is step_reached.
        if not self.include_recordings:
            query.select.append(
                ast.Alias(
                    alias="step_reached",
                    expr=ast.TupleAccess(tuple=funnel_agg_expr, index=1, nullish=False),
                )
            )

        return query

    def _add_actors_selection(self, query: ast.SelectQuery) -> ast.SelectQuery:
        """Selects actor_id, variant, and matching_events when recordings are requested."""
        select_exprs: list[ast.Expr] = [
            ast.Alias(alias="actor_id", expr=ast.Field(chain=["entity_id"])),
            ast.Alias(alias="variant", expr=ast.Field(chain=["variant"])),
        ]

        if self.include_recordings:
            # For conversions and drop-offs, select the events of the reached step.
            # step_reached is 0-indexed and HogQL arrays are 1-indexed.
            select_exprs.append(
                ast.Alias(
                    alias="matching_events",
                    expr=parse_expr("matched_events_array[step_reached + 1]"),
                )
            )

        query.select = select_exprs
        return query

    def _add_actors_where_clause(self, query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Filters to the requested step and variant. Mirrors the step filtering in
        FunnelUDF._get_funnel_person_step_condition.
        """
        conditions: list[ast.Expr] = []

        # step_reached is 0-indexed and counts the exposure as step 0:
        # - step_reached = 0: completed exposure only
        # - step_reached = 1: completed exposure + first metric
        # - step_reached = 2: completed exposure + first + second metric
        # funnelStep is 1-indexed for metric steps and does not count the exposure:
        # - funnelStep = 1: first metric step
        # - funnelStep = 2: second metric step

        if self.funnel_step >= 0:
            # Conversion: the user reached this step, so step_reached >= funnel_step.
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["step_reached"]),
                    right=ast.Constant(value=self.funnel_step),
                )
            )
        else:
            # Drop-off: the user reached the prior step but not this one. For funnelStep=-N,
            # that is step_reached >= N-1 AND step_reached < N.
            target_step = abs(self.funnel_step)

            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["step_reached"]),
                    right=ast.Constant(value=target_step - 1),
                )
            )
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["step_reached"]),
                    right=ast.Constant(value=target_step),
                )
            )

        variant_filter = self._build_variant_filter()
        if variant_filter is not None:
            conditions.append(variant_filter)

        query.where = ast.And(exprs=conditions) if conditions else None
        return query

    def _build_variant_filter(self) -> ast.Expr | None:
        """Build a `variant = ...` filter, or None when no variant is requested."""
        if not self.funnel_step_breakdown:
            return None

        if isinstance(self.funnel_step_breakdown, int | float):
            variant_value = str(int(self.funnel_step_breakdown))
        else:
            variant_value = self.funnel_step_breakdown

        return parse_expr(
            "variant = {variant}",
            {"variant": ast.Constant(value=variant_value)},
        )
