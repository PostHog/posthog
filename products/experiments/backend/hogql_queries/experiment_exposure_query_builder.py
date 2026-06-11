from collections.abc import Callable

from posthog.schema import ExperimentEventExposureConfig, MultipleVariantHandling

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.hogql_queries.base_query_utils import event_or_action_to_filter
from products.experiments.backend.hogql_queries.breakdown_injector import BreakdownInjector
from products.experiments.backend.hogql_queries.experiment_query_context import ExperimentQueryContext


def _optimize_and_chain(expr: ast.Expr) -> ast.Expr:
    """
    Remove True constants from AND chains to preserve ClickHouse index optimizations.
    Keeps SQL templates readable while avoiding unnecessary conditions.
    """
    if not isinstance(expr, ast.And):
        return expr

    filtered = [e for e in expr.exprs if not (isinstance(e, ast.Constant) and e.value is True)]

    if len(filtered) == 0:
        return ast.Constant(value=True)
    elif len(filtered) == 1:
        return filtered[0]
    else:
        return ast.And(exprs=filtered)


class ExposureQueryBuilder:
    """
    Builds exposure queries shared across aggregate results, the exposures tab,
    precomputation, and actors queries.

    The exposure SELECT query (``select_query``/``_build_exposure_select_query``
    and its precomputed equivalent ``_build_exposure_from_precomputed``) returns
    one row per entity with the following output columns:

    - ``entity_id``: the experiment entity (person or group)
    - ``variant``: the attributed variant for the entity
    - ``first_exposure_time``: timestamp of the entity's first exposure
    - ``last_exposure_time``: timestamp of the entity's last exposure
    - ``exposure_event_uuid``: uuid of the first exposure event
    - ``exposure_session_id``: session id of the first exposure event
    - optional breakdown columns (one per configured breakdown), attributed from
      the entity's first exposure via ``argMin``

    The builder takes the experiment-level invariants via ``ExperimentQueryContext``
    plus the narrow inputs that depend on the current metric/precomputation state:
    the optional ``breakdown_injector``, a ``maturity_having_builder`` callable
    (which produces the maturity HAVING clause for a given timestamp expression),
    and the optional ``preaggregation_job_ids`` used to read from the precomputed
    exposures table instead of scanning events.
    """

    def __init__(
        self,
        context: ExperimentQueryContext,
        breakdown_injector: BreakdownInjector | None = None,
        maturity_having_builder: Callable[[str], ast.Expr | None] | None = None,
        preaggregation_job_ids: list[str] | None = None,
    ):
        self.context = context
        self.breakdown_injector = breakdown_injector
        self.maturity_having_builder = maturity_having_builder
        self.preaggregation_job_ids = preaggregation_job_ids

    def _maturity_having(self, timestamp_expr: str = "timestamp") -> ast.Expr | None:
        if self.maturity_having_builder is None:
            return None
        return self.maturity_having_builder(timestamp_expr)

    def timeseries_query(self) -> ast.SelectQuery:
        """
        Returns a query for exposure timeseries data.

        Generates daily exposure counts per variant, counting each entity
        only once on their first exposure day.

        Returns:
            SelectQuery with columns: day, variant, exposed_count
        """
        query = parse_select(
            """
            WITH first_exposures AS (
                SELECT
                    {entity_key} AS entity_id,
                    {variant_expr} AS variant,
                    toDate(toString(min(timestamp))) AS day
                FROM events
                WHERE {exposure_predicate}
                GROUP BY entity_id
            )

            SELECT
                first_exposures.day AS day,
                first_exposures.variant AS variant,
                count(first_exposures.entity_id) AS exposed_count
            FROM first_exposures
            WHERE notEmpty(variant)
            GROUP BY first_exposures.day, first_exposures.variant
            ORDER BY first_exposures.day ASC
            """,
            placeholders={
                "entity_key": parse_expr(self.context.entity_key),
                "variant_expr": self.build_variant_expr_for_mean(),
                "exposure_predicate": self.build_exposure_predicate(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def _build_precomputed_entity_id_expr(self) -> ast.Expr:
        return (
            parse_expr("toUUID(t.entity_id)") if self.context.entity_key == "person_id" else parse_expr("t.entity_id")
        )

    def _build_precomputed_variant_expr(self) -> ast.Expr:
        if self.context.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr("argMin(t.variant, t.first_exposure_time)")
        return parse_expr(
            "if(uniqExact(t.variant) > 1, {multiple_key}, argMin(t.variant, t.first_exposure_time))",
            placeholders={"multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY)},
        )

    def daily_exposures_from_precomputed(self, job_ids: list[str]) -> ast.SelectQuery:
        """
        Reads from the precomputed table and aggregates into day/variant/count.
        Used by the Exposures tab in the experiment UI.
        """
        entity_id_expr = self._build_precomputed_entity_id_expr()
        variant_expr = self._build_precomputed_variant_expr()

        query = parse_select(
            """
            WITH deduplicated AS (
                SELECT
                    {entity_id_expr} AS entity_id,
                    {variant_expr} AS variant,
                    min(t.first_exposure_time) AS first_exposure_time
                FROM experiment_exposures_preaggregated AS t
                WHERE t.job_id IN {job_ids}
                    AND t.team_id = {team_id}
                    AND t.first_exposure_time >= {date_from}
                    AND t.first_exposure_time <= {date_to}
                GROUP BY entity_id
            )
            SELECT
                toDate(toString(first_exposure_time)) AS day,
                variant AS variant,
                count(entity_id) AS exposed_count
            FROM deduplicated
            WHERE notEmpty(variant)
            GROUP BY day, variant
            ORDER BY day ASC
            """,
            placeholders={
                "entity_id_expr": entity_id_expr,
                "variant_expr": variant_expr,
                "job_ids": ast.Constant(value=job_ids),
                "team_id": ast.Constant(value=self.context.team.id),
                "date_from": self.context.date_range_query.date_from_as_hogql(),
                "date_to": self.context.date_range_query.date_to_as_hogql(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def build_test_accounts_filter(self) -> ast.Expr:
        if (
            self.context.filter_test_accounts
            and isinstance(self.context.team.test_account_filters, list)
            and len(self.context.team.test_account_filters) > 0
        ):
            return ast.And(
                exprs=[
                    property_to_expr(property, self.context.team) for property in self.context.team.test_account_filters
                ]
            )
        return ast.Constant(value=True)

    def build_variant_property(self) -> ast.Field:
        """Derive which event property that should be used for variants"""

        # $feature_flag_called events are special as we can use the $feature_flag_response
        if (
            isinstance(self.context.exposure_config, ExperimentEventExposureConfig)
            and self.context.exposure_config.event == "$feature_flag_called"
        ):
            return ast.Field(chain=["properties", "$feature_flag_response"])

        return ast.Field(chain=["properties", f"$feature/{self.context.feature_flag_key}"])

    def build_exposure_event_predicate(self) -> ast.Expr:
        """
        Builds the event predicate for exposure filtering (without timestamp conditions).

        This handles:
        - Custom exposure events via event_or_action_to_filter
        - Special $feature_flag_called filtering (matching the flag key)

        Used by both _build_exposure_predicate() and get_exposure_query_for_precomputation().
        """
        event_predicate = event_or_action_to_filter(self.context.team, self.context.exposure_config)

        # $feature_flag_called events are special. We need to check that the property
        # $feature_flag matches the flag
        if (
            isinstance(self.context.exposure_config, ExperimentEventExposureConfig)
            and self.context.exposure_config.event == "$feature_flag_called"
        ):
            flag_property = f"$feature_flag"
            event_predicate = ast.And(
                exprs=[
                    event_predicate,
                    parse_expr(
                        "{flag_property} = {feature_flag_key}",
                        placeholders={
                            "flag_property": ast.Field(chain=["properties", flag_property]),
                            "feature_flag_key": ast.Constant(value=self.context.feature_flag_key),
                        },
                    ),
                ]
            )

        return event_predicate

    def build_exposure_predicate(self) -> ast.Expr:
        """
        Builds the exposure predicate as an AST expression.
        """
        return _optimize_and_chain(
            parse_expr(
                """
                timestamp >= {date_from}
                AND timestamp <= {date_to}
                AND {event_predicate}
                AND {test_accounts_filter}
                AND {variant_property} IN {variants}
                """,
                placeholders={
                    "date_from": self.context.date_range_query.date_from_as_hogql(),
                    "date_to": self.context.date_range_query.date_to_as_hogql(),
                    "event_predicate": self.build_exposure_event_predicate(),
                    "variant_property": self.build_variant_property(),
                    "variants": ast.Constant(value=list(self.context.variants)),
                    "test_accounts_filter": self.build_test_accounts_filter(),
                },
            )
        )

    def select_query(self) -> ast.SelectQuery:
        if self.preaggregation_job_ids and not self.context.breakdowns:
            return self.precomputed_select_query(self.preaggregation_job_ids)

        return self._build_exposure_select_query()

    def _build_exposure_select_query(self) -> ast.SelectQuery:
        exposure_query = parse_select(
            """
                SELECT
                    {entity_key} AS entity_id,
                    {variant_expr} AS variant,
                    min(timestamp) AS first_exposure_time,
                    max(timestamp) AS last_exposure_time,
                    argMin(uuid, timestamp) AS exposure_event_uuid,
                    argMin(`$session_id`, timestamp) AS exposure_session_id
                    -- breakdown columns added programmatically below
                FROM events
                WHERE {exposure_predicate}
                GROUP BY entity_id
                -- breakdown columns added programmatically below
            """,
            placeholders={
                "entity_key": parse_expr(self.context.entity_key),
                "variant_expr": self.build_variant_expr_for_mean(),
                "exposure_predicate": self.build_exposure_predicate(),
            },
        )
        assert isinstance(exposure_query, ast.SelectQuery)

        # Inject breakdown columns into the exposure query if needed
        if self.breakdown_injector:
            breakdown_exprs = self.breakdown_injector.build_breakdown_exprs(table_alias="")

            # Add breakdown columns to SELECT using argMin attribution
            # This ensures each user is attributed to exactly one breakdown value
            # (from their first exposure), preventing duplicate counting when users
            # have multiple exposures with different breakdown property values
            for alias, expr in breakdown_exprs:
                # Use argMin to attribute breakdown value from first exposure
                # This matches the variant attribution logic
                breakdown_attributed = parse_expr("argMin({expr}, timestamp)", placeholders={"expr": expr})
                exposure_query.select.append(ast.Alias(alias=alias, expr=breakdown_attributed))

        # Filter out users whose conversion window hasn't elapsed yet
        maturity_having = self._maturity_having()
        if maturity_having is not None:
            if exposure_query.having is None:
                exposure_query.having = maturity_having
            else:
                exposure_query.having = ast.And(exprs=[exposure_query.having, maturity_having])

        return exposure_query

    def precomputed_select_query(self, job_ids: list[str]) -> ast.SelectQuery:
        """
        Builds the exposure CTE by reading from the lazy-computed table instead of scanning events.

        Re-aggregates across jobs since the same user can appear in multiple time-window jobs.
        Returns the same column shape as _build_exposure_select_query().

        Important: Jobs can cover broader time ranges than the experiment (for reusability),
        so we must filter by experiment start/end dates to avoid including exposures outside
        the experiment window.
        """
        # The lazy-computed table stores entity_id as String, but person_id is UUID in events.
        # Cast back to match the type expected by downstream JOINs.
        entity_id_expr = self._build_precomputed_entity_id_expr()
        variant_expr = self._build_precomputed_variant_expr()

        query = parse_select(
            """
                SELECT
                    {entity_id_expr} AS entity_id,
                    {variant_expr} AS variant,
                    min(t.first_exposure_time) AS first_exposure_time,
                    max(t.last_exposure_time) AS last_exposure_time,
                    argMin(t.exposure_event_uuid, t.first_exposure_time) AS exposure_event_uuid,
                    argMin(t.exposure_session_id, t.first_exposure_time) AS exposure_session_id
                FROM experiment_exposures_preaggregated AS t
                WHERE t.job_id IN {job_ids}
                    AND t.team_id = {team_id}
                    AND t.first_exposure_time >= {date_from}
                    AND t.first_exposure_time <= {date_to}
                GROUP BY entity_id
            """,
            placeholders={
                "entity_id_expr": entity_id_expr,
                "variant_expr": variant_expr,
                "job_ids": ast.Constant(value=job_ids),
                "team_id": ast.Constant(value=self.context.team.id),
                "date_from": self.context.date_range_query.date_from_as_hogql(),
                "date_to": self.context.date_range_query.date_to_as_hogql(),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        # Filter out users whose conversion window hasn't elapsed yet
        maturity_having = self._maturity_having(timestamp_expr="t.last_exposure_time")
        if maturity_having is not None:
            if query.having is None:
                query.having = maturity_having
            else:
                query.having = ast.And(exprs=[query.having, maturity_having])

        return query

    def precomputation_query(self) -> tuple[str, dict[str, ast.Expr]]:
        """
        Returns the exposure query and placeholders for lazy computation.

        The query string uses {time_window_min} and {time_window_max} placeholders
        which are filled in by the lazy computation system for each daily bucket.
        Other placeholders are returned in the dict and should be passed to
        ensure_precomputed().

        Returns:
            Tuple of (query_string, placeholders_dict)
        """
        # Query template with placeholders
        # Note: uses < for time_window_max (exclusive end for bucket boundaries)
        # vs <= in normal query (inclusive end for experiment boundary)
        # Keep in sync with _build_exposure_select_query
        #
        # The time_window_min/max placeholders define the job's cache window
        # (UTC-day-aligned). The experiment_date_from/to placeholders tighten
        # the scan to the actual experiment dates so that variant aggregation
        # only considers events within the experiment.
        query_string = """
            SELECT
                {entity_key} AS entity_id,
                {variant_expr} AS variant,
                min(timestamp) AS first_exposure_time,
                max(timestamp) AS last_exposure_time,
                argMin(uuid, timestamp) AS exposure_event_uuid,
                argMin(`$session_id`, timestamp) AS exposure_session_id,
                [] AS breakdown_value
            FROM events
            WHERE timestamp >= {time_window_min}
                AND timestamp < {time_window_max}
                AND timestamp >= {experiment_date_from}
                AND timestamp <= {experiment_date_to}
                AND {event_predicate}
                AND {test_accounts_filter}
                AND {variant_property} IN {variants}
            GROUP BY entity_id
        """

        placeholders = {
            "entity_key": parse_expr(self.context.entity_key),
            "variant_expr": self.build_variant_expr_for_mean(),
            "event_predicate": self.build_exposure_event_predicate(),
            "test_accounts_filter": self.build_test_accounts_filter(),
            "variant_property": self.build_variant_property(),
            "variants": ast.Constant(value=list(self.context.variants)),
            "experiment_date_from": self.context.date_range_query.date_from_as_hogql(),
            "experiment_date_to": self.context.date_range_query.date_to_as_hogql(),
        }

        return query_string, placeholders

    def build_variant_expr_for_mean(self) -> ast.Expr:
        """
        Builds the variant selection expression for mean metrics based on multiple variant handling.
        """

        if self.context.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr(
                "argMin({variant_property}, timestamp)",
                placeholders={
                    "variant_property": self.build_variant_property(),
                },
            )
        else:
            return parse_expr(
                "if(uniqExact({variant_property}) > 1, {multiple_key}, any({variant_property}))",
                placeholders={
                    "variant_property": self.build_variant_property(),
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )
