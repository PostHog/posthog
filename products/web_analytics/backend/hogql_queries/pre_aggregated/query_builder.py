from datetime import timedelta
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import create_preaggregated_channel_type_expr
from posthog.hogql.property import property_to_expr

from posthog.dataclasses import frozen

from products.web_analytics.backend.hogql_queries.pre_aggregated.property_transformer import (
    ChannelTypeReplacer,
    PreAggregatedPropertyTransformer,
)

# V1 tables have been removed - always use v2 tables
get_stats_table = lambda use_v2: "web_pre_aggregated_stats"
get_bounces_table = lambda use_v2: "web_pre_aggregated_bounces"


@frozen
class PeriodFilters:
    previous_period: ast.Expr
    current_period: ast.Expr


class WebAnalyticsPreAggregatedQueryBuilder:
    def __init__(self, runner, supported_props_filters) -> None:
        self.runner = runner
        self.supported_props_filters = supported_props_filters

    @property
    def stats_table(self) -> str:
        return get_stats_table(self.runner.use_v2_tables)

    @property
    def bounces_table(self) -> str:
        return get_bounces_table(self.runner.use_v2_tables)

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
        return create_preaggregated_channel_type_expr(timings=self.runner.timings)

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
