from datetime import datetime, timedelta
from math import isfinite

from django.utils import timezone

from posthog.schema import DateRange, MarketingAnalyticsAttributionQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.marketing_analytics.backend.hogql_queries.attribution_base import (
    MAX_CONVERSIONS_PER_PERSON,
    MAX_TOUCHPOINTS_PER_PERSON,
    PERSON_ARRAYS_CTE,
    ConversionGoal,
)
from products.marketing_analytics.backend.hogql_queries.attribution_table_query_runner import (
    MarketingAnalyticsAttributionQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.constants import MARKETING_SPILL_AFTER_BYTES

MAX_PREVIEW_DAYS = 31


@frozen
class ConversionGoalPreviewOptions:
    goal: ConversionGoal
    date_from: datetime
    date_to: datetime
    lookback_window_days: int | None = None
    allow_multiple_conversions_per_visitor: bool | None = None
    filter_test_accounts: bool | None = None
    exclude_direct_traffic: bool = False
    exclude_unattributed: bool = False

    def __post_init__(self) -> None:
        if timezone.is_naive(self.date_from) or timezone.is_naive(self.date_to):
            raise ValueError("Provide dates with a time zone for the preview.")
        if not timedelta(0) < self.date_to - self.date_from <= timedelta(days=MAX_PREVIEW_DAYS):
            raise ValueError(f"Choose a preview period greater than zero and no longer than {MAX_PREVIEW_DAYS} days.")
        if self.goal.math not in (None, "total", "dau", "sum"):
            raise ValueError("Preview supports total, unique users, or sum math. Update the goal's math.")
        if self.goal.math_group_type_index is not None:
            raise ValueError("Preview requires person identity. Group attribution is not supported yet.")
        if self.goal.math_multiplier not in (None, 1):
            raise ValueError("Convert amounts to currency units in the source before previewing this goal.")
        if self.goal.math == "sum" and not self.goal.math_property:
            raise ValueError("Select an amount property or column for a goal that uses sum math.")
        if self.goal.counts_as_revenue and self.goal.math != "sum":
            raise ValueError("Select sum math and an amount property or column to preview revenue.")


@frozen
class ConversionGoalPreview:
    goal: ConversionGoal
    observed_at: datetime
    date_from: datetime
    date_to: datetime
    timezone: str
    attribution_window_days: int
    allows_multiple_conversions_per_visitor: bool
    filter_test_accounts: bool
    exclude_direct_traffic: bool
    exclude_unattributed: bool
    total_conversions: int
    evaluated_conversions: int
    attributed_conversions: int
    unattributed_conversions: int
    total_value: float | None
    evaluated_value: float | None
    attributed_value: float | None
    unattributed_value: float | None
    currency: str | None
    conversion_limit_reached: bool
    touchpoint_limit_reached: bool
    is_approximate: bool
    warnings: list[str]
    checks_not_performed: list[str]


class ConversionGoalPreviewRunner(MarketingAnalyticsAttributionQueryRunner):
    def __init__(self, *, options: ConversionGoalPreviewOptions, team: Team, user: User) -> None:
        self.options = options
        super().__init__(
            query=MarketingAnalyticsAttributionQuery(
                conversionGoalId=options.goal.conversion_goal_id,
                dateRange=DateRange(
                    date_from=options.date_from.isoformat(), date_to=options.date_to.isoformat(), explicitDate=True
                ),
                properties=[],
                lookbackWindowDays=options.lookback_window_days,
                allowMultipleConversionsPerVisitor=options.allow_multiple_conversions_per_visitor,
                filterTestAccounts=options.filter_test_accounts,
                excludeDirectTraffic=options.exclude_direct_traffic,
                excludeUnattributed=options.exclude_unattributed,
            ),
            team=team,
            user=user,
        )

    def _get_team_conversion_goals(self) -> list[ConversionGoal]:
        return [self.options.goal]

    def preview(self) -> ConversionGoalPreview:
        date_range = self.query_date_range
        # Read the same per-conversion journeys as the report, before dimension pagination or fan-out.
        per_conversion = self._build_per_conversion_select()
        assert per_conversion.select is not None
        per_conversion.select.append(
            ast.Alias(
                alias="touchpoint_limit_reached",
                expr=ast.CompareOperation(
                    left=ast.Call(name="length", args=[ast.Field(chain=["touchpoints"])]),
                    op=ast.CompareOperationOp.GtEq,
                    right=ast.Constant(value=MAX_TOUCHPOINTS_PER_PERSON),
                ),
            )
        )
        query = parse_select(
            """
            SELECT {total_conversions} AS total_conversions,
                count() AS evaluated_conversions,
                countIf(notEmpty(tps)) AS attributed_conversions,
                coalesce(sum(conversion_value), 0) AS evaluated_value,
                coalesce(sumIf(conversion_value, notEmpty(tps)), 0) AS attributed_value,
                countIf(conversion_value IS NULL OR NOT isFinite(conversion_value)) AS invalid_values,
                max(touchpoint_limit_reached) AS touchpoint_limit_reached
            FROM preview_conversions
            """,
            placeholders={"total_conversions": self._total_conversions_expr("i")},
        )
        assert isinstance(query, ast.SelectQuery)
        query.ctes = {
            PERSON_ARRAYS_CTE: ast.CTE(
                name=PERSON_ARRAYS_CTE,
                expr=self._build_person_arrays_select(date_range),
                cte_type="subquery",
            ),
            "preview_conversions": ast.CTE(name="preview_conversions", expr=per_conversion, cte_type="subquery"),
        }
        with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.QUERY, team_id=self.team.pk):
            response = execute_hogql_query(
                query_type="marketing_conversion_goal_preview",
                query=query,
                team=self.team,
                user=self.user,
                modifiers=self.modifiers,
                timings=self.timings,
                context=self._shared_hogql_context,
                settings=HogQLGlobalSettings(
                    max_execution_time=30,
                    timeout_overflow_mode="throw",
                    max_bytes_to_read=1_000_000_000,
                    read_overflow_mode="throw",
                    max_bytes_before_external_group_by=MARKETING_SPILL_AFTER_BYTES,
                ),
            )
        if not response.results or not response.columns:
            raise ValueError("The preview did not return a result. Retry with a shorter date range.")
        row = dict(zip(response.columns, response.results[0]))
        total = int(row["total_conversions"])
        evaluated = int(row["evaluated_conversions"])
        attributed = int(row["attributed_conversions"])
        conversions_capped = evaluated < total
        touches_capped = bool(row["touchpoint_limit_reached"])
        evaluated_value = float(row["evaluated_value"])
        attributed_value = float(row["attributed_value"])
        invalid_values = bool(row["invalid_values"]) or not all(map(isfinite, (evaluated_value, attributed_value)))
        has_value = self.goal.math == "sum" and not invalid_values
        complete_value = has_value and not conversions_capped
        warnings: list[str] = []
        if conversions_capped:
            warnings.append(
                f"Only the most recent {MAX_CONVERSIONS_PER_PERSON} conversions per person were evaluated. "
                "Total value is unavailable; attributed conversions may be understated."
            )
        if touches_capped:
            warnings.append(
                f"At least one person reached the {MAX_TOUCHPOINTS_PER_PERSON}-touchpoint limit. "
                "Attribution may omit older sessions."
            )
        if invalid_values:
            warnings.append("Some conversion values are not finite numbers. Fix the amount mapping and preview again.")
        if not self.allows_multiple_conversions_per_visitor:
            warnings.append(
                "Unique mode uses the first conversion in this period, not the person's first conversion ever."
            )
        if self.goal.math == "sum":
            warnings.append(
                "Amounts must already be in currency units. Missing currencies use the project base currency."
            )
        if self.goal.kind != "DataWarehouseNode" and self.goal.math == "sum":
            warnings.append("Missing or nonnumeric event amounts follow the report's zero-value fallback.")
            warnings.append(
                "Event and action sums do not deduplicate payments by transaction ID. "
                "Verify that each matching event represents a separate transaction."
            )
        if self.goal.counts_as_customer:
            warnings.append(
                "This preview does not establish first-ever customers or count unique accounts. "
                "Confirm that the source matches your customer definition."
            )
        return ConversionGoalPreview(
            goal=self.goal,
            observed_at=timezone.now(),
            date_from=date_range.date_from(),
            date_to=date_range.date_to(),
            timezone=self.team.timezone,
            attribution_window_days=self.lookback_window_days,
            allows_multiple_conversions_per_visitor=self.allows_multiple_conversions_per_visitor,
            filter_test_accounts=self.filter_test_accounts,
            exclude_direct_traffic=self.options.exclude_direct_traffic,
            exclude_unattributed=self.options.exclude_unattributed,
            total_conversions=total,
            evaluated_conversions=evaluated,
            attributed_conversions=attributed,
            unattributed_conversions=max(total - attributed, 0),
            total_value=evaluated_value if complete_value else None,
            evaluated_value=evaluated_value if has_value else None,
            attributed_value=attributed_value if has_value else None,
            unattributed_value=evaluated_value - attributed_value if complete_value else None,
            currency=self.team.base_currency if self.goal.counts_as_revenue else None,
            conversion_limit_reached=conversions_capped,
            touchpoint_limit_reached=touches_capped,
            is_approximate=conversions_capped or touches_capped or invalid_values,
            warnings=warnings,
            checks_not_performed=[
                "source_row_quality_profile",
                "missing_timestamps_outside_date_range",
                "native_currency_breakdown",
                "currency_code_and_rate_validation",
                "identity_match_coverage",
                "source_sync_freshness",
                "business_definition_validation",
                "transaction_uniqueness",
                "first_ever_customer_validation",
            ],
        )
