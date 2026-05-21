//! The `Emitter` trait abstracts AST node construction so the parser can
//! emit either `serde_json::Value` (via `JsonEmitter`, used by the
//! `parse_*_json` entry points + the future WASM build) or Python
//! `posthog.hogql.ast` dataclass instances directly during parse (via
//! `PyEmitter` in `emit_py.rs`, used by the `parse_*_py` entry points).
//!
//! Field names and shapes mirror the dataclasses at [`posthog/hogql/ast.py`].
//! The Python deserialiser at [`posthog/hogql/json_ast.py`] also builds
//! these dataclasses from the JSON shape, so the two backends produce
//! `__eq__`-equivalent objects.

use serde_json::{json, Value};
use std::borrow::Cow;

/// AST node + value constructor surface. Every construction site in the
/// parser routes through this trait so the same parse logic can produce
/// `serde_json::Value` (kept for the WASM build and tests) or Python
/// dataclass instances directly via PyO3.
///
/// Inspection methods (`node_kind`, `get_field`, …) cover the parser's
/// post-construction AST-surgery patterns: split-and-hoist for nested
/// BETWEEN, AND/OR chain folding, position propagation, and concat
/// merging. JSON impls read the underlying map directly; the Python
/// impl uses PyO3 `getattr` against the dataclass attrs.
pub trait Emitter {
    /// AST tree handle. Cheap to clone (Json: refcount via Value::clone;
    /// Py: `Bound::clone_ref` on the underlying PyObject).
    type Value: Clone;

    // ===== Primitive value constructors =====
    /// `None`-equivalent (Json null / Py None). Used as a sentinel for
    /// "no value" slots that the deserialiser maps to dataclass-field
    /// `None` defaults.
    fn null(&self) -> Self::Value;
    fn bool(&self, v: bool) -> Self::Value;
    fn int(&self, v: i64) -> Self::Value;
    fn string(&self, v: &str) -> Self::Value;

    // ===== AST node builders =====
    fn constant(&self, value: Self::Value) -> Self::Value;
    /// `inf` / `-inf` / `nan` shipped as a string with `value_type: "number"`.
    /// Mirrors cpp's nlohmann::json-string encoding for non-finite floats.
    fn constant_special_number(&self, name: &'static str) -> Self::Value;
    /// Integer-literal Constant whose magnitude exceeds i64. Exact decimal
    /// or `0x…` hex digits with optional leading `-`. Deserialiser
    /// rebuilds an arbitrary-precision Python int.
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
    /// `e IGNORE NULLS` is dropped by the C++ visitor — the expression
    /// returns as-is. Kept as a named helper to leave room for richer
    /// behaviour later.
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

    // ===== Position machinery =====
    /// `{line, column, offset}` per cpp's visitor — line is 1-based,
    /// column is 0-based, offset is the character position.
    fn position(&self, line: u32, column: u32, offset: usize) -> Self::Value;
    /// Inject `start` / `end` position objects. Idempotent: if `start` is
    /// already present (set OR explicitly null-poisoned by `no_pos`), the
    /// existing values are kept — this is how cpp's paren wrap `(expr)`
    /// preserves the inner expression's positions.
    fn with_pos(&self, value: Self::Value, start: Self::Value, end: Self::Value) -> Self::Value;
    /// Mark a node as position-less so downstream `with_pos` calls leave
    /// it bare. Mirrors cpp visitors that emit a node without
    /// `addPositionInfo(json, ctx)` — Python AST shows dataclass defaults
    /// (None). Example: `NamedArgument`.
    fn no_pos(&self, value: Self::Value) -> Self::Value;
    /// Override existing `start` / `end` keys, unlike the idempotent
    /// `with_pos`. Used by call sites that need the outer span to
    /// include tokens the inner expression's wrap didn't see.
    fn replace_pos(&self, value: Self::Value, start: Self::Value, end: Self::Value) -> Self::Value;

    // ===== Inspection =====
    /// Get the AST node kind ("Constant", "ArithmeticOperation", …) or
    /// `None` for non-node values (primitives, lists, positions).
    fn node_kind<'a>(&self, v: &'a Self::Value) -> Option<Cow<'a, str>>;
    /// Get a named field value. Returns `None` if the field is missing or
    /// the value isn't a node. The returned value is owned (cloned).
    fn get_field(&self, v: &Self::Value, name: &str) -> Option<Self::Value>;
    /// True if the field is present at all (even if its value is null).
    /// Distinguishes "field not set" from "field explicitly null" — the
    /// `no_pos` + `with_pos` idempotency relies on this.
    fn has_field(&self, v: &Self::Value, name: &str) -> bool;
    /// `Value::is_null` analogue.
    fn is_null(&self, v: &Self::Value) -> bool;
    /// Extract a string body if `v` is a string value.
    fn as_str<'a>(&self, v: &'a Self::Value) -> Option<Cow<'a, str>>;
    /// Extract the list elements if `v` is a list/array value.
    fn as_list(&self, v: &Self::Value) -> Option<Vec<Self::Value>>;
    /// Get the `offset` field of a position object.
    fn position_offset(&self, v: &Self::Value) -> Option<usize>;
}

// ============================================================================
// JsonEmitter — `serde_json::Value` impl, mirrors the previous free
// `emit::xxx` functions. Used by `parse_*_json` entry points and the
// future WASM build.
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
    fn position_offset(&self, v: &Value) -> Option<usize> {
        v.get("offset").and_then(Value::as_u64).map(|n| n as usize)
    }
}

// ============================================================================
// Migration-compat free functions, scoped behind a `compat` submodule with a
// module-level `dead_code` allow. The parser code originally called these
// directly; during the Phase 2 generic-emitter refactor it's been moved to
// `self.emit.xxx(...)`. These thin wrappers stay for free helper functions
// (where `self` isn't in scope — `apply_between_hoist`,
// `wrap_literal_chunk`, `emit_float_constant`, …) and are re-exported at
// the module root so existing `emit::xxx(...)` call sites keep working.
// ============================================================================

#[allow(dead_code)]
mod compat {
    use super::{Emitter, JsonEmitter};
    use serde_json::Value;

    #[inline]
    pub fn constant(value: Value) -> Value {
        JsonEmitter.constant(value)
    }
    #[inline]
    pub fn constant_special_number(name: &'static str) -> Value {
        JsonEmitter.constant_special_number(name)
    }
    #[inline]
    pub fn constant_number_string(text: String) -> Value {
        JsonEmitter.constant_number_string(text)
    }
    #[inline]
    pub fn field(chain: Vec<Value>) -> Value {
        JsonEmitter.field(chain)
    }
    #[inline]
    pub fn arith(left: Value, op: &str, right: Value) -> Value {
        JsonEmitter.arith(left, op, right)
    }
    #[inline]
    pub fn compare(left: Value, op: &str, right: Value) -> Value {
        JsonEmitter.compare(left, op, right)
    }
    #[inline]
    pub fn compare_is_null(left: Value, negated: bool) -> Value {
        JsonEmitter.compare_is_null(left, negated)
    }
    #[inline]
    pub fn is_distinct_from(left: Value, right: Value, negated: bool) -> Value {
        JsonEmitter.is_distinct_from(left, right, negated)
    }
    #[inline]
    pub fn between(expr: Value, low: Value, high: Value, negated: bool) -> Value {
        JsonEmitter.between(expr, low, high, negated)
    }
    #[inline]
    pub fn not_(expr: Value) -> Value {
        JsonEmitter.not_(expr)
    }
    #[inline]
    pub fn and_(exprs: Vec<Value>) -> Value {
        JsonEmitter.and_(exprs)
    }
    #[inline]
    pub fn or_(exprs: Vec<Value>) -> Value {
        JsonEmitter.or_(exprs)
    }
    #[inline]
    pub fn tuple_(exprs: Vec<Value>) -> Value {
        JsonEmitter.tuple_(exprs)
    }
    #[inline]
    pub fn array_(exprs: Vec<Value>) -> Value {
        JsonEmitter.array_(exprs)
    }
    #[inline]
    pub fn array_access(array: Value, property: Value, nullish: bool) -> Value {
        JsonEmitter.array_access(array, property, nullish)
    }
    #[inline]
    pub fn tuple_access(tuple_: Value, index: i64, nullish: bool) -> Value {
        JsonEmitter.tuple_access(tuple_, index, nullish)
    }
    #[inline]
    pub fn alias(expr: Value, name: &str) -> Value {
        JsonEmitter.alias(expr, name)
    }
    #[inline]
    pub fn call(name: &str, args: Vec<Value>) -> Value {
        JsonEmitter.call(name, args)
    }
    #[allow(clippy::too_many_arguments)]
    #[inline]
    pub fn call_full(
        name: &str,
        params: Option<Vec<Value>>,
        args: Vec<Value>,
        distinct: bool,
        order_by: Option<Vec<Value>>,
        filter_expr: Option<Value>,
        within_group: Option<Vec<Value>>,
    ) -> Value {
        JsonEmitter.call_full(
            name,
            params,
            args,
            distinct,
            order_by,
            filter_expr,
            within_group,
        )
    }
    #[inline]
    pub fn lambda(args: Vec<String>, expr: Value) -> Value {
        JsonEmitter.lambda(args, expr)
    }
    #[inline]
    pub fn type_cast(expr: Value, type_name: &str) -> Value {
        JsonEmitter.type_cast(expr, type_name)
    }
    #[inline]
    pub fn try_cast(expr: Value, type_name: &str) -> Value {
        JsonEmitter.try_cast(expr, type_name)
    }
    #[inline]
    pub fn array_slice(array: Value, start: Option<Value>, end: Option<Value>) -> Value {
        JsonEmitter.array_slice(array, start, end)
    }
    #[inline]
    pub fn dict_(items: Vec<(Value, Value)>) -> Value {
        JsonEmitter.dict_(items)
    }
    #[inline]
    pub fn placeholder(expr: Value) -> Value {
        JsonEmitter.placeholder(expr)
    }
    #[inline]
    pub fn named_argument(name: &str, value: Value) -> Value {
        JsonEmitter.named_argument(name, value)
    }
    #[inline]
    pub fn ignore_nulls(expr: Value) -> Value {
        JsonEmitter.ignore_nulls(expr)
    }
    #[inline]
    pub fn order_expr(expr: Value, order: &str, with_fill: Option<Value>) -> Value {
        JsonEmitter.order_expr(expr, order, with_fill)
    }
    #[inline]
    pub fn columns_expr(
        regex: Option<String>,
        columns: Option<Vec<Value>>,
        all_columns: bool,
        exclude: Option<Vec<String>>,
        replace: Option<Vec<(String, Value)>>,
    ) -> Value {
        JsonEmitter.columns_expr(regex, columns, all_columns, exclude, replace)
    }
    #[inline]
    pub fn spread_expr(expr: Value) -> Value {
        JsonEmitter.spread_expr(expr)
    }
    #[inline]
    pub fn position(line: u32, column: u32, offset: usize) -> Value {
        JsonEmitter.position(line, column, offset)
    }
    #[inline]
    pub fn with_pos(value: Value, start: Value, end: Value) -> Value {
        JsonEmitter.with_pos(value, start, end)
    }
    #[inline]
    pub fn no_pos(value: Value) -> Value {
        JsonEmitter.no_pos(value)
    }
    #[inline]
    pub fn replace_pos(value: Value, start: Value, end: Value) -> Value {
        JsonEmitter.replace_pos(value, start, end)
    }
}

pub use compat::*;
