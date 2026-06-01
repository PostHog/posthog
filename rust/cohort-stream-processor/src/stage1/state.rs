//! Per-leaf Stage 1 state, its persisted wrapper, and the value codec.
//!
//! The internal `#[serde(tag = "v")]` discriminator makes adding the `performed_event_multiple`
//! bucket variants a purely additive change to the on-disk form.

use serde::{Deserialize, Serialize};

/// Which state representation a leaf uses; recorded per [`crate::stage1::key::LeafStateKey`] so the
/// worker can pick the apply path without decoding stored state first.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum StateVariant {
    /// `performed_event`: a single "has any matching event in window" bit.
    BehavioralSingle,
    /// A person-property filter: a last-write-wins boolean.
    PersonProperty,
}

impl StateVariant {
    /// The metric-label / log form.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BehavioralSingle => "behavioral_single",
            Self::PersonProperty => "person_property",
        }
    }
}

/// The incremental per-`(team_id, leaf_state_key, person_id)` state a leaf maintains.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "v")]
pub enum Stage1State {
    /// `performed_event`. `has_match` is never cleared, so the predicate only flips `false → true`.
    BehavioralSingle {
        has_match: bool,
        /// Most recent matching event time (epoch ms), `max`-folded across events.
        last_event_at_ms: i64,
        /// Earliest time (epoch ms) the sweep may evict this state.
        earliest_eviction_at_ms: i64,
    },
    /// A person-property filter: last-write-wins, tie-broken by event-time argMax
    /// (`argMax(matches, (_timestamp, _offset))`).
    PersonProperty {
        matches: bool,
        /// The argMax key's first component.
        last_updated_at_ms: i64,
        /// The argMax key's tiebreaker second component.
        last_updated_offset: i64,
    },
}

impl Stage1State {
    pub fn variant(&self) -> StateVariant {
        match self {
            Self::BehavioralSingle { .. } => StateVariant::BehavioralSingle,
            Self::PersonProperty { .. } => StateVariant::PersonProperty,
        }
    }
}

/// The persisted `cf_stage1` value: a [`Stage1State`] plus the source `(partition, offset)` of the
/// last event folded in, which makes non-idempotent folds replay-safe via
/// [`crate::partitions::offset_tracker::is_replay`].
///
/// Limitation: one `(partition, offset)` pair only dedups within a single source partition. The
/// shuffler re-keys by `hash(team_id, person_id)`, so a replay from a *different* source partition
/// is re-applied. Harmless for the current idempotent folds, but a future non-idempotent
/// `buckets[i] += 1` would need a per-source-partition last-applied map.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StatefulRecord {
    pub state: Stage1State,
    pub last_applied_partition: i32,
    pub last_applied_offset: i64,
}

/// A failure decoding a stored [`StatefulRecord`]; surfaced (never panicked) so a single corrupt
/// row is skipped rather than taking down the worker.
#[derive(Debug, thiserror::Error)]
#[error("decoding Stage1 record: {0}")]
pub struct StateCodecError(#[from] serde_json::Error);

impl StatefulRecord {
    /// Infallible for these plain structs — `serde_json` only errors on a refusing `Serialize` or
    /// non-string map keys, neither of which occurs here.
    pub fn encode(&self) -> Vec<u8> {
        serde_json::to_vec(self).expect("StatefulRecord is plain data and always serializes")
    }

    /// Garbage bytes and unknown `"v"` tags both yield an [`Err`] (forward-compat), never a panic.
    pub fn decode(bytes: &[u8]) -> Result<Self, StateCodecError> {
        Ok(serde_json::from_slice(bytes)?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn behavioral() -> StatefulRecord {
        StatefulRecord {
            state: Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: 1_700_000_000_000 + 7 * 86_400 * 1000,
            },
            last_applied_partition: 17,
            last_applied_offset: 42,
        }
    }

    fn person() -> StatefulRecord {
        StatefulRecord {
            state: Stage1State::PersonProperty {
                matches: false,
                last_updated_at_ms: 1_700_000_000_123,
                last_updated_offset: 99,
            },
            last_applied_partition: 3,
            last_applied_offset: 100,
        }
    }

    #[test]
    fn round_trips_both_variants() {
        for record in [behavioral(), person()] {
            let bytes = record.encode();
            assert_eq!(StatefulRecord::decode(&bytes).unwrap(), record);
        }
    }

    #[test]
    fn garbage_bytes_decode_to_err_not_panic() {
        assert!(StatefulRecord::decode(b"not json at all").is_err());
        assert!(StatefulRecord::decode(&[]).is_err());
    }

    #[test]
    fn unknown_variant_tag_is_a_decode_error() {
        // Forward-compat: a future variant tag must surface as Err, not deserialize into the wrong
        // shape.
        let forward = serde_json::json!({
            "state": { "v": "BehavioralDailyBuckets", "buckets": [1, 2, 3] },
            "last_applied_partition": 0,
            "last_applied_offset": 0,
        });
        let bytes = serde_json::to_vec(&forward).unwrap();
        assert!(StatefulRecord::decode(&bytes).is_err());
    }

    #[test]
    fn variant_reports_the_state_kind() {
        assert_eq!(behavioral().state.variant(), StateVariant::BehavioralSingle);
        assert_eq!(person().state.variant(), StateVariant::PersonProperty);
    }

    #[test]
    fn variant_labels_are_stable() {
        assert_eq!(StateVariant::BehavioralSingle.as_str(), "behavioral_single");
        assert_eq!(StateVariant::PersonProperty.as_str(), "person_property");
    }
}
