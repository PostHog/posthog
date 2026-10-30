from collections.abc import Mapping

from posthog.hogql import ast
from posthog.hogql.database.models import DatabaseField, MapStringDatabaseField
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import CloningVisitor, clone_expr

from posthog.dataclasses import frozen

from products.signals.backend.filter_catalog_schema import CatalogBundle, CatalogField, ColumnRecipe, JsonArrayMapRecipe
from products.signals.backend.filter_expression import FilterExpression, FilterValidationError


def _call(name: str, *args: ast.Expr) -> ast.Call:
    return ast.Call(name=name, args=list(args))


def _expr(template: str, **values: ast.Expr) -> ast.Expr:
    return parse_expr(template, placeholders=values)


@frozen
class _JsonValue:
    raw: ast.Expr
    missing: ast.Expr
    invalid: ast.Expr


@frozen
class FilterProjection:
    field: CatalogField
    value: ast.Expr
    is_null: ast.Expr
    invalid: ast.Expr

    @property
    def name(self) -> str:
        return self.field.name

    @property
    def type(self) -> str:
        return self.field.type

    def guard(self, expression: ast.Expr) -> ast.Expr:
        return _call(
            "if",
            clone_expr(self.invalid),
            _call(
                "throwIf", clone_expr(self.invalid), ast.Constant(value=f"signal_filter:malformed_value:{self.name}")
            ),
            expression,
        )

    def select(self) -> ast.Alias:
        """Arrays project (is_null, values), since ClickHouse cannot represent Nullable(Array)."""
        failure = _call(
            "throwIf", clone_expr(self.invalid), ast.Constant(value=f"signal_filter:malformed_value:{self.name}")
        )
        item_type = self.type[6:-1] if self.type.startswith("array<") else self.type
        conversion = {
            "string": "toString",
            "integer": "toInt",
            "number": "toFloat",
            "boolean": "toBool",
            "datetime": "toDateTime",
        }[item_type]
        failed_value: ast.Expr = _call(conversion, _call("toString", failure) if item_type == "datetime" else failure)
        if self.type.startswith("array<"):
            failed_value = ast.Array(exprs=[failed_value])
        value: ast.Expr = _call("if", clone_expr(self.invalid), failed_value, clone_expr(self.value))
        if self.type.startswith("array<"):
            value = ast.Tuple(exprs=[clone_expr(self.is_null), value])
        return ast.Alias(alias=self.name, expr=value)


class _RecipeBinder(CloningVisitor):
    def __init__(self, projections: Mapping[str, FilterProjection]) -> None:
        super().__init__()
        self.projections = projections

    def visit_field(self, node: ast.Field) -> ast.Expr:
        return clone_expr(self.projections[str(node.chain[0])].value)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        if isinstance(node.left, ast.Constant) and node.left.value is None and isinstance(node.right, ast.Field):
            node = ast.CompareOperation(
                left=node.right, right=node.left, op=node.op, is_null_comparison_style=node.is_null_comparison_style
            )
        if isinstance(node.left, ast.Field) and isinstance(node.right, ast.Constant) and node.right.value is None:
            projection = self.projections[str(node.left.chain[0])]
            if projection.type.startswith("array<"):
                missing = clone_expr(projection.is_null)
                return ast.Not(expr=missing) if node.op == ast.CompareOperationOp.NotEq else missing
        return super().visit_compare_operation(node)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        bound = super().visit_call(node)
        if node.args and isinstance(node.args[0], ast.Field):
            projection = self.projections[str(node.args[0].chain[0])]
            if projection.type.startswith("array<"):
                missing = clone_expr(projection.is_null)
                if node.name.lower() == "isnull":
                    return missing
                if node.name.lower() == "isnotnull":
                    return ast.Not(expr=missing)
                return _call("if", missing, ast.Constant(value=None), bound)
        return bound


class WarehouseFilterBindings:
    MAX_JSON_BYTES = 65536
    MAX_ARRAY_ITEMS = 256

    def __init__(self, catalog: CatalogBundle, columns: Mapping[str, DatabaseField]) -> None:
        self._fields = {field.name: field.model_copy(deep=True) for field in catalog.fields}
        self._columns = dict(columns)
        self.projections = {name: self._compile(field) for name, field in self._fields.items()}

    def predicate(self, expression: str) -> ast.Expr | None:
        """AND this predicate with scope, time and status restrictions before applying a limit."""
        validated = FilterExpression(expression, {name: field.type for name, field in self._fields.items()})
        predicate = validated.predicate()
        if predicate is None:
            return None
        bound = _RecipeBinder(self.projections).visit(predicate)
        bound = _call("ifNull", bound, ast.Constant(value=False))
        for name in sorted(validated.referenced_fields):
            bound = self.projections[name].guard(bound)
        return bound

    @staticmethod
    def _physical_type(column: DatabaseField) -> str | None:
        if isinstance(column, MapStringDatabaseField):
            return None
        value = column.get_constant_type()
        if isinstance(value, ast.StringArrayType):
            return "array<string>"
        if isinstance(value, ast.ArrayType):
            item = WarehouseFilterBindings._constant_type(value.item_type)
            return f"array<{item}>" if item else None
        scalar = WarehouseFilterBindings._constant_type(value)
        return f"array<{scalar}>" if column.array and scalar else scalar

    @staticmethod
    def _constant_type(value: ast.ConstantType) -> str | None:
        for cls, name in (
            (ast.BooleanType, "boolean"),
            (ast.IntegerType, "integer"),
            (ast.FloatType, "number"),
            (ast.StringType, "string"),
            (ast.DateTimeType, "datetime"),
        ):
            if isinstance(value, cls):
                return name
        return None

    @staticmethod
    def _json_path(raw: ast.Expr, path: list[str]) -> _JsonValue:
        prefixes = [raw]
        for key in path:
            prefixes.append(_call("JSONExtractRaw", prefixes[-1], ast.Constant(value=key)))
        missing = [_expr("{raw} = '' OR toString(JSONType({raw})) = 'Null'", raw=prefix) for prefix in prefixes]
        wrong_shapes = [
            _expr("NOT {missing} AND toString(JSONType({raw})) != 'Object'", missing=missing[index], raw=prefix)
            for index, prefix in enumerate(prefixes[:-1])
        ]
        return _JsonValue(
            raw=prefixes[-1],
            missing=ast.Or(exprs=missing),
            invalid=ast.Or(exprs=[_expr("NOT isValidJSON({raw})", raw=raw), *wrong_shapes]),
        )

    @staticmethod
    def _scalar(raw: ast.Expr, field_type: str) -> _JsonValue:
        json_type = _call("toString", _call("JSONType", raw))
        allowed = {
            "string": ["String"],
            "integer": ["Int64", "UInt64"],
            "number": ["Int64", "UInt64", "Double"],
            "boolean": ["Bool"],
            "datetime": ["String"],
        }[field_type]
        wrong_type = _expr(
            "{type} NOT IN {allowed}",
            type=json_type,
            allowed=ast.Tuple(exprs=[ast.Constant(value=item) for item in allowed]),
        )
        if field_type in {"string", "datetime"}:
            value: ast.Expr = _call("JSONExtractString", raw)
            if field_type == "datetime":
                value = _call("parseDateTimeBestEffort", value)
        elif field_type == "boolean":
            value = _call("JSONExtractBool", raw)
        else:
            value = _call(
                "accurateCastOrNull", raw, ast.Constant(value="Int64" if field_type == "integer" else "Float64")
            )
        invalid = _expr("{wrong} OR isNull({value})", wrong=wrong_type, value=value)
        if field_type == "number":
            invalid = _expr("{invalid} OR NOT isFinite(ifNull({value}, 0))", invalid=invalid, value=value)
        return _JsonValue(raw=value, missing=ast.Constant(value=False), invalid=invalid)

    def _compile(self, field: CatalogField) -> FilterProjection:
        recipe = field.binding
        column = self._columns.get(recipe.column)
        if column is None:
            raise FilterValidationError(
                "missing_column", f"Catalog field {field.name} requires column {recipe.column}."
            )
        physical = self._physical_type(column)
        value: ast.Expr = ast.Field(chain=[recipe.column])
        if isinstance(recipe, ColumnRecipe):
            return self._column_projection(field, value, physical)
        if physical != "string":
            raise FilterValidationError("column_type", f"JSON recipe {field.name} requires a JSON string column.")
        raw = _call("ifNull", value, ast.Constant(value="null"))
        path = recipe.array_path if isinstance(recipe, JsonArrayMapRecipe) else recipe.path
        extracted = self._json_path(raw, path)
        invalid = _expr(
            "{invalid} OR length({raw}) > {limit}",
            invalid=extracted.invalid,
            raw=raw,
            limit=ast.Constant(value=self.MAX_JSON_BYTES),
        )
        if field.type.startswith("array<"):
            items = _call("JSONExtractArrayRaw", extracted.raw)
            json_item = self._json_path(
                ast.Field(chain=["_filter_item"]), recipe.value_path if isinstance(recipe, JsonArrayMapRecipe) else []
            )
            scalar = self._scalar(json_item.raw, field.type[6:-1])
            bad_item = ast.Or(exprs=[json_item.missing, json_item.invalid, scalar.invalid])
            invalid = _expr(
                "{invalid} OR (NOT {missing} AND toString(JSONType({raw})) != 'Array') OR length({items}) > {limit} OR arrayExists({bad}, {items})",
                invalid=invalid,
                missing=extracted.missing,
                raw=extracted.raw,
                items=items,
                limit=ast.Constant(value=self.MAX_ARRAY_ITEMS),
                bad=ast.Lambda(args=["_filter_item"], expr=bad_item),
            )
            value = _call("arrayMap", ast.Lambda(args=["_filter_item"], expr=_call("assumeNotNull", scalar.raw)), items)
        else:
            scalar = self._scalar(extracted.raw, field.type)
            invalid = _expr(
                "{invalid} OR (NOT {missing} AND {bad})", invalid=invalid, missing=extracted.missing, bad=scalar.invalid
            )
            value = _call("if", extracted.missing, ast.Constant(value=None), scalar.raw)
        missing = extracted.missing if field.missing_value == "null" else ast.Constant(value=False)
        return FilterProjection(field=field, value=value, is_null=missing, invalid=invalid)

    def _column_projection(self, field: CatalogField, value: ast.Expr, physical: str | None) -> FilterProjection:
        if physical != field.type and not (physical == "integer" and field.type == "number"):
            raise FilterValidationError(
                "column_type", f"Column {field.binding.column} is incompatible with {field.type}."
            )
        missing: ast.Expr = _call("isNull", value)
        invalid: ast.Expr = ast.Constant(value=False)
        if field.type == "integer":
            converted = _call("accurateCastOrNull", value, ast.Constant(value="Int64"))
            invalid = _expr("NOT {missing} AND isNull({value})", missing=missing, value=converted)
            value = converted
        if field.type == "number":
            invalid = _expr("NOT isFinite(ifNull({value}, 0))", value=value)
        if field.type.startswith("array<"):
            item: ast.Expr = ast.Field(chain=["_filter_item"])
            bad_item: ast.Expr = _call("isNull", item)
            if field.type == "array<integer>":
                converted = _call("accurateCastOrNull", item, ast.Constant(value="Int64"))
                bad_item = _call("isNull", converted)
                value = _call(
                    "arrayMap", ast.Lambda(args=["_filter_item"], expr=_call("assumeNotNull", converted)), value
                )
            elif field.type == "array<number>":
                bad_item = _expr("isNull({item}) OR NOT isFinite({item})", item=item)
            invalid = _expr(
                "length({value}) > {limit} OR arrayExists({bad}, {value})",
                value=ast.Field(chain=[field.binding.column]),
                limit=ast.Constant(value=self.MAX_ARRAY_ITEMS),
                bad=ast.Lambda(args=["_filter_item"], expr=bad_item),
            )
        if field.missing_value == "empty_array":
            value = _call("ifNull", value, ast.Array(exprs=[]))
            missing = ast.Constant(value=False)
        return FilterProjection(field=field, value=value, is_null=missing, invalid=invalid)
