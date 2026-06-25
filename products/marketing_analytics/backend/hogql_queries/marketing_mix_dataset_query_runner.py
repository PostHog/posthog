"""Marketing Mix Modeling dataset builder (Phase A of the MMM POC).

Produces the modeling input for the MMM Dagster job and the staff-only "Mix model" tab: a weekly
``week × channel`` spend panel (spend / impressions / clicks) plus a companion weekly outcome series
with calendar controls. It is the one place that turns a team's ad-spend integrations and a single
conversion goal into a clean weekly panel.

It is deliberately a standalone class rather than a registered ``QueryRunner`` subclass: there is no
user-facing insight, no caching, and no schema query-kind to register — it is an internal computation
feeding a Dagster op and a read-only export endpoint. It still reuses the vetted marketing-analytics
machinery: the source-adapter factory (for the per-source cost extraction) and ``ConversionGoalProcessor``
(for the outcome event/where clause), constructing the shared HogQL ``Database`` / ``HogQLContext`` the
same way ``MarketingAnalyticsBaseQueryRunner`` does.

Two design choices worth calling out:

- **Spend has a date axis via the materialization query.** The live adapter union
  (``factory.build_union_query_ast``) pre-aggregates each source to campaign totals with no date
  column, so it can't drive a weekly panel. The per-day path is ``adapter.build_materialization_query``
  (it adds ``cost_date``); we reuse it and resolve its ``time_window_min`` / ``time_window_max``
  placeholders to the modeling window, then roll up to ``toStartOfWeek``. "Channel" here is the ad
  platform (the adapter's ``source_name``) — the GA4 channel-type classifier is for pageview
  attribution and is not used.
- **The outcome is decoupled from ``ConversionGoalsAggregator``.** We take one goal from the team's
  ``conversion_goals`` and build a standalone weekly series from its event/where clause, so the panel
  isn't entangled with the attribution pipeline.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from typing import Optional, cast

from posthog.schema import DateRange, MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team import Team
from posthog.models.team.team import DEFAULT_CURRENCY
from posthog.models.user import User

from .adapters.base import QueryContext
from .adapters.factory import MarketingSourceFactory
from .conversion_goal_processor import ConversionGoalProcessor
from .marketing_analytics_config import MarketingAnalyticsConfig
from .utils import convert_team_conversion_goals_to_objects

# ~18 months of weekly data — enough to clear the ≥52-week sufficiency bar with headroom for the
# holdout the modeling step keeps, while staying recent enough that the spend mix is representative.
DEFAULT_WINDOW_WEEKS = 78

# A channel-week below this (in the team's base currency) doesn't count as "material" for the
# sufficiency guard. A starting heuristic — small enough to admit real but modest channels, large
# enough to reject rounding-noise spend. Tune per team once we have more runs.
MATERIAL_SPEND_WEEKLY_THRESHOLD = 100.0

# MMM needs enough weeks where the spend mix actually varies across channels to identify each
# channel's effect; raw row count isn't the bar (see design doc / MMM-0a).
MIN_SUFFICIENT_WEEKS = 52
MIN_MATERIAL_CHANNELS = 2

# Crude US holiday-heavy ISO week numbers (New Year, July 4th, US Thanksgiving, Christmas). A static
# starting list per the spec — the right long-term answer is a per-region holiday calendar, but a
# binary "is this a holiday-distorted week" control is enough to start de-biasing the outcome series.
HOLIDAY_WEEKS_OF_YEAR = frozenset({1, 27, 47, 48, 51, 52})

# Marker channel for the model's intercept / always-on baseline in the contributions dataset.
BASELINE_CHANNEL = "__baseline__"

STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient_history"


@dataclass
class SpendPanelRow:
    week: datetime.date
    channel: str
    spend: float
    impressions: float
    clicks: float


@dataclass
class OutcomeRow:
    week: datetime.date
    outcome: float
    control_weekofyear: int
    is_holiday_week: int


@dataclass
class MarketingMixDataset:
    status: str
    message: str
    date_from: datetime.date
    date_to: datetime.date
    window_weeks: int
    outcome_kind: str
    outcome_ref: str
    channels: list[str] = field(default_factory=list)
    spend_panel: list[SpendPanelRow] = field(default_factory=list)
    outcome_series: list[OutcomeRow] = field(default_factory=list)

    @property
    def is_sufficient(self) -> bool:
        return self.status == STATUS_OK


def default_window(today: Optional[datetime.date] = None, window_weeks: int = DEFAULT_WINDOW_WEEKS) -> DateRange:
    """The default modeling window: the trailing ``window_weeks`` ending today."""
    today = today or datetime.date.today()
    start = today - datetime.timedelta(weeks=window_weeks)
    return DateRange(date_from=start.isoformat(), date_to=today.isoformat())


class MarketingMixDatasetQueryRunner:
    def __init__(
        self,
        team: Team,
        date_range: Optional[DateRange] = None,
        outcome_index: int = 0,
        user: Optional[User] = None,
        modifiers=None,
    ) -> None:
        self.team = team
        self.user = user
        self.modifiers = modifiers
        self.outcome_index = outcome_index
        self.config = MarketingAnalyticsConfig.from_team(team)
        self._date_range = date_range or default_window()

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(date_range=self._date_range, team=self.team, interval=None, now=datetime.datetime.now())

    @property
    def date_from(self) -> datetime.date:
        return self.query_date_range.date_from().date()

    @property
    def date_to(self) -> datetime.date:
        return self.query_date_range.date_to().date()

    @property
    def window_weeks(self) -> int:
        return max(1, (self.date_to - self.date_from).days // 7)

    @cached_property
    def _database(self) -> Database:
        modifiers = create_default_modifiers_for_team(self.team, self.modifiers)
        return Database.create_for(team=self.team, user=self.user, modifiers=modifiers)

    @cached_property
    def _hogql_context(self) -> HogQLContext:
        return HogQLContext(team_id=self.team.pk, database=self._database)

    def _adapters(self) -> list:
        """Valid ad-spend source adapters at campaign grain over the modeling window."""
        context = QueryContext(
            date_range=self.query_date_range,
            team=self.team,
            base_currency=self.team.base_currency or DEFAULT_CURRENCY,
            # Campaign grain: the spend panel rolls every campaign up to its platform (channel), so we
            # don't need ad-group / ad detail, and campaign-grain rows are the broadest a source emits.
            drill_down_level=MarketingAnalyticsDrillDownLevel.CAMPAIGN,
            database=self._database,
        )
        factory = MarketingSourceFactory(context=context)
        return factory.get_valid_adapters(factory.create_adapters())

    def _build_spend_panel_query(self) -> Optional[ast.SelectQuery]:
        """Union each source's per-day cost rows, then roll up to ``week × channel``.

        Returns None when no source produces a materialization query (no integrations configured).
        """
        adapters = self._adapters()
        # Half-open window [min, max) matches the materialization WHERE; +1 day so the last day counts.
        window_min = ast.Constant(value=datetime.datetime.combine(self.date_from, datetime.time.min))
        window_max = ast.Constant(
            value=datetime.datetime.combine(self.date_to + datetime.timedelta(days=1), datetime.time.min)
        )

        members: list[ast.SelectQuery | ast.SelectSetQuery] = []
        for adapter in adapters:
            materialization = adapter.build_materialization_query(adapter.get_source_id())
            if materialization is None:
                continue
            resolved = replace_placeholders(
                materialization, {"time_window_min": window_min, "time_window_max": window_max}
            )
            members.append(cast(ast.SelectQuery, resolved))

        if not members:
            return None

        union = ast.SelectSetQuery.create_from_queries(members, set_operator="UNION ALL")
        return ast.SelectQuery(
            select=[
                ast.Alias(alias="week", expr=ast.Call(name="toStartOfWeek", args=[ast.Field(chain=["cost_date"])])),
                ast.Alias(alias="channel", expr=ast.Field(chain=["source_name"])),
                ast.Alias(alias="spend", expr=ast.Call(name="sum", args=[ast.Field(chain=["cost"])])),
                ast.Alias(alias="impressions", expr=ast.Call(name="sum", args=[ast.Field(chain=["impressions"])])),
                ast.Alias(alias="clicks", expr=ast.Call(name="sum", args=[ast.Field(chain=["clicks"])])),
            ],
            select_from=ast.JoinExpr(table=union),
            group_by=[ast.Field(chain=["week"]), ast.Field(chain=["channel"])],
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["week"]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=["channel"]), order="ASC"),
            ],
        )

    def _spend_panel(self) -> list[SpendPanelRow]:
        query = self._build_spend_panel_query()
        if query is None:
            return []
        # Tag the query for ClickHouse resource attribution; the custom query_type alone doesn't set
        # product/feature, and this runner bypasses the /query endpoint that would otherwise add them.
        with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.QUERY):
            response = execute_hogql_query(
                query_type="marketing_mmm_spend_panel",
                query=query,
                team=self.team,
                modifiers=self.modifiers,
                context=self._hogql_context,
                user=self.user,
            )
        return [
            SpendPanelRow(
                week=row[0],
                channel=str(row[1]),
                spend=float(row[2] or 0.0),
                impressions=float(row[3] or 0.0),
                clicks=float(row[4] or 0.0),
            )
            for row in (response.results or [])
        ]

    def _selected_goal(self):
        """The conversion goal driving the outcome series, or None when none is configured."""
        goals = convert_team_conversion_goals_to_objects(
            self.team.marketing_analytics_config.conversion_goals, self.team.pk
        )
        if not goals or self.outcome_index >= len(goals):
            return None
        return goals[self.outcome_index]

    def _build_outcome_query(self, processor: ConversionGoalProcessor) -> ast.SelectQuery:
        date_field = processor.get_date_field()  # e.g. "events.timestamp"
        date_expr = ast.Field(chain=[*date_field.split(".")])
        date_as_datetime = ast.Call(name="toDateTime", args=[date_expr])
        window = [
            ast.CompareOperation(
                left=date_as_datetime,
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=self.query_date_range.date_from_str)]),
            ),
            ast.CompareOperation(
                left=date_as_datetime,
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=self.query_date_range.date_to_str)]),
            ),
        ]
        conditions = [*processor.get_base_where_conditions(), *window]
        return ast.SelectQuery(
            select=[
                ast.Alias(alias="week", expr=ast.Call(name="toStartOfWeek", args=[date_expr])),
                ast.Alias(alias="outcome", expr=processor.get_select_field()),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[processor.get_table_name()])),
            where=ast.And(exprs=conditions) if len(conditions) > 1 else conditions[0],
            group_by=[ast.Field(chain=["week"])],
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["week"]), order="ASC")],
        )

    def _outcome_series(self, processor: ConversionGoalProcessor) -> list[OutcomeRow]:
        with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.QUERY):
            response = execute_hogql_query(
                query_type="marketing_mmm_outcome_series",
                query=self._build_outcome_query(processor),
                team=self.team,
                modifiers=self.modifiers,
                context=self._hogql_context,
                user=self.user,
            )
        rows: list[OutcomeRow] = []
        for week, outcome in response.results or []:
            week_of_year, is_holiday = _calendar_controls(week)
            rows.append(
                OutcomeRow(
                    week=week,
                    outcome=float(outcome or 0.0),
                    control_weekofyear=week_of_year,
                    is_holiday_week=is_holiday,
                )
            )
        return rows

    def run(self) -> MarketingMixDataset:
        spend_panel = self._spend_panel()
        channels = sorted({row.channel for row in spend_panel})
        goal = self._selected_goal()

        base = MarketingMixDataset(
            status=STATUS_OK,
            message="",
            date_from=self.date_from,
            date_to=self.date_to,
            window_weeks=self.window_weeks,
            outcome_kind=goal.kind if goal else "",
            outcome_ref=(goal.conversion_goal_name if goal else ""),
            channels=channels,
            spend_panel=spend_panel,
        )

        if goal is None:
            base.status = STATUS_INSUFFICIENT
            base.message = (
                "No conversion goal is configured for this project, so there is no outcome series to "
                "model. Add a conversion goal in marketing analytics settings, then re-run."
            )
            return base

        processor = ConversionGoalProcessor(
            goal=goal, index=self.outcome_index, team=self.team, config=self.config, user=self.user
        )
        base.outcome_series = self._outcome_series(processor)

        sufficient, qualifying_weeks = check_sufficiency(spend_panel)
        if not sufficient:
            base.status = STATUS_INSUFFICIENT
            base.message = (
                f"Insufficient history: only {qualifying_weeks} week(s) have ≥{MIN_MATERIAL_CHANNELS} channels "
                f"each spending ≥{MATERIAL_SPEND_WEEKLY_THRESHOLD:g} in the window, but MMM needs "
                f"≥{MIN_SUFFICIENT_WEEKS}. Widen the window or connect more ad-spend sources."
            )
        return base


def _calendar_controls(week_start: datetime.date) -> tuple[int, int]:
    week_of_year = week_start.isocalendar().week
    return week_of_year, 1 if week_of_year in HOLIDAY_WEEKS_OF_YEAR else 0


def check_sufficiency(spend_panel: list[SpendPanelRow]) -> tuple[bool, int]:
    """Whether the panel clears the sufficiency bar, and the count of qualifying weeks.

    A week qualifies when ≥MIN_MATERIAL_CHANNELS channels each spend ≥MATERIAL_SPEND_WEEKLY_THRESHOLD;
    the panel is sufficient when ≥MIN_SUFFICIENT_WEEKS weeks qualify. Module-level (not bound to the
    runner) so it can be unit-tested without standing up a team or ClickHouse.
    """
    material_channels_by_week: dict[datetime.date, set[str]] = defaultdict(set)
    for row in spend_panel:
        if row.spend >= MATERIAL_SPEND_WEEKLY_THRESHOLD:
            material_channels_by_week[row.week].add(row.channel)
    qualifying = sum(1 for channels in material_channels_by_week.values() if len(channels) >= MIN_MATERIAL_CHANNELS)
    return qualifying >= MIN_SUFFICIENT_WEEKS, qualifying
