import json
from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    FloatArrayDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
)
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute
from posthog.errors import InternalCHQueryError
from posthog.models import Team

from products.signals.backend.filter_catalog_schema import CatalogBundle, JsonPathRecipe
from products.signals.backend.filter_expression import FilterValidationError
from products.signals.backend.filter_recipes import WarehouseFilterBindings


def catalog_bundle(field_type: str = "string", kind: str = "json_path", missing: str = "null") -> CatalogBundle:
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
                    "missing_value": missing,
                    "malformed_value": "error",
                }
            ],
            "starter_expressions": [],
        }
    )


def bindings(field_type: str = "string", kind: str = "json_path", missing: str = "null") -> WarehouseFilterBindings:
    column: DatabaseField = (
        IntegerDatabaseField(name="payload")
        if kind == "column" and field_type == "integer"
        else StringDatabaseField(name="payload")
    )
    return WarehouseFilterBindings(catalog_bundle(field_type, kind, missing), {"payload": column})


class TestFilterRecipeValidation(SimpleTestCase):
    def test_rejects_incompatible_columns_before_querying(self) -> None:
        bundle = catalog_bundle()
        with self.assertRaises(FilterValidationError) as raised:
            WarehouseFilterBindings(bundle, {})
        self.assertEqual(raised.exception.code, "missing_column")
        with self.assertRaises(FilterValidationError) as raised:
            WarehouseFilterBindings(bundle, {"payload": IntegerDatabaseField(name="payload")})
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
                table=ast.SelectQuery(select=[ast.Alias(alias="payload", expr=ast.Constant(value=payload))])
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
        return sync_execute(sql, context.values, flush=False)

    @parameterized.expand(
        [
            ("string", '{"value":"Core"}', "Core"),
            ("integer", '{"value":0}', 0),
            ("integer", '{"value":-2}', -2),
            ("number", '{"value":1.25}', 1.25),
            ("boolean", '{"value":false}', False),
            ("datetime", '{"value":"2026-01-02T03:04:05Z"}', datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("string", "{}", None),
            ("string", '{"value":null}', None),
            ("string", "null", None),
            ("string", " null ", None),
            ("string", None, None),
            (
                "string",
                '{"value":"Core"}',
                1,
                "startsWith(lower(value), 'co') AND endsWith(upper(value), 'RE') AND notEmpty(value)",
            ),
            ("boolean", '{"value":true}', 1, "value"),
            ("datetime", '{"value":"2026-01-02T03:04:05Z"}', 1, "value >= toDateTime('2026-01-02T00:00:00Z')"),
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
            ("number", '{"value":"no"}'),
            ("number", '{"value":1e999}'),
            ("boolean", '{"value":1}'),
            ("datetime", '{"value":"invalid"}'),
        ]
    )
    def test_malformed_values_surface_errors(self, field_type: str, payload: str) -> None:
        engine = bindings(field_type)
        self.assert_malformed(engine, payload)
        self.assert_malformed(engine, payload, "true OR isNull(value)")

    @parameterized.expand(
        [
            ('{"nodes":[{"name":"internal"},{"name":"feature"}]}', (False, ["internal", "feature"])),
            ('{"nodes":[]}', (False, [])),
            ("{}", (False, [])),
            ("null", (False, [])),
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

    def test_null_arrays_and_nullable_predicates(self) -> None:
        engine = bindings("array<string>", "json_array_map")
        self.assertEqual(self.execute(engine, "{}"), (True, []))
        self.assertEqual(self.execute(engine, "{}", "isNull(value)"), 1)
        self.assertEqual(self.execute(engine, "{}", "value IS NOT NULL"), 0)
        self.assertEqual(self.execute(engine, "{}", "NULL = value"), 1)
        self.assertEqual(self.execute(engine, "{}", "isNotNull(value)"), 0)
        self.assertEqual(self.execute(engine, "{}", "NOT has(value, 'internal')"), 0)
        self.assertEqual(self.execute(engine, '{"nodes":[]}', "NOT has(value, 'internal')"), 1)

    def test_json_array_and_column_recipes(self) -> None:
        self.assertEqual(self.execute(bindings("array<integer>"), '{"value":[0,1,2]}'), (False, [0, 1, 2]))
        self.assertEqual(self.execute(bindings("integer", "column"), 0, "value IN (1,2)"), 0)
        self.assertEqual(self.execute(bindings("integer", "column"), 2, "value IN (1,2)"), 1)
        self.assertEqual(self.execute(bindings("string", "column"), "literal' OR true", "value = 'other'"), 0)
        self.assertEqual(self.execute(bindings("integer", "column"), 2, "false"), 0)
        self.assertIsNone(bindings().predicate(""))

    def test_runtime_size_bounds(self) -> None:
        for payload, engine in [
            (json.dumps({"value": "x" * 65536}), bindings()),
            (json.dumps({"value": list(range(257))}), bindings("array<integer>")),
        ]:
            self.assert_malformed(engine, payload)

    @parameterized.expand(
        [
            ("array<number>", '{"value":[0,1.5]}', (False, [0.0, 1.5])),
            ("array<boolean>", '{"value":[true,false]}', (False, [True, False])),
        ]
    )
    def test_typed_json_arrays(self, field_type: str, payload: str, expected: object) -> None:
        self.assertEqual(self.execute(bindings(field_type), payload), expected)

    @parameterized.expand(
        [
            ("array<string>", StringArrayDatabaseField(name="payload"), ["a", "b"]),
            ("array<integer>", IntegerDatabaseField(name="payload", array=True), [0, 2]),
            ("array<number>", FloatArrayDatabaseField(name="payload"), [1.25, 2.5]),
            ("array<boolean>", BooleanDatabaseField(name="payload", array=True), [True, False]),
        ]
    )
    def test_native_array_columns(
        self, field_type: str, column: DatabaseField, items: list[str | int | float | bool]
    ) -> None:
        engine = WarehouseFilterBindings(catalog_bundle(field_type, "column"), {"payload": column})
        query = ast.SelectQuery(
            select=[engine.projections["value"].select()],
            select_from=ast.JoinExpr(
                table=ast.SelectQuery(
                    select=[
                        ast.Alias(alias="payload", expr=ast.Array(exprs=[ast.Constant(value=item) for item in items]))
                    ]
                )
            ),
        )
        self.assertEqual(self.execute_query(query), [((False, items),)])

    def test_native_integer_overflow_is_malformed(self) -> None:
        with self.assertRaises(InternalCHQueryError) as raised:
            self.execute(bindings("integer", "column"), 9223372036854775808)
        self.assertEqual(raised.exception.code, 395)

    def test_nested_paths_and_literal_path_keys(self) -> None:
        bundle = catalog_bundle()
        bundle.fields[0].binding = JsonPathRecipe(kind="json_path", column="payload", path=["outer", "value"])
        engine = WarehouseFilterBindings(bundle, {"payload": StringDatabaseField(name="payload")})
        self.assertIsNone(self.execute(engine, "{}"))
        self.assert_malformed(engine, '{"outer":[]}')
        key = "key'); SELECT true; --"
        bundle.fields[0].binding = JsonPathRecipe(kind="json_path", column="payload", path=[key])
        engine = WarehouseFilterBindings(bundle, {"payload": StringDatabaseField(name="payload")})
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
        engine = WarehouseFilterBindings(bundle, columns)
        predicate = engine.predicate(
            "team_id = 'team-a' AND project_name = 'Core' AND assignee_id IS NULL AND state_type = 'unstarted' AND NOT has(label_names, 'internal') AND priority IN (1,2)"
        )
        assert predicate is not None
        query = ast.SelectQuery(
            select=[projection.select() for projection in engine.projections.values()],
            select_from=ast.JoinExpr(
                table=ast.SelectQuery(
                    select=[ast.Alias(alias=name, expr=ast.Constant(value=value)) for name, value in payloads.items()]
                )
            ),
            where=ast.And(exprs=[ast.Constant(value=True), predicate]),
            limit=ast.Constant(value=1),
        )
        self.assertEqual(
            self.execute_query(query), [("team-a", "project-a", "Core", None, "unstarted", (False, ["feature"]), 2)]
        )
