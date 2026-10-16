import uuid
from datetime import timedelta
from typing import Optional

import structlog

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import ChannelTypeExprs, create_channel_type_expr
from posthog.hogql.property import property_to_expr

from posthog.dataclasses import frozen

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.web_analytics.backend.hogql_queries.pre_aggregated.property_transformer import (
    ChannelTypeReplacer,
    PreAggregatedPropertyTransformer,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
    WEB_STATS_DIMENSIONAL_READ_TABLE,
    web_bounces_dimensional_ready_jobs,
    web_stats_dimensional_ready_jobs,
)

# V1 tables have been removed - always use v2 tables
get_stats_table = lambda use_v2: "web_pre_aggregated_stats"
get_bounces_table = lambda use_v2: "web_pre_aggregated_bounces"


logger = structlog.get_logger(__name__)


@frozen
class PeriodFilters:
    previous_period: ast.Expr
    current_period: ast.Expr


class WebAnalyticsPreAggregatedQueryBuilder:
    def __init__(self, runner, supported_props_filters) -> None:
        self.runner = runner
        self.supported_props_filters = supported_props_filters
        # Resolved once per build: "stats"/"bounces" -> READY dimensional jobs.
        self._dimensional_ready_jobs: dict[str, LazyComputationResult] = {}
        self._has_property_access_rules: bool | None = None

    def _ready_jobs_for(self, which: str) -> LazyComputationResult:
        if which not in self._dimensional_ready_jobs:
            # Cover the compare period too, since both feed the same SELECT.
            start = self.runner.query_date_range.date_from()
            if self.runner.query_compare_to_date_range:
                start = min(start, self.runner.query_compare_to_date_range.date_from())
            end = self.runner.query_date_range.date_to()
            resolver = web_stats_dimensional_ready_jobs if which == "stats" else web_bounces_dimensional_ready_jobs
            try:
                self._dimensional_ready_jobs[which] = resolver(self.runner.team, start, end)
            except Exception:
                # The dimensional read is optional, so a failed lookup must not fail the tile.
                # A not-ready result makes the runner use the legacy or live path instead.
                logger.exception("web_dimensional_ready_jobs_lookup_failed", team_id=self.runner.team.pk)
                self._dimensional_ready_jobs[which] = LazyComputationResult(ready=False, job_ids=[])
        return self._dimensional_ready_jobs[which]

    def _job_ids_for(self, which: str) -> list[uuid.UUID]:
        return self._ready_jobs_for(which).job_ids

    def use_dimensional_tables(self) -> bool:
        """Serve opted-in queries from the dimensional precompute tables when both
        stats and bounces have READY data for the window; otherwise fall back to v2.
        """
        web_query_modifiers = self.runner.query.webQueryModifiers
        if not (web_query_modifiers and web_query_modifiers.useDimensionalTables):
            return False
        # The tables are built without a user, so a team with property-level access rules
        # skips them, like the lazy precompute does. The HogQL schema also masks the columns
        # that copy a restricted property, which covers a read that reaches the tables directly.
        if self._team_has_property_access_rules():
            return False
        return bool(self._job_ids_for("stats")) and bool(self._job_ids_for("bounces"))

    def _team_has_property_access_rules(self) -> bool:
        if self._has_property_access_rules is None:
            self._has_property_access_rules = team_has_property_access_rules(team_id=self.runner.team.pk)
        return self._has_property_access_rules

    @property
    def stats_table(self) -> str:
        if self.use_dimensional_tables():
            return WEB_STATS_DIMENSIONAL_READ_TABLE
        return get_stats_table(self.runner.use_v2_tables)

    @property
    def bounces_table(self) -> str:
        if self.use_dimensional_tables():
            return WEB_BOUNCES_DIMENSIONAL_READ_TABLE
        return get_bounces_table(self.runner.use_v2_tables)

    def _dimensional_job_id_filter(self, table_name: str) -> Optional[ast.Expr]:
        """`job_id IN (ready ids)` for a dimensional table read. The tables hold
        multiple generations per recent window (one per precompute job), so without
        this filter `sumMerge`/`uniqMerge` would double-count. v2 tables (one
        version per partition) need no such filter.
        """
        if table_name == WEB_STATS_DIMENSIONAL_READ_TABLE:
            job_ids = self._job_ids_for("stats")
        elif table_name == WEB_BOUNCES_DIMENSIONAL_READ_TABLE:
            job_ids = self._job_ids_for("bounces")
        else:
            return None
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=[table_name, "job_id"]),
            right=ast.Constant(value=[str(j) for j in job_ids]),
        )

    def can_use_preaggregated_tables(self) -> bool:
        query = self.runner.query

        if self.runner.rewritten_first_pageview_filters:
            return False

        for prop in query.properties:
            if hasattr(prop, "type") and prop.type == "cohort":
                return False
            if hasattr(prop, "key") and prop.key not in self.supported_props_filters:
                return False

        if self._is_recent_relative_date_range():
            return False

        return True

    def _is_recent_relative_date_range(self) -> bool:
        """Returns True if the query covers a short relative date range (6 hours or less ending at 'now').

        Pre-aggregated tables are updated periodically and may not contain the most recent data,
        so we fall back to raw event tables for recent time windows.
        """
        date_range = getattr(self.runner.query, "dateRange", None)

        # Only applies when date_to is not explicitly set (meaning the query ends at "now")
        if date_range and date_range.date_to:
            return False

        date_from = self.runner.query_date_range.date_from()
        date_to = self.runner.query_date_range.date_to()
        return (date_to - date_from) <= timedelta(hours=6)

    def _get_channel_type_expr(self) -> ast.Expr:
        def _wrap_with_null_if_empty(expr: ast.Expr) -> ast.Expr:
            return ast.Call(
                name="nullIf",
                args=[ast.Call(name="nullIf", args=[expr, ast.Constant(value="")]), ast.Constant(value="null")],
            )

        def _wrap_with_lower(expr: ast.Expr) -> ast.Expr:
            return ast.Call(name="lower", args=[expr])

        channel_type_exprs = ChannelTypeExprs(
            campaign=_wrap_with_lower(_wrap_with_null_if_empty(ast.Field(chain=["utm_campaign"]))),
            medium=_wrap_with_lower(_wrap_with_null_if_empty(ast.Field(chain=["utm_medium"]))),
            source=_wrap_with_lower(_wrap_with_null_if_empty(ast.Field(chain=["utm_source"]))),
            referring_domain=_wrap_with_null_if_empty(ast.Field(chain=["referring_domain"])),
            url=ast.Constant(value=None),  # URL not available in pre-aggregated tables
            hostname=ast.Field(chain=["host"]),
            pathname=ast.Field(chain=["entry_pathname"]),
            has_gclid=ast.Field(chain=["has_gclid"]),
            has_fbclid=ast.Field(chain=["has_fbclid"]),
            # To keep this compatible with the non-pre-aggregated version, we need to return '1' when the boolean is true, null otherwise
            gad_source=ast.Call(
                name="if",
                args=[
                    ast.Field(chain=["has_gad_source_paid_search"]),
                    ast.Constant(value="1"),
                    ast.Constant(value=None),
                ],
            ),
        )

        return create_channel_type_expr(
            custom_rules=None,  # Custom rules not supported for pre-aggregated tables yet
            source_exprs=channel_type_exprs,
            timings=self.runner.timings,
        )

    def _get_filters(self, table_name: str, exclude_pathname: bool = False):
        filter_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=[table_name, "period_bucket"]),
                right=ast.Constant(
                    value=(
                        self.runner.query_compare_to_date_range.date_from()
                        if self.runner.query_compare_to_date_range
                        else self.runner.query_date_range.date_from()
                    )
                ),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=[table_name, "period_bucket"]),
                right=ast.Constant(value=self.runner.query_date_range.date_to()),
            ),
        ]

        job_id_filter = self._dimensional_job_id_filter(table_name)
        if job_id_filter is not None:
            filter_exprs.append(job_id_filter)

        if self.runner.query.properties:
            virtual_properties = []
            regular_properties = []

            for prop in self.runner.query.properties:
                if hasattr(prop, "key") and prop.key in self.supported_props_filters:
                    if exclude_pathname and prop.key == "$pathname":
                        continue
                    if self.supported_props_filters[prop.key] is None:
                        virtual_properties.append(prop)
                    else:
                        regular_properties.append(prop)

            if regular_properties:
                property_expr = property_to_expr(regular_properties, self.runner.team)
                transformer = PreAggregatedPropertyTransformer(table_name, self.supported_props_filters)
                transformed_expr = transformer.visit(property_expr)
                filter_exprs.append(transformed_expr)

            if virtual_properties:
                for prop in virtual_properties:
                    if prop.key == "$channel_type":
                        replacer = ChannelTypeReplacer(self._get_channel_type_expr())
                        filter_exprs.append(replacer.visit(property_to_expr([prop], self.runner.team)))

        return ast.And(exprs=filter_exprs)

    def get_date_ranges(self, table_name: Optional[str] = None) -> PeriodFilters:
        current_date_from = self.runner.query_date_range.date_from()
        current_date_to = self.runner.query_date_range.date_to()

        if self.runner.query_compare_to_date_range:
            previous_date_from = self.runner.query_compare_to_date_range.date_from()
            previous_date_to = self.runner.query_compare_to_date_range.date_to()
        else:
            # If we don't have a previous period, we can just use the same data as the values won't be used
            # and our query stays simpler.
            previous_date_from = current_date_from
            previous_date_to = current_date_to

        # Create the field reference for period_bucket
        period_bucket_field = ast.Field(chain=[table_name, "period_bucket"] if table_name else ["period_bucket"])

        current_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=period_bucket_field,
                    right=ast.Constant(value=current_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=period_bucket_field,
                    right=ast.Constant(value=current_date_to),
                ),
            ]
        )

        previous_period_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=period_bucket_field,
                    right=ast.Constant(value=previous_date_from),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=period_bucket_field,
                    right=ast.Constant(value=previous_date_to),
                ),
            ]
        )

        return PeriodFilters(previous_period=previous_period_filter, current_period=current_period_filter)
