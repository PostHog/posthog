from dataclasses import dataclass
from typing import Union

from posthog.schema import ActionsNode, EventsNode, ExperimentDataWarehouseNode

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.clickhouse.query_tagging import tag_contains_user_hogql


@dataclass
class MetricSourceInfo:
    """
    Normalized metadata for an events, actions, or data warehouse metric source,
    so query builders can handle all three the same way. Funnel queries need this
    most, because one funnel can mix source types.
    """

    kind: str
    table_name: str
    entity_key: ast.Expr
    timestamp_field: str
    has_uuid: bool
    has_session_id: bool

    @classmethod
    def from_source(
        cls,
        source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode],
        entity_key: str | None = None,
    ) -> "MetricSourceInfo":
        """
        entity_key is the experiment entity key, for example "person_id" or "$group_0".
        Events and actions sources require it and raise ValueError without it. Data
        warehouse sources ignore it and use their data_warehouse_join_key.
        """
        if isinstance(source, ExperimentDataWarehouseNode):
            # `data_warehouse_join_key` is the user-supplied HogQL parsed below.
            tag_contains_user_hogql()
            return cls(
                kind="datawarehouse",
                table_name=source.table_name,
                entity_key=parse_expr(source.data_warehouse_join_key),
                timestamp_field=source.timestamp_field,
                has_uuid=False,
                has_session_id=False,
            )
        elif isinstance(source, ActionsNode):
            if entity_key is None:
                raise ValueError("entity_key is required for ActionsNode sources to support group aggregation")
            return cls(
                kind="actions",
                table_name="events",
                entity_key=parse_expr(entity_key),
                timestamp_field="timestamp",
                has_uuid=True,
                has_session_id=True,
            )
        else:  # EventsNode
            if entity_key is None:
                raise ValueError("entity_key is required for EventsNode sources to support group aggregation")
            return cls(
                kind="events",
                table_name="events",
                entity_key=parse_expr(entity_key),
                timestamp_field="timestamp",
                has_uuid=True,
                has_session_id=True,
            )

    def build_select_fields(self) -> list[ast.Alias]:
        """
        All sources in a UNION ALL must return the same columns:
        - entity_id (String for all sources)
        - variant (always empty, because the variant comes from the exposure join)
        - timestamp
        - uuid (zero UUID for DW sources)
        - session_id (empty string for DW sources)
        """
        fields = [
            ast.Alias(
                alias="entity_id",
                expr=ast.Call(
                    name="toString",
                    args=[self.entity_key],
                ),
            ),
            ast.Alias(
                alias="variant",
                expr=ast.Constant(value=""),
            ),
            # For DW sources, use the unqualified field name, because a dotted table name
            # such as "schema.table" would become "schema.table.timestamp" if qualified.
            ast.Alias(
                alias="timestamp",
                expr=ast.Field(
                    chain=[self.timestamp_field]
                    if self.kind == "datawarehouse"
                    else [self.table_name, self.timestamp_field]
                ),
            ),
        ]

        uuid_expr: ast.Expr
        if self.has_uuid:
            uuid_expr = ast.Field(chain=["uuid"])
        else:
            uuid_expr = ast.Call(
                name="toUUID",
                args=[ast.Constant(value="00000000-0000-0000-0000-000000000000")],
            )

        fields.append(ast.Alias(alias="uuid", expr=uuid_expr))

        session_id_expr: ast.Expr
        if self.has_session_id:
            session_id_expr = ast.Field(chain=["properties", "$session_id"])
        else:
            session_id_expr = ast.Constant(value="")

        fields.append(ast.Alias(alias="session_id", expr=session_id_expr))

        return fields
