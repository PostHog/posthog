//! `LeafStateKey` derivation and `Stage1Key`.
//!
//! The save-time `conditionHash` encodes only the event matcher (`value`, `key`, `event_filters`),
//! never the window/threshold/operator, so two leaves matching the same event with different
//! windows (e.g. "≥ 3 in 7d" vs "≥ 5 in 30d") collide on it. State is therefore keyed by a derived
//! [`LeafStateKey`] over the full per-leaf predicate configuration.
//!
//! [`LeafStateKey::for_behavioral`] is a cross-runtime contract a future Python port and the
//! save-time normalizer must reproduce **byte-for-byte**:
//!
//! 1. Fields are hashed in the order written below, with **no length delimiters**.
//! 2. Integer fields are little-endian, `0` for absent; optional strings use `""` for absent.
//! 3. `negation` is **excluded** — the state is invariant to it; the output is inverted at Stage 2.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::filters::tree::BehavioralLeafConfig;

/// 16-byte key that discriminates Stage 1 state per cohort leaf. For person-property leaves it
/// equals `condition_hash`; for behavioral leaves it is the SHA-256 over the full predicate config.
///
/// The `Serialize`/`Deserialize` form is not a cross-runtime contract — only the hash *input* in
/// [`LeafStateKey::for_behavioral`] is.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
pub struct LeafStateKey(pub [u8; 16]);

impl LeafStateKey {
    /// Person-property leaves reuse `condition_hash` unchanged — the bytecode already encodes key,
    /// value, and operator.
    pub fn for_person_property(condition_hash: &[u8; 16]) -> Self {
        Self(*condition_hash)
    }

    /// Hash the full predicate config per the cross-runtime contract at the module level — do not
    /// reorder fields or insert separators without updating the Python port.
    pub fn for_behavioral(leaf: &BehavioralLeafConfig) -> Self {
        let mut h = Sha256::new();
        h.update(leaf.condition_hash);
        h.update(leaf.value.as_str().as_bytes());
        h.update(leaf.time_value.unwrap_or(0).to_le_bytes());
        h.update(leaf.time_interval.as_deref().unwrap_or("").as_bytes());
        h.update(leaf.explicit_datetime.as_deref().unwrap_or("").as_bytes());
        h.update(
            leaf.explicit_datetime_to
                .as_deref()
                .unwrap_or("")
                .as_bytes(),
        );
        h.update(leaf.operator.as_deref().unwrap_or("").as_bytes());
        h.update(leaf.operator_value.unwrap_or(0).to_le_bytes());

        let digest = h.finalize();
        let mut out = [0u8; 16];
        out.copy_from_slice(&digest[..16]);
        Self(out)
    }
}

/// Stage 1 state-storage key. The partition prefix enables per-partition `delete_range` on
/// rebalance; the byte encoding belongs to the RocksDB store.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Stage1Key {
    pub partition_id: u16,
    pub team_id: u64,
    pub leaf_state_key: LeafStateKey,
    pub person_id: Uuid,
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::filters::tree::{BehavioralLeafConfig, BehavioralValue};

    const HASH: [u8; 16] = *b"0123456789abcdef";

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
            bytecode: Arc::new(vec![]),
        }
        .with_state_key()
    }

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

    /// Cross-runtime contract fixture: the Python port must reproduce the exact 16-byte digest in
    /// [`for_behavioral_matches_known_vector`]. Every hashed field is a distinct, non-default value
    /// so the vector pins each field's position; the hashed input, in order, no delimiters:
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
            bytecode: Arc::new(vec![]),
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
        // `event_key` is not hashed: the event name is already in `condition_hash`, so hashing it
        // again would diverge from the Python normalizer's field set.
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
        // `negation` is structurally absent from `BehavioralLeafConfig`: the state is invariant to
        // it and the output is inverted at Stage 2.
        assert_eq!(
            LeafStateKey::for_behavioral(&baseline()),
            LeafStateKey::for_behavioral(&baseline()),
        );
    }
}
