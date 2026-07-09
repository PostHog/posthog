//! The persisted `cf_stage2` membership state and its JSON codec.

use serde::{Deserialize, Serialize};

/// The composed membership of one `(cohort, person)`: whether the person is in the cohort, and when
/// that was last evaluated.
///
/// `last_evaluated_at_ms` is write-only for now (nothing reads it). It is the source event's
/// timestamp, not a wall clock, so the value is replay-stable.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Stage2State {
    pub in_cohort: bool,
    pub last_evaluated_at_ms: i64,
}

/// A failure decoding a stored [`Stage2State`]; surfaced (never panicked) so a single corrupt row is
/// skipped rather than taking down the worker.
#[derive(Debug, thiserror::Error)]
#[error("decoding Stage2 state: {0}")]
pub struct Stage2CodecError(#[from] serde_json::Error);

impl Stage2State {
    /// Infallible for this plain struct — `serde_json` only errors on a refusing `Serialize` or
    /// non-string map keys, neither of which occurs here.
    pub fn encode(&self) -> Vec<u8> {
        serde_json::to_vec(self).expect("Stage2State is plain data and always serializes")
    }

    /// Garbage bytes and missing fields both yield an [`Err`], never a panic.
    pub fn decode(bytes: &[u8]) -> Result<Self, Stage2CodecError> {
        Ok(serde_json::from_slice(bytes)?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_both_bits() {
        for in_cohort in [true, false] {
            let state = Stage2State {
                in_cohort,
                last_evaluated_at_ms: 1_700_000_000_123,
            };
            let bytes = state.encode();
            assert_eq!(Stage2State::decode(&bytes).unwrap(), state);
        }
    }

    #[test]
    fn decodes_from_its_on_disk_shape() {
        // Pin the on-disk JSON so a future codec change is caught.
        let on_disk = serde_json::json!({
            "in_cohort": true,
            "last_evaluated_at_ms": 1_700_000_000_123_i64,
        });
        let bytes = serde_json::to_vec(&on_disk).unwrap();
        assert_eq!(
            Stage2State::decode(&bytes).unwrap(),
            Stage2State {
                in_cohort: true,
                last_evaluated_at_ms: 1_700_000_000_123,
            },
        );
    }

    #[test]
    fn garbage_bytes_decode_to_err_not_panic() {
        assert!(Stage2State::decode(b"not json at all").is_err());
        assert!(Stage2State::decode(&[]).is_err());
        // A missing required field is an error, not a silent default.
        let partial = serde_json::to_vec(&serde_json::json!({ "in_cohort": true })).unwrap();
        assert!(Stage2State::decode(&partial).is_err());
    }
}
