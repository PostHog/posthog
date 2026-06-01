//! Raw leaf JSON → classified leaf.
//!
//! Mirrors the Node filter manager's leaf gate (`realtime-supported-filter-manager-cdp.ts`) and the
//! save-time bytecode rules (`posthog/cdp/filters.py`): only leaves that produced realtime bytecode
//! (and therefore a `conditionHash`) are state-keyed; cohort references are kept in the tree but
//! not indexed; everything else is dropped with a reason for the counter.
//!
//! Absent optional predicate fields hash as `""`/`0` per the [`LeafStateKey`] contract.

use std::sync::Arc;

use serde_json::Value;

use crate::filters::tree::{
    BehavioralLeafConfig, BehavioralValue, CohortLeaf, CohortRefLeafConfig, PersonLeafConfig,
};
use crate::filters::CohortId;
use crate::stage1::key::LeafStateKey;
use crate::stage1::pick_state::pick_state_variant;

/// Why a leaf was dropped during parse. Doubles as the `reason` label on the skip counter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeafDropReason {
    /// No `conditionHash`, or one that is not a 16-character string.
    MissingConditionHash,
    /// No inline array `bytecode`. Node gates on `conditionHash` *and* `bytecode` (`manager.ts:137`).
    MissingBytecode,
    /// A behavioral `value` outside the two bytecode-producing types.
    UnsupportedBehavioralValue,
    /// A behavioral leaf keyed by an action id (integer `key`) — never produced bytecode.
    BehavioralActionKey,
    /// A bytecode-bearing behavioral leaf whose Stage 1 state variant is not yet representable
    /// (`performed_event_multiple`, or a `performed_event` with no resolvable window). Dropped here
    /// so an unsupported variant never reaches the worker.
    UnsupportedStateVariant,
    /// A `type` outside `{person, behavioral, cohort}`. Matches Node, which logs and skips
    /// (`realtime-supported-filter-manager-cdp.ts:146-159`); canonical cohorts always carry a
    /// `type`, so this only fires on malformed input.
    UnknownLeafType,
    /// A leaf that matches none of the recognized shapes.
    MalformedLeaf,
}

impl LeafDropReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::MissingConditionHash => "missing_condition_hash",
            Self::MissingBytecode => "missing_bytecode",
            Self::UnsupportedBehavioralValue => "unsupported_behavioral_value",
            Self::BehavioralActionKey => "behavioral_action_key",
            Self::UnsupportedStateVariant => "unsupported_state_variant",
            Self::UnknownLeafType => "unknown_leaf_type",
            Self::MalformedLeaf => "malformed_leaf",
        }
    }
}

/// The outcome of classifying one leaf: a state-keyed `Keep`, an unindexed `CohortRef` kept in the
/// tree, or a counted `Drop` that produces no node.
pub enum LeafClass {
    Keep(CohortLeaf),
    Drop(LeafDropReason),
    CohortRef(CohortRefLeafConfig),
}

pub fn classify_leaf(node: &Value) -> LeafClass {
    match node.get("type").and_then(Value::as_str) {
        Some("behavioral") => classify_behavioral(node),
        Some("cohort") => classify_cohort_ref(node),
        Some("person") => classify_person(node),
        _ => LeafClass::Drop(LeafDropReason::UnknownLeafType),
    }
}

fn classify_behavioral(node: &Value) -> LeafClass {
    let value = match node
        .get("value")
        .and_then(Value::as_str)
        .and_then(BehavioralValue::from_wire)
    {
        Some(value) if value.contributes_bytecode() => value,
        _ => return LeafClass::Drop(LeafDropReason::UnsupportedBehavioralValue),
    };

    // An integer `key` is an action id; action-keyed behavioral leaves never produced bytecode
    // (`filters.py:341` returns None).
    if node.get("key").is_some_and(Value::is_number) {
        return LeafClass::Drop(LeafDropReason::BehavioralActionKey);
    }

    let Some(condition_hash) = condition_hash_bytes(node.get("conditionHash")) else {
        return LeafClass::Drop(LeafDropReason::MissingConditionHash);
    };

    // Node gates on conditionHash *and* bytecode together.
    let Some(bytecode) = bytecode_array(node.get("bytecode")) else {
        return LeafClass::Drop(LeafDropReason::MissingBytecode);
    };

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
        bytecode,
    }
    .with_state_key();

    match pick_state_variant(&leaf) {
        Ok((variant, _window)) => {
            LeafClass::Keep(CohortLeaf::Behavioral(leaf.with_state_variant(variant)))
        }
        Err(_) => LeafClass::Drop(LeafDropReason::UnsupportedStateVariant),
    }
}

fn classify_cohort_ref(node: &Value) -> LeafClass {
    match cohort_id_from_value(node.get("value")) {
        Some(id) => LeafClass::CohortRef(CohortRefLeafConfig {
            referenced_cohort_id: CohortId(id),
            negation: cohort_ref_negation(node),
        }),
        None => LeafClass::Drop(LeafDropReason::MalformedLeaf),
    }
}

/// Cohort-ref negation has two equivalent encodings that both invert the Stage 2 membership bit:
/// explicit `negation: true`, or `operator: "not_in"` (the insight/query path's exclusion form).
/// Mirrors `posthog/cdp/filters.py:103`. Resolved here because the raw node is not retained on
/// `CohortRefLeafConfig`.
fn cohort_ref_negation(node: &Value) -> bool {
    let explicit = node
        .get("negation")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let not_in = node.get("operator").and_then(Value::as_str) == Some("not_in");
    explicit || not_in
}

fn classify_person(node: &Value) -> LeafClass {
    let Some(condition_hash) = condition_hash_bytes(node.get("conditionHash")) else {
        return LeafClass::Drop(LeafDropReason::MissingConditionHash);
    };
    let Some(bytecode) = bytecode_array(node.get("bytecode")) else {
        return LeafClass::Drop(LeafDropReason::MissingBytecode);
    };
    LeafClass::Keep(CohortLeaf::PersonProperty(PersonLeafConfig {
        condition_hash,
        leaf_state_key: LeafStateKey::for_person_property(&condition_hash),
        bytecode,
        raw: node.clone(),
    }))
}

/// The 16 ASCII bytes of the hex `conditionHash` string, carried verbatim (not hex-decoded) so the
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

/// The leaf's inline `bytecode`, or `None` if absent or not an array. `Arc` so tree clones /
/// ArcSwap snapshots share one allocation. Not validated here — `Program::new` does that at
/// evaluation time.
fn bytecode_array(value: Option<&Value>) -> Option<Arc<Vec<Value>>> {
    let array = value?.as_array()?;
    Some(Arc::new(array.clone()))
}

/// A referenced cohort id as a JSON number or string-encoded int, mirroring `cohort.py`'s
/// `int(cohort_id)` coercion.
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

    /// A representative program; only that `bytecode` is present and array-valued matters here.
    fn bytecode() -> Value {
        json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
    }

    fn hash_bytes() -> [u8; 16] {
        *b"0123456789abcdef"
    }

    #[test]
    fn performed_event_is_kept_with_cached_key_and_variant() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "time_value": 7,
            "time_interval": "day",
            "conditionHash": HASH,
            "bytecode": bytecode(),
        });
        let LeafClass::Keep(CohortLeaf::Behavioral(leaf)) = classify_leaf(&node) else {
            panic!("expected a kept behavioral leaf");
        };
        assert_eq!(leaf.condition_hash, hash_bytes());
        assert_eq!(leaf.value, BehavioralValue::PerformedEvent);
        assert_eq!(leaf.event_key, "$pageview");
        assert_eq!(leaf.time_value, Some(7));
        assert_eq!(leaf.leaf_state_key, LeafStateKey::for_behavioral(&leaf));
        assert_eq!(leaf.bytecode.as_ref(), bytecode().as_array().unwrap());
        assert_eq!(
            leaf.state_variant,
            Some(crate::stage1::state::StateVariant::BehavioralSingle),
        );
    }

    #[test]
    fn performed_event_multiple_is_dropped_as_unsupported_variant() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event_multiple",
            "key": "$pageview",
            "time_value": 7,
            "time_interval": "day",
            "operator": "gte",
            "operator_value": 3,
            "conditionHash": HASH,
            "bytecode": bytecode(),
        });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::UnsupportedStateVariant)
        ));
    }

    #[test]
    fn performed_event_without_window_is_dropped_as_unsupported_variant() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "conditionHash": HASH,
            "bytecode": bytecode(),
        });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::UnsupportedStateVariant)
        ));
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
            "bytecode": bytecode(),
        });
        let LeafClass::Keep(CohortLeaf::PersonProperty(leaf)) = classify_leaf(&node) else {
            panic!("expected a kept person leaf");
        };
        assert_eq!(leaf.condition_hash, hash_bytes());
        assert_eq!(leaf.leaf_state_key, LeafStateKey(hash_bytes()));
        assert_eq!(leaf.bytecode.as_ref(), bytecode().as_array().unwrap());
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
    fn behavioral_without_bytecode_is_dropped() {
        // conditionHash present but no bytecode → not realtime-executable (Node manager.ts:137).
        let node = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "conditionHash": HASH,
        });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::MissingBytecode)
        ));
    }

    #[test]
    fn person_without_bytecode_is_dropped() {
        let node = json!({
            "type": "person",
            "key": "email",
            "value": "a@b.com",
            "conditionHash": HASH,
        });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::MissingBytecode)
        ));
    }

    #[test]
    fn non_array_bytecode_is_dropped() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "conditionHash": HASH,
            "bytecode": "not-an-array",
        });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::MissingBytecode)
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
    fn cohort_ref_negation_honors_not_in_operator() {
        let not_in = json!({ "type": "cohort", "value": 7, "operator": "not_in" });
        let LeafClass::CohortRef(config) = classify_leaf(&not_in) else {
            panic!("expected a cohort ref");
        };
        assert_eq!(config.referenced_cohort_id, CohortId(7));
        assert!(config.negation, "`operator: not_in` must set negation");

        let both = json!({ "type": "cohort", "value": 7, "operator": "not_in", "negation": true });
        let LeafClass::CohortRef(config) = classify_leaf(&both) else {
            panic!("expected a cohort ref");
        };
        assert!(config.negation);

        let in_op = json!({ "type": "cohort", "value": 7, "operator": "in" });
        let LeafClass::CohortRef(config) = classify_leaf(&in_op) else {
            panic!("expected a cohort ref");
        };
        assert!(!config.negation, "`operator: in` must not set negation");
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
    fn unknown_type_is_dropped_even_with_condition_hash() {
        let node = json!({
            "type": "event",
            "key": "$pageview",
            "conditionHash": HASH,
            "bytecode": bytecode(),
        });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::UnknownLeafType)
        ));
    }

    #[test]
    fn absent_type_is_dropped_as_unknown() {
        let node = json!({ "foo": "bar" });
        assert!(matches!(
            classify_leaf(&node),
            LeafClass::Drop(LeafDropReason::UnknownLeafType)
        ));
    }
}
