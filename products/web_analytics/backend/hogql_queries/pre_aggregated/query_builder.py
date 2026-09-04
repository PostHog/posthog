from datetime import timedelta
from typing import Optional

from posthog.schema import PropertyOperator

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import ChannelTypeExprs, create_channel_type_expr
from posthog.hogql.property import property_to_expr

from posthog.dataclasses import frozen

from products.web_analytics.backend.hogql_queries.pre_aggregated.property_transformer import (
    ChannelTypeReplacer,
    PreAggregatedPropertyTransformer,
)

# V1 tables have been removed - always use v2 tables
get_stats_table = lambda use_v2: "web_pre_aggregated_stats"
get_bounces_table = lambda use_v2: "web_pre_aggregated_bounces"


def _prop_attr(prop, attr: str):
    # Drill-down filters are pydantic property objects; saved test-account filters are raw dicts.
    if isinstance(prop, dict):
        return prop.get(attr)
    return getattr(prop, attr, None)


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

    def _filter_properties(self) -> list:
        # Drill-down filters plus the saved test-account filters (empty unless filterTestAccounts is on).
        return [*self.runner.query.properties, *self.runner._test_account_filters]

    def can_use_preaggregated_tables(self) -> bool:
        if self.runner.rewritten_first_pageview_filters:
            return False

        # A property the pre-aggregated tables cannot express forces the raw-events path. Test-account
        # filters go through the same gate, so a saved filter that pre-aggregation cannot reproduce
        # falls back instead of being silently dropped from the query.
        for prop in self._filter_properties():
            if _prop_attr(prop, "type") == "cohort":
                return False
            key = _prop_attr(prop, "key")
            if key is not None and key not in self.supported_props_filters:
                return False
            # Pre-aggregated columns store an unset value as an empty string, not NULL, so
            # is_set / is_not_set cannot be reproduced on them. Fall back to raw events.
            if _prop_attr(prop, "operator") in (PropertyOperator.IS_SET, PropertyOperator.IS_NOT_SET):
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

        filter_properties = self._filter_properties()
        if filter_properties:
            virtual_properties = []
            regular_properties = []

            for prop in filter_properties:
                key = _prop_attr(prop, "key")
                if key is not None and key in self.supported_props_filters:
                    if exclude_pathname and key == "$pathname":
                        continue
                    if self.supported_props_filters[key] is None:
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
