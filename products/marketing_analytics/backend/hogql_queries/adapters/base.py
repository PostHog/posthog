# Base Marketing Source Adapter

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Optional, TypeVar, cast

import structlog

from posthog.schema import (
    MarketingAnalyticsColumnsSchemaNames,
    MarketingAnalyticsConstants,
    MarketingAnalyticsDrillDownLevel,
    SourceMap,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import DEFAULT_CURRENCY, Team

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

from products.marketing_analytics.backend.hogql_queries.constants import (
    DRILL_DOWN_LEVEL_CONFIG,
    MATCH_KEY_FIELD,
    UNSYNCED_HIERARCHY_LABEL,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

logger = structlog.get_logger(__name__)

ConfigType = TypeVar("ConfigType", bound="BaseMarketingConfig")


@dataclass
class BaseMarketingConfig(ABC):
    """Base configuration for marketing source adapters"""

    source_type: str
    source_id: str


@dataclass
class ExternalConfig(BaseMarketingConfig):
    """Configuration for external marketing sources"""

    table: DataWarehouseTable
    source_map: SourceMap
    schema_name: str


@dataclass
class HierarchicalNativeAdsConfig(BaseMarketingConfig):
    """Shared config for native ads sources organized as campaign → ad-group → ad.

    Ad-group and ad tables are optional — left None when the user hasn't synced them.
    """

    campaign_table: DataWarehouseTable
    stats_table: DataWarehouseTable
    adset_table: Optional[DataWarehouseTable] = None
    adset_stats_table: Optional[DataWarehouseTable] = None
    ad_table: Optional[DataWarehouseTable] = None
    ad_stats_table: Optional[DataWarehouseTable] = None


# Per-source configs are kept as named subclasses so each adapter can declare
# `MarketingSourceAdapter[XxxAdsConfig]` for type-checking, even though the field
# layout is identical across them.
@dataclass
class GoogleAdsConfig(HierarchicalNativeAdsConfig):
    pass


@dataclass
class LinkedinAdsConfig(HierarchicalNativeAdsConfig):
    pass


@dataclass
class RedditAdsConfig(HierarchicalNativeAdsConfig):
    pass


@dataclass
class MetaAdsConfig(HierarchicalNativeAdsConfig):
    pass


@dataclass
class TikTokAdsConfig(HierarchicalNativeAdsConfig):
    pass


@dataclass
class BingAdsConfig(HierarchicalNativeAdsConfig):
    pass


@dataclass
class SnapchatAdsConfig(HierarchicalNativeAdsConfig):
    pass


@dataclass
class PinterestAdsConfig(HierarchicalNativeAdsConfig):
    pass


@dataclass
class ValidationResult:
    """Result of source validation"""

    is_valid: bool
    errors: list[str]


@dataclass
class HierarchicalLevelTables:
    """Bundle of tables + join column names for a given drill-down level.

    Returned by `MarketingSourceAdapter._level_tables()` so the shared FROM/GROUP BY
    builders don't need to know which level we're at — they just consume the bundle.
    """

    entity_table: DataWarehouseTable
    stats_table: DataWarehouseTable
    entity_id_column: str  # PK on entity_table — joined with stats_entity_id_column
    stats_entity_id_column: str  # FK on stats_table → entity_table.entity_id_column
    entity_name_column: str
    entity_id_output_column: str  # column on entity_table representing the platform ID


@dataclass
class QueryContext:
    """Context needed for query building"""

    date_range: Optional[QueryDateRange]
    team: Team
    global_filters: list[Any] = field(default_factory=list)
    base_currency: str = DEFAULT_CURRENCY
    # AD_GROUP / AD pull from ad-group / ad-level tables; CAMPAIGN and below stay at campaign stats.
    drill_down_level: MarketingAnalyticsDrillDownLevel = MarketingAnalyticsDrillDownLevel.CAMPAIGN
    # Prebuilt HogQL database shared across factories in one request — the factory only needs it for
    # warehouse table names, and Database.create_for is ~550ms. None → factory builds its own.
    database: Optional["Database"] = None


class MarketingSourceAdapter(ABC, Generic[ConfigType]):
    """
    Base adapter that all marketing sources must implement.
    Each adapter is responsible for:
    1. Validating that it can provide marketing data
    2. Building a SQL query fragment that returns standardized marketing data
    """

    # Default fields for the marketing analytics table
    campaign_name_field: str = MarketingAnalyticsColumnsSchemaNames.CAMPAIGN
    campaign_id_field: str = MarketingAnalyticsColumnsSchemaNames.ID
    source_name_field: str = MarketingAnalyticsColumnsSchemaNames.SOURCE
    impressions_field: str = MarketingAnalyticsColumnsSchemaNames.IMPRESSIONS
    clicks_field: str = MarketingAnalyticsColumnsSchemaNames.CLICKS
    cost_field: str = MarketingAnalyticsColumnsSchemaNames.COST
    reported_conversion_field: str = MarketingAnalyticsColumnsSchemaNames.REPORTED_CONVERSION
    reported_conversion_value_field: str = MarketingAnalyticsColumnsSchemaNames.REPORTED_CONVERSION_VALUE
    # Ad-group / ad granularity. Emitted by every adapter (NULL when the source doesn't
    # support that granularity or the query isn't at that drill-down level) so the
    # campaign_costs CTE has a stable schema.
    ad_group_name_field: str = MarketingAnalyticsColumnsSchemaNames.AD_GROUP_NAME
    ad_group_id_field: str = MarketingAnalyticsColumnsSchemaNames.AD_GROUP_ID
    ad_name_field: str = MarketingAnalyticsColumnsSchemaNames.AD_NAME
    ad_id_field: str = MarketingAnalyticsColumnsSchemaNames.AD_ID
    match_key_field: str = MATCH_KEY_FIELD

    CONSTANT_VALUE_PREFIX = MarketingAnalyticsConstants.CONST_

    @staticmethod
    def _is_simple_column_name(value: str) -> bool:
        if len(value) == 1:
            return value.isalnum() or value == "_"
        return (
            bool(value)
            and value.replace("_", "").replace(".", "").isalnum()
            and not value.startswith(".")
            and not value.endswith(".")
        )

    def _resolve_field_expr(self, field_value: str) -> ast.Expr:
        if self._is_simple_column_name(field_value):
            parts: list[str | int] = list(field_value.split("."))
            return ast.Field(chain=parts)
        return parse_expr(field_value)

    # Matches bare ISO 4217 currency codes like "USD", "EUR", "GBP"
    _ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

    def _resolve_field_or_constant(self, field_value: str) -> ast.Expr:
        """Resolve a field value that may be a column reference or a constant.
        Values prefixed with 'const:' are treated as string constants.
        For backwards compatibility, bare ISO currency codes (e.g. "USD")
        saved before the frontend enforced the 'const:' prefix are also
        treated as constants.
        """
        if field_value.startswith(self.CONSTANT_VALUE_PREFIX):
            return ast.Constant(value=field_value[len(self.CONSTANT_VALUE_PREFIX) :])
        if self._ISO_CURRENCY_RE.match(field_value):
            return ast.Constant(value=field_value)
        return self._resolve_field_expr(field_value)

    @classmethod
    @abstractmethod
    def get_source_identifier_mapping(cls) -> dict[str, list[str]]:
        """
        Return a mapping of primary source identifier to all possible UTM source values.
        Used to normalize conversion goal sources to match campaign costs.

        Example:
            return {"google": ["google", "youtube", "search", "display", ...]}

        For single-source adapters, return a mapping with just the primary source:
            return {"meta": ["meta"]}
        """
        pass

    def __init__(self, config: ConfigType, context: QueryContext):
        self.team = context.team
        self.config: ConfigType = config
        self.logger = logger.bind(source_type=self.get_source_type(), team_id=self.team.pk if self.team else None)
        self.context = context
        # Cache for `_table_has_column` lookups, keyed by (id(table), column_name) —
        # the same stats table is introspected several times per query.
        self._table_column_cache: dict[tuple[int, str], bool] = {}

    @abstractmethod
    def get_source_type(self) -> str:
        """Return unique identifier for this source type"""
        pass

    def get_source_id(self) -> str:
        """Return the source ID for filtering purposes"""
        return self.config.source_id

    @abstractmethod
    def validate(self) -> ValidationResult:
        """
        Validate that this source can provide marketing data.
        Should check:
        - Required tables/fields exist
        - Proper permissions/credentials
        - Data availability
        """
        pass

    def _get_campaign_name_field(self) -> ast.Expr:
        """Default: at AD_GROUP / AD, return the parent campaign name from the LEFT JOIN
        (with orphan fallback). At CAMPAIGN, the entity name from the FROM table directly.
        In unified mode (Bing reports), read the embedded `_unified_campaign_name_column`
        from the entity table since there's no separate campaigns join.
        Hierarchical adapters get this for free; non-hierarchical ones must override."""
        if not self._has_hierarchical_config():
            raise NotImplementedError(
                f"{self.__class__.__name__} must override _get_campaign_name_field() — "
                "base default only works for hierarchical native ads configs."
            )
        config = cast(HierarchicalNativeAdsConfig, self.config)
        level = self.context.drill_down_level
        if level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
            if self._uses_unified_entity_stats:
                tables = self._level_tables()
                return ast.Call(
                    name="toString",
                    args=[ast.Field(chain=[tables.entity_table.name, self._unified_campaign_name_column])],
                )
            return self._string_field_with_orphan_fallback(
                config.campaign_table.name, self._campaign_name_column, "Unknown campaign"
            )
        tables = self._level_tables()
        return ast.Call(name="toString", args=[ast.Field(chain=[tables.entity_table.name, tables.entity_name_column])])

    def _get_campaign_id_field(self) -> ast.Expr:
        """Default mirror of `_get_campaign_name_field` for the ID column."""
        if not self._has_hierarchical_config():
            raise NotImplementedError(
                f"{self.__class__.__name__} must override _get_campaign_id_field() — "
                "base default only works for hierarchical native ads configs."
            )
        config = cast(HierarchicalNativeAdsConfig, self.config)
        level = self.context.drill_down_level
        if level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
            if self._uses_unified_entity_stats:
                tables = self._level_tables()
                return ast.Call(
                    name="toString",
                    args=[ast.Field(chain=[tables.entity_table.name, self._unified_campaign_pk_column])],
                )
            return self._string_field_with_orphan_fallback(
                config.campaign_table.name, self._campaign_pk_column, "unknown"
            )
        tables = self._level_tables()
        return ast.Call(
            name="toString", args=[ast.Field(chain=[tables.entity_table.name, tables.entity_id_output_column])]
        )

    def _get_source_name_field(self) -> ast.Expr:
        """
        Get the source name field expression (returns the primary source identifier).
        Default implementation returns the key from get_source_identifier_mapping().
        For example, {"reddit": ["reddit", "red"]} returns "reddit".
        Override if you need custom logic (e.g., user-configured sources).
        """
        mapping = self.get_source_identifier_mapping()
        if not mapping:
            raise NotImplementedError(
                f"{self.__class__.__name__} has no source identifier mapping. "
                "Either provide a mapping or override _get_source_name_field()."
            )
        assert len(mapping) > 0, "Should have at least one source identifier mapping"
        primary_source = next(iter(mapping.keys()))
        return ast.Call(name="toString", args=[ast.Constant(value=primary_source)])

    @abstractmethod
    def _get_impressions_field(self) -> ast.Expr:
        """Get the impressions field expression"""
        pass

    @abstractmethod
    def _get_clicks_field(self) -> ast.Expr:
        """Get the clicks field expression"""
        pass

    @abstractmethod
    def _get_cost_field(self) -> ast.Expr:
        """Get the cost field expression"""
        pass

    @abstractmethod
    def _get_reported_conversion_field(self) -> ast.Expr:
        """Get the reported conversion count field expression"""
        pass

    @abstractmethod
    def _get_reported_conversion_value_field(self) -> ast.Expr:
        """Get the reported conversion value (monetary) field expression"""
        pass

    def _get_ad_group_name_field(self) -> ast.Expr:
        """Ad group name for hierarchical adapters. At AD the adsets are reached via
        LEFT JOIN, so an orphan fallback labels deleted-parent rows; unified-report
        sources read ad-group columns straight off the entity table. NULL otherwise.
        """
        if not self._has_hierarchical_config():
            return ast.Constant(value=None)
        config = cast(HierarchicalNativeAdsConfig, self.config)
        level = self.context.drill_down_level
        if self._uses_unified_entity_stats and level == MarketingAnalyticsDrillDownLevel.AD:
            tables = self._level_tables()
            return ast.Call(
                name="toString", args=[ast.Field(chain=[tables.entity_table.name, self._adset_name_column])]
            )
        if not config.adset_table:
            if level == MarketingAnalyticsDrillDownLevel.AD:
                return ast.Constant(value=UNSYNCED_HIERARCHY_LABEL)
            return ast.Constant(value=None)
        if level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
            return ast.Call(name="toString", args=[ast.Field(chain=[config.adset_table.name, self._adset_name_column])])
        if level == MarketingAnalyticsDrillDownLevel.AD:
            return self._string_field_with_orphan_fallback(
                config.adset_table.name, self._adset_name_column, "Unknown ad group"
            )
        return ast.Constant(value=None)

    def _get_ad_group_id_field(self) -> ast.Expr:
        """Same shape as `_get_ad_group_name_field` for the ID column."""
        if not self._has_hierarchical_config():
            return ast.Constant(value=None)
        config = cast(HierarchicalNativeAdsConfig, self.config)
        level = self.context.drill_down_level
        if self._uses_unified_entity_stats and level == MarketingAnalyticsDrillDownLevel.AD:
            tables = self._level_tables()
            return ast.Call(name="toString", args=[ast.Field(chain=[tables.entity_table.name, self._adset_pk_column])])
        if not config.adset_table:
            if level == MarketingAnalyticsDrillDownLevel.AD:
                return ast.Constant(value=UNSYNCED_HIERARCHY_LABEL)
            return ast.Constant(value=None)
        if level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
            return ast.Call(name="toString", args=[ast.Field(chain=[config.adset_table.name, self._adset_pk_column])])
        if level == MarketingAnalyticsDrillDownLevel.AD:
            return self._string_field_with_orphan_fallback(config.adset_table.name, self._adset_pk_column, "unknown")
        return ast.Constant(value=None)

    def _get_ad_name_field(self) -> ast.Expr:
        """Ad name — only emitted at AD level (where ad table IS the FROM table)."""
        if not self._has_hierarchical_config():
            return ast.Constant(value=None)
        config = cast(HierarchicalNativeAdsConfig, self.config)
        return self._string_field_when_level(
            (MarketingAnalyticsDrillDownLevel.AD,), config.ad_table, self._ad_name_column
        )

    def _get_ad_id_field(self) -> ast.Expr:
        """Ad ID — only emitted at AD level."""
        if not self._has_hierarchical_config():
            return ast.Constant(value=None)
        config = cast(HierarchicalNativeAdsConfig, self.config)
        return self._string_field_when_level(
            (MarketingAnalyticsDrillDownLevel.AD,), config.ad_table, self._ad_pk_column
        )

    def _string_field_when_level(
        self,
        levels: tuple[MarketingAnalyticsDrillDownLevel, ...],
        table: Optional[DataWarehouseTable],
        column: str,
    ) -> ast.Expr:
        """Helper for adapters implementing hierarchy fields. Returns
        toString(table.column) when the current drill-down level is in `levels`
        and the table is configured; otherwise NULL.
        """
        if table is not None and self.context.drill_down_level in levels:
            return ast.Call(name="toString", args=[ast.Field(chain=[table.name, column])])
        return ast.Constant(value=None)

    @staticmethod
    def _string_field_with_orphan_fallback(table_name: str, column: str, fallback: str) -> ast.Expr:
        """Wrap toString(table.column) with coalesce against `fallback`. Used when the
        table is reached via LEFT JOIN — orphan rows (e.g. ads.adset_id pointing to a
        deleted adset) would otherwise produce NULLs that all collapse into a single
        unlabelled row in GROUP BY.
        """
        return ast.Call(
            name="coalesce",
            args=[
                ast.Call(name="toString", args=[ast.Field(chain=[table_name, column])]),
                ast.Constant(value=fallback),
            ],
        )

    # Hierarchy infrastructure: native adapters override the column-name attributes
    # below so the shared FROM/GROUP BY/WHERE builders know how to join across levels.
    # Same shape per source, different column names; defaults match `id` / `name`.

    # Stats table date column used for the WHERE date range. Override per source.
    _stats_date_column: str = "date_stop"

    # When True, the source's adset/ad "tables" are performance reports that embed
    # entity + parent columns directly — no separate entity table to join (Bing).
    # The default builders then skip the entity→stats and parent-campaign joins and
    # read campaign columns off the report via `_unified_campaign_*_column`.
    _uses_unified_entity_stats: bool = False
    # Column names on a unified report that hold parent campaign info. Only consulted
    # when `_uses_unified_entity_stats` is True. Default to snake_case since most
    # warehouse imports lowercase the platform's CamelCase fields.
    _unified_campaign_pk_column: str = "campaign_id"
    _unified_campaign_name_column: str = "campaign_name"

    # Campaign-level metadata (from CampaignTable / CampaignStats)
    _campaign_pk_column: str = "id"
    _campaign_name_column: str = "name"
    _campaign_stats_fk_column: str = "campaign_id"

    # Adset / ad-group level metadata (only consulted when adset_table present)
    _adset_pk_column: str = "id"
    _adset_name_column: str = "name"
    _adset_campaign_fk_column: str = "campaign_id"
    _adset_stats_fk_column: str = "adset_id"

    # Ad level metadata (only consulted when ad_table present)
    _ad_pk_column: str = "id"
    _ad_name_column: str = "name"
    _ad_adset_fk_column: str = "adset_id"
    _ad_campaign_fk_column: str = "campaign_id"
    _ad_stats_fk_column: str = "ad_id"

    def _has_hierarchical_config(self) -> bool:
        """Whether `self.config` is a HierarchicalNativeAdsConfig — only those carry
        the optional adset / ad tables. Non-native (External, self-managed) configs
        return False, so they fall through the `supports_level` default."""
        return isinstance(self.config, HierarchicalNativeAdsConfig)

    def supports_level(self, level: MarketingAnalyticsDrillDownLevel) -> bool:
        """Whether this adapter can return data for the given drill-down level.
        For hierarchical native ads: AD_GROUP needs adset_table+adset_stats, AD needs
        ad_table+ad_stats. Other configs (External, self-managed) only support
        campaign-level and below."""
        if not self._has_hierarchical_config():
            return level not in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD)
        config = cast(HierarchicalNativeAdsConfig, self.config)
        if level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
            return config.adset_table is not None and config.adset_stats_table is not None
        if level == MarketingAnalyticsDrillDownLevel.AD:
            return config.ad_table is not None and config.ad_stats_table is not None
        return True

    def _level_tables(self) -> HierarchicalLevelTables:
        """Return the entity + stats tables for the current drill-down level.

        Adapters that aren't hierarchical (External, self-managed) shouldn't reach
        this — they implement their own `_get_from` / `_get_where_conditions`.
        """
        if not self._has_hierarchical_config():
            raise NotImplementedError(
                f"{self.__class__.__name__} uses a non-hierarchical config; either override "
                "_level_tables() or implement _get_from / _get_where_conditions / _get_group_by directly."
            )
        config = cast(HierarchicalNativeAdsConfig, self.config)
        level = self.context.drill_down_level
        if level == MarketingAnalyticsDrillDownLevel.AD_GROUP:
            if not (config.adset_table and config.adset_stats_table):
                raise ValueError(
                    f"{self.__class__.__name__} reached _level_tables at AD_GROUP without adset tables — "
                    "MarketingSourceFactory must skip via supports_level(AD_GROUP)."
                )
            return HierarchicalLevelTables(
                entity_table=config.adset_table,
                stats_table=config.adset_stats_table,
                entity_id_column=self._adset_pk_column,
                stats_entity_id_column=self._adset_stats_fk_column,
                entity_name_column=self._adset_name_column,
                entity_id_output_column=self._adset_pk_column,
            )
        if level == MarketingAnalyticsDrillDownLevel.AD:
            if not (config.ad_table and config.ad_stats_table):
                raise ValueError(
                    f"{self.__class__.__name__} reached _level_tables at AD without ad tables — "
                    "MarketingSourceFactory must skip via supports_level(AD)."
                )
            return HierarchicalLevelTables(
                entity_table=config.ad_table,
                stats_table=config.ad_stats_table,
                entity_id_column=self._ad_pk_column,
                stats_entity_id_column=self._ad_stats_fk_column,
                entity_name_column=self._ad_name_column,
                entity_id_output_column=self._ad_pk_column,
            )
        return HierarchicalLevelTables(
            entity_table=config.campaign_table,
            stats_table=config.stats_table,
            entity_id_column=self._campaign_pk_column,
            stats_entity_id_column=self._campaign_stats_fk_column,
            entity_name_column=self._campaign_name_column,
            entity_id_output_column=self._campaign_pk_column,
        )

    def _get_where_conditions(self) -> list[ast.Expr]:
        """Default: filter the current level's stats table by `date_range` against the
        `_stats_date_column` column. Adapters with a non-standard WHERE override this."""
        conditions: list[ast.Expr] = []
        if not self.context.date_range:
            return conditions
        stats_table_name = self._level_tables().stats_table.name
        date_field = ast.Call(name="toDateTime", args=[ast.Field(chain=[stats_table_name, self._stats_date_column])])
        from_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_from_str)])
        to_date = ast.Call(name="toDateTime", args=[ast.Constant(value=self.context.date_range.date_to_str)])
        conditions.append(ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.GtEq, right=from_date))
        conditions.append(ast.CompareOperation(left=date_field, op=ast.CompareOperationOp.LtEq, right=to_date))
        return conditions

    def _get_from(self) -> ast.JoinExpr:
        """Default FROM clause for hierarchical native ads adapters.

        Builds: entity LEFT JOIN stats [LEFT JOIN parent adset (at AD)] [LEFT JOIN campaigns
        (at AD_GROUP/AD)]. Non-hierarchical adapters override this entirely.
        """
        if not self._has_hierarchical_config():
            raise NotImplementedError(
                f"{self.__class__.__name__} must override _get_from() — base default only handles "
                "hierarchical native ads configs."
            )
        config = cast(HierarchicalNativeAdsConfig, self.config)
        tables = self._level_tables()
        entity_table_name = tables.entity_table.name
        stats_table_name = tables.stats_table.name
        level = self.context.drill_down_level
        is_unified = self._uses_unified_entity_stats and level in (
            MarketingAnalyticsDrillDownLevel.AD_GROUP,
            MarketingAnalyticsDrillDownLevel.AD,
        )

        # Entity and report/stats tables can store the same id with different types
        # (e.g. Reddit's ad_groups.id vs ad_group_report.ad_group_id), so cast both
        # join keys to String — otherwise the LEFT JOIN silently matches zero rows.
        def join_key(table: str, column: str) -> ast.Call:
            return ast.Call(name="toString", args=[ast.Field(chain=[table, column])])

        # entity LEFT JOIN stats ON entity.<pk> = stats.<fk> — skipped in unified mode
        # because entity_table === stats_table (a single performance report).
        stats_join: ast.JoinExpr | None = None
        if not is_unified:
            stats_join = ast.JoinExpr(
                table=ast.Field(chain=[stats_table_name]),
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        left=join_key(entity_table_name, tables.entity_id_column),
                        op=ast.CompareOperationOp.Eq,
                        right=join_key(stats_table_name, tables.stats_entity_id_column),
                    ),
                    constraint_type="ON",
                ),
            )

        parent_joins: list[ast.JoinExpr] = []
        # In unified mode the report already exposes campaign / ad-group context as
        # columns, so skip parent joins entirely. `_get_campaign_*` / `_get_ad_group_*`
        # below read those directly from the entity table.
        if is_unified:
            return ast.JoinExpr(table=ast.Field(chain=[entity_table_name]))
        # At AD level with adsets synced, chain ads → adsets → campaigns. Going through
        # adsets matters: not every source carries `campaign_id` directly on the ads table
        # (or ships it consistently), but adsets always have `campaign_id` since adsets
        # belong to a campaign. We only fall back to ads.<campaign_fk> → campaigns when
        # adsets aren't synced.
        if level == MarketingAnalyticsDrillDownLevel.AD and config.adset_table:
            parent_joins.append(
                ast.JoinExpr(
                    table=ast.Field(chain=[config.adset_table.name]),
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            left=join_key(entity_table_name, self._ad_adset_fk_column),
                            op=ast.CompareOperationOp.Eq,
                            right=join_key(config.adset_table.name, self._adset_pk_column),
                        ),
                        constraint_type="ON",
                    ),
                )
            )
        # At AD_GROUP / AD, LEFT JOIN campaigns to surface campaign name/id.
        if level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
            # Source side of the campaign join: at AD_GROUP the FROM table is adsets;
            # at AD prefer adsets (when synced) since the campaign FK is reliably on
            # adsets, only falling back to ads when adsets aren't available.
            if level == MarketingAnalyticsDrillDownLevel.AD and config.adset_table:
                campaign_join_table = config.adset_table.name
                campaign_fk = self._adset_campaign_fk_column
            elif level == MarketingAnalyticsDrillDownLevel.AD:
                campaign_join_table = entity_table_name
                campaign_fk = self._ad_campaign_fk_column
            else:
                campaign_join_table = entity_table_name
                campaign_fk = self._adset_campaign_fk_column
            parent_joins.append(
                ast.JoinExpr(
                    table=ast.Field(chain=[config.campaign_table.name]),
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            left=join_key(campaign_join_table, campaign_fk),
                            op=ast.CompareOperationOp.Eq,
                            right=join_key(config.campaign_table.name, self._campaign_pk_column),
                        ),
                        constraint_type="ON",
                    ),
                )
            )

        # `stats_join` is only None in unified mode, which returns earlier above.
        assert stats_join is not None
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

    def _get_group_by(self) -> list[ast.Expr]:
        """Default GROUP BY for hierarchical adapters: campaign columns at every level,
        plus ad-group columns at AD_GROUP/AD, plus ad columns at AD."""
        level = self.context.drill_down_level
        group_by: list[ast.Expr] = [self._get_campaign_name_field(), self._get_campaign_id_field()]
        if level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD):
            group_by.extend([self._get_ad_group_name_field(), self._get_ad_group_id_field()])
        if level == MarketingAnalyticsDrillDownLevel.AD:
            group_by.extend([self._get_ad_name_field(), self._get_ad_id_field()])
        return group_by

    def _get_campaign_field_preference(self) -> str:
        """
        Get campaign field matching preference for this integration from team config.

        Returns: "campaign_name" or "campaign_id"

        Defaults to campaign_name if no preference set (backward compatible).
        """
        try:
            preferences = self.team.marketing_analytics_config.campaign_field_preferences
            integration_prefs = preferences.get(self.get_source_type(), {})
            return integration_prefs.get("match_field", "campaign_name")
        except Exception:
            # If any error accessing config, default to campaign_name
            return "campaign_name"

    def get_campaign_match_field(self) -> ast.Expr:
        """
        Get the campaign field expression to use for matching with utm_campaign.
        This respects the campaign_field_preferences setting.

        Returns either campaign_name or campaign_id field based on configuration.
        """
        preference = self._get_campaign_field_preference()
        if preference == "campaign_id":
            return self._get_campaign_id_field()
        return self._get_campaign_name_field()

    def _get_match_key_expr(self) -> ast.Expr:
        """Expression for the `match_key` column (JOINed against unified_conversion_goals).
        At levels that exclude conversion goals the JOIN is skipped, so emit an empty
        constant instead of a confusing duplicate of `campaign_name`.
        """
        level_config = DRILL_DOWN_LEVEL_CONFIG.get(self.context.drill_down_level)
        if level_config and level_config.get("excludes_conversion_goals"):
            return ast.Constant(value="")
        return self.get_campaign_match_field()

    def _table_has_column(self, table: DataWarehouseTable, column_name: str) -> bool:
        """Cached column-existence check for warehouse tables. Used by hot paths like
        `_apply_currency_conversion` and `_build_actions_conversion_sum` (Meta) that
        call into the same table multiple times per query."""
        cache_key = (id(table), column_name)
        cached = self._table_column_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            columns = getattr(table, "columns", None)
            present = bool(columns and hasattr(columns, "__contains__") and column_name in columns)
        except (TypeError, AttributeError, KeyError):
            present = False
        self._table_column_cache[cache_key] = present
        return present

    def _apply_currency_conversion(
        self,
        table: DataWarehouseTable,
        table_name: str,
        currency_column: str,
        value_expr: ast.Expr,
    ) -> ast.Expr | None:
        """Wrap value_expr with currency conversion if the currency column exists in the table.

        Returns toFloat(convertCurrency(coalesce(currency_col, base_currency), base_currency, value_expr))
        or None if the column doesn't exist or can't be checked.
        """
        if not self._table_has_column(table, currency_column):
            return None
        currency_field = ast.Field(chain=[table_name, currency_column])
        currency_with_fallback = ast.Call(
            name="coalesce", args=[currency_field, ast.Constant(value=self.context.base_currency)]
        )
        converted = ast.Call(
            name="convertCurrency",
            args=[currency_with_fallback, ast.Constant(value=self.context.base_currency), value_expr],
        )
        return ast.Call(name="toFloat", args=[converted])

    def _log_validation_errors(self, errors: list[str]):
        """Helper to log validation issues"""
        if errors:
            self.logger.error("Source validation failed", errors=errors)

    def _log_query_generation(self, success: bool, error: str | None = None):
        """Helper to log query generation status"""
        if success:
            self.logger.debug("Query generated successfully")
        else:
            self.logger.error("Query generation failed", error=error)

    def _build_select_columns(self) -> list[ast.Expr]:
        """Build the standardized SELECT columns for marketing analytics queries.
        match_key first (stable position for joins), then data columns.

        The ad_group / ad columns are only emitted at AD_GROUP / AD drill-down levels —
        at other levels the 9-column schema is preserved for backward compatibility.
        """
        columns: list[ast.Expr] = [
            ast.Alias(alias=self.match_key_field, expr=self._get_match_key_expr()),
            ast.Alias(alias=self.campaign_name_field, expr=self._get_campaign_name_field()),
            ast.Alias(alias=self.campaign_id_field, expr=self._get_campaign_id_field()),
            ast.Alias(alias=self.source_name_field, expr=self._get_source_name_field()),
        ]
        if self.context.drill_down_level in (
            MarketingAnalyticsDrillDownLevel.AD_GROUP,
            MarketingAnalyticsDrillDownLevel.AD,
        ):
            columns.extend(
                [
                    ast.Alias(alias=self.ad_group_name_field, expr=self._get_ad_group_name_field()),
                    ast.Alias(alias=self.ad_group_id_field, expr=self._get_ad_group_id_field()),
                    ast.Alias(alias=self.ad_name_field, expr=self._get_ad_name_field()),
                    ast.Alias(alias=self.ad_id_field, expr=self._get_ad_id_field()),
                ]
            )
        columns.extend(
            [
                ast.Alias(alias=self.impressions_field, expr=self._get_impressions_field()),
                ast.Alias(alias=self.clicks_field, expr=self._get_clicks_field()),
                ast.Alias(alias=self.cost_field, expr=self._get_cost_field()),
                ast.Alias(alias=self.reported_conversion_field, expr=self._get_reported_conversion_field()),
                ast.Alias(alias=self.reported_conversion_value_field, expr=self._get_reported_conversion_value_field()),
            ]
        )
        return columns

    def build_query(self) -> Optional[ast.SelectQuery]:
        """Build the standardized SelectQuery for this source.

        The campaign_costs CTE expects the same column shape from every adapter at a
        given level: 9 columns at CHANNEL/SOURCE/CAMPAIGN/MEDIUM/CONTENT/TERM, 13 at
        AD_GROUP/AD (ad_group_name/id + ad_name/id inserted after source_name).
        Returns None if this source cannot provide data for the given context.
        """
        try:
            select_columns = self._build_select_columns()

            # Build query components
            from_expr = self._get_from()
            where_conditions = self._get_where_conditions()
            group_by_exprs = self._get_group_by()

            # Build WHERE clause
            where_expr = None
            if where_conditions:
                if len(where_conditions) == 1:
                    where_expr = where_conditions[0]
                else:
                    where_expr = ast.And(exprs=where_conditions)

            # Build GROUP BY clause
            group_by = group_by_exprs if group_by_exprs else None

            # Create the complete SelectQuery
            query = ast.SelectQuery(select=select_columns, select_from=from_expr, where=where_expr, group_by=group_by)

            self._log_query_generation(True)
            return query

        except Exception as e:
            error_msg = f"Query generation error: {str(e)}"
            self.logger.error("Query generation failed", error=error_msg, exc_info=True)
            self._log_query_generation(False, error_msg)
            return None

    def _cost_date_expr(self) -> ast.Expr:
        """Per-day cost date (`toDate` of the source's stats date column) for the materialized table."""
        stats_table_name = self._level_tables().stats_table.name
        return ast.Call(name="toDate", args=[ast.Field(chain=[stats_table_name, self._stats_date_column])])

    def _materialization_date_where(self) -> ast.Expr:
        """Date filter using `time_window_min`/`time_window_max` placeholders so the lazy framework
        resolves the per-job window (unlike the read-time WHERE, which bakes in the request's range).
        The window is half-open `[min, max)` to match the framework convention — using `<=` on the
        upper bound double-counts boundary days that fall in two adjacent job windows."""
        stats_table_name = self._level_tables().stats_table.name
        date_field = ast.Call(name="toDateTime", args=[ast.Field(chain=[stats_table_name, self._stats_date_column])])
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    left=date_field,
                    op=ast.CompareOperationOp.GtEq,
                    right=ast.Placeholder(expr=ast.Field(chain=["time_window_min"])),
                ),
                ast.CompareOperation(
                    left=date_field,
                    op=ast.CompareOperationOp.Lt,
                    right=ast.Placeholder(expr=ast.Field(chain=["time_window_max"])),
                ),
            ]
        )

    def build_materialization_query(self, source_id: str) -> Optional[ast.SelectQuery]:
        """Fine-grain (per-day) SELECT for materializing this source's cost rows into
        `marketing_costs_preaggregated`. Reuses the normalized metric/dimension exprs (currency,
        micros, JSON conversions) but re-aliases to the table schema, adds `source_id` + per-day
        `cost_date`, and filters by `time_window` placeholders so the lazy framework runs it per job.

        The caller sets `context.drill_down_level` to the source's finest supported level
        (AD > AD_GROUP > CAMPAIGN); levels the source doesn't reach emit '-' for ad_group/ad so the
        table schema stays stable. `match_key` is always the campaign match field (not the read-time
        `_get_match_key_expr`, which blanks at AD levels) so the read-side conversion-goal join works
        after aggregating back up to campaign level.
        """
        try:
            level = self.context.drill_down_level
            at_ad_group = level in (MarketingAnalyticsDrillDownLevel.AD_GROUP, MarketingAnalyticsDrillDownLevel.AD)
            at_ad = level == MarketingAnalyticsDrillDownLevel.AD
            empty = ast.Constant(value="-")

            select_columns: list[ast.Expr] = [
                ast.Alias(alias="source_id", expr=ast.Constant(value=source_id)),
                ast.Alias(alias="source_name", expr=self._get_source_name_field()),
                # grain = the level this row was materialized at (campaign/ad_group/ad); the read-side
                # picks the matching grain per drill-down so each level keeps the platform's own stats
                # (a campaign-stats row is NOT the roll-up of its ads).
                ast.Alias(alias="grain", expr=ast.Constant(value=str(level.value))),
                ast.Alias(alias="match_key", expr=self.get_campaign_match_field()),
                ast.Alias(alias="campaign_id", expr=self._get_campaign_id_field()),
                ast.Alias(alias="campaign_name", expr=self._get_campaign_name_field()),
                ast.Alias(alias="ad_group_id", expr=self._get_ad_group_id_field() if at_ad_group else empty),
                ast.Alias(alias="ad_group_name", expr=self._get_ad_group_name_field() if at_ad_group else empty),
                ast.Alias(alias="ad_id", expr=self._get_ad_id_field() if at_ad else empty),
                ast.Alias(alias="ad_name", expr=self._get_ad_name_field() if at_ad else empty),
                ast.Alias(alias="cost_date", expr=self._cost_date_expr()),
                ast.Alias(alias="cost", expr=self._get_cost_field()),
                ast.Alias(alias="clicks", expr=self._get_clicks_field()),
                ast.Alias(alias="impressions", expr=self._get_impressions_field()),
                ast.Alias(alias="reported_conversions", expr=self._get_reported_conversion_field()),
                ast.Alias(alias="reported_conversion_value", expr=self._get_reported_conversion_value_field()),
            ]
            group_by = [*self._get_group_by(), self._cost_date_expr()]
            return ast.SelectQuery(
                select=select_columns,
                select_from=self._get_from(),
                where=self._materialization_date_where(),
                group_by=group_by,
            )
        except Exception as e:
            self.logger.error("Materialization query generation failed", error=str(e), exc_info=True)
            return None
