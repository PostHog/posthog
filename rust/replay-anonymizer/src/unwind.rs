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

/// Cap on the panic text carried into an error. Standard slice/`expect` panics interpolate a chunk
/// of the offending value (`byte index N is not a char boundary ... of \`<raw input>\``), so the
/// message can embed unscrubbed input. The ingestion path drops the message entirely (see
/// `snapshot::contain_panics`); the offline `anyhow` entry points keep it for diagnosis but bound
/// it here so a pathological payload can't splice an unbounded slice of itself into the error.
const MAX_PANIC_MESSAGE_LEN: usize = 200;

fn panic_message(panic: &(dyn std::any::Any + Send)) -> String {
    let raw = if let Some(s) = panic.downcast_ref::<&str>() {
        *s
    } else if let Some(s) = panic.downcast_ref::<String>() {
        s.as_str()
    } else {
        "non-string panic payload"
    };
    match raw.char_indices().nth(MAX_PANIC_MESSAGE_LEN) {
        Some((cut, _)) => format!("{}…", &raw[..cut]),
        None => raw.to_string(),
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
