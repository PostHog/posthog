//! Convert a parser-built `serde_json::Value` AST into `posthog.hogql.ast` dataclass instances directly, skipping the JSON-string serialise step on the Rust side AND the orjson + `_deserialize_node` walk on the Python side. Mirrors [`posthog/hogql/json_ast.py`].
//!
//! Used by the `parse_*_py` PyO3 entry points in [`crate::lib`]. The `parse_*_json` entry points stay alongside for callers that need the string form (tests, future WASM build that can't link to CPython).
//!
//! Strategy: walk the existing `Value` tree once and construct Python objects via PyO3. The intermediate `Value` is still built by the parser; a later iteration that emits Python objects directly during parsing would skip that too, but the value→PyObject converter proves out the integration first and lets us measure the JSON-elimination win on its own.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};
use serde_json::Value;

/// Raise the matching `posthog.hogql.errors` exception for a parser error envelope, importing ONLY the errors module — error paths don't pay for the success-path converter's AST/enum imports. Mirrors `json_ast.py`'s `SyntaxError`/`ParsingError`/else mapping; shared by `Converter::build_error` and the standalone `parse_string_literal_text` entry point.
pub(crate) fn raise_error_envelope(
    py: Python<'_>,
    error_type: &str,
    message: &str,
    start: Option<u64>,
    end: Option<u64>,
) -> PyErr {
    let errors_module = match py.import_bound("posthog.hogql.errors") {
        Ok(m) => m,
        Err(e) => return e,
    };
    let cls_name = match error_type {
        "SyntaxError" => "SyntaxError",
        "ParsingError" => "ParsingError",
        _ => "ExposedHogQLError",
    };
    let cls = match errors_module.getattr(cls_name) {
        Ok(c) => c,
        Err(e) => return e,
    };
    let kwargs = PyDict::new_bound(py);
    if let Err(e) = kwargs.set_item("start", start) {
        return e;
    }
    if let Err(e) = kwargs.set_item("end", end) {
        return e;
    }
    let args = PyTuple::new_bound(py, [message]);
    match cls.call(&args, Some(&kwargs)) {
        Ok(exc) => PyErr::from_value_bound(exc),
        Err(e) => e,
    }
}

/// Cached refs: AST module, two StrEnum types from `_ENUM_FIELDS` in `json_ast.py`, and the `int` builtin for big-int parsing. Built once per call and reused across the walk; cheaper than `import` + `getattr` per node.
pub struct Converter<'py> {
    py: Python<'py>,
    ast_module: Bound<'py, PyModule>,
    arith_op_enum: Bound<'py, PyAny>,
    compare_op_enum: Bound<'py, PyAny>,
    /// Python builtin `int` class. Mirrors `PyEmitter::cls_int`; cached so big-int literals don't pay `py.eval_bound("int", ...)` per call.
    cls_int: Bound<'py, PyAny>,
}

impl<'py> Converter<'py> {
    pub fn new(py: Python<'py>) -> PyResult<Self> {
        let ast_module = py.import_bound("posthog.hogql.ast")?;
        let arith_op_enum = ast_module.getattr("ArithmeticOperationOp")?;
        let compare_op_enum = ast_module.getattr("CompareOperationOp")?;
        let cls_int = py.import_bound("builtins")?.getattr("int")?;
        Ok(Self {
            py,
            ast_module,
            arith_op_enum,
            compare_op_enum,
            cls_int,
        })
    }

    /// Top-level entry: convert the root `Value` to a Python AST instance. Raises `ExposedHogQLError` / `SyntaxError` / `ParsingError` if the parser returned an error envelope.
    pub fn convert_root(&self, value: &Value) -> PyResult<PyObject> {
        self.convert(value)
    }

    /// Recursive walk. Mirrors `_deserialize_node` in `json_ast.py`.
    fn convert(&self, value: &Value) -> PyResult<PyObject> {
        match value {
            Value::Null => Ok(self.py.None()),
            Value::Bool(b) => Ok(b.into_py(self.py)),
            Value::Number(n) => {
                if let Some(i) = n.as_i64() {
                    Ok(i.into_py(self.py))
                } else if let Some(u) = n.as_u64() {
                    Ok(u.into_py(self.py))
                } else if let Some(f) = n.as_f64() {
                    Ok(f.into_py(self.py))
                } else {
                    Err(PyValueError::new_err(format!("Invalid JSON number: {n}")))
                }
            }
            Value::String(s) => Ok(s.as_str().into_py(self.py)),
            Value::Array(items) => {
                let list = PyList::empty_bound(self.py);
                for item in items {
                    list.append(self.convert(item)?)?;
                }
                Ok(list.into())
            }
            Value::Object(map) => {
                // Error envelope per `_deserialize_node`'s `data.get("error") is True` branch.
                if matches!(map.get("error"), Some(Value::Bool(true))) {
                    return Err(self.build_error(map));
                }

                let node_type = match map.get("node") {
                    Some(Value::String(s)) => s.as_str(),
                    _ => {
                        return Err(PyValueError::new_err(
                            "Invalid AST node: missing 'node' field",
                        ))
                    }
                };

                let ast_class = self.ast_module.getattr(node_type).map_err(|_| {
                    PyValueError::new_err(format!("Unknown AST node type: {node_type}"))
                })?;

                let is_constant = node_type == "Constant";
                let value_type = if is_constant {
                    map.get("value_type").and_then(Value::as_str)
                } else {
                    None
                };

                let kwargs = PyDict::new_bound(self.py);
                for (key, val) in map.iter() {
                    if key == "node" || key == "value_type" {
                        continue;
                    }

                    // Position envelopes `{offset: N}` → offset int.
                    if (key == "start" || key == "end") && val.is_object() {
                        if let Some(offset) = val.get("offset").and_then(Value::as_u64) {
                            kwargs.set_item(key, offset)?;
                            continue;
                        }
                        if let Some(offset) = val.get("offset").and_then(Value::as_i64) {
                            kwargs.set_item(key, offset)?;
                            continue;
                        }
                    }

                    // Numeric Constants serialised as strings: non-finite floats (Infinity / NaN) and integer literals wider than int64.
                    if is_constant && key == "value" && value_type == Some("number") {
                        if let Value::String(s) = val {
                            if let Some(f) = parse_special_float(s) {
                                kwargs.set_item(key, f)?;
                                continue;
                            }
                            if let Some(py_int) = self.parse_large_int_literal(s)? {
                                kwargs.set_item(key, py_int)?;
                                continue;
                            }
                            return Err(PyValueError::new_err(format!(
                                "Unknown numeric constant value: {s:?}"
                            )));
                        }
                    }

                    // `ctes` may arrive as a list of nodes carrying `name` — fold into a dict keyed by name, preserving order.
                    if key == "ctes" {
                        if let Value::Array(items) = val {
                            let dict = PyDict::new_bound(self.py);
                            for item in items {
                                let name =
                                    item.get("name").and_then(Value::as_str).ok_or_else(|| {
                                        PyValueError::new_err(
                                            "cte entry missing 'name' field for dict folding",
                                        )
                                    })?;
                                dict.set_item(name, self.convert(item)?)?;
                            }
                            kwargs.set_item(key, dict)?;
                            continue;
                        }
                    }

                    // `window_exprs`, `replace`, and `ctes`-as-dict: dict-shaped fields whose values are child nodes.
                    if (key == "window_exprs" || key == "replace" || key == "ctes")
                        && val.is_object()
                        && !val.as_object().is_some_and(|m| m.contains_key("node"))
                    {
                        let map = val.as_object().unwrap();
                        let dict = PyDict::new_bound(self.py);
                        for (k, v) in map.iter() {
                            dict.set_item(k, self.convert(v)?)?;
                        }
                        kwargs.set_item(key, dict)?;
                        continue;
                    }

                    let converted = self.convert(val)?;

                    // Enum coercion for `ArithmeticOperation.op` and `CompareOperation.op` — both StrEnums; pull the member via `cls[name]`.
                    if let Value::String(s) = val {
                        let enum_cls = match (node_type, key.as_str()) {
                            ("ArithmeticOperation", "op") => Some(&self.arith_op_enum),
                            ("CompareOperation", "op") => Some(&self.compare_op_enum),
                            _ => None,
                        };
                        if let Some(cls) = enum_cls {
                            if let Ok(member) = cls.get_item(s) {
                                kwargs.set_item(key, member)?;
                                continue;
                            }
                            // Fall through to the converted string on KeyError — matches the Python deserializer's `except KeyError: pass`.
                        }
                    }

                    kwargs.set_item(key, converted)?;
                }

                let args = PyTuple::empty_bound(self.py);
                Ok(ast_class.call(&args, Some(&kwargs))?.unbind())
            }
        }
    }

    /// Build a Python exception object from a parser error envelope `{error: true, type, message, start: {offset}, end: {offset}}` as set by `ParseError::to_json_value` in `error.rs`.
    fn build_error(&self, map: &serde_json::Map<String, Value>) -> PyErr {
        let error_type = map
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or("ExposedHogQLError");
        let message = map
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("Unknown error");
        let start = map
            .get("start")
            .and_then(|v| v.get("offset"))
            .and_then(Value::as_u64);
        let end = map
            .get("end")
            .and_then(|v| v.get("offset"))
            .and_then(Value::as_u64);
        raise_error_envelope(self.py, error_type, message, start, end)
    }

    /// Build a Python `int` from an integer literal in the lossless-string envelope (decimal or `0x…` hex, optional leading `-`). Rust can't natively represent arbitrary-precision ints, so we hand the raw digits to Python's `int(text, base)` constructor via the cached `cls_int`.
    fn parse_large_int_literal(&self, value: &str) -> PyResult<Option<PyObject>> {
        let body = value.strip_prefix('-').unwrap_or(value);
        let is_hex = body.starts_with("0x") || body.starts_with("0X");
        let base = if is_hex { 16 } else { 10 };
        // Validate by trying as Rust i128 first for the common in-range case; fall through to Python `int(...)` for true bignums.
        let body_no_prefix = if is_hex { &body[2..] } else { body };
        if !body_no_prefix.chars().all(|c| c.is_ascii_alphanumeric()) {
            return Ok(None);
        }
        let args = PyTuple::new_bound(self.py, [value.into_py(self.py), base.into_py(self.py)]);
        match self.cls_int.call(&args, None) {
            Ok(obj) => Ok(Some(obj.unbind())),
            Err(_) => Ok(None),
        }
    }
}

fn parse_special_float(s: &str) -> Option<f64> {
    match s {
        "Infinity" => Some(f64::INFINITY),
        "-Infinity" => Some(f64::NEG_INFINITY),
        "NaN" => Some(f64::NAN),
        _ => None,
    }
}
