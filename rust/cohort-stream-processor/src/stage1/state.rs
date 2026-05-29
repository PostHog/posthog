//! Per-leaf Stage 1 state, its persisted wrapper, and the value codec (TDD §4.1, §4.1.1).
//!
//! PR 1.6 ships exactly the two M1 state variants — [`Stage1State::BehavioralSingle`] for
//! `performed_event` and [`Stage1State::PersonProperty`] for person-property leaves. The bucket
//! variants for `performed_event_multiple` (TDD §4.1) are PR 2.1; the internal `#[serde(tag = "v")]`
//! discriminator makes adding them a purely additive change to the on-disk form.
//!
//! ## Codec choice
//!
//! [`StatefulRecord`] serializes with `serde_json` (no new workspace dependency). M1 is shadow-only,
//! so no persisted state must survive a future codec swap — the store returns opaque bytes
//! ([`crate::store::CohortStore::get_stage1`]) and the value format is entirely owned here. A
//! compact binary codec is flagged as an M9 perf item, not a correctness concern.

use serde::{Deserialize, Serialize};

/// Which state representation a leaf's [`Stage1State`] uses — the lightweight discriminator the
/// filter catalog records per [`crate::stage1::key::LeafStateKey`] so the worker can pick the
/// right apply path without decoding stored state first. PR 2.1 adds the bucket variants.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum StateVariant {
    /// `performed_event` (any interval): a single "has any matching event in window" bit.
    BehavioralSingle,
    /// A person-property filter: a last-write-wins boolean.
    PersonProperty,
}

impl StateVariant {
    /// The metric-label / log form. Stable across the codebase so the same series is emitted
    /// everywhere this variant is reported.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BehavioralSingle => "behavioral_single",
            Self::PersonProperty => "person_property",
        }
    }
}

/// The incremental per-`(team_id, leaf_state_key, person_id)` state a leaf maintains (TDD §4.1).
///
/// The `#[serde(tag = "v")]` discriminator is written into every serialized record, so PR 2.1's
/// bucket variants slot in additively and an unknown tag decodes to an `Err` (forward-compat;
/// see [`StatefulRecord::decode`]).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "v")]
pub enum Stage1State {
    /// `performed_event`: membership is simply "has matched at least once in the live window".
    /// M1 never clears `has_match` (eviction is PR 2.2–2.3), so the predicate only ever flips
    /// `false → true`.
    BehavioralSingle {
        has_match: bool,
        /// Most recent matching event time (epoch ms). `max`-folded across events.
        last_event_at_ms: i64,
        /// Earliest time (epoch ms) the sweep may evict this state. Computed but not yet acted
        /// on in PR 1.6 — eviction firing is PR 2.2–2.3.
        earliest_eviction_at_ms: i64,
    },
    /// A person-property filter: last-write-wins boolean, tie-broken by event-time argMax
    /// (TDD §4.1.1: `argMax(matches, (_timestamp, _offset))`).
    PersonProperty {
        matches: bool,
        /// Event time (epoch ms) of the write that set `matches` — the argMax key's first
        /// component.
        last_updated_at_ms: i64,
        /// Source offset of that write — the argMax key's tiebreaker second component.
        last_updated_offset: i64,
    },
}

impl Stage1State {
    /// The [`StateVariant`] this value represents — for metric labelling at write time.
    pub fn variant(&self) -> StateVariant {
        match self {
            Self::BehavioralSingle { .. } => StateVariant::BehavioralSingle,
            Self::PersonProperty { .. } => StateVariant::PersonProperty,
        }
    }
}

/// The persisted `cf_stage1` value: a [`Stage1State`] plus the source `(partition, offset)` of the
/// last event folded into it (TDD §4.1.1). The source coordinates make non-idempotent folds
/// replay-safe via [`crate::partitions::offset_tracker::is_replay`].
///
/// TODO(PR 2.1): this single `(partition, offset)` pair only dedups replays within one source
/// partition. The shuffler re-keys by `hash(team_id, person_id)`, so one person's events can span
/// multiple source partitions; a replay from a *different* source partition than the one stored
/// here is re-applied (`is_replay` returns false). Harmless for M1's idempotent folds (`has_match`
/// OR, event-time argMax), but PR 2.1's non-idempotent `buckets[i] += 1` needs a
/// per-source-partition last-applied map (or a dedicated CF). See TDD §10 L11.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StatefulRecord {
    pub state: Stage1State,
    /// Source partition of the last event applied (defends the replay check against a re-key /
    /// rebalance moving a key to a different upstream partition — §4.1.1).
    pub last_applied_partition: i32,
    /// Source offset of the last event applied. On replay, an offset `≤` this on the same source
    /// partition is skipped.
    pub last_applied_offset: i64,
}

/// A failure decoding a stored [`StatefulRecord`]. Surfaced (never panicked) so a single corrupt
/// row is skipped + counted rather than taking down the worker — mirrors the merge operator's
/// "never panic" discipline (`store::secondary_index`).
#[derive(Debug, thiserror::Error)]
#[error("decoding Stage1 record: {0}")]
pub struct StateCodecError(#[from] serde_json::Error);

impl StatefulRecord {
    /// Encode to the stored byte form. Infallible for these plain structs — `serde_json` only
    /// errors on a `Serialize` impl that refuses or a map with non-string keys, neither of which
    /// occurs here.
    pub fn encode(&self) -> Vec<u8> {
        serde_json::to_vec(self).expect("StatefulRecord is plain data and always serializes")
    }

    /// Decode from the stored byte form. Garbage bytes and unknown `"v"` tags both yield an
    /// [`Err`] (the latter is the PR 2.1 forward-compat contract), never a panic.
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
        // PR 2.1 forward-compat: a future bucket variant tag must surface as Err on a PR-1.6
        // binary rather than silently deserializing into the wrong shape.
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
