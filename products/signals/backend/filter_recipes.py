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
    invalid: ast.Expr

    def error(self) -> ast.Expr:
        return _call(
            "throwIf", clone_expr(self.invalid), ast.Constant(value=f"signal_filter:malformed_value:{self.field.name}")
        )

    def select(self) -> ast.Alias:
        failure: ast.Expr = _call("toInt" if self.field.type == "integer" else "toString", self.error())
        if self.field.type == "array<string>":
            failure = ast.Array(exprs=[failure])
        return ast.Alias(
            alias=self.field.name, expr=_call("if", clone_expr(self.invalid), failure, clone_expr(self.value))
        )


class _RecipeBinder(CloningVisitor):
    def __init__(self, projections: Mapping[str, FilterProjection]) -> None:
        super().__init__()
        self.projections = projections

    def visit_field(self, node: ast.Field) -> ast.Expr:
        return clone_expr(self.projections[str(node.chain[0])].value)


class WarehouseFilterBindings:
    MAX_JSON_BYTES = 65536
    MAX_ARRAY_ITEMS = 256

    def __init__(self, catalog: CatalogBundle, columns: Mapping[str, DatabaseField], *, source_alias: str) -> None:
        self._fields = {field.name: field.model_copy(deep=True) for field in catalog.fields}
        FilterExpression("", {name: field.type for name, field in self._fields.items()})
        for field in self._fields.values():
            expected = "empty_array" if field.type == "array<string>" else "null"
            if field.missing_value != expected:
                raise FilterValidationError(
                    "unsupported_missing_value", f"Catalog field {field.name} requires missing_value={expected}."
                )
        self._columns = dict(columns)
        self._source_alias = source_alias
        self.projections = {name: self._compile(field) for name, field in self._fields.items()}

    def predicate(self, expression: str) -> ast.Expr | None:
        """AND this predicate with scope, time and status restrictions before applying a limit."""
        validated = FilterExpression(expression, {name: field.type for name, field in self._fields.items()})
        predicate = validated.predicate()
        if predicate is None:
            return None
        bound = _call("ifNull", _RecipeBinder(self.projections).visit(predicate), ast.Constant(value=False))
        guards = [
            expr
            for name in sorted(validated.referenced_fields)
            for expr in (clone_expr(self.projections[name].invalid), self.projections[name].error())
        ]
        return _call("multiIf", *guards, bound) if guards else bound

    @staticmethod
    def _physical_type(column: DatabaseField) -> str | None:
        if isinstance(column, MapStringDatabaseField):
            return None
        value = column.get_constant_type()
        if isinstance(value, ast.StringArrayType) or (
            isinstance(value, ast.ArrayType) and isinstance(value.item_type, ast.StringType)
        ):
            return "array<string>"
        if isinstance(value, ast.StringType):
            return "array<string>" if column.array else "string"
        if isinstance(value, ast.IntegerType) and not column.array:
            return "integer"
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
        allowed = ["String"] if field_type == "string" else ["Int64", "UInt64"]
        wrong_type = _expr(
            "toString(JSONType({raw})) NOT IN {allowed}",
            raw=raw,
            allowed=ast.Tuple(exprs=[ast.Constant(value=item) for item in allowed]),
        )
        value = (
            _call("JSONExtractString", raw)
            if field_type == "string"
            else _call("accurateCastOrNull", _call("JSONExtractRaw", raw), ast.Constant(value="Int64"))
        )
        return _JsonValue(
            raw=value,
            missing=ast.Constant(value=False),
            invalid=_expr("{wrong} OR isNull({value})", wrong=wrong_type, value=value),
        )

    def _compile(self, field: CatalogField) -> FilterProjection:
        recipe = field.binding
        column = self._columns.get(recipe.column)
        if column is None:
            raise FilterValidationError(
                "missing_column", f"Catalog field {field.name} requires column {recipe.column}."
            )
        physical = self._physical_type(column)
        value: ast.Expr = ast.Field(chain=[self._source_alias, recipe.column])
        if isinstance(recipe, ColumnRecipe):
            if physical != field.type:
                raise FilterValidationError("column_type", f"Column {recipe.column} is incompatible with {field.type}.")
            invalid: ast.Expr = ast.Constant(value=False)
            if field.type == "integer":
                converted = _call("accurateCastOrNull", value, ast.Constant(value="Int64"))
                invalid = _expr("NOT isNull({original}) AND isNull({converted})", original=value, converted=converted)
                value = converted
            elif field.type == "array<string>":
                oversized = _expr(
                    "length({value}) > {limit}", value=value, limit=ast.Constant(value=self.MAX_ARRAY_ITEMS)
                )
                value = _call("if", oversized, ast.Array(exprs=[]), value)
                invalid = _expr("{oversized} OR arrayExists(x -> isNull(x), {value})", oversized=oversized, value=value)
            return FilterProjection(field=field, value=value, invalid=invalid)
        if physical != "string":
            raise FilterValidationError("column_type", f"JSON recipe {field.name} requires a JSON string column.")
        raw = _call("ifNull", value, ast.Constant(value="null"))
        oversized = _expr("length({raw}) > {limit}", raw=raw, limit=ast.Constant(value=self.MAX_JSON_BYTES))
        bounded = _call("if", oversized, ast.Constant(value="null"), raw)
        path = recipe.array_path if isinstance(recipe, JsonArrayMapRecipe) else recipe.path
        extracted = self._json_path(bounded, path)
        invalid = ast.Or(exprs=[oversized, extracted.invalid])
        if field.type == "array<string>":
            items = _call("JSONExtractArrayRaw", extracted.raw)
            too_many = _expr("length({items}) > {limit}", items=items, limit=ast.Constant(value=self.MAX_ARRAY_ITEMS))
            items = _call("if", too_many, ast.Array(exprs=[]), items)
            item = self._json_path(
                ast.Field(chain=["_filter_item"]), recipe.value_path if isinstance(recipe, JsonArrayMapRecipe) else []
            )
            scalar = self._scalar(item.raw, "string")
            invalid = _expr(
                "{invalid} OR (NOT {missing} AND toString(JSONType({raw})) != 'Array') OR {too_many} OR arrayExists({bad}, {items})",
                invalid=invalid,
                missing=extracted.missing,
                raw=extracted.raw,
                too_many=too_many,
                items=items,
                bad=ast.Lambda(args=["_filter_item"], expr=ast.Or(exprs=[item.missing, item.invalid, scalar.invalid])),
            )
            value = _call("arrayMap", ast.Lambda(args=["_filter_item"], expr=scalar.raw), items)
        else:
            scalar = self._scalar(extracted.raw, field.type)
            invalid = _expr(
                "{invalid} OR (NOT {missing} AND {bad})", invalid=invalid, missing=extracted.missing, bad=scalar.invalid
            )
            value = _call("if", extracted.missing, ast.Constant(value=None), scalar.raw)
        return FilterProjection(field=field, value=value, invalid=invalid)
