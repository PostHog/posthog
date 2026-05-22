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

use pyo3::prelude::*;

mod emit;
mod error;
mod lex;
mod parse;

fn run<F>(f: F) -> String
where
    F: FnOnce() -> Result<serde_json::Value, error::ParseError>,
{
    match f() {
        Ok(value) => serde_json::to_string(&value).unwrap_or_else(|_| {
            // serde_json::Value -> string never fails in practice, but emit
            // a structured error rather than panicking across the FFI.
            error::ParseError::syntax("internal: failed to serialize AST", 0, 0).to_json_string()
        }),
        Err(err) => err.to_json_string(),
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

#[pymodule]
fn hogql_parser_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_expr_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_order_expr_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_select_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_program_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_full_template_string_json, m)?)?;
    Ok(())
}
