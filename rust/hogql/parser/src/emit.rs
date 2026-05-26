//! The `Emitter` trait abstracts AST node construction so the parser can emit either `serde_json::Value` (via `JsonEmitter`, used by `parse_*_json` entry points + the future WASM build) or Python `posthog.hogql.ast` dataclass instances directly during parse (via `PyEmitter` in `emit_py.rs`, used by `parse_*_py`).
//!
//! Field names and shapes mirror the dataclasses at [`posthog/hogql/ast.py`]. The Python deserialiser at [`posthog/hogql/json_ast.py`] also builds these dataclasses from the JSON shape, so the two backends produce `__eq__`-equivalent objects.

use serde_json::{json, Value};
use std::borrow::Cow;

/// AST node + value constructor surface. Every construction site in the parser routes through this trait so the same parse logic can produce `serde_json::Value` (kept for WASM and tests) or Python dataclass instances directly via PyO3.
///
/// Inspection methods (`node_kind`, `get_field`, …) cover the parser's post-construction AST-surgery patterns: split-and-hoist for nested BETWEEN, AND/OR chain folding, position propagation, and concat merging. JSON impls read the underlying map directly; the Python impl uses PyO3 `getattr` against the dataclass attrs.
pub trait Emitter {
    /// AST tree handle. Cheap to clone (Json: refcount via Value::clone; Py: `Bound::clone_ref` on the underlying PyObject).
    type Value: Clone;

    // ===== Primitive value constructors =====
    /// `None`-equivalent (Json null / Py None). Sentinel for "no value" slots that the deserialiser maps to dataclass-field `None` defaults.
    fn null(&self) -> Self::Value;
    fn bool(&self, v: bool) -> Self::Value;
    fn int(&self, v: i64) -> Self::Value;
    fn string(&self, v: &str) -> Self::Value;
    /// Finite float as `Value::Number` (Json) / Python float (Py). Non-finite (NaN, ±Inf) routes through `constant_special_number` instead.
    fn float(&self, v: f64) -> Self::Value;
    /// Unsigned integer beyond i64 range. JSON emits as `Value::Number` via `u64` (preserving magnitude); Py emits as a Python int.
    fn uint(&self, v: u64) -> Self::Value;
    /// Raw map value (JSON object / Python dict) keyed by string. Used for AST fields whose JSON shape is `{key: child_node, …}` rather than a list: `window_exprs`, `ctes` (dict-form), `replace`. The deserialiser respects this via `_DICT_FIELDS`.
    fn string_keyed_map(&self, pairs: Vec<(String, Self::Value)>) -> Self::Value;
    /// Raw list value (JSON array / Python list). Distinct from the `Array(...)` AST node — used for fields whose value is a plain list, e.g. `HogQLXAttribute.children`.
    fn list_value(&self, items: Vec<Self::Value>) -> Self::Value;

    // ===== AST node builders =====
    fn constant(&self, value: Self::Value) -> Self::Value;
    /// `inf` / `-inf` / `nan` shipped as a string with `value_type: "number"`. Mirrors cpp's nlohmann::json-string encoding for non-finite floats.
    fn constant_special_number(&self, name: &'static str) -> Self::Value;
    /// Integer-literal Constant whose magnitude exceeds i64. Exact decimal or `0x…` hex digits with optional leading `-`; deserialiser rebuilds an arbitrary-precision Python int.
    fn constant_number_string(&self, text: String) -> Self::Value;
    fn field(&self, chain: Vec<Self::Value>) -> Self::Value;
    fn arith(&self, left: Self::Value, op: &str, right: Self::Value) -> Self::Value;
    fn compare(&self, left: Self::Value, op: &str, right: Self::Value) -> Self::Value;
    fn compare_is_null(&self, left: Self::Value, negated: bool) -> Self::Value;
    fn is_distinct_from(&self, left: Self::Value, right: Self::Value, negated: bool)
        -> Self::Value;
    fn between(
        &self,
        expr: Self::Value,
        low: Self::Value,
        high: Self::Value,
        negated: bool,
    ) -> Self::Value;
    fn not_(&self, expr: Self::Value) -> Self::Value;
    fn and_(&self, exprs: Vec<Self::Value>) -> Self::Value;
    fn or_(&self, exprs: Vec<Self::Value>) -> Self::Value;
    fn tuple_(&self, exprs: Vec<Self::Value>) -> Self::Value;
    fn array_(&self, exprs: Vec<Self::Value>) -> Self::Value;
    fn array_access(&self, array: Self::Value, property: Self::Value, nullish: bool)
        -> Self::Value;
    fn tuple_access(&self, tuple_: Self::Value, index: i64, nullish: bool) -> Self::Value;
    fn alias(&self, expr: Self::Value, name: &str) -> Self::Value;
    fn call(&self, name: &str, args: Vec<Self::Value>) -> Self::Value;
    #[allow(clippy::too_many_arguments)]
    fn call_full(
        &self,
        name: &str,
        params: Option<Vec<Self::Value>>,
        args: Vec<Self::Value>,
        distinct: bool,
        order_by: Option<Vec<Self::Value>>,
        filter_expr: Option<Self::Value>,
        within_group: Option<Vec<Self::Value>>,
    ) -> Self::Value;
    fn lambda(&self, args: Vec<String>, expr: Self::Value) -> Self::Value;
    /// `ExprCall(expr, args)` — call where the head is an arbitrary expression rather than a function name. Emitted by `ColumnExprCall` (always) and `ColumnExprCallSelect` (when LHS isn't a single-element Field chain).
    fn expr_call(&self, expr: Self::Value, args: Vec<Self::Value>) -> Self::Value;
    fn type_cast(&self, expr: Self::Value, type_name: &str) -> Self::Value;
    fn try_cast(&self, expr: Self::Value, type_name: &str) -> Self::Value;
    fn array_slice(
        &self,
        array: Self::Value,
        start: Option<Self::Value>,
        end: Option<Self::Value>,
    ) -> Self::Value;
    fn dict_(&self, items: Vec<(Self::Value, Self::Value)>) -> Self::Value;
    fn placeholder(&self, expr: Self::Value) -> Self::Value;
    fn named_argument(&self, name: &str, value: Self::Value) -> Self::Value;
    /// `e IGNORE NULLS` is dropped by the C++ visitor — the expression returns as-is. Kept as a named helper to leave room for richer behaviour later.
    fn ignore_nulls(&self, expr: Self::Value) -> Self::Value {
        expr
    }
    fn order_expr(
        &self,
        expr: Self::Value,
        order: &str,
        with_fill: Option<Self::Value>,
    ) -> Self::Value;
    fn columns_expr(
        &self,
        regex: Option<String>,
        columns: Option<Vec<Self::Value>>,
        all_columns: bool,
        exclude: Option<Vec<String>>,
        replace: Option<Vec<(String, Self::Value)>>,
    ) -> Self::Value;
    fn spread_expr(&self, expr: Self::Value) -> Self::Value;
    /// `{positional_ref: index}` — the `$N` form inside Hog blocks. Mirrors cpp's `PositionalRef` node.
    fn positional_ref(&self, index: i64) -> Self::Value;

    /// `Program(declarations)`.
    fn program(&self, declarations: Vec<Self::Value>) -> Self::Value;
    /// `Block(declarations)`.
    fn block(&self, declarations: Vec<Self::Value>) -> Self::Value;
    /// `ExprStatement(expr)`.
    fn expr_statement(&self, expr: Self::Value) -> Self::Value;
    /// `IfStatement(expr, then, else_)`.
    fn if_statement(&self, cond: Self::Value, then: Self::Value, else_: Self::Value)
        -> Self::Value;
    /// `WhileStatement(expr, body)`.
    fn while_statement(&self, cond: Self::Value, body: Self::Value) -> Self::Value;
    /// `ForInStatement(keyVar, valueVar, expr, body)`.
    fn for_in_statement(
        &self,
        key_var: Self::Value,
        value_var: Self::Value,
        expr: Self::Value,
        body: Self::Value,
    ) -> Self::Value;
    /// `ForStatement(initializer, condition, increment, body)`.
    fn for_statement(
        &self,
        initializer: Self::Value,
        condition: Self::Value,
        increment: Self::Value,
        body: Self::Value,
    ) -> Self::Value;
    /// `Function(name, params, body)`.
    fn function_(&self, name: &str, params: Vec<Self::Value>, body: Self::Value) -> Self::Value;
    /// `VariableAssignment(left, right)`.
    fn variable_assignment(&self, left: Self::Value, right: Self::Value) -> Self::Value;
    /// `ReturnStatement(expr)`. `expr` may be null for `return;`.
    fn return_statement(&self, expr: Self::Value) -> Self::Value;
    /// `TryCatchStatement(try_stmt, catches, finally_stmt)`. Each catch is itself a `[var, type, body]` tuple — encoded as a list value.
    fn try_catch_statement(
        &self,
        try_stmt: Self::Value,
        catches: Vec<Self::Value>,
        finally_stmt: Self::Value,
    ) -> Self::Value;
    /// `ThrowStatement(expr)`.
    fn throw_statement(&self, expr: Self::Value) -> Self::Value;
    /// `VariableDeclaration(name, expr)`.
    fn variable_declaration(&self, name: &str, expr: Self::Value) -> Self::Value;
    /// One element of a `try_catch` `catches` list: `[var, type, body]` — array of three values matching cpp's nlohmann::json shape.
    fn catch_clause(&self, var: Self::Value, ty: Self::Value, body: Self::Value) -> Self::Value;

    // ===== Query / clause builders =====
    /// `CTE(name, expr, cte_type)`. `cte_type` is "column" / "subquery".
    fn cte(&self, name: &str, expr: Self::Value, cte_type: &str) -> Self::Value;
    /// Subquery CTE with optional columns/using_key/materialized flags.
    fn cte_subquery(
        &self,
        name: &str,
        expr: Self::Value,
        columns: Option<Vec<String>>,
        using_key: Option<Vec<String>>,
        materialized: Option<bool>,
    ) -> Self::Value;
    /// `JoinConstraint(expr, constraint_type)`. constraint_type is "ON"/"USING".
    fn join_constraint(&self, expr: Self::Value, constraint_type: &str) -> Self::Value;
    /// `ValuesQuery(rows)`.
    fn values_query(&self, rows: Vec<Self::Value>) -> Self::Value;
    /// `PivotColumn(column, values)`.
    fn pivot_column(&self, column: Self::Value, values: Vec<Self::Value>) -> Self::Value;
    /// `UnpivotColumn(value_columns, name_columns, unpivot_values)`.
    fn unpivot_column(
        &self,
        value_columns: Self::Value,
        name_columns: Self::Value,
        unpivot_values: Vec<Self::Value>,
    ) -> Self::Value;
    /// `GroupingSet(exprs)`.
    fn grouping_set(&self, exprs: Vec<Self::Value>) -> Self::Value;
    /// `HogQLXTag(kind, attributes)`.
    fn hogqlx_tag(&self, kind: &str, attributes: Vec<Self::Value>) -> Self::Value;
    /// `HogQLXAttribute(name, value)`.
    fn hogqlx_attribute(&self, name: &str, value: Self::Value) -> Self::Value;
    /// `SelectSetQuery(initial_select_query, subsequent_select_queries)`.
    fn select_set_query(&self, initial: Self::Value, subsequent: Vec<Self::Value>) -> Self::Value;
    /// Empty `WindowExpr` shell — caller adds fields via `set_field`.
    fn window_expr_empty(&self) -> Self::Value;
    /// `WindowFrameExpr(frame_type, frame_value)`. `frame_value` may be null (CURRENT ROW / UNBOUNDED forms) or a Constant / expr.
    fn window_frame_bound(&self, frame_type: &str, frame_value: Self::Value) -> Self::Value;
    /// `InterpolateExpr(expr, value?)`.
    fn interpolate_expr(&self, expr: Self::Value, value: Option<Self::Value>) -> Self::Value;
    /// `LimitByExpr(n, exprs, offset_value?)`.
    fn limit_by_expr(
        &self,
        n: Self::Value,
        exprs: Vec<Self::Value>,
        offset_value: Option<Self::Value>,
    ) -> Self::Value;
    /// Empty `SelectQuery` shell — caller adds fields via `set_field`. Used by the SELECT-clause builder; surfacing every optional field as a constructor argument would balloon the trait method count.
    fn select_query_empty(&self) -> Self::Value;
    /// `SelectSetNode(select_query, set_operator)`. Used inside `SelectSetQuery.subsequent_select_queries`.
    fn select_set_node(&self, select_query: Self::Value, set_operator: Option<&str>)
        -> Self::Value;
    /// `SampleExpr(sample_value, offset_value?)`.
    fn sample_expr(
        &self,
        sample_value: Self::Value,
        offset_value: Option<Self::Value>,
    ) -> Self::Value;
    /// `RatioExpr(left, right?)`.
    fn ratio_expr(&self, left: Self::Value, right: Option<Self::Value>) -> Self::Value;
    /// `PivotExpr(table, aggregates, columns, group_by?)`.
    fn pivot_expr(
        &self,
        table: Self::Value,
        aggregates: Vec<Self::Value>,
        columns: Vec<Self::Value>,
        group_by: Option<Vec<Self::Value>>,
    ) -> Self::Value;
    /// `UnpivotExpr(table, columns, include_nulls)`.
    fn unpivot_expr(
        &self,
        table: Self::Value,
        columns: Vec<Self::Value>,
        include_nulls: bool,
    ) -> Self::Value;
    /// `JoinExpr(table, alias?, table_args?, column_aliases?, table_final?, sample?)`.
    fn join_expr(
        &self,
        table: Self::Value,
        alias: Option<String>,
        table_args: Option<Self::Value>,
        column_aliases: Option<Vec<String>>,
        table_final: bool,
        sample: Option<Self::Value>,
    ) -> Self::Value;
    /// `WindowFunction(name, exprs, args, over_expr, over_identifier)`. `over_expr` and `over_identifier` are alternatives — only one is set per node. `args` defaults to empty list (NOT None) so the deserialiser's `__eq__` distinguishes from non-window calls.
    fn window_function(
        &self,
        name: &str,
        exprs: Vec<Self::Value>,
        args: Vec<Self::Value>,
        over_expr: Option<Self::Value>,
        over_identifier: Option<String>,
    ) -> Self::Value;
    /// `WithFillExpr(from_value?, to_value?, step_value?)`.
    fn with_fill_expr(
        &self,
        from_value: Option<Self::Value>,
        to_value: Option<Self::Value>,
        step_value: Option<Self::Value>,
    ) -> Self::Value;

    // ===== Position machinery =====
    /// `{line, column, offset}` per cpp's visitor — line is 1-based, column is 0-based, offset is the character position.
    fn position(&self, line: u32, column: u32, offset: usize) -> Self::Value;
    /// Inject `start` / `end` position objects. Idempotent: if `start` is already set (or explicitly null-poisoned by `no_pos`), existing values are kept — this is how cpp's paren wrap `(expr)` preserves the inner expression's positions.
    fn with_pos(&self, value: Self::Value, start: Self::Value, end: Self::Value) -> Self::Value;
    /// Mark a node as position-less so downstream `with_pos` calls leave it bare. Mirrors cpp visitors that emit a node without `addPositionInfo(json, ctx)` — Python AST shows dataclass defaults (None). Example: `NamedArgument`.
    fn no_pos(&self, value: Self::Value) -> Self::Value;
    /// Override existing `start` / `end` keys, unlike the idempotent `with_pos`. Used when the outer span needs to include tokens the inner expression's wrap didn't see.
    fn replace_pos(&self, value: Self::Value, start: Self::Value, end: Self::Value) -> Self::Value;

    // ===== Inspection =====
    /// Get the AST node kind ("Constant", "ArithmeticOperation", …) or `None` for non-node values (primitives, lists, positions).
    fn node_kind<'a>(&self, v: &'a Self::Value) -> Option<Cow<'a, str>>;
    /// Get a named field value. Returns `None` if the field is missing or the value isn't a node. Returned value is owned (cloned).
    fn get_field(&self, v: &Self::Value, name: &str) -> Option<Self::Value>;
    /// True if the field is present at all (even if its value is null). Distinguishes "field not set" from "field explicitly null" — the `no_pos` + `with_pos` idempotency relies on this.
    fn has_field(&self, v: &Self::Value, name: &str) -> bool;
    /// `Value::is_null` analogue.
    fn is_null(&self, v: &Self::Value) -> bool;
    /// Extract a string body if `v` is a string value.
    fn as_str<'a>(&self, v: &'a Self::Value) -> Option<Cow<'a, str>>;
    /// Extract the list elements if `v` is a list/array value.
    fn as_list(&self, v: &Self::Value) -> Option<Vec<Self::Value>>;
    /// Extract a boolean if `v` is a boolean value.
    fn as_bool(&self, v: &Self::Value) -> Option<bool>;
    /// Extract an `i64` if `v` is an integer value.
    fn as_i64(&self, v: &Self::Value) -> Option<i64>;

    // ===== Mutation =====
    /// Remove a named field from a node, returning the previous value (or None when absent). Used to drop sentinel keys before the node leaves the parser, e.g. `__rust_offset_liftable`.
    fn remove_field(&self, v: &mut Self::Value, name: &str) -> Option<Self::Value>;
    /// Set / overwrite a named field on a node. Used by AST-surgery sites that copy a node and tweak one field — primarily BETWEEN-split recursion, merge-select-decorators, and CTE injection. JSON inserts into the underlying `Map`; Py calls `obj.setattr(name, value)`.
    fn set_field(&self, v: &mut Self::Value, name: &str, value: Self::Value);
}

// ============================================================================
// JsonEmitter — `serde_json::Value` impl, mirrors the previous free `emit::xxx` functions. Used by `parse_*_json` entry points and the future WASM build.
// ============================================================================

#[derive(Default, Clone, Copy)]
pub struct JsonEmitter;

impl Emitter for JsonEmitter {
    type Value = Value;

    fn null(&self) -> Value {
        Value::Null
    }
    fn bool(&self, v: bool) -> Value {
        Value::Bool(v)
    }
    fn int(&self, v: i64) -> Value {
        Value::Number(v.into())
    }
    fn string(&self, v: &str) -> Value {
        Value::String(v.into())
    }
    fn float(&self, v: f64) -> Value {
        serde_json::Number::from_f64(v)
            .map(Value::Number)
            .unwrap_or(Value::Null)
    }
    fn uint(&self, v: u64) -> Value {
        Value::Number(v.into())
    }
    fn list_value(&self, items: Vec<Value>) -> Value {
        Value::Array(items)
    }
    fn string_keyed_map(&self, pairs: Vec<(String, Value)>) -> Value {
        let mut obj = serde_json::Map::new();
        for (k, v) in pairs {
            obj.insert(k, v);
        }
        Value::Object(obj)
    }

    fn constant(&self, value: Value) -> Value {
        json!({"node": "Constant", "value": value})
    }
    fn constant_special_number(&self, name: &'static str) -> Value {
        json!({"node": "Constant", "value": name, "value_type": "number"})
    }
    fn constant_number_string(&self, text: String) -> Value {
        json!({"node": "Constant", "value": text, "value_type": "number"})
    }
    fn field(&self, chain: Vec<Value>) -> Value {
        json!({"node": "Field", "chain": chain})
    }
    fn arith(&self, left: Value, op: &str, right: Value) -> Value {
        json!({"node": "ArithmeticOperation", "left": left, "right": right, "op": op})
    }
    fn compare(&self, left: Value, op: &str, right: Value) -> Value {
        json!({"node": "CompareOperation", "left": left, "right": right, "op": op})
    }
    fn compare_is_null(&self, left: Value, negated: bool) -> Value {
        json!({
            "node": "CompareOperation",
            "left": left,
            "right": json!({"node": "Constant", "value": Value::Null}),
            "op": if negated { "!=" } else { "==" },
            "is_null_comparison_style": true,
        })
    }
    fn is_distinct_from(&self, left: Value, right: Value, negated: bool) -> Value {
        json!({"node": "IsDistinctFrom", "left": left, "right": right, "negated": negated})
    }
    fn between(&self, expr: Value, low: Value, high: Value, negated: bool) -> Value {
        json!({"node": "BetweenExpr", "expr": expr, "low": low, "high": high, "negated": negated})
    }
    fn not_(&self, expr: Value) -> Value {
        json!({"node": "Not", "expr": expr})
    }
    fn and_(&self, exprs: Vec<Value>) -> Value {
        json!({"node": "And", "exprs": exprs})
    }
    fn or_(&self, exprs: Vec<Value>) -> Value {
        json!({"node": "Or", "exprs": exprs})
    }
    fn tuple_(&self, exprs: Vec<Value>) -> Value {
        json!({"node": "Tuple", "exprs": exprs})
    }
    fn array_(&self, exprs: Vec<Value>) -> Value {
        json!({"node": "Array", "exprs": exprs})
    }
    fn array_access(&self, array: Value, property: Value, nullish: bool) -> Value {
        if nullish {
            json!({"node": "ArrayAccess", "array": array, "property": property, "nullish": true})
        } else {
            json!({"node": "ArrayAccess", "array": array, "property": property})
        }
    }
    fn tuple_access(&self, tuple_: Value, index: i64, nullish: bool) -> Value {
        if nullish {
            json!({"node": "TupleAccess", "tuple": tuple_, "index": index, "nullish": true})
        } else {
            json!({"node": "TupleAccess", "tuple": tuple_, "index": index})
        }
    }
    fn alias(&self, expr: Value, name: &str) -> Value {
        json!({"node": "Alias", "expr": expr, "alias": name})
    }
    fn call(&self, name: &str, args: Vec<Value>) -> Value {
        json!({"node": "Call", "name": name, "args": args})
    }
    fn call_full(
        &self,
        name: &str,
        params: Option<Vec<Value>>,
        args: Vec<Value>,
        distinct: bool,
        order_by: Option<Vec<Value>>,
        filter_expr: Option<Value>,
        within_group: Option<Vec<Value>>,
    ) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("Call".into()));
        obj.insert("name".into(), Value::String(name.into()));
        obj.insert("args".into(), Value::Array(args));
        if let Some(p) = params {
            obj.insert("params".into(), Value::Array(p));
        }
        if distinct {
            obj.insert("distinct".into(), Value::Bool(true));
        }
        if let Some(ob) = order_by {
            obj.insert("order_by".into(), Value::Array(ob));
        }
        if let Some(fe) = filter_expr {
            obj.insert("filter_expr".into(), fe);
        }
        if let Some(wg) = within_group {
            obj.insert("within_group".into(), Value::Array(wg));
        }
        Value::Object(obj)
    }
    fn lambda(&self, args: Vec<String>, expr: Value) -> Value {
        let args_json: Vec<Value> = args.into_iter().map(Value::String).collect();
        json!({"node": "Lambda", "args": args_json, "expr": expr})
    }
    fn expr_call(&self, expr: Value, args: Vec<Value>) -> Value {
        json!({"node": "ExprCall", "expr": expr, "args": args})
    }
    fn type_cast(&self, expr: Value, type_name: &str) -> Value {
        json!({"node": "TypeCast", "expr": expr, "type_name": type_name})
    }
    fn try_cast(&self, expr: Value, type_name: &str) -> Value {
        json!({"node": "TryCast", "expr": expr, "type_name": type_name})
    }
    fn array_slice(&self, array: Value, start: Option<Value>, end: Option<Value>) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("ArraySlice".into()));
        obj.insert("array".into(), array);
        if let Some(s) = start {
            obj.insert("start_expr".into(), s);
        }
        if let Some(e) = end {
            obj.insert("end_expr".into(), e);
        }
        Value::Object(obj)
    }
    fn dict_(&self, items: Vec<(Value, Value)>) -> Value {
        let items_json: Vec<Value> = items
            .into_iter()
            .map(|(k, v)| Value::Array(vec![k, v]))
            .collect();
        json!({"node": "Dict", "items": items_json})
    }
    fn placeholder(&self, expr: Value) -> Value {
        json!({"node": "Placeholder", "expr": expr})
    }
    fn named_argument(&self, name: &str, value: Value) -> Value {
        self.no_pos(json!({"node": "NamedArgument", "name": name, "value": value}))
    }
    fn order_expr(&self, expr: Value, order: &str, with_fill: Option<Value>) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("OrderExpr".into()));
        obj.insert("expr".into(), expr);
        obj.insert("order".into(), Value::String(order.into()));
        if let Some(wf) = with_fill {
            obj.insert("with_fill".into(), wf);
        }
        Value::Object(obj)
    }
    fn columns_expr(
        &self,
        regex: Option<String>,
        columns: Option<Vec<Value>>,
        all_columns: bool,
        exclude: Option<Vec<String>>,
        replace: Option<Vec<(String, Value)>>,
    ) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("ColumnsExpr".into()));
        if let Some(r) = regex {
            obj.insert("regex".into(), Value::String(r));
        }
        if let Some(c) = columns {
            obj.insert("columns".into(), Value::Array(c));
        }
        if all_columns {
            obj.insert("all_columns".into(), Value::Bool(true));
        }
        if let Some(e) = exclude {
            obj.insert(
                "exclude".into(),
                Value::Array(e.into_iter().map(Value::String).collect()),
            );
        }
        if let Some(r) = replace {
            let mut m = serde_json::Map::new();
            for (k, v) in r {
                m.insert(k, v);
            }
            obj.insert("replace".into(), Value::Object(m));
        }
        Value::Object(obj)
    }
    fn spread_expr(&self, expr: Value) -> Value {
        json!({"node": "SpreadExpr", "expr": expr})
    }
    fn positional_ref(&self, index: i64) -> Value {
        json!({"node": "PositionalRef", "index": index})
    }

    fn program(&self, declarations: Vec<Value>) -> Value {
        json!({"node": "Program", "declarations": declarations})
    }
    fn block(&self, declarations: Vec<Value>) -> Value {
        json!({"node": "Block", "declarations": declarations})
    }
    fn expr_statement(&self, expr: Value) -> Value {
        json!({"node": "ExprStatement", "expr": expr})
    }
    fn if_statement(&self, cond: Value, then: Value, else_: Value) -> Value {
        json!({"node": "IfStatement", "expr": cond, "then": then, "else_": else_})
    }
    fn while_statement(&self, cond: Value, body: Value) -> Value {
        json!({"node": "WhileStatement", "expr": cond, "body": body})
    }
    fn for_in_statement(
        &self,
        key_var: Value,
        value_var: Value,
        expr: Value,
        body: Value,
    ) -> Value {
        json!({
            "node": "ForInStatement",
            "keyVar": key_var,
            "valueVar": value_var,
            "expr": expr,
            "body": body,
        })
    }
    fn for_statement(
        &self,
        initializer: Value,
        condition: Value,
        increment: Value,
        body: Value,
    ) -> Value {
        json!({
            "node": "ForStatement",
            "initializer": initializer,
            "condition": condition,
            "increment": increment,
            "body": body,
        })
    }
    fn function_(&self, name: &str, params: Vec<Value>, body: Value) -> Value {
        json!({"node": "Function", "name": name, "params": params, "body": body})
    }
    fn variable_assignment(&self, left: Value, right: Value) -> Value {
        json!({"node": "VariableAssignment", "left": left, "right": right})
    }
    fn return_statement(&self, expr: Value) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("ReturnStatement".into()));
        obj.insert("expr".into(), expr);
        Value::Object(obj)
    }
    fn try_catch_statement(
        &self,
        try_stmt: Value,
        catches: Vec<Value>,
        finally_stmt: Value,
    ) -> Value {
        json!({
            "node": "TryCatchStatement",
            "try_stmt": try_stmt,
            "catches": catches,
            "finally_stmt": finally_stmt,
        })
    }
    fn throw_statement(&self, expr: Value) -> Value {
        json!({"node": "ThrowStatement", "expr": expr})
    }
    fn variable_declaration(&self, name: &str, expr: Value) -> Value {
        json!({"node": "VariableDeclaration", "name": name, "expr": expr})
    }
    fn catch_clause(&self, var: Value, ty: Value, body: Value) -> Value {
        json!([var, ty, body])
    }
    fn cte(&self, name: &str, expr: Value, cte_type: &str) -> Value {
        json!({"node": "CTE", "name": name, "expr": expr, "cte_type": cte_type})
    }
    fn cte_subquery(
        &self,
        name: &str,
        expr: Value,
        columns: Option<Vec<String>>,
        using_key: Option<Vec<String>>,
        materialized: Option<bool>,
    ) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("CTE".into()));
        obj.insert("name".into(), Value::String(name.into()));
        obj.insert("expr".into(), expr);
        obj.insert("cte_type".into(), Value::String("subquery".into()));
        if let Some(c) = columns {
            obj.insert(
                "columns".into(),
                Value::Array(c.into_iter().map(Value::String).collect()),
            );
        }
        if let Some(uk) = using_key {
            obj.insert(
                "using_key".into(),
                Value::Array(uk.into_iter().map(Value::String).collect()),
            );
        }
        if let Some(m) = materialized {
            obj.insert("materialized".into(), Value::Bool(m));
        }
        Value::Object(obj)
    }
    fn join_constraint(&self, expr: Value, constraint_type: &str) -> Value {
        json!({"node": "JoinConstraint", "expr": expr, "constraint_type": constraint_type})
    }
    fn values_query(&self, rows: Vec<Value>) -> Value {
        json!({"node": "ValuesQuery", "rows": rows})
    }
    fn pivot_column(&self, column: Value, values: Vec<Value>) -> Value {
        json!({"node": "PivotColumn", "column": column, "values": values})
    }
    fn unpivot_column(
        &self,
        value_columns: Value,
        name_columns: Value,
        unpivot_values: Vec<Value>,
    ) -> Value {
        json!({
            "node": "UnpivotColumn",
            "value_columns": value_columns,
            "name_columns": name_columns,
            "unpivot_values": unpivot_values,
        })
    }
    fn grouping_set(&self, exprs: Vec<Value>) -> Value {
        json!({"node": "GroupingSet", "exprs": exprs})
    }
    fn hogqlx_tag(&self, kind: &str, attributes: Vec<Value>) -> Value {
        json!({"node": "HogQLXTag", "kind": kind, "attributes": attributes})
    }
    fn hogqlx_attribute(&self, name: &str, value: Value) -> Value {
        json!({"node": "HogQLXAttribute", "name": name, "value": value})
    }
    fn window_function(
        &self,
        name: &str,
        exprs: Vec<Value>,
        args: Vec<Value>,
        over_expr: Option<Value>,
        over_identifier: Option<String>,
    ) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("WindowFunction".into()));
        obj.insert("name".into(), Value::String(name.into()));
        obj.insert("exprs".into(), Value::Array(exprs));
        obj.insert("args".into(), Value::Array(args));
        if let Some(we) = over_expr {
            obj.insert("over_expr".into(), we);
        }
        if let Some(id) = over_identifier {
            obj.insert("over_identifier".into(), Value::String(id));
        }
        Value::Object(obj)
    }
    fn with_fill_expr(
        &self,
        from_value: Option<Value>,
        to_value: Option<Value>,
        step_value: Option<Value>,
    ) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("WithFillExpr".into()));
        if let Some(v) = from_value {
            obj.insert("from_value".into(), v);
        }
        if let Some(v) = to_value {
            obj.insert("to_value".into(), v);
        }
        if let Some(v) = step_value {
            obj.insert("step_value".into(), v);
        }
        Value::Object(obj)
    }
    fn sample_expr(&self, sample_value: Value, offset_value: Option<Value>) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("SampleExpr".into()));
        obj.insert("sample_value".into(), sample_value);
        if let Some(o) = offset_value {
            obj.insert("offset_value".into(), o);
        }
        Value::Object(obj)
    }
    fn ratio_expr(&self, left: Value, right: Option<Value>) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("RatioExpr".into()));
        obj.insert("left".into(), left);
        if let Some(r) = right {
            obj.insert("right".into(), r);
        }
        Value::Object(obj)
    }
    fn pivot_expr(
        &self,
        table: Value,
        aggregates: Vec<Value>,
        columns: Vec<Value>,
        group_by: Option<Vec<Value>>,
    ) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("PivotExpr".into()));
        obj.insert("table".into(), table);
        obj.insert("aggregates".into(), Value::Array(aggregates));
        obj.insert("columns".into(), Value::Array(columns));
        if let Some(g) = group_by {
            obj.insert("group_by".into(), Value::Array(g));
        }
        Value::Object(obj)
    }
    fn unpivot_expr(&self, table: Value, columns: Vec<Value>, include_nulls: bool) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("UnpivotExpr".into()));
        obj.insert("table".into(), table);
        obj.insert("columns".into(), Value::Array(columns));
        obj.insert("include_nulls".into(), Value::Bool(include_nulls));
        Value::Object(obj)
    }
    fn join_expr(
        &self,
        table: Value,
        alias: Option<String>,
        table_args: Option<Value>,
        column_aliases: Option<Vec<String>>,
        table_final: bool,
        sample: Option<Value>,
    ) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("JoinExpr".into()));
        obj.insert("table".into(), table);
        if let Some(ta) = table_args {
            obj.insert("table_args".into(), ta);
        }
        if let Some(a) = alias {
            obj.insert("alias".into(), Value::String(a));
        }
        if table_final {
            obj.insert("table_final".into(), Value::Bool(true));
        }
        if let Some(s) = sample {
            obj.insert("sample".into(), s);
        }
        if let Some(ca) = column_aliases {
            obj.insert(
                "column_aliases".into(),
                Value::Array(ca.into_iter().map(Value::String).collect()),
            );
        }
        Value::Object(obj)
    }
    fn select_set_query(&self, initial: Value, subsequent: Vec<Value>) -> Value {
        json!({
            "node": "SelectSetQuery",
            "initial_select_query": initial,
            "subsequent_select_queries": subsequent,
        })
    }
    fn window_expr_empty(&self) -> Value {
        json!({"node": "WindowExpr"})
    }
    fn window_frame_bound(&self, frame_type: &str, frame_value: Value) -> Value {
        json!({"node": "WindowFrameExpr", "frame_type": frame_type, "frame_value": frame_value})
    }
    fn interpolate_expr(&self, expr: Value, value: Option<Value>) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("InterpolateExpr".into()));
        obj.insert("expr".into(), expr);
        if let Some(v) = value {
            obj.insert("value".into(), v);
        }
        Value::Object(obj)
    }
    fn limit_by_expr(&self, n: Value, exprs: Vec<Value>, offset_value: Option<Value>) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("LimitByExpr".into()));
        obj.insert("n".into(), n);
        obj.insert("exprs".into(), Value::Array(exprs));
        if let Some(o) = offset_value {
            obj.insert("offset_value".into(), o);
        }
        Value::Object(obj)
    }
    fn select_query_empty(&self) -> Value {
        json!({"node": "SelectQuery"})
    }
    fn select_set_node(&self, select_query: Value, set_operator: Option<&str>) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("node".into(), Value::String("SelectSetNode".into()));
        obj.insert("select_query".into(), select_query);
        if let Some(op) = set_operator {
            obj.insert("set_operator".into(), Value::String(op.into()));
        }
        Value::Object(obj)
    }

    fn position(&self, line: u32, column: u32, offset: usize) -> Value {
        json!({"line": line, "column": column, "offset": offset})
    }
    fn with_pos(&self, mut value: Value, start: Value, end: Value) -> Value {
        if let Some(obj) = value.as_object_mut() {
            if !obj.contains_key("start") {
                obj.insert("start".into(), start);
                obj.insert("end".into(), end);
            }
        }
        value
    }
    fn no_pos(&self, mut value: Value) -> Value {
        if let Some(obj) = value.as_object_mut() {
            obj.insert("start".into(), Value::Null);
            obj.insert("end".into(), Value::Null);
        }
        value
    }
    fn replace_pos(&self, mut value: Value, start: Value, end: Value) -> Value {
        if let Some(obj) = value.as_object_mut() {
            obj.insert("start".into(), start);
            obj.insert("end".into(), end);
        }
        value
    }

    fn node_kind<'a>(&self, v: &'a Value) -> Option<Cow<'a, str>> {
        v.get("node").and_then(Value::as_str).map(Cow::Borrowed)
    }
    fn get_field(&self, v: &Value, name: &str) -> Option<Value> {
        v.get(name).cloned()
    }
    fn has_field(&self, v: &Value, name: &str) -> bool {
        v.as_object().is_some_and(|m| m.contains_key(name))
    }
    fn is_null(&self, v: &Value) -> bool {
        v.is_null()
    }
    fn as_str<'a>(&self, v: &'a Value) -> Option<Cow<'a, str>> {
        v.as_str().map(Cow::Borrowed)
    }
    fn as_list(&self, v: &Value) -> Option<Vec<Value>> {
        v.as_array().cloned()
    }
    fn as_bool(&self, v: &Value) -> Option<bool> {
        v.as_bool()
    }
    fn as_i64(&self, v: &Value) -> Option<i64> {
        v.as_i64()
    }
    fn remove_field(&self, v: &mut Value, name: &str) -> Option<Value> {
        v.as_object_mut().and_then(|obj| obj.remove(name))
    }
    fn set_field(&self, v: &mut Value, name: &str, value: Value) {
        if let Some(obj) = v.as_object_mut() {
            obj.insert(name.into(), value);
        }
    }
}
