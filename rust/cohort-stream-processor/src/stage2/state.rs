//! The persisted `cf_stage2` membership state and its JSON codec.

use serde::{Deserialize, Serialize};

/// The registered membership of one `(cohort, person)`: whether the person is in the cohort, and
/// when that was last evaluated. Single-leaf cohorts write this directly from their leaf state;
/// composable cohorts write it after Boolean composition.
///
/// `last_evaluated_at_ms` is write-only for now (nothing reads it). Writers use the timestamp of the
/// operation that evaluated membership: event time for live/merge work, the sweep cutoff for
/// evictions, and application time for seed work.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Stage2State {
    pub in_cohort: bool,
    pub last_evaluated_at_ms: i64,
}

/// Who last established the persisted bit. Transfer fallbacks are deliberately explicit so the
/// first receiver-side evaluation can claim the row even when it computes identical membership.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Stage2Ownership {
    #[default]
    Local,
    TransferredFallback,
}

impl Stage2Ownership {
    const fn is_local(&self) -> bool {
        matches!(self, Self::Local)
    }
}

#[derive(Debug, Serialize, Deserialize)]
struct PersistedStage2State {
    in_cohort: bool,
    last_evaluated_at_ms: i64,
    #[serde(default, skip_serializing_if = "Stage2Ownership::is_local")]
    ownership: Stage2Ownership,
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

    /// Encode a conservative merge-carried fallback. The additive ownership field is omitted from
    /// ordinary rows, preserving their existing on-disk bytes.
    pub(crate) fn encode_transferred_fallback(&self) -> Vec<u8> {
        serde_json::to_vec(&PersistedStage2State {
            in_cohort: self.in_cohort,
            last_evaluated_at_ms: self.last_evaluated_at_ms,
            ownership: Stage2Ownership::TransferredFallback,
        })
        .expect("PersistedStage2State is plain data and always serializes")
    }

    /// Garbage bytes and missing fields both yield an [`Err`], never a panic.
    pub fn decode(bytes: &[u8]) -> Result<Self, Stage2CodecError> {
        Ok(Self::decode_with_ownership(bytes)?.0)
    }

    pub(crate) fn decode_with_ownership(
        bytes: &[u8],
    ) -> Result<(Self, Stage2Ownership), Stage2CodecError> {
        let persisted: PersistedStage2State = serde_json::from_slice(bytes)?;
        Ok((
            Self {
                in_cohort: persisted.in_cohort,
                last_evaluated_at_ms: persisted.last_evaluated_at_ms,
            },
            persisted.ownership,
        ))
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
    fn transferred_fallback_is_additive_and_decodes_through_the_normal_codec() {
        let state = Stage2State {
            in_cohort: false,
            last_evaluated_at_ms: 1_700_000_000_123,
        };
        let bytes = state.encode_transferred_fallback();

        assert_eq!(Stage2State::decode(&bytes).unwrap(), state);
        assert_eq!(
            Stage2State::decode_with_ownership(&bytes).unwrap(),
            (state, Stage2Ownership::TransferredFallback),
        );
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&bytes).unwrap(),
            serde_json::json!({
                "in_cohort": false,
                "last_evaluated_at_ms": 1_700_000_000_123_i64,
                "ownership": "transferred_fallback",
            }),
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
