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
// Style lints that conflict with the parser's deliberate shape: a few internal helpers return wide tuples (the table-alias chain, function-arg bundles) rather than one-off structs; some builder-style helpers are named `from_*` but take `&self`; and the heavily-prose doc comments use markdown lists clippy's `doc_lazy_continuation` flags. None are actionable without churning the parser, so allow them crate-wide.
#![allow(
    clippy::type_complexity,
    clippy::wrong_self_convention,
    clippy::doc_lazy_continuation
)]

use pyo3::prelude::*;
use std::panic::AssertUnwindSafe;

mod emit;
mod emit_py;
mod error;
mod lex;
mod parse;
mod pyobject;

#[cfg(feature = "coverage")]
mod cov;

fn run<F>(f: F) -> String
where
    F: FnOnce() -> Result<serde_json::Value, error::ParseError>,
{
    // Catch panics so a parser bug surfaces as a structured JSON error envelope (a `NotImplementedError` the Python side maps to the `ExposedHogQLError` family) instead of a `PanicException` — a `BaseException` that slips past callers' `except Exception` and the shadow-comparison harness's guard, crashing the primary parse. `run_py` wraps its deep parse the same way; the `*_json` entry points have no other unwind boundary, so they need it here.
    let outcome = std::panic::catch_unwind(AssertUnwindSafe(f));
    let result = match outcome {
        Ok(r) => r,
        Err(panic) => {
            let msg = panic
                .downcast_ref::<&'static str>()
                .copied()
                .map(str::to_string)
                .or_else(|| panic.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "parser panicked".to_string());
            Err(error::ParseError::not_implemented(
                format!("internal parser panic: {msg}"),
                0,
                0,
            ))
        }
    };
    match result {
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
    // Drive the emitter under `catch_unwind`: a dataclass constructor / `__post_init__` raising mid-build unwinds via panic (the `Emitter` trait is infallible, so there's no Result channel out of the deep parse).
    let outcome = std::panic::catch_unwind(AssertUnwindSafe(|| f(emitter)));
    let result = match outcome {
        Ok(r) => r,
        Err(panic) => {
            // `PyEmitter::build` restores the original Python exception before unwinding, so re-raise it verbatim — rust-py then surfaces the same exception the json backends do (they hit it in `deserialize_ast`), rather than a wrapped envelope.
            if let Some(err) = PyErr::take(py) {
                return Err(err);
            }
            // Genuine (non-PyErr) panic: wrap as a `NotImplementedError` envelope so production callers catching the `ExposedHogQLError` family intercept it, instead of PyO3 surfacing a raw `PanicException`.
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

/// Byte-for-byte twin of the C++ wheel's `parse_string_literal_text`, closing the last cpp/rust API gap.
/// Errors route through the shared converter so `SyntaxError`/`ParsingError` match the C++ wheel's classes.
#[pyfunction]
fn parse_string_literal_text(py: Python<'_>, text: &str) -> PyResult<String> {
    // catch_unwind like the other entry points: a future panic in the decoder must not cross FFI as a PanicException.
    match std::panic::catch_unwind(AssertUnwindSafe(|| parse::parse_string_literal_text(text))) {
        Ok(Ok(decoded)) => Ok(decoded),
        Ok(Err(err)) => Err(raise_parse_error(py, err)),
        Err(_) => Err(raise_parse_error(
            py,
            error::ParseError::not_implemented("internal panic in parse_string_literal_text", 0, 0),
        )),
    }
}

/// Raise the matching `posthog.hogql.errors` exception for `err`, importing only the errors module (not the AST/enum-laden `Converter`).
fn raise_parse_error(py: Python<'_>, err: error::ParseError) -> PyErr {
    pyobject::raise_error_envelope(
        py,
        err.kind.type_str(),
        &err.message,
        Some(err.start as u64),
        Some(err.end as u64),
    )
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
    m.add_function(wrap_pyfunction!(parse_string_literal_text, m)?)?;

    #[cfg(feature = "coverage")]
    {
        // Edge-coverage bitmap for the parser-parity grind. Only present in
        // wheels built with `--features coverage`; the PBT detects via
        // `hasattr(hogql_parser_rs, "cov_snapshot")` and gracefully skips the
        // rust_edges steering signal on a production wheel. See `src/cov.rs`.
        m.add_function(wrap_pyfunction!(cov::cov_snapshot, m)?)?;
        m.add_function(wrap_pyfunction!(cov::cov_reset, m)?)?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_converts_panic_to_json_error_envelope() {
        // A panic on a `*_json` path must surface as a structured error envelope, not unwind across the FFI as a `PanicException` (a `BaseException` that escapes callers' `except Exception` and the shadow harness). cargo captures the expected panic's stderr for a passing test, so no hook silencing is needed.
        let out = run(|| panic!("synthetic json-path panic"));
        assert!(out.contains("\"error\":true"), "got: {out}");
        assert!(out.contains("NotImplementedError"), "got: {out}");
        assert!(out.contains("synthetic json-path panic"), "got: {out}");
    }

    #[test]
    fn run_passes_through_ok_and_error_results() {
        // The catch_unwind wrapper must not disturb the normal Ok / Err paths.
        let ok = run(|| Ok(serde_json::json!({"node": "Constant"})));
        assert!(ok.contains("Constant"), "got: {ok}");
        let err = run(|| Err(error::ParseError::syntax("nope", 1, 2)));
        assert!(
            err.contains("SyntaxError") && err.contains("nope"),
            "got: {err}"
        );
    }
}
