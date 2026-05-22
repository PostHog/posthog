//! Hand-rolled Rust HogQL parser — ALL(*) variant.
//!
//! Forked from `hogql_parser_rs` at the ~99.88% cpp-parity baseline.
//! From here we make per-site upgrades to match cpp's ALL(*) behavior
//! exactly at the structural decision points that the Pratt+heuristic
//! parser couldn't resolve (BETWEEN body absorbing trailing AND,
//! lambda body inside an outer construct, paren-vs-subquery dispatch,
//! …). Each upgrade hard-codes whatever technique is fastest for that
//! specific site — AST surgery, scan probe, targeted backtrack — with
//! the cpp output as the spec.
//!
//! Each PyO3 entry point catches `ParseError`s and emits the JSON error
//! envelope expected by [`posthog/hogql/json_ast.py`] so the Python side
//! can raise `ExposedHogQLError` / `SyntaxError` from it.

// `#[pyfunction]`'s expansion does an `.into()` on the `PyResult<PyObject>` return value, which is an identity conversion when the function already returns the target type — clippy's `useless_conversion` doesn't see through the macro and would flag every `parse_*_py` entry point. The lint isn't actionable from our side without leaving pyo3's `#[pyfunction]` abstraction.
#![allow(clippy::useless_conversion)]

use pyo3::prelude::*;
use std::panic::AssertUnwindSafe;

mod emit;
mod emit_py;
mod error;
mod lex;
mod parse;
mod pyobject;

fn run<F>(f: F) -> String
where
    F: FnOnce() -> Result<serde_json::Value, error::ParseError>,
{
    match f() {
        Ok(value) => serde_json::to_string(&value).unwrap_or_else(|_| {
            // serde_json::Value -> string never fails in practice, but emit a structured error rather than panic across the FFI.
            error::ParseError::syntax("internal: failed to serialize AST", 0, 0).to_json_string()
        }),
        Err(err) => err.to_json_string(),
    }
}

/// Counterpart to [`run`] for `parse_*_py` entry points: drive a `PyEmitter` so the parser constructs `posthog.hogql.ast` instances directly, returning the unbound `Py<PyAny>`. Skips both the JSON-string serialise step AND the post-walk `Value`→`PyObject` converter used by the `*_json` entry points — no `serde_json::Value` intermediate on the success path.
///
/// Error path still routes through the JSON-envelope `Converter` so Python exception construction stays in one place.
fn run_py<'py, F>(py: Python<'py>, f: F) -> PyResult<PyObject>
where
    F: FnOnce(emit_py::PyEmitter<'py>) -> Result<emit_py::PyAst, error::ParseError>,
{
    let emitter = emit_py::PyEmitter::new(py)?;
    // Convert any panic from the emitter drive (e.g. `class(**kwargs)` tripping dataclass `__post_init__`) into a `NotImplementedError` envelope. PyO3 would surface it as `PanicException`, which production callers catching the `ExposedHogQLError` family won't intercept.
    let outcome = std::panic::catch_unwind(AssertUnwindSafe(|| f(emitter)));
    let result = match outcome {
        Ok(r) => r,
        Err(panic) => {
            let msg = panic
                .downcast_ref::<&'static str>()
                .copied()
                .map(str::to_string)
                .or_else(|| panic.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "ast construction panicked".to_string());
            Err(error::ParseError::not_implemented(msg, 0, 0))
        }
    };
    match result {
        Ok(v) => Ok(v.obj),
        Err(err) => {
            // Build the JSON error envelope so the converter raises the matching Python exception with start/end positions — one code path for both error sources.
            let value = err.to_json_value();
            let converter = pyobject::Converter::new(py)?;
            converter.convert_root(&value)
        }
    }
}

#[pyfunction]
#[pyo3(signature = (statement, is_internal=false))]
fn parse_expr_json(statement: &str, is_internal: bool) -> String {
    run(|| parse::parse_expr(statement, is_internal))
}

#[pyfunction]
fn parse_order_expr_json(statement: &str) -> String {
    run(|| parse::parse_order_expr(statement))
}

#[pyfunction]
fn parse_select_json(statement: &str) -> String {
    run(|| parse::parse_select(statement))
}

#[pyfunction]
fn parse_program_json(source: &str) -> String {
    run(|| parse::parse_program(source))
}

#[pyfunction]
fn parse_full_template_string_json(string: &str) -> String {
    run(|| parse::parse_full_template_string(string))
}

// `parse_*_py` mirror the `_json` entry points but return Python ast dataclass instances directly, skipping the JSON serialise/deserialise round-trip on both sides. The `_json` versions stay alongside for the future WASM build and for tests that compare on JSON shape.

#[pyfunction]
#[pyo3(signature = (statement, is_internal=false))]
fn parse_expr_py(py: Python<'_>, statement: &str, is_internal: bool) -> PyResult<PyObject> {
    run_py(py, |emit| {
        parse::parse_expr_with_emit(emit, statement, is_internal)
    })
}

#[pyfunction]
fn parse_order_expr_py(py: Python<'_>, statement: &str) -> PyResult<PyObject> {
    run_py(py, |emit| {
        parse::parse_order_expr_with_emit(emit, statement)
    })
}

#[pyfunction]
fn parse_select_py(py: Python<'_>, statement: &str) -> PyResult<PyObject> {
    run_py(py, |emit| parse::parse_select_with_emit(emit, statement))
}

#[pyfunction]
fn parse_program_py(py: Python<'_>, source: &str) -> PyResult<PyObject> {
    run_py(py, |emit| parse::parse_program_with_emit(emit, source))
}

#[pyfunction]
fn parse_full_template_string_py(py: Python<'_>, string: &str) -> PyResult<PyObject> {
    run_py(py, |emit| {
        parse::parse_full_template_string_with_emit(emit, string)
    })
}

#[pymodule]
fn hogql_parser_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_expr_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_order_expr_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_select_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_program_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_full_template_string_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_expr_py, m)?)?;
    m.add_function(wrap_pyfunction!(parse_order_expr_py, m)?)?;
    m.add_function(wrap_pyfunction!(parse_select_py, m)?)?;
    m.add_function(wrap_pyfunction!(parse_program_py, m)?)?;
    m.add_function(wrap_pyfunction!(parse_full_template_string_py, m)?)?;
    Ok(())
}
