//! Per-event capture of `print()` output.
//!
//! The `print` host function has no way to reach the result being built for the current event, so
//! it writes to a thread-local buffer instead. An event executes entirely on one thread (the JS
//! thread for `executeSync`, a rayon worker for `executeBatch`), so resetting the buffer before
//! each execution and draining it right after cannot mix events up.

use std::cell::RefCell;

// The Node executor stops collecting print logs after 24 entries (MAX_HOG_LOGS = 25, the 25th
// call becomes a "too many logs" warning).
pub const MAX_CAPTURED_LOGS: usize = 24;

struct LogBuffer {
    messages: Vec<String>,
    truncated: bool,
}

thread_local! {
    static LOG_BUFFER: RefCell<LogBuffer> = const {
        RefCell::new(LogBuffer {
            messages: Vec::new(),
            truncated: false,
        })
    };
}

pub fn reset() {
    LOG_BUFFER.with(|buffer| {
        let mut buffer = buffer.borrow_mut();
        buffer.messages.clear();
        buffer.truncated = false;
    });
}

pub fn push(message: String) {
    LOG_BUFFER.with(|buffer| {
        let mut buffer = buffer.borrow_mut();
        if buffer.messages.len() >= MAX_CAPTURED_LOGS {
            buffer.truncated = true;
        } else {
            buffer.messages.push(message);
        }
    });
}

/// Drain the current thread's buffer, returning the captured messages and whether any were
/// dropped past the cap.
pub fn take() -> (Vec<String>, bool) {
    LOG_BUFFER.with(|buffer| {
        let mut buffer = buffer.borrow_mut();
        let truncated = buffer.truncated;
        buffer.truncated = false;
        (std::mem::take(&mut buffer.messages), truncated)
    })
}
