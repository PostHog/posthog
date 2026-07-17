//! Boundary backstop: convert a panic on untrusted input into an error at the public entry
//! points, so callers are fail-closed by construction instead of by a documented `catch_unwind`
//! obligation. Internal code stays panic-free-by-intent — this is the last line of defense, not a
//! license to panic. Under `panic = "abort"` the backstop cannot run (the process dies before
//! `catch_unwind` sees anything); builds that must fail closed need `panic = "unwind"`, which the
//! Node addon enforces at compile time.

use std::panic::{catch_unwind, AssertUnwindSafe};

/// Run `f`, converting an unwind into `err(message)`.
///
/// `AssertUnwindSafe` is sound at these boundaries because the fail-closed contract already
/// requires callers to discard whatever `f` mutated (buffers, parsed trees) whenever an error
/// comes back — a half-scrubbed value can never be observed on the `Err` path.
pub(crate) fn contain_unwind<T, E>(
    f: impl FnOnce() -> Result<T, E>,
    err: impl FnOnce(String) -> E,
) -> Result<T, E> {
    catch_unwind(AssertUnwindSafe(f)).unwrap_or_else(|panic| Err(err(panic_message(&*panic))))
}

fn panic_message(panic: &(dyn std::any::Any + Send)) -> String {
    if let Some(s) = panic.downcast_ref::<&str>() {
        (*s).to_string()
    } else if let Some(s) = panic.downcast_ref::<String>() {
        s.clone()
    } else {
        "non-string panic payload".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn panics_become_errors_and_results_pass_through() {
        let caught = contain_unwind(
            || -> Result<(), String> { panic!("boom {}", 42) },
            |msg| format!("panic while anonymizing: {msg}"),
        );
        assert_eq!(caught.unwrap_err(), "panic while anonymizing: boom 42");

        assert_eq!(contain_unwind(|| Ok::<_, String>(7), |m| m).unwrap(), 7);
        assert_eq!(
            contain_unwind(|| Err::<(), _>("plain error".to_string()), |m| m).unwrap_err(),
            "plain error"
        );
    }
}
