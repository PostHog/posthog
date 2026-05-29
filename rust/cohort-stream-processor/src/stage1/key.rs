//! `LeafStateKey` derivation and `Stage1Key` (TDD §4.1.0).
//!
//! ## Why state is keyed per leaf, not per `conditionHash`
//!
//! The save-time `conditionHash` is `sha256(bytecode)[:16]`, and the bytecode
//! (`posthog/cdp/filters.py::build_behavioral_event_expr`) encodes **only** the event
//! matcher (`value` as a gate, `key`, `event_filters`) — never `time_value`,
//! `time_interval`, `operator`, `operator_value`, `explicit_datetime`,
//! `explicit_datetime_to`, or `negation`. So two leaves that match the same event but use
//! different windows/thresholds (e.g. "performed `$pageview` ≥ 3 in 7d" vs "≥ 5 in 30d")
//! collide on `conditionHash` yet need entirely different Stage 1 state. State is therefore
//! keyed by a derived [`LeafStateKey`] that discriminates by the full per-leaf predicate
//! configuration.
//!
//! ## Cross-runtime hashing contract
//!
//! [`LeafStateKey::for_behavioral`] is a stable contract: a future Python port
//! (`posthog/models/cohort/leaf_state_key.py`, Phase 7) and the §4.10 save-time normalizer
//! must reproduce it **byte-for-byte**. The rules, which the port copies verbatim:
//!
//! 1. The fields are hashed in the exact order written below.
//! 2. There are **no length delimiters** between fields — bytes are concatenated directly.
//! 3. Integer fields use little-endian (`i32::to_le_bytes`), with `0` for an absent value.
//! 4. Optional string fields use the empty string `""` for an absent value.
//! 5. `negation` is **excluded** (D12 — the state data is invariant to negation; the
//!    predicate output is inverted at Stage 2 composition time).

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::filters::tree::BehavioralLeafConfig;

/// 16-byte key that discriminates Stage 1 state per cohort leaf.
///
/// For person-property leaves it equals the leaf's `condition_hash` (the bytecode already
/// encodes key + value + operator). For behavioral leaves it is the truncated SHA-256 over
/// the full predicate configuration — see [`LeafStateKey::for_behavioral`].
///
/// The `Serialize`/`Deserialize` impls exist for state storage; the serialized *form* is
/// not a cross-runtime contract (only the hash *input* in `for_behavioral` is).
#[derive(Copy, Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
pub struct LeafStateKey(pub [u8; 16]);

impl LeafStateKey {
    /// Person-property leaves reuse the `condition_hash` unchanged: the bytecode already
    /// encodes the key, value, and operator, so no widening is necessary.
    pub fn for_person_property(condition_hash: &[u8; 16]) -> Self {
        Self(*condition_hash)
    }

    /// Behavioral leaves hash the full predicate configuration. The field order, LE-int,
    /// empty-string, and no-delimiter rules are the cross-runtime contract documented at the
    /// module level — do not reorder or insert separators without updating the Python port.
    pub fn for_behavioral(leaf: &BehavioralLeafConfig) -> Self {
        let mut h = Sha256::new();
        h.update(leaf.condition_hash);
        // `value` discriminates performed_event vs performed_event_multiple, which need
        // different state representations.
        h.update(leaf.value.as_str().as_bytes());
        // Window spec: one of (time_value + time_interval) or explicit_datetime[_to].
        h.update(leaf.time_value.unwrap_or(0).to_le_bytes());
        h.update(leaf.time_interval.as_deref().unwrap_or("").as_bytes());
        h.update(leaf.explicit_datetime.as_deref().unwrap_or("").as_bytes());
        h.update(
            leaf.explicit_datetime_to
                .as_deref()
                .unwrap_or("")
                .as_bytes(),
        );
        // Predicate (only meaningful for performed_event_multiple).
        h.update(leaf.operator.as_deref().unwrap_or("").as_bytes());
        h.update(leaf.operator_value.unwrap_or(0).to_le_bytes());

        let digest = h.finalize();
        let mut out = [0u8; 16];
        out.copy_from_slice(&digest[..16]);
        Self(out)
    }
}

/// Stage 1 state-storage key. The partition prefix enables per-partition `delete_range` on
/// rebalance (the byte *encoding* of this struct belongs to PR 1.2's RocksDB store; only the
/// struct shape is defined here). `team_id` is `u64` per §4.1.0 and is converted from the
/// catalog's `i32` `TeamId` at the store boundary in PR 1.6.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Stage1Key {
    pub partition_id: u16,
    pub team_id: u64,
    pub leaf_state_key: LeafStateKey,
    pub person_id: Uuid,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::filters::tree::{BehavioralLeafConfig, BehavioralValue};

    const HASH: [u8; 16] = *b"0123456789abcdef";

    /// A `performed_event_multiple` leaf with every discriminating field populated, the
    /// baseline for the discrimination matrix.
    fn baseline() -> BehavioralLeafConfig {
        BehavioralLeafConfig {
            condition_hash: HASH,
            value: BehavioralValue::PerformedEventMultiple,
            event_key: "$pageview".to_string(),
            time_value: Some(7),
            time_interval: Some("day".to_string()),
            operator: Some("gte".to_string()),
            operator_value: Some(3),
            explicit_datetime: None,
            explicit_datetime_to: None,
            leaf_state_key: LeafStateKey([0u8; 16]),
            state_variant: None,
        }
        .with_state_key()
    }

    /// Assert that mutating one field of the baseline changes the derived key.
    fn assert_field_discriminates(mutate: impl FnOnce(&mut BehavioralLeafConfig)) {
        let base = baseline();
        let mut variant = base.clone();
        mutate(&mut variant);
        assert_ne!(
            LeafStateKey::for_behavioral(&base),
            LeafStateKey::for_behavioral(&variant),
        );
    }

    #[test]
    fn person_property_key_is_the_condition_hash() {
        assert_eq!(LeafStateKey::for_person_property(&HASH), LeafStateKey(HASH));
    }

    #[test]
    fn behavioral_key_is_deterministic() {
        assert_eq!(
            LeafStateKey::for_behavioral(&baseline()),
            LeafStateKey::for_behavioral(&baseline()),
        );
    }

    /// A fully-populated leaf with every hashed field set to a distinct, non-default value, so
    /// the expected digest pins each field's *position* in the byte layout — reordering any two
    /// `h.update(...)` calls, or changing the LE-int / empty-string / no-delimiter encoding,
    /// flips this vector while leaving the relative (discrimination/determinism) tests green.
    ///
    /// This is the cross-runtime contract fixture: the Phase-7 Python port
    /// (`leaf_state_key.py`) and the §4.10 normalizer must reproduce the exact 16 bytes below.
    /// The hashed input, in order, no delimiters (see [`LeafStateKey::for_behavioral`]):
    ///   `b"0123456789abcdef"` ++ `b"performed_event_multiple"` ++ `7i32.to_le_bytes()`
    ///   ++ `b"day"` ++ `b"2026-01-01T00:00:00Z"` ++ `b"2026-02-01T00:00:00Z"`
    ///   ++ `b"gte"` ++ `3i32.to_le_bytes()`, then `sha256(..)[..16]`.
    fn golden_leaf() -> BehavioralLeafConfig {
        BehavioralLeafConfig {
            condition_hash: HASH,
            value: BehavioralValue::PerformedEventMultiple,
            event_key: "$pageview".to_string(),
            time_value: Some(7),
            time_interval: Some("day".to_string()),
            operator: Some("gte".to_string()),
            operator_value: Some(3),
            explicit_datetime: Some("2026-01-01T00:00:00Z".to_string()),
            explicit_datetime_to: Some("2026-02-01T00:00:00Z".to_string()),
            leaf_state_key: LeafStateKey([0u8; 16]),
            state_variant: None,
        }
        .with_state_key()
    }

    #[test]
    fn for_behavioral_matches_known_vector() {
        const EXPECTED: [u8; 16] = [
            0xac, 0xe2, 0xf2, 0x56, 0xd8, 0x43, 0x41, 0xa9, 0x2d, 0x9f, 0xeb, 0xe4, 0x44, 0x9a,
            0x41, 0xb7,
        ];
        assert_eq!(
            LeafStateKey::for_behavioral(&golden_leaf()),
            LeafStateKey(EXPECTED),
            "the cross-runtime hash encoding changed; update the Python port + §4.10 normalizer \
             to match, or revert the encoding change",
        );
    }

    #[test]
    fn event_key_is_excluded_from_the_key() {
        // `event_key` is captured for Stage 1's matcher/state-variant picking (PR 1.6) but is
        // *not* hashed: the event name is already encoded in `condition_hash` (it is part of the
        // bytecode), so hashing it again would diverge from the §4.10 Python normalizer's field
        // set. Two leaves differing only in `event_key` must share a key.
        let mut other = golden_leaf();
        other.event_key = "$autocapture".to_string();
        assert_eq!(
            LeafStateKey::for_behavioral(&golden_leaf()),
            LeafStateKey::for_behavioral(&other),
        );
    }

    #[test]
    fn with_state_key_caches_the_derived_key() {
        let leaf = baseline();
        assert_eq!(leaf.leaf_state_key, LeafStateKey::for_behavioral(&leaf));
    }

    #[test]
    fn behavioral_key_differs_from_raw_condition_hash() {
        // A behavioral leaf must never collide with the person-property reuse of the same hash.
        assert_ne!(
            LeafStateKey::for_behavioral(&baseline()),
            LeafStateKey::for_person_property(&HASH),
        );
    }

    #[test]
    fn each_discriminating_field_changes_the_key() {
        assert_field_discriminates(|l| l.value = BehavioralValue::PerformedEvent);
        assert_field_discriminates(|l| l.time_value = Some(30));
        assert_field_discriminates(|l| l.time_interval = Some("week".to_string()));
        assert_field_discriminates(|l| l.operator = Some("lte".to_string()));
        assert_field_discriminates(|l| l.operator_value = Some(5));
        assert_field_discriminates(|l| l.explicit_datetime = Some("2026-01-01".to_string()));
        assert_field_discriminates(|l| l.explicit_datetime_to = Some("2026-02-01".to_string()));
    }

    #[test]
    fn condition_hash_changes_the_key() {
        assert_field_discriminates(|l| l.condition_hash = *b"fedcba9876543210");
    }

    #[test]
    fn negation_is_excluded_from_the_key() {
        // `negation` is structurally absent from `BehavioralLeafConfig` (D12): two otherwise
        // identical leaves share a key regardless of negation, because the state data is
        // invariant to it and the predicate output is inverted at Stage 2.
        assert_eq!(
            LeafStateKey::for_behavioral(&baseline()),
            LeafStateKey::for_behavioral(&baseline()),
        );
    }
}
