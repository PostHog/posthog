import json

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
)
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.errors import InternalCHQueryError
from posthog.models import Team

from products.signals.backend.filter_catalog_schema import CatalogBundle, JsonPathRecipe
from products.signals.backend.filter_expression import FilterValidationError
from products.signals.backend.filter_recipes import WarehouseFilterBindings


def catalog_bundle(field_type: str = "string", kind: str = "json_path", missing: str | None = None) -> CatalogBundle:
    recipe: dict[str, object] = {"kind": kind, "column": "payload"}
    if kind == "json_path":
        recipe["path"] = ["value"]
    elif kind == "json_array_map":
        recipe.update(array_path=["nodes"], value_path=["name"])
    return CatalogBundle.model_validate(
        {
            "schema_version": 1,
            "fields": [
                {
                    "name": "value",
                    "type": field_type,
                    "description": "Synthetic value.",
                    "binding": recipe,
                    "missing_value": missing
                    if missing is not None
                    else "empty_array"
                    if field_type.startswith("array<")
                    else "null",
                    "malformed_value": "error",
                }
            ],
            "starter_expressions": [],
        }
    )


def bindings(
    field_type: str = "string", kind: str = "json_path", missing: str | None = None
) -> WarehouseFilterBindings:
    column: DatabaseField = (
        IntegerDatabaseField(name="payload")
        if kind == "column" and field_type == "integer"
        else StringDatabaseField(name="payload")
    )
    return WarehouseFilterBindings(
        catalog_bundle(field_type, kind, missing), {"payload": column}, source_alias="source"
    )


class TestFilterRecipeValidation(SimpleTestCase):
    @parameterized.expand(
        ["boolean", "number", "datetime", "array<integer>", "array<number>", "array<boolean>", "array<string>"]
    )
    def test_rejects_unsupported_catalog_configuration(self, field_type: str) -> None:
        with self.assertRaises(FilterValidationError) as raised:
            bindings(field_type, missing="null")
        self.assertEqual(
            raised.exception.code,
            "unsupported_missing_value" if field_type == "array<string>" else "unsupported_field_type",
        )

    def test_rejects_incompatible_columns_before_querying(self) -> None:
        bundle = catalog_bundle()
        with self.assertRaises(FilterValidationError) as raised:
            WarehouseFilterBindings(bundle, {}, source_alias="source")
        self.assertEqual(raised.exception.code, "missing_column")
        with self.assertRaises(FilterValidationError) as raised:
            WarehouseFilterBindings(bundle, {"payload": IntegerDatabaseField(name="payload")}, source_alias="source")
        self.assertEqual(raised.exception.code, "column_type")
        with self.assertRaises(FilterValidationError):
            bindings("array<string>", "column")


class TestFilterRecipeExecution(SimpleTestCase):
    def assert_malformed(self, engine: WarehouseFilterBindings, payload: str, expression: str | None = None) -> None:
        with self.assertRaisesRegex(InternalCHQueryError, "signal_filter:malformed_value:value") as raised:
            self.execute(engine, payload, expression)
        self.assertEqual(raised.exception.code, 395)

    def execute(
        self, engine: WarehouseFilterBindings, payload: str | int | None, expression: str | None = None
    ) -> object:
        selected: ast.Expr = (
            engine.projections["value"].select()
            if expression is None
            else engine.predicate(expression) or ast.Constant(value=True)
        )
        query = ast.SelectQuery(
            select=[selected],
            select_from=ast.JoinExpr(
                alias="source",
                table=ast.SelectQuery(select=[ast.Alias(alias="payload", expr=ast.Constant(value=payload))]),
            ),
        )
        return self.execute_query(query)[0][0]

    def execute_query(self, query: ast.SelectQuery) -> list[tuple[object, ...]]:
        context = HogQLContext(
            team=Team(id=1, project_id=1),
            database=Database(),
            enable_select_queries=True,
            restricted_properties=set(),
            apply_events_retention_floor=False,
            use_new_events_schema=False,
        )
        sql, _ = prepare_and_print_ast(query, context, "clickhouse")
        return sync_execute(sql, context.values, flush=False, workload=Workload.OFFLINE)

    @parameterized.expand(
        [
            ("string", '{"value":"Core"}', "Core"),
            ("integer", '{"value":0}', 0),
            ("integer", '{"value":-2}', -2),
            ("string", "{}", None),
            ("string", '{"value":null}', None),
            ("string", "null", None),
            ("string", " null ", None),
            ("string", None, None),
            ("string", "{}", 1, "NOT (value = 'Core')"),
        ]
    )
    def test_scalar_values_and_missing(
        self, field_type: str, payload: str | None, expected: object, expression: str | None = None
    ) -> None:
        self.assertEqual(self.execute(bindings(field_type), payload, expression), expected)

    @parameterized.expand(
        [
            ("string", "broken"),
            ("string", ""),
            ("string", "[]"),
            ("string", '{"value":42}'),
            ("string", '{"value":{}}'),
            ("integer", '{"value":"2"}'),
            ("integer", '{"value":1.5}'),
            ("integer", '{"value":9223372036854775808}'),
        ]
    )
    def test_malformed_values_surface_errors(self, field_type: str, payload: str) -> None:
        engine = bindings(field_type)
        self.assert_malformed(engine, payload)
        self.assert_malformed(engine, payload, "true OR isNull(value)")
        self.assert_malformed(engine, payload, "false AND isNull(value)")

    @parameterized.expand(
        [
            ('{"nodes":[{"name":"internal"},{"name":"feature"}]}', ["internal", "feature"]),
            ('{"nodes":[]}', []),
            ('{"nodes":null}', []),
            ("{}", []),
            ("null", []),
        ]
    )
    def test_array_map_and_empty_policy(self, payload: str, expected: object) -> None:
        self.assertEqual(self.execute(bindings("array<string>", "json_array_map", "empty_array"), payload), expected)

    @parameterized.expand(
        [
            "[]",
            '{"nodes":{}}',
            '{"nodes":[{}]}',
            '{"nodes":[{"name":null}]}',
            '{"nodes":[{"name":2}]}',
            '{"nodes":[null]}',
        ]
    )
    def test_array_shape_and_elements_fail_closed(self, payload: str) -> None:
        self.assert_malformed(
            bindings("array<string>", "json_array_map", "empty_array"), payload, "NOT has(value, 'internal')"
        )

    def test_json_array_and_column_recipes(self) -> None:
        self.assertEqual(self.execute(bindings("array<string>"), '{"value":["a","b"]}'), ["a", "b"])
        self.assertEqual(self.execute(bindings("integer", "column"), 0, "value IN (1,2)"), 0)
        self.assertEqual(self.execute(bindings("integer", "column"), 2, "value IN (1,2)"), 1)
        self.assertEqual(self.execute(bindings("integer", "column"), 2, "value IN (2)"), 1)
        self.assertEqual(self.execute(bindings("integer", "column"), 1, "value IN (2)"), 0)
        self.assertEqual(self.execute(bindings("string", "column"), "Core", "value NOT IN ('Core')"), 0)
        self.assertEqual(self.execute(bindings("string", "column"), "Other", "value NOT IN ('Core')"), 1)
        self.assertEqual(self.execute(bindings("string", "column"), "literal' OR true", "value = 'other'"), 0)
        self.assertEqual(self.execute(bindings("integer", "column"), 2, "false"), 0)
        self.assertIsNone(bindings().predicate(""))

    @parameterized.expand(
        [
            (" 2 ", 2),
            ("\t2\t", 2),
            ("\n2\n", 2),
            (" 9223372036854775807 ", 9223372036854775807),
            (" -9223372036854775808 ", -9223372036854775808),
            (" 9223372036854775808 ", None),
            (" -9223372036854775809 ", None),
        ]
    )
    def test_root_json_integer_whitespace(self, payload: str, expected: int | None) -> None:
        bundle = catalog_bundle("integer")
        bundle.fields[0].binding = JsonPathRecipe(kind="json_path", column="payload", path=[])
        engine = WarehouseFilterBindings(
            bundle, {"payload": StringDatabaseField(name="payload")}, source_alias="source"
        )
        if expected is None:
            self.assert_malformed(engine, payload)
        else:
            self.assertEqual(self.execute(engine, payload), expected)
            self.assertEqual(self.execute(engine, payload, f"value = {expected}"), 1)

    def test_runtime_size_bounds(self) -> None:
        for payload, engine in [
            (json.dumps({"value": "x" * 65536}), bindings()),
            (json.dumps({"nodes": [{"name": "a"}] * 257}), bindings("array<string>", "json_array_map")),
        ]:
            self.assert_malformed(engine, payload)

    def test_native_integer_overflow_is_malformed(self) -> None:
        with self.assertRaises(InternalCHQueryError) as raised:
            self.execute(bindings("integer", "column"), 9223372036854775808)
        self.assertEqual(raised.exception.code, 395)

    def test_native_string_array_projection(self) -> None:
        engine = WarehouseFilterBindings(
            catalog_bundle("array<string>", "column"),
            {"payload": StringArrayDatabaseField(name="payload")},
            source_alias="source",
        )
        query = ast.SelectQuery(
            select=[engine.projections["value"].select()],
            select_from=ast.JoinExpr(
                alias="source",
                table=ast.SelectQuery(
                    select=[ast.Alias(alias="payload", expr=ast.Array(exprs=[ast.Constant(value="feature")]))]
                ),
            ),
        )
        self.assertEqual(self.execute_query(query), [(["feature"],)])

    def test_shared_column_with_colliding_projection_name(self) -> None:
        bundle = catalog_bundle()
        bundle.fields[0].name = "payload"
        bundle.fields.append(
            bundle.fields[0].model_copy(
                update={"name": "other", "binding": JsonPathRecipe(kind="json_path", column="payload", path=["other"])}
            )
        )
        engine = WarehouseFilterBindings(
            bundle, {"payload": StringDatabaseField(name="payload")}, source_alias="source"
        )
        query = ast.SelectQuery(
            select=[projection.select() for projection in engine.projections.values()],
            select_from=ast.JoinExpr(
                alias="source",
                table=ast.SelectQuery(
                    select=[ast.Alias(alias="payload", expr=ast.Constant(value='{"value":"Core","other":"Team"}'))]
                ),
            ),
            where=engine.predicate("payload = 'Core' AND other = 'Team'"),
        )
        self.assertEqual(self.execute_query(query), [("Core", "Team")])

    def test_many_referenced_fields_resolve_and_execute(self) -> None:
        bundle = catalog_bundle(kind="column")
        bundle.fields = [bundle.fields[0].model_copy(update={"name": f"field_{index}"}) for index in range(127)]
        engine = WarehouseFilterBindings(
            bundle, {"payload": StringDatabaseField(name="payload")}, source_alias="source"
        )
        self.assertEqual(
            self.execute(engine, "assigned", " OR ".join(f"isNull(field_{index})" for index in range(127))), 0
        )

    def test_nested_paths_and_literal_path_keys(self) -> None:
        bundle = catalog_bundle()
        bundle.fields[0].binding = JsonPathRecipe(kind="json_path", column="payload", path=["outer", "value"])
        engine = WarehouseFilterBindings(
            bundle, {"payload": StringDatabaseField(name="payload")}, source_alias="source"
        )
        self.assertIsNone(self.execute(engine, "{}"))
        self.assert_malformed(engine, '{"outer":[]}')
        key = "key'); SELECT true; --"
        bundle.fields[0].binding = JsonPathRecipe(kind="json_path", column="payload", path=[key])
        engine = WarehouseFilterBindings(
            bundle, {"payload": StringDatabaseField(name="payload")}, source_alias="source"
        )
        self.assertEqual(self.execute(engine, json.dumps({key: "safe"})), "safe")

    def test_linear_recipes_in_scoped_query(self) -> None:
        specs = [
            ("team_id", "team", "id"),
            ("project_id", "project", "id"),
            ("project_name", "project", "name"),
            ("assignee_id", "assignee", "id"),
            ("state_type", "state", "type"),
            ("label_names", "labels", "name"),
        ]
        fields: list[dict[str, object]] = [
            {
                "name": name,
                "type": "array<string>" if name == "label_names" else "string",
                "description": "Synthetic issue field.",
                "binding": {"kind": "json_array_map", "column": column, "array_path": ["nodes"], "value_path": [key]}
                if name == "label_names"
                else {"kind": "json_path", "column": column, "path": [key]},
                "missing_value": "empty_array" if name == "label_names" else "null",
                "malformed_value": "error",
            }
            for name, column, key in specs
        ]
        fields.append(
            {
                "name": "priority",
                "type": "integer",
                "description": "Synthetic issue priority.",
                "binding": {"kind": "column", "column": "priority"},
                "missing_value": "null",
                "malformed_value": "error",
            }
        )
        bundle = CatalogBundle.model_validate({"schema_version": 1, "fields": fields, "starter_expressions": []})
        payloads: dict[str, str | int] = {
            "team": json.dumps({"id": "team-a", "name": "Engineering", "key": "ENG"}),
            "project": json.dumps({"id": "project-a", "name": "Core"}),
            "assignee": "null",
            "state": json.dumps({"id": "state-a", "name": "Todo", "type": "unstarted", "color": "#000000"}),
            "labels": json.dumps({"nodes": [{"id": "label-a", "name": "feature", "color": "#ffffff"}]}),
            "priority": 2,
        }
        columns: dict[str, DatabaseField] = {name: StringDatabaseField(name=name) for name in payloads}
        columns["priority"] = IntegerDatabaseField(name="priority")
        engine = WarehouseFilterBindings(bundle, columns, source_alias="source")
        predicate = engine.predicate(
            "team_id = 'team-a' AND project_name = 'Core' AND assignee_id IS NULL AND state_type = 'unstarted' AND NOT has(label_names, 'internal') AND priority IN (1,2)"
        )
        assert predicate is not None
        query = ast.SelectQuery(
            select=[projection.select() for projection in engine.projections.values()],
            select_from=ast.JoinExpr(
                alias="source",
                table=ast.SelectQuery(
                    select=[ast.Alias(alias=name, expr=ast.Constant(value=value)) for name, value in payloads.items()]
                ),
            ),
            where=ast.And(exprs=[ast.Constant(value=True), predicate]),
            limit=ast.Constant(value=1),
        )
        self.assertEqual(
            self.execute_query(query), [("team-a", "project-a", "Core", None, "unstarted", ["feature"], 2)]
        )
