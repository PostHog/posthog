//! JSON node builders matching the AST dataclasses at
//! [`posthog/hogql/ast.py`].
//!
//! The Python deserialiser at [`posthog/hogql/json_ast.py`] builds the
//! dataclass from each JSON object's fields and falls back to dataclass
//! defaults for anything missing. So we can emit a minimal shape (just the
//! fields we have a value for) and still produce equivalent objects to the
//! C++ visitor's more verbose output. Tests compare via
//! `assertEqual(parse(...), ast.Foo(...))` which invokes the dataclass
//! `__eq__`; default-equal fields pass either way.

use serde_json::{json, Value};

pub fn constant(value: Value) -> Value {
    json!({"node": "Constant", "value": value})
}

/// `inf`, `-inf`, `nan` go through as a string with `value_type: "number"`
/// envelope. Mirrors the C++ visitor which uses `nlohmann::json` strings for
/// non-finite floats since standard JSON doesn't represent them.
pub fn constant_special_number(name: &'static str) -> Value {
    json!({"node": "Constant", "value": name, "value_type": "number"})
}

/// An integer-literal Constant whose magnitude exceeds `i64`. The exact
/// digit text (decimal, or `0x…` hex, with an optional leading `-`) is
/// carried in the same `value_type: "number"` string envelope; the
/// deserialiser rebuilds an arbitrary-precision Python `int` from it.
/// `serde_json::Value` can't hold an integer wider than `u64`, so the
/// literal can't round-trip as a native JSON number.
pub fn constant_number_string(text: String) -> Value {
    json!({"node": "Constant", "value": text, "value_type": "number"})
}

pub fn field(chain: Vec<Value>) -> Value {
    json!({"node": "Field", "chain": chain})
}

pub fn arith(left: Value, op: &str, right: Value) -> Value {
    json!({"node": "ArithmeticOperation", "left": left, "right": right, "op": op})
}

pub fn compare(left: Value, op: &str, right: Value) -> Value {
    json!({"node": "CompareOperation", "left": left, "right": right, "op": op})
}

pub fn compare_is_null(left: Value, negated: bool) -> Value {
    json!({
        "node": "CompareOperation",
        "left": left,
        "right": Value::Null.tagged_constant(),
        "op": if negated { "!=" } else { "==" },
        "is_null_comparison_style": true,
    })
}

pub fn is_distinct_from(left: Value, right: Value, negated: bool) -> Value {
    json!({"node": "IsDistinctFrom", "left": left, "right": right, "negated": negated})
}

pub fn between(expr: Value, low: Value, high: Value, negated: bool) -> Value {
    json!({"node": "BetweenExpr", "expr": expr, "low": low, "high": high, "negated": negated})
}

pub fn not_(expr: Value) -> Value {
    json!({"node": "Not", "expr": expr})
}

pub fn and_(exprs: Vec<Value>) -> Value {
    json!({"node": "And", "exprs": exprs})
}

pub fn or_(exprs: Vec<Value>) -> Value {
    json!({"node": "Or", "exprs": exprs})
}

pub fn tuple_(exprs: Vec<Value>) -> Value {
    json!({"node": "Tuple", "exprs": exprs})
}

pub fn array_(exprs: Vec<Value>) -> Value {
    json!({"node": "Array", "exprs": exprs})
}

pub fn array_access(array: Value, property: Value, nullish: bool) -> Value {
    if nullish {
        json!({"node": "ArrayAccess", "array": array, "property": property, "nullish": true})
    } else {
        json!({"node": "ArrayAccess", "array": array, "property": property})
    }
}

pub fn tuple_access(tuple_: Value, index: i64, nullish: bool) -> Value {
    if nullish {
        json!({"node": "TupleAccess", "tuple": tuple_, "index": index, "nullish": true})
    } else {
        json!({"node": "TupleAccess", "tuple": tuple_, "index": index})
    }
}

pub fn alias(expr: Value, name: &str) -> Value {
    json!({"node": "Alias", "expr": expr, "alias": name})
}

/// Synthetic `Call` — ternary `?:` (→ `if`), `||` (→ `concat`), `??` (→
/// `ifNull`), and other rewrites. The C++ visitor emits these without the
/// four extra fields (`distinct`, `filter_expr`, `order_by`, `params`),
/// which dataclass defaults absorb on the Python side.
pub fn call(name: &str, args: Vec<Value>) -> Value {
    json!({"node": "Call", "name": name, "args": args})
}

/// Function call carrying every optional shape the grammar's
/// `ColumnExprFunction` can produce: parametric `name(params)(args)`,
/// `DISTINCT`, in-arg `ORDER BY`, and trailing `FILTER (WHERE …)`.
/// Each None / empty field is omitted; the Python dataclass picks up its
/// default (None / False / empty) on deserialise.
#[allow(clippy::too_many_arguments)]
pub fn call_full(
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

pub fn lambda(args: Vec<String>, expr: Value) -> Value {
    let args_json: Vec<Value> = args.into_iter().map(Value::String).collect();
    json!({"node": "Lambda", "args": args_json, "expr": expr})
}

pub fn type_cast(expr: Value, type_name: &str) -> Value {
    json!({"node": "TypeCast", "expr": expr, "type_name": type_name})
}

pub fn try_cast(expr: Value, type_name: &str) -> Value {
    json!({"node": "TryCast", "expr": expr, "type_name": type_name})
}

pub fn array_slice(array: Value, start: Option<Value>, end: Option<Value>) -> Value {
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

pub fn dict_(items: Vec<(Value, Value)>) -> Value {
    let items_json: Vec<Value> = items
        .into_iter()
        .map(|(k, v)| Value::Array(vec![k, v]))
        .collect();
    json!({"node": "Dict", "items": items_json})
}

pub fn placeholder(expr: Value) -> Value {
    json!({"node": "Placeholder", "expr": expr})
}

pub fn named_argument(name: &str, value: Value) -> Value {
    json!({"node": "NamedArgument", "name": name, "value": value})
}

pub fn ignore_nulls(expr: Value) -> Value {
    // `e IGNORE NULLS` is dropped by the C++ visitor — the expression
    // returns as-is. Kept as a named helper to make the call site readable
    // and to leave room for richer behaviour later.
    expr
}

pub fn order_expr(expr: Value, order: &str, with_fill: Option<Value>) -> Value {
    let mut obj = serde_json::Map::new();
    obj.insert("node".into(), Value::String("OrderExpr".into()));
    obj.insert("expr".into(), expr);
    obj.insert("order".into(), Value::String(order.into()));
    if let Some(wf) = with_fill {
        obj.insert("with_fill".into(), wf);
    }
    Value::Object(obj)
}

/// `ColumnsExpr` covering the COLUMNS('regex') / COLUMNS(expr,...) /
/// (*|TABLE.*) EXCLUDE (...) REPLACE (...) family. Every field is optional;
/// the Python dataclass defaults None/False fill in.
pub fn columns_expr(
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
        // C++ emits `replace` as an object keyed by name -> Expr.
        let mut m = serde_json::Map::new();
        for (k, v) in r {
            m.insert(k, v);
        }
        obj.insert("replace".into(), Value::Object(m));
    }
    Value::Object(obj)
}

pub fn spread_expr(expr: Value) -> Value {
    json!({"node": "SpreadExpr", "expr": expr})
}

trait ConstantExt {
    fn tagged_constant(self) -> Value;
}

impl ConstantExt for Value {
    fn tagged_constant(self) -> Value {
        json!({"node": "Constant", "value": self})
    }
}
