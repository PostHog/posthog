//! `LeafStateKey` derivation.
//!
//! `conditionHash` encodes only the event matcher, so two leaves with different windows can share
//! the same hash. State is keyed by a [`LeafStateKey`] that hashes the full predicate configuration.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::filters::tree::BehavioralLeafConfig;

/// 16-byte key discriminating Stage 1 state per cohort leaf.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
pub struct LeafStateKey(pub [u8; 16]);

impl LeafStateKey {
    /// Person-property leaves reuse `condition_hash` unchanged.
    pub fn for_person_property(condition_hash: &[u8; 16]) -> Self {
        Self(*condition_hash)
    }

    /// Hash the full predicate config. Field order must match the Python port
    /// (`_extract_leaf_state_keys` in `posthog/models/cohort/dependencies.py`).
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
            negated: false,
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

    /// Golden vector leaf with every field set to a distinct, non-default value.
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
            negated: false,
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
            "the cross-runtime hash encoding changed; update the Python port to match",
        );
    }

    #[test]
    fn event_key_is_excluded_from_the_key() {
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
        let positive = baseline();
        let mut negated = baseline();
        negated.negated = true;
        assert_eq!(
            LeafStateKey::for_behavioral(&positive),
            LeafStateKey::for_behavioral(&negated),
            "configs differing only in `negated` must hash equal — state is invariant to negation",
        );
    }
}
