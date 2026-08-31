import uuid
import threading
from collections.abc import Sequence
from dataclasses import (
    dataclass,
    field as dataclass_field,
)
from datetime import datetime, timedelta
from typing import ClassVar, Optional, Union

import structlog

from posthog.schema import (
    AttributionMode,
    BaseMathType,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    MarketingAnalyticsDrillDownLevel,
    PropertyMathType,
)

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import ChannelTypeExprs, create_channel_type_expr
from posthog.hogql.database.schema.exchange_rate import convert_currency_call
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.timings import HogQLTimings

from posthog.dataclasses import frozen
from posthog.models import PropertyDefinition, Team, User

from products.access_control.backend.property_access_control import get_restricted_property_names
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
)

from .adapters.factory import MarketingSourceFactory
from .attribution_weights import (
    DAY_IN_SECONDS,
    build_linear_weights,
    build_position_based_weights,
    build_time_decay_weights,
)
from .conversion_goal_conditions import (
    action_match_expr,
    add_conversion_goal_property_filters,
    conversion_goal_match_expr,
)
from .marketing_analytics_config import MarketingAnalyticsConfig
from .marketing_lazy_precompute import marketing_ensure_precomputed
from .metrics import CONVERSION_GOAL_PRECOMPUTE_FALLBACK_COUNTER
from .utils import build_source_normalization_expr

# Freshness windows for the precompute read path. The Dagster warmer
# (products/marketing_analytics/dags/marketing_precompute.py) MUST drive ensure_precomputed with this
# exact schedule — otherwise the read path's freshness check would treat warmed rows as stale and
# recompute them inline, defeating the warm-up.
PRECOMPUTE_TTL_SECONDS = {"0d": 15 * 60, "1d": 60 * 60, "7d": 24 * 60 * 60, "default": 7 * 24 * 60 * 60}

logger = structlog.get_logger(__name__)


# kw_only off: the TRACKED_FIELDS table below reads as a table, one positional row per field.
@frozen(kw_only=False)
class TrackedField:
    """A field tracked through the conversion attribution pipeline for channel classification."""

    name: str  # Pipeline-internal name (e.g., "campaign", "referring_domain")
    event_property: str  # Default event property name (e.g., "utm_campaign", "$referring_domain")
    schema_map_key: str | None = None  # Key in schema_map for DataWarehouse custom mapping
    default_value: str = ""  # Default when field is empty/missing in organic context
    click_identifier: bool = False  # Ad click id (gclid, fbclid, …): on its own it marks a paid touchpoint
    click_id_source: str = ""  # Ad network this click id names when the pageview carries no utm_source

    @property
    def conversion_array(self) -> str:
        return f"conversion_{self.name}s"

    @property
    def utm_array(self) -> str:
        return f"utm_{self.name}s"

    @property
    def conversion_value(self) -> str:
        return f"conversion_{self.name}"

    @property
    def fallback_value(self) -> str:
        return f"fallback_{self.name}"

    @property
    def attributed_name(self) -> str:
        return f"{self.name}_name"


# Fields tracked through the 4-stage attribution pipeline.
# source (plus the click identifiers) gates whether a pageview counts as a paid touchpoint.
TRACKED_FIELDS: list[TrackedField] = [
    TrackedField("campaign", "utm_campaign", "utm_campaign_name"),
    TrackedField("source", "utm_source", "utm_source_name"),
    TrackedField("medium", "utm_medium", "utm_medium_name"),
    TrackedField("content", "utm_content", "utm_content_name"),
    TrackedField("term", "utm_term", "utm_term_name"),
    TrackedField("referring_domain", "$referring_domain", None, "$direct"),
    # Unprefixed: these are the names the SDK writes on the event (see CAMPAIGN_PROPERTIES
    # in posthog/taxonomy/taxonomy.py). The `$initial_*` forms channel_type reads are
    # person-scoped copies derived from these, and `$gclid` exists nowhere at all.
    TrackedField("gclid", "gclid", click_identifier=True, click_id_source="google"),
    # Not a click identifier: Facebook appends fbclid to every outbound link, organic posts
    # included, so it names the network without saying the click was paid. `channel_type`'s paid
    # branch and `attribution_health`'s paid counter both exclude it for that reason; treating it
    # as evidence here would admit organic Facebook traffic as a paid touchpoint and then have
    # channel_type call the same row organic.
    TrackedField("fbclid", "fbclid"),
    TrackedField("gad_source", "gad_source", click_identifier=True, click_id_source="google"),
]

# Property names of the ad click identifiers. A pageview that carries one of these is a paid
# touchpoint even with no utm_source. Deliberately only the Google Ads pair — see fbclid above.
# referring_domain is out too: it defaults to $direct on organic traffic, so it is not evidence
# of an ad click.
CLICK_ID_PROPERTIES: list[str] = [f.event_property for f in TRACKED_FIELDS if f.click_identifier]

CLICK_ID_FIELDS: list[TrackedField] = [f for f in TRACKED_FIELDS if f.click_identifier]


def build_pageview_touchpoint_condition(source_field: str) -> ast.Expr:
    """A pageview is a paid touchpoint when it carries utm_source or any ad click identifier.

    utm_campaign is optional — a source alone is enough. The precompute path
    (build_touchpoints_precompute_query) and the fallback path (_build_pageview_event_filter,
    _build_utm_pageview_array) must all gate on this same rule, or the two disagree and one
    window's touchpoints go missing.
    """

    def not_empty(event_property: str) -> ast.Expr:
        return ast.Call(
            name="notEmpty",
            args=[
                ast.Call(
                    name="toString",
                    args=[
                        ast.Call(
                            name="ifNull",
                            args=[ast.Field(chain=["events", "properties", event_property]), ast.Constant(value="")],
                        )
                    ],
                )
            ],
        )

    return ast.Or(exprs=[not_empty(source_field), *[not_empty(p) for p in CLICK_ID_PROPERTIES]])


def build_touchpoints_precompute_query() -> ast.SelectQuery:
    """Config-agnostic touchpoint precompute: one row per UTM-tagged pageview, independent of any
    goal, attribution mode or window. Every attribution query reuses the same materialized rows
    (identical query hash → one shared lazy-computation job per team); attribution happens at read
    time. Columns are aliased to the marketing_touchpoints_preaggregated schema — the lazy framework
    prepends team_id/job_id and appends expires_at, and resolves the time_window placeholders per job.
    """

    def _prop_to_string(event_property: str) -> ast.Expr:
        return ast.Call(
            name="toString",
            args=[
                ast.Call(
                    name="ifNull",
                    args=[ast.Field(chain=["events", "properties", event_property]), ast.Constant(value="")],
                )
            ],
        )

    select_columns: list[ast.Expr] = [
        ast.Alias(alias="person_id", expr=ast.Field(chain=["events", "person_id"])),
        ast.Alias(alias="touchpoint_timestamp", expr=ast.Field(chain=["events", "timestamp"])),
    ]
    for tracked in TRACKED_FIELDS:
        select_columns.append(ast.Alias(alias=tracked.attributed_name, expr=_prop_to_string(tracked.event_property)))

    # Touchpoint definition shared with the fallback path (build_pageview_touchpoint_condition):
    # utm_source or any click id, campaign optional — keep the two paths in lockstep.
    return ast.SelectQuery(
        select=select_columns,
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value="$pageview"),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "timestamp"]),
                    op=ast.CompareOperationOp.GtEq,
                    right=ast.Placeholder(expr=ast.Field(chain=["time_window_min"])),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "timestamp"]),
                    op=ast.CompareOperationOp.LtEq,
                    right=ast.Placeholder(expr=ast.Field(chain=["time_window_max"])),
                ),
                build_pageview_touchpoint_condition("utm_source"),
            ]
        ),
    )


class SharedTouchpointsPrecompute:
    """One touchpoints materialization shared by every conversion goal in a request.

    `build_touchpoints_precompute_query()` takes no goal input and the range depends only on the
    team's attribution window, so the call every goal makes is byte-identical. Each goal was driving
    its own `ensure_precomputed` for the same window: redundant ClickHouse work, and concurrent
    materializations of the same window risk landing under separate job_ids.

    The first goal to ask does the work; the rest reuse its result. Goals run in a thread pool, hence
    the lock.
    """

    def __init__(self, team: Team, config: MarketingAnalyticsConfig) -> None:
        self._team = team
        self._config = config
        self._lock = threading.Lock()
        self._result: Optional[LazyComputationResult] = None
        self._range: Optional[tuple[datetime, datetime]] = None

    def get(self, date_from: datetime, date_to: datetime) -> LazyComputationResult:
        with self._lock:
            if self._result is None:
                window = timedelta(days=self._config.attribution_window_days)
                self._range = (date_from, date_to)
                self._result = marketing_ensure_precomputed(
                    team=self._team,
                    insert_query=build_touchpoints_precompute_query(),
                    time_range_start=date_from - window,
                    time_range_end=date_to,
                    ttl_seconds=PRECOMPUTE_TTL_SECONDS,
                    table=LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED,
                )
            elif self._range != (date_from, date_to):
                # One handle is scoped to one read, whose goals all share its date range. Handing back
                # the first caller's window for a different range would attribute one window's
                # touchpoints to another — silently, and in the shape of the double-counting bug this
                # class exists to prevent.
                raise ValueError(
                    f"SharedTouchpointsPrecompute is scoped to one date range per read: "
                    f"materialized {self._range}, asked for {(date_from, date_to)}"
                )
            return self._result


def goal_sums_a_property(goal: Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]) -> bool:
    """Whether a goal's column holds a summed property value rather than a conversion count.

    Everything that divides by a goal's column — the ROAS numerator, the CAC denominator, and the
    processor-selection guards that decide which goals to build — needs the same answer, so they
    all route through here rather than each re-deriving it from `math` and drifting apart.
    """
    math_type = goal.math
    return math_type in ["sum", PropertyMathType.SUM] or str(math_type).endswith("_sum")


# Mutable by design: `precompute_stale` is set while building the query, and each
# processor owns a `timings` clone the runner merges back after the pool joins.
@dataclass(frozen=False)
class ConversionGoalProcessor:
    """
    Processes conversion goals for marketing analytics queries.

    This class handles two main query types:
    1. Array-based attribution: For Events/Actions with sophisticated UTM tracking
    2. Direct field access: For DataWarehouse nodes with simple field mapping
    """

    goal: Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]
    index: int
    team: Team
    config: MarketingAnalyticsConfig
    # Requesting user, threaded through to enforce per-user property access on the precompute path.
    user: Optional[User] = None
    # Per-goal timings. HogQLTimings is not thread safe and goals are built in parallel, so each
    # processor owns a clone (see HogQLTimings.clone_for_subquery); the runner merges them back once
    # the pool has joined. Defaults to a standalone instance for callers outside the read path.
    timings: HogQLTimings = dataclass_field(default_factory=HogQLTimings)
    # Set when this goal's precompute was served from expired-within-grace rows instead of rebuilt. Read
    # by the runner after the goal pool joins, to schedule one background revalidation for the read.
    precompute_stale: bool = False

    _UTM_LEVEL_FIELD_MAP: ClassVar[dict[MarketingAnalyticsDrillDownLevel, str]] = {
        MarketingAnalyticsDrillDownLevel.MEDIUM: "medium",
        MarketingAnalyticsDrillDownLevel.CONTENT: "content",
        MarketingAnalyticsDrillDownLevel.TERM: "term",
    }

    def get_cte_name(self) -> str:
        """Get unique CTE name for this conversion goal"""
        return self.goal.conversion_goal_id

    def get_table_name(self) -> str:
        """Get table name for querying based on goal type"""
        if self.goal.kind in ["EventsNode", "ActionsNode"]:
            return "events"
        elif self.goal.kind == "DataWarehouseNode" and isinstance(self.goal, ConversionGoalFilter3):
            return self.goal.table_name
        return "events"

    def get_utm_expressions(self) -> tuple[ast.Expr, ast.Expr]:
        """Build UTM campaign and source expressions for different node types"""
        schema_map = self.goal.schema_map
        campaign_field = schema_map.get("utm_campaign_name", "utm_campaign")
        source_field = schema_map.get("utm_source_name", "utm_source")

        if self.goal.kind in ["EventsNode", "ActionsNode"]:
            # For events table, UTM data is in properties
            return (
                ast.Field(chain=["events", "properties", campaign_field]),
                ast.Field(chain=["events", "properties", source_field]),
            )
        else:
            # For data warehouse, UTM data is in direct columns
            return (
                ast.Field(chain=[campaign_field]),
                ast.Field(chain=[source_field]),
            )

    def _resolve_field_name(self, field: TrackedField) -> str:
        """Resolve a tracked field's event property name, checking schema_map for overrides."""
        if field.schema_map_key:
            return self.goal.schema_map.get(field.schema_map_key, field.event_property)
        return field.event_property

    def sums_a_property(self) -> bool:
        """Whether this goal's column holds a summed property value rather than a conversion count.

        Shares the branch with `get_select_field` via `goal_sums_a_property` rather than re-deriving
        it from `math`.
        """
        return goal_sums_a_property(self.goal)

    def get_count_field(self) -> ast.Expr:
        """Conversions counted, whatever the goal's own math is.

        A summing goal's column holds money, so anything needing "how many" — cost per
        customer, say — can't divide by it.

        Branches on attribution mode for the same reason `_get_aggregation_expr` does: multi-touch
        explodes one conversion into a row per touchpoint, so counting rows would report a purchase
        with three touchpoints as three customers. The weights sum to 1.0 per conversion, so summing
        them recovers the count with each touchpoint credited its share. A goal that scans directly
        never explodes and has no weight column to read.
        """
        if self.config.is_multi_touch and self.uses_attribution_pipeline:
            return ast.Call(name="sum", args=[ast.Field(chain=["attribution_weight"])])
        return ast.Call(name="count", args=[ast.Constant(value="*")])

    def get_select_field(self) -> ast.Expr:
        """Build select field expression based on math aggregation type"""
        math_type = self.goal.math

        if math_type in [BaseMathType.DAU, "dau"]:
            return self._build_dau_select()
        elif self.sums_a_property():
            return self._build_sum_select()
        else:
            return ast.Call(name="count", args=[ast.Constant(value="*")])

    def _build_dau_select(self) -> ast.Expr:
        """Build DAU (Daily Active Users) select expression"""
        if self.goal.kind == "DataWarehouseNode":
            schema_map = self.goal.schema_map
            distinct_id_field = schema_map.get("distinct_id_field", self.config.default_distinct_id_field)
            return ast.Call(name="uniq", args=[ast.Field(chain=[distinct_id_field])])
        return ast.Call(name="uniq", args=[ast.Field(chain=["events", self.config.default_distinct_id_field])])

    def _build_sum_select(self) -> ast.Expr:
        """Build SUM aggregation select expression"""
        math_property = self.goal.math_property
        if not math_property:
            return ast.Constant(value=0)

        if self.goal.kind == "DataWarehouseNode":
            property_field = ast.Field(chain=[math_property])
            timestamp_field = self.goal.schema_map.get("timestamp_field", "timestamp")
            timestamp_expr: ast.Expr = ast.Field(chain=[timestamp_field])
        else:
            property_field = ast.Field(chain=["events", "properties", math_property])
            timestamp_expr = ast.Field(chain=["events", "timestamp"])

        value_per_row = self._to_base_currency(property_field, timestamp_expr)

        return ast.Call(
            name="round",
            args=[
                ast.Call(name="sum", args=[value_per_row]),
                ast.Constant(value=self.config.decimal_precision),
            ],
        )

    def _to_base_currency(self, property_field: ast.Expr, timestamp_expr: ast.Expr) -> ast.Expr:
        """Turn a raw revenue property into a float in the team's base currency.

        When the goal declares a math_property_revenue_currency, convert each value at the exchange
        rate of its own event day. Without it, the value is assumed to already be in the base currency
        and is only cast to float, which keeps goals that never set a currency behaving as before.
        """
        amount = ast.Call(name="toFloat", args=[property_field])
        currency = self.goal.math_property_revenue_currency
        if currency is None:
            return amount

        base_currency = ast.Constant(value=self.team.base_currency)
        date = ast.Call(name="_toDate", args=[timestamp_expr])

        if currency.property:
            if self.goal.kind == "DataWarehouseNode":
                currency_from: ast.Expr = ast.Field(chain=[currency.property])
            else:
                currency_from = ast.Field(chain=["events", "properties", currency.property])
            currency_from = ast.Call(
                name="nullIf", args=[ast.Call(name="upper", args=[currency_from]), ast.Constant(value="")]
            )
            # A row can be missing the currency property or carry an empty string; treat those as already
            # in the base currency rather than letting convertCurrency null the whole amount out.
            return ast.Call(
                name="if",
                args=[
                    ast.Call(name="isNull", args=[currency_from]),
                    amount,
                    ast.Call(name="toFloat", args=[convert_currency_call(amount, currency_from, base_currency, date)]),
                ],
            )

        if currency.static:
            currency_from = ast.Constant(value=currency.static.value)
            return ast.Call(name="toFloat", args=[convert_currency_call(amount, currency_from, base_currency, date)])

        return amount

    def get_base_where_conditions(self) -> list[ast.Expr]:
        """Build base WHERE conditions for conversion goal filtering"""
        if self.goal.kind == "ActionsNode":
            # A goal whose action is gone matches nothing, so the Dashboard's other goals still render.
            return [action_match_expr(self.goal, self.team) or ast.Constant(value=False)]

        match = conversion_goal_match_expr(self.goal, self.team)
        return [match] if match is not None else []

    def get_date_field(self) -> str:
        """Get appropriate timestamp field based on goal type"""
        if self.goal.kind == "DataWarehouseNode":
            schema_map = self.goal.schema_map
            return schema_map.get("timestamp_field", "timestamp")
        return "events.timestamp"

    def generate_cte_query(
        self,
        additional_conditions: Sequence[ast.Expr],
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        touchpoints: Optional[SharedTouchpointsPrecompute] = None,
    ) -> ast.SelectQuery:
        """Generate main CTE query for conversion goal.

        `touchpoints` lets callers running several goals share one touchpoints materialization. When
        omitted the goal materializes its own, so standalone callers keep working unchanged.
        """
        if self.uses_attribution_pipeline:
            return self._generate_funnel_query(additional_conditions, date_from, date_to, touchpoints)
        return self._generate_direct_query(additional_conditions)

    @property
    def uses_attribution_pipeline(self) -> bool:
        """Whether this goal's rows come from the attribution pipeline rather than a direct scan.

        Only the pipeline emits the columns attribution adds — `attribution_weight` above all — so
        anything reading one has to ask first. Warehouse goals and a zero-length window both scan
        directly.
        """
        return self.goal.kind in ["EventsNode", "ActionsNode"] and self.config.attribution_window_days > 0

    def build_array_collection_query(self, additional_conditions: Sequence[ast.Expr]) -> ast.SelectQuery:
        """Build the per-person array-collection subquery.

        This is the upstream stage of the attribution pipeline: for each
        person, it groups conversion events and UTM pageviews into parallel
        arrays. The downstream ``build_attribution_pipeline`` consumes this.
        """
        conversion_event: Optional[str] = self.goal.event if self.goal.kind == "EventsNode" else None
        where_conditions = self.get_base_where_conditions()
        where_conditions = add_conversion_goal_property_filters(where_conditions, self.goal, self.team)
        where_conditions.extend(additional_conditions)
        return self._build_array_collection_subquery(conversion_event, where_conditions)

    def build_attribution_pipeline(self, array_source: ast.SelectQuery) -> ast.SelectQuery:
        """Apply ARRAY JOIN, attribution and final aggregation on top of an
        array-collection source."""
        attribution_window_seconds = self.config.attribution_window_days * DAY_IN_SECONDS

        if self.config.is_multi_touch:
            array_join = self._build_multi_touch_array_join_subquery(array_source, attribution_window_seconds)
            attribution = self._build_multi_touch_attribution_subquery(array_join)
        else:
            array_join = self._build_single_touch_array_join_subquery(array_source, attribution_window_seconds)
            attribution = self._build_single_touch_attribution_subquery(array_join)

        return self._build_final_aggregation_query(attribution)

    def _generate_funnel_query(
        self,
        additional_conditions: Sequence[ast.Expr],
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        touchpoints: Optional[SharedTouchpointsPrecompute] = None,
    ) -> ast.SelectQuery:
        """Generate multi-step funnel query with attribution window.

        Reads the preagg table when eligible, falls back to events scan on any failure.
        """
        if self._should_use_precompute(date_from, date_to):
            # `_should_use_precompute` returns False unless both dates are set; narrow for mypy.
            assert date_from is not None and date_to is not None
            try:
                precomputed = self._build_attribution_from_precomputes(date_from, date_to, touchpoints)
                if precomputed is not None:
                    return precomputed
            except Exception:
                CONVERSION_GOAL_PRECOMPUTE_FALLBACK_COUNTER.inc()
                logger.exception(
                    "conversion_goal_precompute_failed",
                    goal_id=self.goal.conversion_goal_id,
                    team_id=self.team.pk,
                )

        # Live events scan. Reaching here means the precompute did not serve this goal.
        with self.timings.measure("ma_goal_events_fallback"):
            array_collection = self.build_array_collection_query(additional_conditions)
            return self.build_attribution_pipeline(array_collection)

    def is_goal_precomputable(self) -> bool:
        """Goal-level precompute eligibility, independent of the requesting user, date range, or flag.

        Shared by the live read path (`_should_use_precompute`) and the Dagster warmer
        (products/marketing_analytics/dags/marketing_precompute.py) so both agree on which goals get a
        conversions precompute job — otherwise the warmer could materialize jobs the read never asks for,
        or skip ones it does.
        """
        if self.goal.kind not in ("EventsNode", "ActionsNode"):
            return False
        if self.goal.kind == "EventsNode" and not self.goal.event:
            return False
        # Only ConversionGoalFilter2 (ActionsNode) has `id` — guard with getattr.
        if self.goal.kind == "ActionsNode" and not getattr(self.goal, "id", None):
            return False
        if self.config.attribution_window_days <= 0:
            return False
        for prop in self.goal.properties or []:
            if prop.type in ("person", "cohort"):
                return False
        # The shared touchpoints precompute is config-agnostic: build_touchpoints_precompute_query()
        # always materializes the default UTM property names. A goal that remaps any tracked field via
        # schema_map would read mismatched columns on the conversion side, so use the direct path.
        if any(self._resolve_field_name(field) != field.event_property for field in TRACKED_FIELDS):
            return False
        return True

    def _should_use_precompute(self, date_from: Optional[datetime], date_to: Optional[datetime]) -> bool:
        """Read-path eligibility: flag on, explicit date range, goal precomputable, no restricted props."""
        if not self.config.conversion_goal_precomputation_enabled:
            return False
        if date_from is None or date_to is None:
            return False
        if not self.is_goal_precomputable():
            return False
        # User-scoped: the precompute path materializes some event properties as plain columns, bypassing
        # per-user masking. When any is restricted for THIS user, fall back to the masked direct path.
        if self._precompute_properties_restricted_for_user():
            return False
        return True

    def _precompute_materialized_event_properties(self) -> set[str]:
        """Event property names the precompute path resolves into scalar columns of the preagg table."""
        # $session_id is materialized into the session_id column (see build_conversions_precompute_query),
        # so it must be part of the restriction check — otherwise a user denied access to $session_id
        # could still read it from the preagg table, bypassing the per-property HogQL masking.
        props = {"$session_id"}
        props.update(self._resolve_field_name(field) for field in TRACKED_FIELDS)
        math_property = getattr(self.goal, "math_property", None)
        if math_property:
            props.add(math_property)
        # A property-sourced currency is folded into conversion_math_value by _to_base_currency, so the
        # converted amount leaks it just as directly as math_property itself.
        currency = getattr(self.goal, "math_property_revenue_currency", None)
        if currency is not None and currency.property:
            props.add(currency.property)
        return props

    def _precompute_properties_restricted_for_user(self) -> bool:
        """True if any property the precompute would materialize is restricted for the requesting user.

        The precompute path resolves these ``events.properties`` reads server-side and stores them as
        plain scalar columns, which bypasses the per-user property masking HogQL applies to
        ``events.properties`` at print time. When any such property is restricted, skip precompute so
        the direct events query — which enforces masking via ``JSONDropKeys`` — is used instead.
        """
        restricted = get_restricted_property_names(
            team_id=self.team.pk,
            user=self.user,
            property_type=PropertyDefinition.Type.EVENT,
        )
        return bool(restricted) and not restricted.isdisjoint(self._precompute_materialized_event_properties())

    def build_conversions_precompute_query(self) -> ast.SelectQuery:
        """Per-goal conversion precompute: one row per conversion event, independent of attribution mode
        or window. The query embeds the goal's event/action + property filters + math, so its query hash
        is one shared lazy job per (goal, filters, math) — reused across modes, windows and views;
        attribution happens at read time. Columns are aliased to the marketing_conversions_preaggregated
        schema — the lazy framework prepends team_id/job_id and appends expires_at, and resolves the
        time_window placeholders per job. Sibling of build_touchpoints_precompute_query (pageview side).
        """
        conversion_event = self.goal.event if self.goal.kind == "EventsNode" else None

        def _prop_to_string(event_property: str) -> ast.Expr:
            return ast.Call(
                name="toString",
                args=[
                    ast.Call(
                        name="ifNull",
                        args=[ast.Field(chain=["events", "properties", event_property]), ast.Constant(value="")],
                    )
                ],
            )

        select_columns: list[ast.Expr] = [
            ast.Alias(alias="person_id", expr=ast.Field(chain=["events", "person_id"])),
            ast.Alias(alias="conversion_timestamp", expr=ast.Field(chain=["events", "timestamp"])),
            ast.Alias(alias="conversion_math_value", expr=self._get_conversion_value_expr()),
            # Stored for a future "show conversion session recordings" feature; the attribution read ignores it.
            ast.Alias(alias="session_id", expr=_prop_to_string("$session_id")),
        ]
        # Conversion-side UTM value per tracked field, aliased to the {field}_name table columns.
        for tracked in TRACKED_FIELDS:
            select_columns.append(
                ast.Alias(alias=tracked.attributed_name, expr=_prop_to_string(self._resolve_field_name(tracked)))
            )

        where_exprs: list[ast.Expr] = [
            self._build_conversion_event_condition(conversion_event),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Placeholder(expr=ast.Field(chain=["time_window_min"])),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Placeholder(expr=ast.Field(chain=["time_window_max"])),
            ),
        ]
        where_exprs = add_conversion_goal_property_filters(where_exprs, self.goal, self.team)

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=where_exprs),
        )

    def _build_attribution_from_precomputes(
        self,
        date_from: datetime,
        date_to: datetime,
        touchpoints: Optional[SharedTouchpointsPrecompute] = None,
    ) -> Optional[ast.SelectQuery]:
        """Reusable-precompute read path: ensure both the config-agnostic touchpoints and the per-goal
        conversions are materialized, then attribute at read time by feeding a precompute-sourced array
        collection through the existing pipeline (all modes). Neither precompute depends on attribution
        mode or window. Returns None if either set of jobs isn't ready — caller falls back.
        """
        window = timedelta(days=self.config.attribution_window_days)

        # Touchpoints extend back by the attribution window; conversions only span the query range.
        # Both ensure_precomputed calls can materialize inline (PG + Redis + ClickHouse) when a slice
        # is stale, so they are timed separately from the AST work that follows.
        #
        # Touchpoints are config-agnostic, so a multi-goal read shares one materialization. Without a
        # shared handle each goal materializes the same window itself, which is what a standalone
        # caller gets.
        shared_touchpoints = touchpoints or SharedTouchpointsPrecompute(self.team, self.config)
        with self.timings.measure("ma_ensure_touchpoints"):
            touchpoints_result = shared_touchpoints.get(date_from, date_to)
        if not touchpoints_result.ready:
            return None

        with self.timings.measure("ma_ensure_conversions"):
            conversions_result = marketing_ensure_precomputed(
                team=self.team,
                insert_query=self.build_conversions_precompute_query(),
                time_range_start=date_from,
                time_range_end=date_to,
                ttl_seconds=PRECOMPUTE_TTL_SECONDS,
                table=LazyComputationTable.MARKETING_CONVERSIONS_PREAGGREGATED,
            )
        if not conversions_result.ready:
            return None

        # Either ensure may have been served from expired-within-grace rows rather than rebuilt. The
        # runner collects this once the goal pool has joined and schedules the revalidation.
        if touchpoints_result.stale or conversions_result.stale:
            self.precompute_stale = True

        with self.timings.measure("ma_attribution_pipeline_precomputed"):
            array_collection = self._build_array_collection_from_precomputes(
                touchpoints_result.job_ids, conversions_result.job_ids, date_from, date_to, window
            )
            return self.build_attribution_pipeline(array_collection)

    def _build_array_collection_from_precomputes(
        self,
        touchpoint_job_ids: Sequence[str | uuid.UUID],
        conversion_job_ids: Sequence[str | uuid.UUID],
        date_from: datetime,
        date_to: datetime,
        window: timedelta,
    ) -> ast.SelectQuery:
        """Reusable-precompute analogue of build_array_collection_query: identical per-person array
        contract, but conversion arrays come from the precomputed marketing_conversions table and
        touchpoint arrays from the precomputed marketing_touchpoints table (joined on person_id),
        instead of inline events scans. build_attribution_pipeline runs unchanged for every mode.

        Each side is bounded to the same window it was materialized for (conversions span the query
        range; touchpoints extend back by the attribution window), mirroring the ensure_precomputed
        calls above — a reused job can cover a wider window than the request, so the job_id filter
        alone would over-count out-of-range rows into the per-person arrays.
        """
        conversions = self._build_conversion_arrays_from_table(conversion_job_ids, date_from, date_to)
        touchpoints = self._build_touchpoint_arrays_from_table(touchpoint_job_ids, date_from - window, date_to)

        select_columns: list[ast.Expr] = []
        for col in ("person_id", "conversion_timestamps", "conversion_math_values"):
            select_columns.append(ast.Alias(alias=col, expr=ast.Field(chain=["c", col])))
        for field in TRACKED_FIELDS:
            select_columns.append(
                ast.Alias(alias=field.conversion_array, expr=ast.Field(chain=["c", field.conversion_array]))
            )
        # LEFT JOIN: organic conversions (no matching person in the touchpoints table) get empty
        # touchpoint arrays (ClickHouse fills missing Array columns with []), handled downstream.
        select_columns.append(ast.Alias(alias="utm_timestamps", expr=ast.Field(chain=["t", "utm_timestamps"])))
        for field in TRACKED_FIELDS:
            select_columns.append(ast.Alias(alias=field.utm_array, expr=ast.Field(chain=["t", field.utm_array])))

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(
                table=conversions,
                alias="c",
                next_join=ast.JoinExpr(
                    table=touchpoints,
                    alias="t",
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["c", "person_id"]),
                            right=ast.Field(chain=["t", "person_id"]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
        )

    def _build_conversion_only_arrays(
        self, conversion_event: Optional[str], date_from: datetime, date_to: datetime
    ) -> ast.SelectQuery:
        """Per-person conversion arrays from events (no touchpoint scan) — the live half of the
        touchpoint-sourced array collection. Mirrors the conversion columns of build_array_collection_query.
        """
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["events", "person_id"]),
            self._build_conversion_timestamps_array(conversion_event),
            self._build_conversion_math_values_array(conversion_event),
        ]
        for field in TRACKED_FIELDS:
            select_columns.append(
                self._build_conversion_utm_array(
                    field.conversion_array, conversion_event, self._resolve_field_name(field)
                )
            )

        where_exprs: list[ast.Expr] = [
            self._build_conversion_event_condition(conversion_event),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.Constant(value=date_from),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Constant(value=date_to),
            ),
        ]
        where_exprs = add_conversion_goal_property_filters(where_exprs, self.goal, self.team)

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=where_exprs),
            group_by=[ast.Field(chain=["events", "person_id"])],
            having=ast.CompareOperation(
                left=ast.Call(name="length", args=[ast.Field(chain=["conversion_timestamps"])]),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0),
            ),
        )

    def _build_conversion_arrays_from_table(
        self, job_ids: Sequence[str | uuid.UUID], date_from: datetime, date_to: datetime
    ) -> ast.SelectQuery:
        """Per-person conversion arrays read from the precomputed marketing_conversions table, matching
        the array shape _build_conversion_only_arrays produces from a live events scan. Each table row is
        already a single conversion (event filtered at INSERT time), so we just groupArray per person —
        the same arrayFilter sentinels are kept so the result is row-for-row identical to the fallback.

        The preagg table is a ReplacingMergeTree keyed on (team_id, job_id, person_id, conversion_timestamp);
        because job_id is part of the dedup key, the same physical conversion materialized under several
        job_ids (overlapping windows, compare-period, re-materialization on TTL) survives as distinct rows
        even with FINAL. Reading across multiple job_ids would therefore double-count. We deduplicate by the
        FULL conversion identity — (person_id, conversion_timestamp, conversion_math_value, all UTM dims) —
        ignoring job_id/computed_at, so only true duplicates (same row under a different job_id) collapse;
        two genuinely distinct conversions of one person at the same timestamp with the same math value but
        different dims (or vice versa) are preserved.
        """
        positive = ast.Lambda(
            args=["x"],
            expr=ast.CompareOperation(
                left=ast.Field(chain=["x"]), op=ast.CompareOperationOp.Gt, right=ast.Constant(value=0)
            ),
        )
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Alias(
                alias="conversion_timestamps",
                expr=ast.Call(
                    name="arrayFilter",
                    args=[
                        positive,
                        ast.Call(
                            name="groupArray",
                            args=[ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["conversion_timestamp"])])],
                        ),
                    ],
                ),
            ),
            ast.Alias(
                alias="conversion_math_values",
                expr=ast.Call(
                    name="arrayFilter",
                    args=[positive, ast.Call(name="groupArray", args=[ast.Field(chain=["conversion_math_value"])])],
                ),
            ),
        ]
        for field in TRACKED_FIELDS:
            select_columns.append(
                ast.Alias(
                    alias=field.conversion_array,
                    expr=ast.Call(
                        name="arrayFilter",
                        args=[
                            ast.Lambda(
                                args=["x"],
                                expr=ast.Call(
                                    name="notEmpty", args=[ast.Call(name="toString", args=[ast.Field(chain=["x"])])]
                                ),
                            ),
                            ast.Call(name="groupArray", args=[ast.Field(chain=[field.attributed_name])]),
                        ],
                    ),
                )
            )

        deduped_rows = self._build_distinct_preagg_rows(
            table="marketing_conversions_preaggregated",
            job_ids=job_ids,
            row_columns=[
                ast.Field(chain=["person_id"]),
                ast.Field(chain=["conversion_timestamp"]),
                ast.Field(chain=["conversion_math_value"]),
                *[ast.Field(chain=[field.attributed_name]) for field in TRACKED_FIELDS],
            ],
            date_from=date_from,
            date_to=date_to,
            timestamp_column="conversion_timestamp",
        )

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=deduped_rows),
            group_by=[ast.Field(chain=["person_id"])],
        )

    def _build_touchpoint_arrays_from_table(
        self, job_ids: Sequence[str | uuid.UUID], date_from: datetime, date_to: datetime
    ) -> ast.SelectQuery:
        """Per-person touchpoint arrays (utm_timestamps + per-field UTM arrays) read from the
        precomputed marketing_touchpoints table, matching the array shape build_array_collection_query
        produces from a UTM-pageview scan.

        The preagg table is a ReplacingMergeTree keyed on (team_id, job_id, person_id, touchpoint_timestamp);
        job_id being in the dedup key means the same physical touchpoint materialized under several job_ids
        (overlapping windows, compare-period, re-materialization on TTL) survives as distinct rows even with
        FINAL. groupArray-ing across those job_ids would inflate the touchpoint arrays and over-credit the
        conversion. We deduplicate by the FULL touchpoint identity — (person_id, touchpoint_timestamp, all
        UTM dims) — ignoring job_id/computed_at, so only true duplicates collapse.
        """
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Alias(
                alias="utm_timestamps",
                expr=ast.Call(
                    name="groupArray",
                    args=[ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["touchpoint_timestamp"])])],
                ),
            ),
        ]
        for field in TRACKED_FIELDS:
            # Unfiltered, to stay index-parallel with `utm_timestamps` above: these arrays are read
            # positionally against it, and a stored row can legitimately carry an empty value for any
            # field except campaign and source (which the precompute WHERE requires). Filtering the
            # empties out here shifted every later element onto the wrong touchpoint.
            select_columns.append(
                ast.Alias(
                    alias=field.utm_array,
                    expr=ast.Call(name="groupArray", args=[ast.Field(chain=[field.attributed_name])]),
                )
            )

        deduped_rows = self._build_distinct_preagg_rows(
            table="marketing_touchpoints_preaggregated",
            job_ids=job_ids,
            row_columns=[
                ast.Field(chain=["person_id"]),
                ast.Field(chain=["touchpoint_timestamp"]),
                *[ast.Field(chain=[field.attributed_name]) for field in TRACKED_FIELDS],
            ],
            date_from=date_from,
            date_to=date_to,
            timestamp_column="touchpoint_timestamp",
        )

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=deduped_rows),
            group_by=[ast.Field(chain=["person_id"])],
        )

    def _build_distinct_preagg_rows(
        self,
        table: str,
        job_ids: Sequence[str | uuid.UUID],
        row_columns: list[ast.Expr],
        date_from: datetime,
        date_to: datetime,
        timestamp_column: str,
    ) -> ast.SelectQuery:
        """SELECT DISTINCT over the full row identity (excluding job_id/computed_at) for one team across
        the given job_ids. Collapses rows that are physically identical but materialized under different
        job_ids, which the ReplacingMergeTree dedup key (which includes job_id) cannot merge away. The
        downstream groupArray then sees each real touchpoint/conversion exactly once.

        The job_id filter alone is not enough: the lazy framework reuses a job whose materialized window
        can be wider than the request (TTL bands merge daily windows, compare-period reuse, …), so the
        rows for those job_ids span more than the requested range. We bound `timestamp_column` to
        [date_from, date_to] — matching the ensure_precomputed window and the live events scan
        (`_build_conversion_only_arrays`) — so the per-person arrays don't pull in out-of-range rows.
        """
        return ast.SelectQuery(
            select=row_columns,
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", table])),
            where=ast.And(
                exprs=[
                    ast.Call(
                        name="in",
                        args=[
                            ast.Field(chain=["job_id"]),
                            ast.Tuple(exprs=[ast.Constant(value=str(jid)) for jid in job_ids]),
                        ],
                    ),
                    ast.CompareOperation(
                        left=ast.Field(chain=[timestamp_column]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.Constant(value=date_from),
                    ),
                    ast.CompareOperation(
                        left=ast.Field(chain=[timestamp_column]),
                        op=ast.CompareOperationOp.LtEq,
                        right=ast.Constant(value=date_to),
                    ),
                    ast.CompareOperation(
                        left=ast.Field(chain=["team_id"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=self.team.pk),
                    ),
                ]
            ),
        )

    def _build_array_collection_subquery(
        self, conversion_event: Optional[str], where_conditions: list[ast.Expr]
    ) -> ast.SelectQuery:
        """Build subquery that collects arrays of conversion and UTM data per person"""
        resolved = {f.name: self._resolve_field_name(f) for f in TRACKED_FIELDS}
        utm_source_field = resolved["source"]

        # Build WHERE clause with clean separation of concerns
        final_where = self._build_comprehensive_where_clause(conversion_event, where_conditions, utm_source_field)

        # Build SELECT columns
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["events", "person_id"]),
            self._build_conversion_timestamps_array(conversion_event),
            self._build_conversion_math_values_array(conversion_event),
        ]

        # Add conversion arrays for each tracked field
        for field in TRACKED_FIELDS:
            select_columns.append(
                self._build_conversion_utm_array(field.conversion_array, conversion_event, resolved[field.name])
            )

        # Add pageview UTM arrays (timestamps + each tracked field)
        select_columns.append(self._build_utm_pageview_array("utm_timestamps", utm_source_field, "timestamp"))
        for field in TRACKED_FIELDS:
            select_columns.append(
                self._build_utm_pageview_array(field.utm_array, utm_source_field, resolved[field.name])
            )

        # Build HAVING clause
        having_expr = ast.CompareOperation(
            left=ast.Call(name="length", args=[ast.Field(chain=["conversion_timestamps"])]),
            op=ast.CompareOperationOp.Gt,
            right=ast.Constant(value=0),
        )

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=final_where,
            group_by=[ast.Field(chain=["events", "person_id"])],
            having=having_expr,
        )

    def _build_comprehensive_where_clause(
        self,
        conversion_event: Optional[str],
        input_conditions: list[ast.Expr],
        utm_source_field: str,
    ) -> ast.Expr:
        """Build complete WHERE clause with proper condition separation"""

        # Separate input conditions by type
        date_conditions = [c for c in input_conditions if self._is_date_condition(c)]
        non_event_conditions = [
            c
            for c in input_conditions
            if not self._is_date_condition(c) and not self._is_event_condition(c, conversion_event)
        ]

        # Build event-specific conditions
        event_filter: ast.Expr
        if conversion_event:
            # For specific conversion events, we need both conversion and pageview logic
            if conversion_event == "$pageview":
                # For pageview conversions, we only need attribution pageviews (with UTM data).
                # No need for separate conversion filter since conversion IS the pageview.
                event_filter = self._build_pageview_event_filter(date_conditions, utm_source_field)
            else:
                # For non-pageview conversions, use both filters (no overlap possible)
                event_filter = ast.Or(
                    exprs=[
                        self._build_conversion_event_filter(conversion_event, date_conditions),
                        self._build_pageview_event_filter(date_conditions, utm_source_field),
                    ]
                )
        elif self.goal.kind == "ActionsNode" and self.config.attribution_window_days > 0:
            # For ActionsNode with attribution, we need both action events and pageview events
            action_conditions = self.get_base_where_conditions()
            action_filter = self._build_action_event_filter(action_conditions, date_conditions)
            pageview_filter = self._build_pageview_event_filter(date_conditions, utm_source_field)
            event_filter = ast.Or(exprs=[action_filter, pageview_filter])
        else:
            # For general queries, apply date conditions to all events
            event_filter = self._build_general_event_filter(date_conditions)

        # Combine all conditions
        all_conditions = [event_filter, *non_event_conditions]
        return ast.And(exprs=all_conditions) if len(all_conditions) > 1 else all_conditions[0]

    def _build_action_event_filter(
        self, action_conditions: list[ast.Expr], date_conditions: list[ast.Expr]
    ) -> ast.Expr:
        """Build filter for action events with their specific date constraints"""
        conditions: list[ast.Expr] = []

        # Add action conditions (this includes the action_to_expr logic)
        conditions.extend(action_conditions)

        # Apply regular date conditions to action events
        for date_condition in date_conditions:
            if isinstance(date_condition, ast.CompareOperation):
                conditions.append(
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=date_condition.op,
                        right=self._ensure_datetime_call(date_condition.right),
                    )
                )

        return ast.And(exprs=conditions) if conditions else ast.Constant(value=True)

    def _build_conversion_event_filter(self, conversion_event: str, date_conditions: list[ast.Expr]) -> ast.Expr:
        """Build filter for conversion events with their specific date constraints"""
        conditions: list[ast.Expr] = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=conversion_event),
            )
        ]

        # Apply regular date conditions to conversion events
        for date_condition in date_conditions:
            if isinstance(date_condition, ast.CompareOperation):
                conditions.append(
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=date_condition.op,
                        right=self._ensure_datetime_call(date_condition.right),
                    )
                )

        return ast.And(exprs=conditions)

    def _build_pageview_event_filter(self, date_conditions: list[ast.Expr], utm_source_field: str) -> ast.Expr:
        """Build filter for pageview events with UTM requirements and extended date range"""
        conditions = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
            build_pageview_touchpoint_condition(utm_source_field),
        ]

        # Apply extended date conditions for pageviews (attribution window)
        attribution_window_seconds = self.config.attribution_window_days * DAY_IN_SECONDS
        for date_condition in date_conditions:
            if isinstance(date_condition, ast.CompareOperation):
                if date_condition.op == ast.CompareOperationOp.GtEq:
                    # Extend start date backwards by attribution window
                    conditions.append(
                        ast.CompareOperation(
                            left=ast.Field(chain=["events", "timestamp"]),
                            op=ast.CompareOperationOp.GtEq,
                            right=ast.ArithmeticOperation(
                                left=self._ensure_datetime_call(date_condition.right),
                                op=ast.ArithmeticOperationOp.Sub,
                                right=ast.Call(
                                    name="toIntervalSecond", args=[ast.Constant(value=attribution_window_seconds)]
                                ),
                            ),
                        )
                    )
                elif date_condition.op == ast.CompareOperationOp.LtEq:
                    conditions.append(
                        ast.CompareOperation(
                            left=ast.Field(chain=["events", "timestamp"]),
                            op=ast.CompareOperationOp.LtEq,
                            right=self._ensure_datetime_call(date_condition.right),
                        )
                    )

        return ast.And(exprs=conditions)

    def _build_general_event_filter(self, date_conditions: list[ast.Expr]) -> ast.Expr:
        """Build filter for general case when no specific conversion event is defined"""
        if not date_conditions:
            return ast.Constant(value=True)

        # Apply date conditions directly to all events
        conditions: list[ast.Expr] = [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=condition.op,
                right=self._ensure_datetime_call(condition.right),
            )
            for condition in date_conditions
            if isinstance(condition, ast.CompareOperation)
        ]

        return ast.And(exprs=conditions) if conditions else ast.Constant(value=True)

    def _build_conversion_timestamps_array(self, conversion_event: Optional[str]) -> ast.Alias:
        """Build conversion timestamps array.

        Uses 0 as sentinel for non-conversion events. A Unix timestamp of 0
        (1970-01-01) is impossible for real events, so x > 0 safely filters them.
        """
        return ast.Alias(
            alias="conversion_timestamps",
            expr=ast.Call(
                name="arrayFilter",
                args=[
                    ast.Lambda(
                        args=["x"],
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=["x"]),
                            op=ast.CompareOperationOp.Gt,
                            right=ast.Constant(value=0),
                        ),
                    ),
                    ast.Call(
                        name="groupArray",
                        args=[
                            ast.Call(
                                name="if",
                                args=[
                                    self._build_conversion_event_condition(conversion_event),
                                    ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])]),
                                    ast.Constant(value=0),
                                ],
                            )
                        ],
                    ),
                ],
            ),
        )

    def _build_conversion_math_values_array(self, conversion_event: Optional[str]) -> ast.Alias:
        """Build conversion math values array.

        Uses 0 as sentinel for non-conversion events. This means $0-value
        and negative-value conversions are also filtered from math_values,
        but that's safe: conversion_timestamps is the source of truth for
        which conversions happened (TOTAL/DAU), and summing $0 doesn't
        change the result (SUM). Negative conversion values (e.g. refunds)
        are not currently supported — they would be dropped by the filter.
        """
        return ast.Alias(
            alias="conversion_math_values",
            expr=ast.Call(
                name="arrayFilter",
                args=[
                    ast.Lambda(
                        args=["x"],
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=["x"]),
                            op=ast.CompareOperationOp.Gt,
                            right=ast.Constant(value=0),
                        ),
                    ),
                    ast.Call(
                        name="groupArray",
                        args=[
                            ast.Call(
                                name="if",
                                args=[
                                    self._build_conversion_event_condition(conversion_event),
                                    self._get_conversion_value_expr(),
                                    ast.Constant(value=0),
                                ],
                            )
                        ],
                    ),
                ],
            ),
        )

    def _build_conversion_event_condition(self, conversion_event: Optional[str]) -> ast.Expr:
        """Build condition for conversion event matching"""
        if conversion_event:
            return ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=conversion_event),
            )

        # For ActionsNode (when conversion_event is None), we need to use the action condition
        # instead of matching all events
        if self.goal.kind == "ActionsNode":
            # A goal whose action is gone matches nothing, so the Dashboard's other goals still render.
            return action_match_expr(self.goal, self.team) or ast.Constant(value=False)

        # Fallback for other cases
        return ast.Constant(value=True)

    def _get_conversion_value_expr(self) -> ast.Expr:
        """Get conversion value expression for array collection"""
        math_type = self.goal.math

        if math_type in [BaseMathType.DAU, "dau"]:
            return ast.Call(name="toFloat", args=[ast.Constant(value=1)])
        elif math_type in ["sum", PropertyMathType.SUM] or str(math_type).endswith("_sum"):
            math_property = self.goal.math_property
            if math_property:
                property_field = ast.Field(chain=["events", "properties", math_property])
                value = self._to_base_currency(property_field, ast.Field(chain=["events", "timestamp"]))
                return ast.Call(name="coalesce", args=[value, ast.Constant(value=0.0)])

        return ast.Call(name="toFloat", args=[ast.Constant(value=1)])

    def _build_conversion_utm_array(self, alias: str, conversion_event: Optional[str], utm_field: str) -> ast.Alias:
        """Build array for conversion event UTM data"""
        return ast.Alias(
            alias=alias,
            expr=ast.Call(
                name="arrayFilter",
                args=[
                    ast.Lambda(
                        args=["x"],
                        expr=ast.Call(name="notEmpty", args=[ast.Call(name="toString", args=[ast.Field(chain=["x"])])]),
                    ),
                    ast.Call(
                        name="groupArray",
                        args=[
                            ast.Call(
                                name="if",
                                args=[
                                    self._build_conversion_event_condition(conversion_event),
                                    ast.Call(
                                        name="toString",
                                        args=[
                                            ast.Call(
                                                name="ifNull",
                                                args=[
                                                    ast.Field(chain=["events", "properties", utm_field]),
                                                    ast.Constant(value=""),
                                                ],
                                            )
                                        ],
                                    ),
                                    ast.Constant(value=""),
                                ],
                            )
                        ],
                    ),
                ],
            ),
        )

    def _build_utm_pageview_array(self, alias: str, utm_source_field: str, return_field: str) -> ast.Alias:
        """Build array for UTM pageview data.

        Every array this builds is read positionally against `utm_timestamps`
        (`_build_filtered_utm_field_expr`, `_build_single_touch_fallback_expr`), so all of them must
        keep exactly one element per UTM pageview, in the same order. That means **every** array is
        filtered by the same predicate — the timestamp being non-zero, i.e. the row qualified — and
        never by whether its own value happens to be set. `utm_source` or an ad click id is the
        touchpoint qualifier; every other tracked field, `utm_campaign` included, is routinely empty
        on a qualifying pageview, and dropping those positions used to shift every later element:
        touchpoint i's timestamp paired with touchpoint j's value.
        """
        pageview_with_utm = ast.And(
            exprs=[
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "event"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value="$pageview"),
                ),
                build_pageview_touchpoint_condition(utm_source_field),
            ]
        )
        timestamp_expr = ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])])
        qualified_timestamp = ast.Call(name="if", args=[pageview_with_utm, timestamp_expr, ast.Constant(value=0)])
        qualified = ast.Lambda(
            args=["_tp"],
            expr=ast.CompareOperation(
                left=ast.TupleAccess(tuple=ast.Field(chain=["_tp"]), index=1),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0),
            ),
        )

        if return_field == "timestamp":
            return ast.Alias(
                alias=alias,
                expr=ast.Call(
                    name="arrayFilter",
                    args=[
                        ast.Lambda(
                            args=["x"],
                            expr=ast.CompareOperation(
                                left=ast.Field(chain=["x"]),
                                op=ast.CompareOperationOp.Gt,
                                right=ast.Constant(value=0),
                            ),
                        ),
                        ast.Call(name="groupArray", args=[qualified_timestamp]),
                    ],
                ),
            )

        value_expr = ast.Call(
            name="toString",
            args=[
                ast.Call(
                    name="ifNull",
                    args=[
                        ast.Field(chain=["events", "properties", return_field]),
                        ast.Constant(value=""),
                    ],
                )
            ],
        )
        # Paired with the timestamp so the filter can key off the row qualifying rather than off this
        # field being set; the tuple is unpacked immediately, so the array's shape is unchanged.
        return ast.Alias(
            alias=alias,
            expr=ast.Call(
                name="arrayMap",
                args=[
                    ast.Lambda(args=["_tp"], expr=ast.TupleAccess(tuple=ast.Field(chain=["_tp"]), index=2)),
                    ast.Call(
                        name="arrayFilter",
                        args=[
                            qualified,
                            ast.Call(
                                name="groupArray",
                                args=[
                                    ast.Tuple(
                                        exprs=[
                                            qualified_timestamp,
                                            ast.Call(
                                                name="if",
                                                args=[pageview_with_utm, value_expr, ast.Constant(value="")],
                                            ),
                                        ]
                                    )
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        )

    def _build_single_touch_array_join_subquery(
        self, inner_query: ast.SelectQuery, attribution_window_seconds: int
    ) -> ast.SelectQuery:
        """Build subquery with ARRAY JOIN and attribution window logic"""
        select_columns: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Alias(
                alias="conversion_time",
                expr=ast.ArrayAccess(
                    array=ast.Field(chain=["conversion_timestamps"]),
                    property=ast.Field(chain=["i"]),
                ),
            ),
            ast.Alias(
                alias="conversion_math_value",
                expr=ast.ArrayAccess(
                    array=ast.Field(chain=["conversion_math_values"]),
                    property=ast.Field(chain=["i"]),
                ),
            ),
        ]

        # Add conversion value and fallback for each tracked field
        for field in TRACKED_FIELDS:
            select_columns.append(
                ast.Alias(
                    alias=field.conversion_value,
                    expr=ast.ArrayAccess(
                        array=ast.Field(chain=[field.conversion_array]),
                        property=ast.Field(chain=["i"]),
                    ),
                )
            )

        select_columns.append(self._build_single_touch_timestamp_expr(attribution_window_seconds))

        for field in TRACKED_FIELDS:
            select_columns.append(self._build_single_touch_fallback_expr(field.fallback_value, field.utm_array))

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=inner_query),
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(
                    expr=ast.Call(name="arrayEnumerate", args=[ast.Field(chain=["conversion_timestamps"])]),
                    alias="i",
                )
            ],
        )

    def _build_single_touch_timestamp_expr(self, attribution_window_seconds: int) -> ast.Alias:
        """Build expression to find most recent UTM pageview within attribution window"""
        return ast.Alias(
            alias="last_utm_timestamp",
            expr=ast.Call(
                name=self.config.attribution_mode_operator,
                args=[
                    ast.Call(
                        name="arrayFilter",
                        args=[
                            ast.Lambda(
                                args=["x"],
                                expr=ast.And(
                                    exprs=[
                                        ast.CompareOperation(
                                            left=ast.Field(chain=["x"]),
                                            op=ast.CompareOperationOp.LtEq,
                                            right=ast.ArrayAccess(
                                                array=ast.Field(chain=["conversion_timestamps"]),
                                                property=ast.Field(chain=["i"]),
                                            ),
                                        ),
                                        ast.CompareOperation(
                                            left=ast.Field(chain=["x"]),
                                            op=ast.CompareOperationOp.GtEq,
                                            right=ast.ArithmeticOperation(
                                                left=ast.ArrayAccess(
                                                    array=ast.Field(chain=["conversion_timestamps"]),
                                                    property=ast.Field(chain=["i"]),
                                                ),
                                                op=ast.ArithmeticOperationOp.Sub,
                                                right=ast.Constant(value=attribution_window_seconds),
                                            ),
                                        ),
                                    ]
                                ),
                            ),
                            ast.Field(chain=["utm_timestamps"]),
                        ],
                    ),
                ],
            ),
        )

    def _build_single_touch_fallback_expr(self, alias: str, utm_array_field: str) -> ast.Alias:
        """Build expression for fallback UTM data"""
        return ast.Alias(
            alias=alias,
            expr=ast.Call(
                name="if",
                args=[
                    ast.Call(
                        name="isNotNull",
                        args=[ast.Field(chain=["last_utm_timestamp"])],
                    ),
                    ast.ArrayAccess(
                        array=ast.Field(chain=[utm_array_field]),
                        property=ast.Call(
                            name="indexOf",
                            args=[
                                ast.Field(chain=["utm_timestamps"]),
                                ast.Field(chain=["last_utm_timestamp"]),
                            ],
                        ),
                    ),
                    ast.Constant(value=""),
                ],
            ),
        )

    def _build_filtered_utm_timestamps_expr(self, attribution_window_seconds: int) -> ast.Call:
        """Build expression to filter utm_timestamps within the attribution window before conversion time."""
        return ast.Call(
            name="arrayFilter",
            args=[
                ast.Lambda(
                    args=["x"],
                    expr=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["x"]),
                                op=ast.CompareOperationOp.LtEq,
                                right=ast.ArrayAccess(
                                    array=ast.Field(chain=["conversion_timestamps"]),
                                    property=ast.Field(chain=["i"]),
                                ),
                            ),
                            ast.CompareOperation(
                                left=ast.Field(chain=["x"]),
                                op=ast.CompareOperationOp.GtEq,
                                right=ast.ArithmeticOperation(
                                    left=ast.ArrayAccess(
                                        array=ast.Field(chain=["conversion_timestamps"]),
                                        property=ast.Field(chain=["i"]),
                                    ),
                                    op=ast.ArithmeticOperationOp.Sub,
                                    right=ast.Constant(value=attribution_window_seconds),
                                ),
                            ),
                        ]
                    ),
                ),
                ast.Field(chain=["utm_timestamps"]),
            ],
        )

    def _build_multi_touch_weights_expr(
        self, filtered_timestamps_alias: str, attribution_window_seconds: int
    ) -> ast.Expr:
        """Build weight array expression based on multi-touch attribution mode."""
        filtered_ts = ast.Field(chain=[filtered_timestamps_alias])

        if self.config.attribution_mode == AttributionMode.LINEAR:
            return build_linear_weights(filtered_ts)
        elif self.config.attribution_mode == AttributionMode.TIME_DECAY:
            conversion_time = ast.ArrayAccess(
                array=ast.Field(chain=["conversion_timestamps"]),
                property=ast.Field(chain=["i"]),
            )
            return build_time_decay_weights(filtered_ts, conversion_time, attribution_window_seconds)
        elif self.config.attribution_mode == AttributionMode.POSITION_BASED:
            return build_position_based_weights(filtered_ts)

        raise ValueError(f"Unknown multi-touch attribution mode: {self.config.attribution_mode}")

    def _build_multi_touch_array_join_subquery(
        self, inner_query: ast.SelectQuery, attribution_window_seconds: int
    ) -> ast.SelectQuery:
        """Build subquery with ARRAY JOIN for conversions, plus filtered touchpoint arrays for multi-touch."""
        filtered_ts_expr = self._build_filtered_utm_timestamps_expr(attribution_window_seconds)

        select_columns: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Alias(
                alias="conversion_time",
                expr=ast.ArrayAccess(
                    array=ast.Field(chain=["conversion_timestamps"]),
                    property=ast.Field(chain=["i"]),
                ),
            ),
            ast.Alias(
                alias="conversion_math_value",
                expr=ast.ArrayAccess(
                    array=ast.Field(chain=["conversion_math_values"]),
                    property=ast.Field(chain=["i"]),
                ),
            ),
        ]

        # Add conversion value for each tracked field
        for field in TRACKED_FIELDS:
            select_columns.append(
                ast.Alias(
                    alias=field.conversion_value,
                    expr=ast.ArrayAccess(
                        array=ast.Field(chain=[field.conversion_array]),
                        property=ast.Field(chain=["i"]),
                    ),
                )
            )

        # Add filtered touchpoint timestamps
        select_columns.append(ast.Alias(alias="filtered_utm_timestamps", expr=filtered_ts_expr))

        # Add filtered UTM arrays (filter to same indices as filtered timestamps)
        for field in TRACKED_FIELDS:
            select_columns.append(
                ast.Alias(
                    alias=f"filtered_{field.utm_array}",
                    expr=self._build_filtered_utm_field_expr(field.utm_array, attribution_window_seconds),
                )
            )

        # Add weights array
        select_columns.append(
            ast.Alias(
                alias="attribution_weights",
                expr=self._build_multi_touch_weights_expr("filtered_utm_timestamps", attribution_window_seconds),
            )
        )

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=inner_query),
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(
                    expr=ast.Call(name="arrayEnumerate", args=[ast.Field(chain=["conversion_timestamps"])]),
                    alias="i",
                )
            ],
        )

    def _build_filtered_utm_field_expr(self, utm_array_field: str, attribution_window_seconds: int) -> ast.Call:
        """Filter a UTM field array to only entries within the attribution window."""
        conversion_time = ast.ArrayAccess(
            array=ast.Field(chain=["conversion_timestamps"]),
            property=ast.Field(chain=["i"]),
        )
        window_start = ast.ArithmeticOperation(
            left=conversion_time,
            op=ast.ArithmeticOperationOp.Sub,
            right=ast.Constant(value=attribution_window_seconds),
        )

        # Use arrayFilter with index to match the same positions as filtered_utm_timestamps
        return ast.Call(
            name="arrayMap",
            args=[
                ast.Lambda(
                    args=["idx"],
                    expr=ast.ArrayAccess(
                        array=ast.Field(chain=[utm_array_field]),
                        property=ast.Field(chain=["idx"]),
                    ),
                ),
                # Get indices of utm_timestamps that are within the window
                ast.Call(
                    name="arrayFilter",
                    args=[
                        ast.Lambda(
                            args=["j"],
                            expr=ast.And(
                                exprs=[
                                    ast.CompareOperation(
                                        left=ast.ArrayAccess(
                                            array=ast.Field(chain=["utm_timestamps"]),
                                            property=ast.Field(chain=["j"]),
                                        ),
                                        op=ast.CompareOperationOp.LtEq,
                                        right=conversion_time,
                                    ),
                                    ast.CompareOperation(
                                        left=ast.ArrayAccess(
                                            array=ast.Field(chain=["utm_timestamps"]),
                                            property=ast.Field(chain=["j"]),
                                        ),
                                        op=ast.CompareOperationOp.GtEq,
                                        right=window_start,
                                    ),
                                ]
                            ),
                        ),
                        ast.Call(name="arrayEnumerate", args=[ast.Field(chain=["utm_timestamps"])]),
                    ],
                ),
            ],
        )

    def _build_multi_touch_attribution_subquery(
        self,
        array_join_query: ast.SelectQuery,
    ) -> ast.SelectQuery:
        """Build subquery that explodes touchpoints and applies multi-touch weights.

        Takes one row per conversion (from array_join_query) and produces one row
        per touchpoint, each with the attribution weight for that touchpoint.

        Emits conversion_value = value * weight for direct-path consumption.
        """
        # Inner subquery: ARRAY JOIN on touchpoints to explode them
        touchpoint_select: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Field(chain=["conversion_math_value"]),
        ]

        for field in TRACKED_FIELDS:
            touchpoint_select.append(ast.Field(chain=[field.conversion_value]))

        for field in TRACKED_FIELDS:
            touchpoint_select.append(
                ast.Alias(
                    alias=field.fallback_value,
                    expr=ast.ArrayAccess(
                        array=ast.Field(chain=[f"filtered_{field.utm_array}"]),
                        property=ast.Field(chain=["tp_idx"]),
                    ),
                )
            )

        touchpoint_select.append(
            ast.Alias(
                alias="attribution_weight",
                expr=ast.ArrayAccess(
                    array=ast.Field(chain=["attribution_weights"]),
                    property=ast.Field(chain=["tp_idx"]),
                ),
            )
        )

        touchpoint_exploded = ast.SelectQuery(
            select=touchpoint_select,
            select_from=ast.JoinExpr(table=array_join_query),
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(
                    expr=ast.Call(
                        name="arrayEnumerate",
                        args=[ast.Field(chain=["attribution_weights"])],
                    ),
                    alias="tp_idx",
                )
            ],
        )

        person_id_field = ast.Field(chain=["person_id"])
        outer_select: list[ast.Expr] = [
            person_id_field,
        ]

        for field in TRACKED_FIELDS:
            outer_select.append(
                ast.Alias(
                    alias=field.attributed_name,
                    expr=self._build_attribution_expr(field.conversion_value, field.fallback_value),
                )
            )

        outer_select.extend(
            [
                ast.Alias(alias="campaign_id", expr=ast.Constant(value="-")),
                ast.Alias(
                    alias="conversion_value",
                    expr=ast.ArithmeticOperation(
                        left=self._get_final_conversion_value_expr(),
                        op=ast.ArithmeticOperationOp.Mult,
                        right=ast.Field(chain=["attribution_weight"]),
                    ),
                ),
                # Carried out of the subquery so a consumer can count conversions rather than
                # rows: these sum to 1.0 per conversion, so summing them undoes the explode.
                ast.Field(chain=["attribution_weight"]),
            ]
        )

        return ast.SelectQuery(
            select=outer_select,
            select_from=ast.JoinExpr(table=touchpoint_exploded),
        )

    def _build_single_touch_attribution_subquery(
        self,
        array_join_query: ast.SelectQuery,
    ) -> ast.SelectQuery:
        """Build subquery that applies attribution logic."""
        person_id_field = ast.Field(chain=["person_id"])
        select_columns: list[ast.Expr] = [
            person_id_field,
        ]

        for field in TRACKED_FIELDS:
            select_columns.append(
                ast.Alias(
                    alias=field.attributed_name,
                    expr=self._build_attribution_expr(field.conversion_value, field.fallback_value),
                )
            )

        select_columns.append(
            ast.Alias(
                alias="campaign_id",
                # Campaign IDs don't exist in event data, only in marketing platform data
                expr=ast.Constant(value="-"),
            )
        )

        select_columns.append(
            ast.Alias(
                alias="conversion_value",
                expr=self._get_final_conversion_value_expr(),
            )
        )

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=array_join_query),
        )

    def _build_attribution_expr(self, direct_field: str, fallback_field: str) -> ast.Call:
        """Build attribution expression with direct and fallback logic"""
        return ast.Call(
            name="if",
            args=[
                ast.Call(name="notEmpty", args=[ast.Field(chain=[direct_field])]),
                ast.Field(chain=[direct_field]),
                ast.Call(
                    name="if",
                    args=[
                        ast.Call(name="notEmpty", args=[ast.Field(chain=[fallback_field])]),
                        ast.Field(chain=[fallback_field]),
                        ast.Constant(value=""),
                    ],
                ),
            ],
        )

    def _get_final_conversion_value_expr(self) -> ast.Expr:
        """Get numeric conversion value expression for attribution logic.

        For SUM math, returns the actual property value (e.g. revenue).
        For TOTAL and DAU, returns 1. DAU aggregation uses uniq(person_id)
        directly and ignores conversion_value.
        """
        math_type = self.goal.math

        if math_type in ["sum", PropertyMathType.SUM] or str(math_type).endswith("_sum"):
            return ast.Call(name="toFloat", args=[ast.Field(chain=["conversion_math_value"])])
        else:
            return ast.Constant(value=1)

    def _normalize_source_field(self, source_expr: ast.Expr) -> ast.Expr:
        """
        Normalize source field to map alternative UTM sources to primary sources.
        Case-insensitive matching - 'YouTube', 'youtube', 'YOUTUBE' all map to 'google'.
        Includes both adapter-defined sources and team-configured custom sources.
        """
        source_mappings = MarketingSourceFactory.get_all_source_identifier_mappings(
            team_config=self.team.marketing_analytics_config
        )
        return build_source_normalization_expr(source_expr, source_mappings)

    def _build_final_aggregation_query(self, attribution_query: ast.SelectQuery) -> ast.SelectQuery:
        """Build final aggregation query with organic defaults"""
        level = self.config.drill_down_level

        # Build organic-default expressions for each tracked field
        # Campaign and source use config-driven organic defaults; others use TrackedField defaults
        organic_overrides = {
            "campaign": self.config.organic_campaign,
            "source": self.config.organic_source,
        }
        field_exprs: dict[str, ast.Expr] = {}
        for field in TRACKED_FIELDS:
            default = organic_overrides.get(field.name, field.default_value)
            field_expr: ast.Expr
            if field.name == "source":
                field_expr = self._normalize_source_field(self._build_source_expr(field, default))
            else:
                field_expr = self._build_organic_default_expr(field.attributed_name, default)
            field_exprs[field.name] = field_expr

        campaign_expr = field_exprs["campaign"]
        source_expr = field_exprs["source"]

        if level == MarketingAnalyticsDrillDownLevel.CHANNEL:
            channel_type_expr = self._build_channel_type_expr(field_exprs=field_exprs)
            select_columns: list[ast.Expr] = [
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.campaign_field, expr=channel_type_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=ast.Constant(value="")),
                ast.Alias(
                    alias=self.config.get_conversion_goal_column_name(self.index),
                    expr=self._get_aggregation_expr(),
                ),
            ]
            group_by: list[ast.Expr] = [channel_type_expr]
        elif level == MarketingAnalyticsDrillDownLevel.CHANNEL_SOURCE:
            channel_type_expr = self._build_channel_type_expr(field_exprs=field_exprs)
            select_columns = [
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.campaign_field, expr=channel_type_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=source_expr),
                ast.Alias(
                    alias=self.config.get_conversion_goal_column_name(self.index),
                    expr=self._get_aggregation_expr(),
                ),
            ]
            group_by = [channel_type_expr, source_expr]
        elif level == MarketingAnalyticsDrillDownLevel.SOURCE:
            # At source level, group by source_name only
            select_columns = [
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.campaign_field, expr=source_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=source_expr),
                ast.Alias(
                    alias=self.config.get_conversion_goal_column_name(self.index),
                    expr=self._get_aggregation_expr(),
                ),
            ]
            group_by = [source_expr]
        elif level in (
            MarketingAnalyticsDrillDownLevel.MEDIUM,
            MarketingAnalyticsDrillDownLevel.CONTENT,
            MarketingAnalyticsDrillDownLevel.TERM,
        ):
            utm_expr = field_exprs[self._UTM_LEVEL_FIELD_MAP[level]]
            select_columns = [
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.campaign_field, expr=utm_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=ast.Constant(value="")),
                ast.Alias(
                    alias=self.config.get_conversion_goal_column_name(self.index),
                    expr=self._get_aggregation_expr(),
                ),
            ]
            group_by = [utm_expr]
        else:
            # Schema: [0]=match_key, [1]=campaign, [2]=id, [3]=source, [4]=conversion
            select_columns = [
                ast.Alias(alias=self.config.match_key_field, expr=campaign_expr),
                ast.Alias(alias=self.config.campaign_field, expr=campaign_expr),
                ast.Alias(
                    alias=self.config.id_field,
                    expr=self._build_organic_default_expr("campaign_id", "-"),
                ),
                ast.Alias(alias=self.config.source_field, expr=source_expr),
                ast.Alias(
                    alias=self.config.get_conversion_goal_column_name(self.index),
                    expr=self._get_aggregation_expr(),
                ),
            ]
            group_by = [ast.Field(chain=[field]) for field in self.config.group_by_fields]

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=attribution_query, alias="attributed_conversions"),
            group_by=group_by,
        )

    def _build_organic_default_expr(self, field_name: str, default_value: str) -> ast.Call:
        """Build expression with organic default"""
        return ast.Call(
            name="if",
            args=[
                ast.Call(name="notEmpty", args=[ast.Field(chain=[field_name])]),
                ast.Field(chain=[field_name]),
                ast.Constant(value=default_value),
            ],
        )

    def _build_source_expr(self, source: TrackedField, default_value: str) -> ast.Expr:
        """Attributed source, naming the ad network when only a click id identifies it.

        A pageview qualifies as a touchpoint on a click id alone, and channel_type reads those
        same click ids to classify the row as paid. Falling straight through to the organic
        default would put an organic source next to a paid channel on one row, and would leave
        the conversion in the organic bucket on the campaign and source levels.
        """
        source_field = ast.Field(chain=[source.attributed_name])
        fallback: ast.Expr = ast.Constant(value=default_value)
        for field in reversed(CLICK_ID_FIELDS):
            fallback = ast.Call(
                name="if",
                args=[
                    ast.Call(name="notEmpty", args=[ast.Field(chain=[field.attributed_name])]),
                    ast.Constant(value=field.click_id_source),
                    fallback,
                ],
            )
        return ast.Call(
            name="if",
            args=[ast.Call(name="notEmpty", args=[source_field]), source_field, fallback],
        )

    def _apply_organic_default(self, expr: ast.Expr, default_value: str) -> ast.Call:
        """Fall back to the organic default when the value is NULL or empty, matching the
        events attribution path so all goal kinds classify unattributed conversions alike."""
        return ast.Call(
            name="if",
            args=[
                ast.Call(
                    name="notEmpty",
                    args=[ast.Call(name="coalesce", args=[expr, ast.Constant(value="")])],
                ),
                expr,
                ast.Constant(value=default_value),
            ],
        )

    def _resolve_direct_field_expr(self, field: TrackedField, table: str) -> ast.Expr:
        """Resolve a tracked field to an AST expression for direct queries (no attribution pipeline)."""
        if self.goal.kind in ["EventsNode", "ActionsNode"]:
            resolved_name = self._resolve_field_name(field)
            raw_expr: ast.Expr = ast.Field(chain=["events", "properties", resolved_name])
            return ast.Call(name="coalesce", args=[raw_expr, ast.Constant(value=field.default_value)])
        elif field.schema_map_key and field.schema_map_key in self.goal.schema_map:
            raw_expr = ast.Field(chain=[self.goal.schema_map[field.schema_map_key]])
            return ast.Call(name="coalesce", args=[raw_expr, ast.Constant(value=field.default_value)])
        else:
            return ast.Constant(value=field.default_value)

    def _build_channel_type_expr(self, field_exprs: dict[str, ast.Expr]) -> ast.Expr:
        """Compute channel_type for conversion goal data using web analytics' classification.

        Uses all tracked fields from the attribution pipeline for accurate classification.
        """
        modifiers = create_default_modifiers_for_team(self.team)

        # Convert gclid/fbclid string values to boolean presence checks
        gclid_expr = field_exprs.get("gclid", ast.Constant(value=""))
        has_gclid = ast.Call(name="notEmpty", args=[ast.Call(name="toString", args=[gclid_expr])])

        fbclid_expr = field_exprs.get("fbclid", ast.Constant(value=""))
        has_fbclid = ast.Call(name="notEmpty", args=[ast.Call(name="toString", args=[fbclid_expr])])

        return create_channel_type_expr(
            custom_rules=modifiers.customChannelTypeRules,
            source_exprs=ChannelTypeExprs(
                source=field_exprs.get("source", ast.Constant(value="")),
                medium=field_exprs.get("medium", ast.Constant(value="")),
                campaign=field_exprs.get("campaign", ast.Constant(value="")),
                referring_domain=field_exprs.get("referring_domain", ast.Constant(value="$direct")),
                url=ast.Constant(value=""),
                hostname=ast.Constant(value=""),
                pathname=ast.Constant(value=""),
                has_gclid=has_gclid,
                has_fbclid=has_fbclid,
                gad_source=field_exprs.get("gad_source", ast.Constant(value=None)),
            ),
        )

    def _get_aggregation_expr(self) -> ast.Expr:
        """Get aggregation expression based on math type.

        For multi-touch attribution, conversion_value already contains the weighted
        fractional credit, so we always sum it instead of counting rows.
        """
        math_type = self.goal.math

        if self.config.is_multi_touch:
            # Multi-touch: conversion_value already has weight applied (e.g. 0.5 for linear with 2 touchpoints)
            # Always sum the weighted values regardless of math type
            if math_type in [BaseMathType.DAU, "dau"]:
                # DAU uses uniq(person_id) without weighting — a person who converted
                # via 3 campaigns counts as 1 unique user in each campaign row.
                # This means campaign-level totals can exceed the true unique user count,
                # which is intentional: you cannot fractionally split a person.
                return ast.Call(name="uniq", args=[ast.Field(chain=["person_id"])])
            sum_expr = ast.Call(name="sum", args=[ast.Field(chain=["conversion_value"])])
            return ast.Call(name="coalesce", args=[sum_expr, ast.Constant(value=0)])

        if math_type in [BaseMathType.DAU, "dau"]:
            # uniq() already returns 0 for no rows, no need for COALESCE
            return ast.Call(name="uniq", args=[ast.Field(chain=["person_id"])])
        elif math_type in ["sum", PropertyMathType.SUM] or str(math_type).endswith("_sum"):
            # sum() returns NULL for no rows, wrap with COALESCE to return 0
            sum_expr = ast.Call(name="sum", args=[ast.Field(chain=["conversion_value"])])
            return ast.Call(name="coalesce", args=[sum_expr, ast.Constant(value=0)])
        else:
            # count() already returns 0 for no rows, no need for COALESCE
            return ast.Call(name="count", args=[])

    def _generate_direct_query(self, additional_conditions: Sequence[ast.Expr]) -> ast.SelectQuery:
        """Generate direct field access query for DataWarehouse nodes"""
        level = self.config.drill_down_level
        table = self.get_table_name()
        select_field = self.get_select_field()
        utm_campaign_expr, utm_source_expr = self.get_utm_expressions()

        # Build WHERE conditions
        where_conditions = self.get_base_where_conditions()
        where_conditions = add_conversion_goal_property_filters(where_conditions, self.goal, self.team)
        where_conditions.extend(additional_conditions)

        # Campaign expression with organic default
        campaign_expr = self._apply_organic_default(utm_campaign_expr, self.config.organic_campaign)
        source_expr = self._normalize_source_field(
            self._apply_organic_default(utm_source_expr, self.config.organic_source)
        )

        # Build field expressions for all tracked fields
        field_exprs: dict[str, ast.Expr] = {
            "campaign": campaign_expr,
            "source": source_expr,
        }
        for field in TRACKED_FIELDS:
            if field.name in ("campaign", "source"):
                continue  # Already handled above with special organic defaults
            field_expr = self._resolve_direct_field_expr(field, table)
            field_exprs[field.name] = field_expr

        if level == MarketingAnalyticsDrillDownLevel.CHANNEL:
            channel_type_expr = self._build_channel_type_expr(field_exprs=field_exprs)
            select_columns: list[ast.Expr] = [
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.campaign_field, expr=channel_type_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.get_conversion_goal_column_name(self.index), expr=select_field),
            ]
            group_by: list[ast.Expr] = [channel_type_expr]
        elif level == MarketingAnalyticsDrillDownLevel.CHANNEL_SOURCE:
            channel_type_expr = self._build_channel_type_expr(field_exprs=field_exprs)
            select_columns = [
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.campaign_field, expr=channel_type_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=source_expr),
                ast.Alias(alias=self.config.get_conversion_goal_column_name(self.index), expr=select_field),
            ]
            group_by = [channel_type_expr, source_expr]
        elif level == MarketingAnalyticsDrillDownLevel.SOURCE:
            select_columns = [
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.campaign_field, expr=source_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=source_expr),
                ast.Alias(alias=self.config.get_conversion_goal_column_name(self.index), expr=select_field),
            ]
            group_by = [source_expr]
        elif level in (
            MarketingAnalyticsDrillDownLevel.MEDIUM,
            MarketingAnalyticsDrillDownLevel.CONTENT,
            MarketingAnalyticsDrillDownLevel.TERM,
        ):
            utm_expr = field_exprs[self._UTM_LEVEL_FIELD_MAP[level]]
            select_columns = [
                ast.Alias(alias=self.config.match_key_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.campaign_field, expr=utm_expr),
                ast.Alias(alias=self.config.id_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.source_field, expr=ast.Constant(value="")),
                ast.Alias(alias=self.config.get_conversion_goal_column_name(self.index), expr=select_field),
            ]
            group_by = [utm_expr]
        else:
            select_columns = [
                ast.Alias(alias=self.config.match_key_field, expr=campaign_expr),
                ast.Alias(alias=self.config.campaign_field, expr=campaign_expr),
                ast.Alias(
                    alias=self.config.id_field,
                    expr=ast.Constant(value="-"),
                ),
                ast.Alias(alias=self.config.source_field, expr=source_expr),
                ast.Alias(alias=self.config.get_conversion_goal_column_name(self.index), expr=select_field),
            ]
            group_by = [ast.Field(chain=[field]) for field in self.config.group_by_fields]

        # Build WHERE clause
        where_expr: Optional[ast.Expr] = None
        if where_conditions:
            where_expr = ast.And(exprs=where_conditions) if len(where_conditions) > 1 else where_conditions[0]

        return ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=[table])),
            where=where_expr,
            group_by=group_by,
        )

    def generate_join_clause(self, use_full_outer_join: bool = False) -> ast.JoinExpr:
        """Generate JOIN clause for this conversion goal"""
        cte_name = self.get_cte_name()
        alias = self.config.get_conversion_goal_alias(self.index)

        join_condition = ast.And(
            exprs=[
                ast.CompareOperation(
                    left=ast.Field(chain=self.config.get_campaign_cost_field_chain(self.config.campaign_field)),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Field(chain=[alias, self.config.campaign_field]),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=self.config.get_campaign_cost_field_chain(self.config.source_field)),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Field(chain=[alias, self.config.source_field]),
                ),
            ]
        )

        join_type = "FULL OUTER JOIN" if use_full_outer_join else "LEFT JOIN"
        return ast.JoinExpr(
            join_type=join_type,
            table=ast.Field(chain=[cte_name]),
            alias=alias,
            constraint=ast.JoinConstraint(expr=join_condition, constraint_type="ON"),
        )

    def generate_select_columns(self) -> list[ast.Alias]:
        """Generate SELECT columns for this conversion goal"""
        goal_name = self.goal.conversion_goal_name
        alias_prefix = self.config.get_conversion_goal_alias(self.index)

        conversion_goal_field = ast.Field(chain=[alias_prefix, self.config.get_conversion_goal_column_name(self.index)])
        conversion_goal_alias = ast.Alias(alias=goal_name, expr=conversion_goal_field)

        # Cost per conversion calculation
        cost_field = ast.Field(chain=self.config.get_campaign_cost_field_chain(self.config.total_cost_field))
        goal_field = ast.Field(chain=[alias_prefix, self.config.get_conversion_goal_column_name(self.index)])

        cost_per_goal_expr = ast.Call(
            name="round",
            args=[
                ast.ArithmeticOperation(
                    left=cost_field,
                    op=ast.ArithmeticOperationOp.Div,
                    right=ast.Call(name="nullif", args=[goal_field, ast.Constant(value=0)]),
                ),
                ast.Constant(value=self.config.decimal_precision),
            ],
        )

        cost_per_goal_alias = ast.Alias(
            alias=f"{self.config.cost_per_prefix} {goal_name}",
            expr=cost_per_goal_expr,
        )

        return [conversion_goal_alias, cost_per_goal_alias]

    def _ensure_datetime_call(self, date_expr: ast.Expr) -> ast.Expr:
        """Convert toDate to toDateTime for proper date handling"""
        if isinstance(date_expr, ast.Call) and date_expr.name == "toDate":
            return ast.Call(name="toDateTime", args=date_expr.args)
        return date_expr

    def _is_date_condition(self, condition: ast.Expr) -> bool:
        """Check if condition filters on timestamp fields"""

        def has_timestamp_field(expr: ast.Expr) -> bool:
            if isinstance(expr, ast.Field):
                return "timestamp" in expr.chain
            elif isinstance(expr, ast.CompareOperation):
                return has_timestamp_field(expr.left) or has_timestamp_field(expr.right)
            elif isinstance(expr, ast.Call):
                return any(has_timestamp_field(arg) for arg in expr.args)
            return False

        return has_timestamp_field(condition)

    def _is_event_condition(self, condition: ast.Expr, conversion_event: Optional[str]) -> bool:
        """Check if condition filters on event types that we handle explicitly"""
        # For ActionsNode, we need to check if this is an action condition
        if self.goal.kind == "ActionsNode" and conversion_event is None:
            # Check if this condition comes from action_to_expr (complex action conditions)
            # Action conditions can be complex AST expressions, not just simple event comparisons
            # We identify them by checking if they're in our base conditions
            base_conditions = self.get_base_where_conditions()
            for base_condition in base_conditions:
                if condition == base_condition:
                    return True

        if isinstance(condition, ast.CompareOperation):
            if (
                isinstance(condition.left, ast.Field)
                and condition.left.chain == ["events", "event"]
                and condition.op == ast.CompareOperationOp.Eq
                and isinstance(condition.right, ast.Constant)
            ):
                event_value = condition.right.value
                # Only consider it an "event condition we handle" if it's related to our conversion logic
                return event_value == conversion_event or event_value == "$pageview"

        return False
