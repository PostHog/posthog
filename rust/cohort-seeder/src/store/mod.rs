//! The sole owner of the seeder's PostgreSQL access: `sqlx` is confined to this module tree (and
//! `test_support`). Everything above receives typed rows and typed errors; nothing below leaks a DB
//! concept. Submodules: `chunks` (the day-chunk claim/CAS ledger), `runs` (run discovery + boundary
//! establishment + pinned load), `lease` (the heartbeat handle). Depends on `domain` (typed ids and
//! rows) and the `observability` metric constants — nothing else in the crate.

pub mod chunks;
pub mod lease;
pub mod runs;

use std::time::Duration;

/// The single character cap for every operator-facing error column (`chunk.last_error`,
/// `run.error`). Bound as `left($n, $m)` at each persistence site, and enforced again in Rust by
/// [`RenderedError`] so an un-truncated string can never reach the wire.
pub const PERSISTED_ERROR_LIMIT: i32 = 4096;

/// A validated worker identity, 1..=255 bytes — the width of `chunk.claimed_by`.
#[derive(Debug, Clone)]
pub struct Claimant(String);

impl Claimant {
    pub fn new(value: impl Into<String>) -> Result<Self, ClaimantError> {
        let value = value.into();
        let len = value.len();
        if !(1..=255).contains(&len) {
            return Err(ClaimantError(len));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("claimant must contain 1 to 255 bytes, got {0}")]
pub struct ClaimantError(pub usize);

/// A lease length validated to the deliberate ≥3 s floor. Storing seconds pre-converted lets the
/// heartbeat interval be exactly `lease / 3` with no `.max(1s)` guard: `secs >= 3` ⇒ `secs / 3 >= 1`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LeaseDuration {
    secs: i64,
}

impl LeaseDuration {
    pub fn new(duration: Duration) -> Result<Self, LeaseDurationError> {
        if duration < Duration::from_secs(3) {
            return Err(LeaseDurationError::TooShort);
        }
        let secs = i64::try_from(duration.as_secs()).map_err(|_| LeaseDurationError::TooLong)?;
        Ok(Self { secs })
    }

    pub const fn as_secs(self) -> i64 {
        self.secs
    }

    pub fn heartbeat_interval(self) -> Duration {
        Duration::from_secs(u64::try_from(self.secs / 3).unwrap_or(1))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum LeaseDurationError {
    #[error("chunk lease must be at least three seconds")]
    TooShort,
    #[error("chunk lease exceeds PostgreSQL interval range")]
    TooLong,
}

/// A retry ceiling validated to 1..=i32::MAX (the width of `chunk.attempts`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MaxAttempts(i32);

impl MaxAttempts {
    pub fn new(value: u32) -> Result<Self, MaxAttemptsError> {
        if value == 0 {
            return Err(MaxAttemptsError::Zero);
        }
        let value = i32::try_from(value).map_err(|_| MaxAttemptsError::OutOfRange(value))?;
        Ok(Self(value))
    }

    pub const fn get(self) -> i32 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum MaxAttemptsError {
    #[error("maximum attempts must be greater than zero")]
    Zero,
    #[error("maximum attempts {0} exceeds PostgreSQL integer range")]
    OutOfRange(u32),
}

/// An error already flattened to its full cause chain and truncated at a character boundary. The
/// persistence sites (`store.fail`, `fail_run`) accept only this, so a bare `.to_string()` — which
/// loses source context — cannot reach the wire.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RenderedError(String);

impl RenderedError {
    pub fn render(error: &dyn std::error::Error) -> Self {
        Self(render_error_chain(error))
    }

    pub fn from_message(message: impl Into<String>) -> Self {
        Self(truncate_chars(message.into(), PERSISTED_ERROR_LIMIT))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Flatten an error and its causes into `"top: cause: root"`, truncated to [`PERSISTED_ERROR_LIMIT`]
/// characters at a UTF-8 boundary.
pub fn render_error_chain(error: &dyn std::error::Error) -> String {
    let mut rendered = error.to_string();
    let mut source = error.source();
    while let Some(cause) = source {
        rendered.push_str(": ");
        rendered.push_str(&cause.to_string());
        source = cause.source();
    }
    truncate_chars(rendered, PERSISTED_ERROR_LIMIT)
}

fn truncate_chars(mut value: String, max_chars: i32) -> String {
    let max_chars = usize::try_from(max_chars).unwrap_or(0);
    if let Some((byte_idx, _)) = value.char_indices().nth(max_chars) {
        value.truncate(byte_idx);
    }
    value
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    #[derive(Debug, thiserror::Error)]
    #[error("outer")]
    struct Outer(#[source] Inner);

    #[derive(Debug, thiserror::Error)]
    #[error("inner")]
    struct Inner;

    #[test]
    fn render_error_chain_joins_the_source_chain() {
        assert_eq!(render_error_chain(&Outer(Inner)), "outer: inner");
    }

    #[test]
    fn rendered_error_truncates_on_a_char_boundary() {
        let multibyte = "é".repeat(5_000);
        let rendered = RenderedError::from_message(multibyte);
        assert_eq!(rendered.as_str().chars().count(), 4_096);
        // Truncation kept whole `é`s: the byte length is exactly 2 per char, never a split byte.
        assert_eq!(rendered.as_str().len(), 4_096 * 2);
    }

    #[test]
    fn value_objects_reject_out_of_range_inputs() {
        assert!(Claimant::new("").is_err());
        assert!(Claimant::new("x".repeat(256)).is_err());
        assert!(Claimant::new("worker").is_ok());
        assert!(LeaseDuration::new(Duration::from_secs(2)).is_err());
        assert_eq!(
            LeaseDuration::new(Duration::from_secs(9))
                .unwrap()
                .heartbeat_interval(),
            Duration::from_secs(3)
        );
        assert!(matches!(MaxAttempts::new(0), Err(MaxAttemptsError::Zero)));
        assert_eq!(MaxAttempts::new(5).unwrap().get(), 5);
    }
}
