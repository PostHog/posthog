# Meta Ads Marketing Source Adapter

from dataclasses import dataclass

from posthog.schema import MarketingAnalyticsDrillDownLevel, NativeMarketingSource

from posthog.hogql import ast

from products.data_warehouse.backend.models import DataWarehouseTable

from ..constants import (
    INTEGRATION_DEFAULT_SOURCES,
    INTEGRATION_FIELD_NAMES,
    INTEGRATION_PRIMARY_SOURCE,
    META_CONVERSION_ACTION_TYPES,
    UNSYNCED_HIERARCHY_LABEL,
)
from .base import MarketingSourceAdapter, MetaAdsConfig, ValidationResult

# Use centralized conversion action types from constants
# Priority: omni (deduplicated) > fallback/aggregated (deduplicated by Meta) > specific (channel breakdowns)
META_OMNI_ACTION_TYPES = META_CONVERSION_ACTION_TYPES["omni"]
META_FALLBACK_ACTION_TYPES = META_CONVERSION_ACTION_TYPES["fallback"]
META_SPECIFIC_ACTION_TYPES = META_CONVERSION_ACTION_TYPES["specific"]


@dataclass
class _MetaLevelTables:
    """Bundle of tables + join column names for a given drill-down level."""

    entity_table: DataWarehouseTable
    stats_table: DataWarehouseTable
    entity_id_column: str  # column on entity_table to join with stats
    stats_entity_id_column: str  # column on stats_table to join with entity
    entity_name_column: str
    entity_id_output_column: str  # column on entity_table representing the platform ID


class MetaAdsAdapter(MarketingSourceAdapter[MetaAdsConfig]):
    """
    Adapter for Meta Ads native marketing data.
    Expects config with:
    - campaign_table + stats_table: always required
    - adset_table + adset_stats_table: optional; needed for AD_GROUP drill-down
    - ad_table + ad_stats_table: optional; needed for AD drill-down
    """

    _source_type = NativeMarketingSource.META_ADS

    @classmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        """Meta Ads campaigns typically use 'meta' as the UTM source"""
        primary = INTEGRATION_PRIMARY_SOURCE[cls._source_type]
        sources = INTEGRATION_DEFAULT_SOURCES[cls._source_type]
        return {primary: list(sources)}

    def get_source_type(self) -> str:
        """Return unique identifier for this source type"""
        return "MetaAds"

    def supports_level(self, level: MarketingAnalyticsDrillDownLevel) -> bool:
        if level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
            return self.config.adset_table is not None and self.config.adset_stats_table is not None
        if level == MarketingAnalyticsDrillDownLevel.AD:
            return self.config.ad_table is not None and self.config.ad_stats_table is not None
        return True

    def validate(self) -> ValidationResult:
        """Validate Meta Ads tables and required fields"""
        errors: list[str] = []

        try:
            # Check for expected table name patterns
            if self.config.campaign_table.name and "campaigns" not in self.config.campaign_table.name.lower():
                errors.append(f"Campaign table name '{self.config.campaign_table.name}' doesn't contain 'campaigns'")
            if self.config.stats_table.name and "campaign_stats" not in self.config.stats_table.name.lower():
                errors.append(f"Stats table name '{self.config.stats_table.name}' doesn't contain 'campaign_stats'")

            is_valid = len(errors) == 0
            self._log_validation_errors(errors)

            return ValidationResult(is_valid=is_valid, errors=errors)

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self.logger.exception("Meta Ads validation failed", error=error_msg)
            return ValidationResult(is_valid=False, errors=[error_msg])

    def _level_tables(self) -> _MetaLevelTables:
        """Return the entity + stats tables for the current drill-down level.

        Hierarchy levels (AD_GROUP / AD) require their corresponding tables; the factory
        skips this adapter via `supports_level()` when they're missing, so reaching
        `_level_tables()` without them is a programming error — raise loudly instead of
        silently falling back to campaign tables (which would emit semantically wrong SQL).
        """
        level = self.context.drill_down_level
        fields = INTEGRATION_FIELD_NAMES[self._source_type]
        if level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
            if not (self.config.adset_table and self.config.adset_stats_table):
                raise ValueError(
                    "MetaAdsAdapter reached _level_tables at AD_GROUP without adset_table / "
                    "adset_stats_table — this is a programming error. MarketingSourceFactory "
                    "must skip this adapter via supports_level(AD_GROUP)."
                )
            return _MetaLevelTables(
                entity_table=self.config.adset_table,
                stats_table=self.config.adset_stats_table,
                entity_id_column="id",
                stats_entity_id_column="adset_id",
                entity_name_column="name",
                entity_id_output_column="id",
            )
        if level == MarketingAnalyticsDrillDownLevel.AD:
            if not (self.config.ad_table and self.config.ad_stats_table):
                raise ValueError(
                    "MetaAdsAdapter reached _level_tables at AD without ad_table / "
                    "ad_stats_table — this is a programming error. MarketingSourceFactory "
                    "must skip this adapter via supports_level(AD)."
                )
            return _MetaLevelTables(
                entity_table=self.config.ad_table,
                stats_table=self.config.ad_stats_table,
                entity_id_column="id",
                stats_entity_id_column="ad_id",
                entity_name_column="name",
                entity_id_output_column="id",
            )
        return _MetaLevelTables(
            entity_table=self.config.campaign_table,
            stats_table=self.config.stats_table,
            entity_id_column=fields["id_field"],
            stats_entity_id_column="campaign_id",
            entity_name_column=fields["name_field"],
            entity_id_output_column=fields["id_field"],
        )

    @staticmethod
    def _string_field_with_orphan_fallback(table_name: str, column: str, fallback: str) -> ast.Expr:
        """Wrap toString(table.column) with coalesce against `fallback`. Used when the
        table is reached via LEFT JOIN — orphan rows (e.g. ads.adset_id pointing to a
        deleted adset) would otherwise produce NULLs that all collapse into a single
        unlabelled row in GROUP BY."""
        return ast.Call(
            name="coalesce",
            args=[
                ast.Call(name="toString", args=[ast.Field(chain=[table_name, column])]),
                ast.Constant(value=fallback),
            ],
        )

    def _get_campaign_name_field(self) -> ast.Expr:
        """At AD_GROUP / AD, return the parent campaign name from the campaigns LEFT JOIN
        (with fallback for orphans). At CAMPAIGN, the entity (campaign) name directly
        — never NULL since campaigns IS the FROM table."""
        level = self.context.drill_down_level
        if level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
            return self._string_field_with_orphan_fallback(self.config.campaign_table.name, "name", "Unknown campaign")
        tables = self._level_tables()
        return ast.Call(name="toString", args=[ast.Field(chain=[tables.entity_table.name, tables.entity_name_column])])

    def _get_campaign_id_field(self) -> ast.Expr:
        """At AD_GROUP / AD, return the parent campaign ID from the LEFT JOIN (with
        fallback). At CAMPAIGN, the entity ID directly."""
        level = self.context.drill_down_level
        if level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
            return self._string_field_with_orphan_fallback(self.config.campaign_table.name, "id", "unknown")
        tables = self._level_tables()
        return ast.Call(
            name="toString",
            args=[ast.Field(chain=[tables.entity_table.name, tables.entity_id_output_column])],
        )

    def _get_impressions_field(self) -> ast.Expr:
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "impressions"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_clicks_field(self) -> ast.Expr:
        stats_table_name = self._level_tables().stats_table.name
        field_as_float = ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toFloat", args=[ast.Field(chain=[stats_table_name, "clicks"])]),
                ast.Constant(value=0),
            ],
        )
        sum = ast.Call(name="SUM", args=[field_as_float])
        return ast.Call(name="toFloat", args=[sum])

    def _get_cost_field(self) -> ast.Expr:
        # Meta's campaign / adset / ad stats schemas all expose `account_currency` (see
        # meta_ads/schemas.py), so conversion applies at every drill-down level. The
        # uncoverted fallback only fires for stale tables predating the schema field.
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        spend_field = ast.Field(chain=[stats_table_name, "spend"])
        spend_float = ast.Call(
            name="ifNull",
            args=[ast.Call(name="toFloat", args=[spend_field]), ast.Constant(value=0)],
        )

        converted = self._apply_currency_conversion(stats_table, stats_table_name, "account_currency", spend_float)
        if converted:
            return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="SUM", args=[spend_float])

    def _build_action_type_filter(self, action_types: list[str]) -> ast.Expr:
        """Build filter condition for specified action types"""
        return ast.Or(
            exprs=[
                ast.CompareOperation(
                    left=ast.Call(
                        name="JSONExtractString", args=[ast.Field(chain=["x"]), ast.Constant(value="action_type")]
                    ),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=action_type),
                )
                for action_type in action_types
            ]
        )

    def _build_array_sum_for_action_types(self, json_array_expr: ast.Expr, action_types: list[str]) -> ast.Expr:
        """Build arraySum expression for specified action types"""
        return ast.Call(
            name="arraySum",
            args=[
                ast.Lambda(
                    args=["x"],
                    expr=ast.Call(
                        name="JSONExtractFloat",
                        args=[ast.Field(chain=["x"]), ast.Constant(value="value")],
                    ),
                ),
                ast.Call(
                    name="arrayFilter",
                    args=[
                        ast.Lambda(args=["x"], expr=self._build_action_type_filter(action_types)),
                        ast.Call(name="JSONExtractArrayRaw", args=[json_array_expr]),
                    ],
                ),
            ],
        )

    def _build_actions_conversion_sum(self, column_name: str, apply_currency: bool = False) -> ast.Expr:
        """Build a SUM over conversion action types from a JSON array column.

        Uses a 3-tier priority to avoid double counting when users have both
        pixel and server-side (CAPI) events configured:
        1. Omni types (omni_lead, omni_purchase) — fully deduplicated by Meta
        2. Aggregated types (lead, purchase) — already deduplicated across channels
        3. Specific types (offsite_conversion.fb_pixel_lead) — channel-specific breakdowns

        Previously, tiers 2 and 3 were combined into a single fallback, causing
        double counting (e.g. lead=2 + offsite_conversion.fb_pixel_lead=2 = 4 instead of 2).

        Returns 0 if the column doesn't exist in the table.
        """
        stats_table = self._level_tables().stats_table
        stats_table_name = stats_table.name

        if not self._table_has_column(stats_table, column_name):
            return ast.Constant(value=0)

        field = ast.Field(chain=[stats_table_name, column_name])
        field_non_null = ast.Call(name="coalesce", args=[field, ast.Constant(value="[]")])

        omni_sum = self._build_array_sum_for_action_types(field_non_null, META_OMNI_ACTION_TYPES)
        fallback_sum = self._build_array_sum_for_action_types(field_non_null, META_FALLBACK_ACTION_TYPES)
        specific_sum = self._build_array_sum_for_action_types(field_non_null, META_SPECIFIC_ACTION_TYPES)

        # 3-tier priority: omni > aggregated > specific
        # if omni > 0 then omni
        # else if aggregated > 0 then aggregated
        # else specific
        array_sum = ast.Call(
            name="if",
            args=[
                ast.CompareOperation(
                    left=omni_sum,
                    op=ast.CompareOperationOp.Gt,
                    right=ast.Constant(value=0),
                ),
                omni_sum,
                ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            left=fallback_sum,
                            op=ast.CompareOperationOp.Gt,
                            right=ast.Constant(value=0),
                        ),
                        fallback_sum,
                        specific_sum,
                    ],
                ),
            ],
        )

        if apply_currency:
            converted = self._apply_currency_conversion(stats_table, stats_table_name, "account_currency", array_sum)
            if converted:
                return ast.Call(name="SUM", args=[converted])

        return ast.Call(name="toFloat", args=[ast.Call(name="SUM", args=[array_sum])])

    def _get_reported_conversion_field(self) -> ast.Expr:
        return self._build_actions_conversion_sum("actions")

    def _get_reported_conversion_value_field(self) -> ast.Expr:
        return self._build_actions_conversion_sum("action_values", apply_currency=True)

    # Levels at which `ads` is the FROM table — its columns are never NULL.
    # Used by `_get_ad_*_field` to keep those getters as one-liners through the
    # `_string_field_when_level` helper. Drives the no-coalesce path of the rule
    # documented on each `_get_ad_group_*` override below.
    _AD_AS_FROM_LEVELS = (MarketingAnalyticsDrillDownLevel.AD,)

    def _get_ad_group_name_field(self) -> ast.Expr:
        # Three cases by level:
        #   AD_GROUP: adsets IS the FROM table → toString(adsets.name), never NULL.
        #   AD:       adsets reached via LEFT JOIN → coalesce orphans (ads pointing to
        #             a deleted adset) to "Unknown ad group" so they surface as one
        #             explicit row instead of collapsing into a silent NULL group.
        #   AD without adsets synced: supports_level(AD) only requires ad_table, so
        #             this branch is reachable. Emit "No sync" placeholder so the
        #             column tells the user *why* it's blank.
        level = self.context.drill_down_level
        if not self.config.adset_table:
            if level == MarketingAnalyticsDrillDownLevel.AD:
                return ast.Constant(value=UNSYNCED_HIERARCHY_LABEL)
            return ast.Constant(value=None)
        if level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
            return ast.Call(name="toString", args=[ast.Field(chain=[self.config.adset_table.name, "name"])])
        if level == MarketingAnalyticsDrillDownLevel.AD:
            return self._string_field_with_orphan_fallback(self.config.adset_table.name, "name", "Unknown ad group")
        return ast.Constant(value=None)

    def _get_ad_group_id_field(self) -> ast.Expr:
        # Same shape as _get_ad_group_name_field — see comment there for the level rules.
        level = self.context.drill_down_level
        if not self.config.adset_table:
            if level == MarketingAnalyticsDrillDownLevel.AD:
                return ast.Constant(value=UNSYNCED_HIERARCHY_LABEL)
            return ast.Constant(value=None)
        if level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
            return ast.Call(name="toString", args=[ast.Field(chain=[self.config.adset_table.name, "id"])])
        if level == MarketingAnalyticsDrillDownLevel.AD:
            return self._string_field_with_orphan_fallback(self.config.adset_table.name, "id", "unknown")
        return ast.Constant(value=None)

    def _get_ad_name_field(self) -> ast.Expr:
        return self._string_field_when_level(self._AD_AS_FROM_LEVELS, self.config.ad_table, "name")

    def _get_ad_id_field(self) -> ast.Expr:
        return self._string_field_when_level(self._AD_AS_FROM_LEVELS, self.config.ad_table, "id")

    def _get_from(self) -> ast.JoinExpr:
        """Build FROM and JOIN clauses. At AD_GROUP / AD, additional joins to parent
        entity tables are added so we can show the campaign / ad-group hierarchy."""
        tables = self._level_tables()
        entity_table_name = tables.entity_table.name
        stats_table_name = tables.stats_table.name
        level = self.context.drill_down_level

        # entity LEFT JOIN stats ON entity.id = stats.<entity_id>
        stats_join = ast.JoinExpr(
            table=ast.Field(chain=[stats_table_name]),
            join_type="LEFT JOIN",
            constraint=ast.JoinConstraint(
                expr=ast.CompareOperation(
                    left=ast.Field(chain=[entity_table_name, tables.entity_id_column]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Field(chain=[stats_table_name, tables.stats_entity_id_column]),
                ),
                constraint_type="ON",
            ),
        )

        # Build hierarchy joins for parent context columns at AD_GROUP / AD level.
        parent_joins: list[ast.JoinExpr] = []
        if level == MarketingAnalyticsDrillDownLevel.AD and self.config.adset_table:
            # ads.adset_id = adsets.id
            parent_joins.append(
                ast.JoinExpr(
                    table=ast.Field(chain=[self.config.adset_table.name]),
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=[entity_table_name, "adset_id"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Field(chain=[self.config.adset_table.name, "id"]),
                        ),
                        constraint_type="ON",
                    ),
                )
            )
        if level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
            # entity.campaign_id = campaigns.id
            parent_joins.append(
                ast.JoinExpr(
                    table=ast.Field(chain=[self.config.campaign_table.name]),
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=[entity_table_name, "campaign_id"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Field(chain=[self.config.campaign_table.name, "id"]),
                        ),
                        constraint_type="ON",
                    ),
                )
            )

        # Chain joins: entity → stats → (adsets) → campaigns
        join_chain = stats_join
        for join in parent_joins:
            current = join_chain
            while current.next_join is not None:
                current = current.next_join
            current.next_join = join

        return ast.JoinExpr(
            table=ast.Field(chain=[entity_table_name]),
            next_join=join_chain,
        )

    def _get_where_conditions(self) -> list[ast.Expr]:
        """Build WHERE conditions against the current level's stats table."""
        conditions: list[ast.Expr] = []

        if self.context.date_range:
            stats_table_name = self._level_tables().stats_table.name

            date_field = ast.Call(name="toDateTime", args=[ast.Field(chain=[stats_table_name, "date_stop"])])

            from_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_from_str)])
            gte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.GtEq, right=from_date)

            to_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_to_str)])
            lte_condition = ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.LtEq, right=to_date)

            conditions.extend([gte_condition, lte_condition])

        return conditions

    def _get_group_by(self) -> list[ast.Expr]:
        """Group by every non-aggregate column emitted at this level. ClickHouse rejects
        the query if a SELECT column isn't either grouped or aggregated."""
        level = self.context.drill_down_level
        group_by: list[ast.Expr] = [self._get_campaign_name_field(), self._get_campaign_id_field()]
        if level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
            group_by.extend([self._get_ad_group_name_field(), self._get_ad_group_id_field()])
        if level == MarketingAnalyticsDrillDownLevel.AD:
            group_by.extend([self._get_ad_name_field(), self._get_ad_id_field()])
        return group_by
