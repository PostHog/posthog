//! Raw leaf JSON → classified leaf (TDD §2.7).
//!
//! Mirrors the Node filter manager's leaf gate (`realtime-supported-filter-manager-cdp.ts`)
//! and the save-time bytecode rules (`posthog/cdp/filters.py`): only leaves that produced
//! realtime bytecode (and therefore a `conditionHash`) are state-keyed; cohort references are
//! kept in the tree but not indexed; everything else is dropped with a reason for the counter.
//!
//! Optional predicate fields are read as-is — absent fields hash as `""`/`0` per the
//! [`LeafStateKey`] contract. Save-time default normalization (§4.10) is deferred.

use serde_json::Value;

use crate::filters::tree::{
    BehavioralLeafConfig, BehavioralValue, CohortLeaf, CohortRefLeafConfig, PersonLeafConfig,
};
use crate::filters::CohortId;
use crate::stage1::key::LeafStateKey;

/// Why a leaf was dropped during parse. Doubles as the `reason` label on the skip counter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeafDropReason {
    /// No `conditionHash`, or one that is not a 16-character string.
    MissingConditionHash,
    /// A behavioral `value` outside the two bytecode-producing types.
    UnsupportedBehavioralValue,
    /// A behavioral leaf keyed by an action id (integer `key`) — never produced bytecode.
    BehavioralActionKey,
    /// A leaf that matches none of the recognized shapes.
    MalformedLeaf,
}

impl LeafDropReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::MissingConditionHash => "missing_condition_hash",
            Self::UnsupportedBehavioralValue => "unsupported_behavioral_value",
            Self::BehavioralActionKey => "behavioral_action_key",
            Self::MalformedLeaf => "malformed_leaf",
        }
    }
}

/// The outcome of classifying one leaf. `Keep` is a state-keyed leaf (indexed); `CohortRef`
/// is kept in the tree but not indexed; `Drop` is counted and produces no node.
pub enum LeafClass {
    Keep(CohortLeaf),
    Drop(LeafDropReason),
    CohortRef(CohortRefLeafConfig),
}

/// Classify a single leaf node by its `type`.
pub fn classify_leaf(node: &Value) -> LeafClass {
    match node.get("type").and_then(Value::as_str) {
        Some("behavioral") => classify_behavioral(node),
        Some("cohort") => classify_cohort_ref(node),
        Some("person") => classify_person(node, LeafDropReason::MissingConditionHash),
        // Unknown/absent type: keep only if it still carries a conditionHash (some
        // person-property leaves omit an explicit "person" type); otherwise it is malformed.
        _ => classify_person(node, LeafDropReason::MalformedLeaf),
    }
}

fn classify_behavioral(node: &Value) -> LeafClass {
    // 1. The value must be one of the two bytecode-producing behavioral types.
    let value = match node
        .get("value")
        .and_then(Value::as_str)
        .and_then(BehavioralValue::from_wire)
    {
        Some(value) if value.contributes_bytecode() => value,
        _ => return LeafClass::Drop(LeafDropReason::UnsupportedBehavioralValue),
    };

    // 2. An integer `key` is an action id; action-keyed behavioral leaves never produced
    //    bytecode (`filters.py:341` returns None), so drop them with a distinct reason.
    if node.get("key").is_some_and(Value::is_number) {
        return LeafClass::Drop(LeafDropReason::BehavioralActionKey);
    }

    // 3. Require a 16-char conditionHash (schema-drift guard).
    let Some(condition_hash) = condition_hash_bytes(node.get("conditionHash")) else {
        return LeafClass::Drop(LeafDropReason::MissingConditionHash);
    };

    // 4. A non-empty string event key (guaranteed when bytecode exists, defended explicitly).
    let Some(event_key) = node
        .get("key")
        .and_then(Value::as_str)
        .filter(|key| !key.is_empty())
    else {
        return LeafClass::Drop(LeafDropReason::MalformedLeaf);
    };

    let leaf = BehavioralLeafConfig {
        condition_hash,
        value,
        event_key: event_key.to_string(),
        time_value: opt_i32(node.get("time_value")),
        operator_value: opt_i32(node.get("operator_value")),
        time_interval: opt_string(node.get("time_interval")),
        operator: opt_string(node.get("operator")),
        explicit_datetime: opt_string(node.get("explicit_datetime")),
        explicit_datetime_to: opt_string(node.get("explicit_datetime_to")),
        leaf_state_key: LeafStateKey([0u8; 16]),
        state_variant: None,
    }
    .with_state_key();

    LeafClass::Keep(CohortLeaf::Behavioral(leaf))
}

fn classify_cohort_ref(node: &Value) -> LeafClass {
    match cohort_id_from_value(node.get("value")) {
        Some(id) => LeafClass::CohortRef(CohortRefLeafConfig {
            referenced_cohort_id: CohortId(id),
            negation: node
                .get("negation")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        }),
        None => LeafClass::Drop(LeafDropReason::MalformedLeaf),
    }
}

fn classify_person(node: &Value, missing_reason: LeafDropReason) -> LeafClass {
    match condition_hash_bytes(node.get("conditionHash")) {
        Some(condition_hash) => LeafClass::Keep(CohortLeaf::PersonProperty(PersonLeafConfig {
            condition_hash,
            leaf_state_key: LeafStateKey::for_person_property(&condition_hash),
            raw: node.clone(),
        })),
        None => LeafClass::Drop(missing_reason),
    }
}

/// The 16 ASCII bytes of the hex `conditionHash` string. The hash is `sha256(bytecode)[:16]`,
/// i.e. exactly 16 ASCII hex chars; the bytes are carried verbatim (not hex-decoded) so the
/// [`LeafStateKey`] maps 1:1. Anything other than a 16-byte string is rejected.
fn condition_hash_bytes(value: Option<&Value>) -> Option<[u8; 16]> {
    let hash = value?.as_str()?;
    let bytes = hash.as_bytes();
    if bytes.len() == 16 {
        let mut out = [0u8; 16];
        out.copy_from_slice(bytes);
        Some(out)
    } else {
        None
    }
}

/// A referenced cohort id, stored as a JSON number or a string-encoded int (`cohort.py` does
/// `int(cohort_id)`); accept either, mirroring that coercion.
fn cohort_id_from_value(value: Option<&Value>) -> Option<i32> {
    let value = value?;
    if let Some(number) = value.as_i64() {
        return i32::try_from(number).ok();
    }
    value.as_str()?.trim().parse().ok()
}

fn opt_i32(value: Option<&Value>) -> Option<i32> {
    value?
        .as_i64()
        .and_then(|number| i32::try_from(number).ok())
}

fn opt_string(value: Option<&Value>) -> Option<String> {
    Some(value?.as_str()?.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const HASH: &str = "0123456789abcdef";

    fn hash_bytes() -> [u8; 16] {
        *b"0123456789abcdef"
    }

    #[test]
    fn behavioral_multiple_is_kept_with_cached_key() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event_multiple",
            "key": "$pageview",
            "time_value": 7,
            "time_interval": "day",
            "operator": "gte",
            "operator_value": 3,
            "conditionHash": HASH,
        });
        let LeafClass::Keep(CohortLeaf::Behavioral(leaf)) = classify_leaf(&node) else {
            panic!("expected a kept behavioral leaf");
        };
        assert_eq!(leaf.condition_hash, hash_bytes());
        assert_eq!(leaf.value, BehavioralValue::PerformedEventMultiple);
        assert_eq!(leaf.event_key, "$pageview");
        assert_eq!(leaf.time_value, Some(7));
        assert_eq!(leaf.operator.as_deref(), Some("gte"));
        assert_eq!(leaf.leaf_state_key, LeafStateKey::for_behavioral(&leaf));
    }

    #[test]
    fn unsupported_behavioral_value_is_dropped() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event_sequence",
            "key": "$pageview",
            "conditionHash": HASH,
        });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::UnsupportedBehavioralValue)
        ));
    }

    #[test]
    fn action_keyed_behavioral_is_dropped() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": 12345,
            "conditionHash": HASH,
        });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::BehavioralActionKey)
        ));
    }

    #[test]
    fn behavioral_without_condition_hash_is_dropped() {
        let node = json!({ "type": "behavioral", "value": "performed_event", "key": "$pageview" });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::MissingConditionHash)
        ));
    }

    #[test]
    fn short_condition_hash_is_rejected() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "conditionHash": "tooshort",
        });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::MissingConditionHash)
        ));
    }

    #[test]
    fn person_leaf_reuses_condition_hash_as_key() {
        let node = json!({
            "type": "person",
            "key": "email",
            "value": "a@b.com",
            "conditionHash": HASH,
        });
        let LeafClass::Keep(CohortLeaf::PersonProperty(leaf)) = classify_leaf(&node) else {
            panic!("expected a kept person leaf");
        };
        assert_eq!(leaf.condition_hash, hash_bytes());
        assert_eq!(leaf.leaf_state_key, LeafStateKey(hash_bytes()));
        assert_eq!(leaf.raw, node);
    }

    #[test]
    fn person_leaf_without_condition_hash_is_dropped() {
        let node = json!({ "type": "person", "key": "email", "value": "a@b.com" });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::MissingConditionHash)
        ));
    }

    #[test]
    fn cohort_ref_accepts_int_and_string_ids() {
        let int_ref = json!({ "type": "cohort", "value": 42 });
        let LeafClass::CohortRef(config) = classify_leaf(&int_ref) else {
            panic!("expected a cohort ref");
        };
        assert_eq!(config.referenced_cohort_id, CohortId(42));
        assert!(!config.negation);

        let str_ref = json!({ "type": "cohort", "value": "99", "negation": true });
        let LeafClass::CohortRef(config) = classify_leaf(&str_ref) else {
            panic!("expected a cohort ref");
        };
        assert_eq!(config.referenced_cohort_id, CohortId(99));
        assert!(config.negation);
    }

    #[test]
    fn cohort_ref_without_value_is_dropped() {
        let node = json!({ "type": "cohort" });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::MalformedLeaf)
        ));
    }

    #[test]
    fn unknown_type_with_condition_hash_is_a_person_leaf() {
        let node = json!({ "type": "event", "key": "$pageview", "conditionHash": HASH });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Keep(CohortLeaf::PersonProperty(_))
        ));
    }

    #[test]
    fn unknown_type_without_condition_hash_is_malformed() {
        let node = json!({ "foo": "bar" });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::MalformedLeaf)
        ));
    }
}
