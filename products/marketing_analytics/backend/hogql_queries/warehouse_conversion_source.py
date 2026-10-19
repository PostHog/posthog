from typing import TYPE_CHECKING

from posthog.schema import ConversionGoalFilter3, DataWarehousePropertyFilter

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.dataclasses import frozen

from .conversion_goal_value import conversion_goal_value_in_base_currency

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

    from posthog.hogql_queries.utils.query_date_range import QueryDateRange
    from posthog.models import Team


@frozen
class WarehouseConversionSource:
    goal: ConversionGoalFilter3
    team: "Team"
    database: "Database"

    def __post_init__(self) -> None:
        if self.goal.math not in (None, "total", "dau", "sum"):
            raise ValueError("Warehouse attribution supports total, unique users, or sum math. Update the goal's math.")
        if self.goal.math_group_type_index is not None:
            raise ValueError("Warehouse attribution requires person identity. Group attribution is not supported yet.")
        if self.goal.math_multiplier not in (None, 1):
            raise ValueError(
                "Convert amounts to currency units in the source view before using this goal for attribution."
            )
        if self.goal.math == "sum" and not self.goal.math_property:
            raise ValueError("Select an amount column for a warehouse goal that uses sum math.")
        for field in ("id_field", "timestamp_field", "distinct_id_field"):
            self.column(field)
        if self.goal.math_property:
            self.validate_column(self.goal.math_property)
        currency = self.goal.math_property_revenue_currency
        if currency and currency.property:
            self.validate_column(currency.property)
        for prop in [*(self.goal.properties or []), *(self.goal.fixedProperties or [])]:
            if not isinstance(prop, DataWarehousePropertyFilter):
                raise ValueError("Warehouse attribution needs warehouse column filters. Update the goal's filters.")
            self.validate_column(prop.key)

    def validate_column(self, column: str) -> None:
        table = self.database.get_table(self.goal.table_name)
        if not column or column not in table.fields:
            raise ValueError(
                f"Column '{column}' was not found in the conversion source. Update the goal's column mapping."
            )

    def column(self, mapping: str) -> ast.Field:
        column = (self.goal.schema_map or {}).get(mapping) or getattr(self.goal, mapping)
        if not isinstance(column, str):
            raise ValueError(f"Select a column for '{mapping}' in the conversion goal.")
        self.validate_column(column)
        return ast.Field(chain=["warehouse_source", column])

    def build_query(self, date_range: "QueryDateRange") -> ast.SelectQuery:
        timestamp = self.column("timestamp_field")
        amount = (
            conversion_goal_value_in_base_currency(
                self.goal,
                self.team,
                ast.Field(chain=["warehouse_source", self.goal.math_property]),
                timestamp,
                warehouse_table_alias="warehouse_source",
            )
            if self.goal.math == "sum" and self.goal.math_property
            else ast.Constant(value=1.0)
        )
        properties: list[DataWarehousePropertyFilter] = []
        for prop in [*(self.goal.properties or []), *(self.goal.fixedProperties or [])]:
            assert isinstance(prop, DataWarehousePropertyFilter)
            warehouse_filter = prop.model_copy(deep=True)
            warehouse_filter.key = "warehouse_source." + prop.key
            properties.append(warehouse_filter)
        rows = parse_select(
            """
            SELECT coalesce(toString({id}), '') AS conversion_id,
                toUnixTimestamp({timestamp}) AS timestamp,
                coalesce(toString({distinct_id}), '') AS distinct_id,
                {amount} AS value
            FROM {table} AS warehouse_source
            WHERE {timestamp} >= {date_from} AND {timestamp} <= {date_to} AND {filters}
            """,
            placeholders={
                "id": self.column("id_field"),
                "timestamp": timestamp,
                "distinct_id": self.column("distinct_id_field"),
                "amount": amount,
                "table": ast.Field(chain=[*self.goal.table_name.split(".")]),
                "date_from": ast.Constant(value=date_range.date_from()),
                "date_to": ast.Constant(value=date_range.date_to()),
                "filters": property_to_expr(properties, team=self.team, strict=True)
                if properties
                else ast.Constant(value=True),
            },
        )
        # A join can duplicate source rows. Collapse identical conversions and reject conflicting values.
        query = parse_select(
            """
            SELECT source.conversion_id AS conversion_id, min(source.timestamp) AS timestamp,
                min(source.distinct_id) AS distinct_id, min(source.value) AS value
            FROM {rows} AS source
            GROUP BY source.conversion_id
            HAVING throwIf(countIf(empty(source.conversion_id)) > 0, 'Conversion IDs must not be empty. Update the source mapping.') = 0
                AND throwIf(uniqExact((source.timestamp, source.distinct_id, source.value)) > 1,
                    'Conversion IDs have conflicting rows. Use unique conversion IDs or deduplicate the source.') = 0
                AND throwIf(countIf(source.value IS NULL OR NOT isFinite(source.value)) > 0,
                    'Conversion amounts must be finite numbers. Update the source amount column.') = 0
            """,
            placeholders={"rows": rows},
        )
        assert isinstance(query, ast.SelectQuery)
        return query
