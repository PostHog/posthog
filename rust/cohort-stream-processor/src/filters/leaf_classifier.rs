//! Raw leaf JSON classification into kept, dropped, or cohort-reference leaves.

use std::sync::Arc;

use serde_json::Value;

use crate::filters::tree::{
    BehavioralLeafConfig, BehavioralValue, CohortLeaf, CohortRefLeafConfig, PersonLeafConfig,
};
use crate::filters::CohortId;
use crate::stage1::key::LeafStateKey;
use crate::stage1::pick_state::pick_state_variant;

/// HogVM `RETURN` opcode, appended to each program at load. Python-compiled cohort bytecode ends at
/// its root comparison with no `RETURN`, which the Rust VM would hit as `EndOfProgram`. A program
/// already ending in `RETURN` stops at the first, so the appended one is inert.
const OP_RETURN: i64 = 38;

/// Why a leaf was dropped during parse. Used as the `reason` label on the skip counter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeafDropReason {
    /// No `conditionHash`, or one that is not a 16-character string.
    MissingConditionHash,
    /// No inline array `bytecode`.
    MissingBytecode,
    /// A behavioral `value` outside the two bytecode-producing types.
    UnsupportedBehavioralValue,
    /// A behavioral leaf keyed by an action id (integer `key`).
    BehavioralActionKey,
    /// A bytecode-bearing behavioral leaf whose Stage 1 state variant is not yet representable.
    UnsupportedStateVariant,
    /// A `type` outside `{person, behavioral, cohort}`.
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

    // An integer `key` is an action id — no bytecode is produced for these.
    if node.get("key").is_some_and(Value::is_number) {
        return LeafClass::Drop(LeafDropReason::BehavioralActionKey);
    }

    let Some(condition_hash) = condition_hash_bytes(node.get("conditionHash")) else {
        return LeafClass::Drop(LeafDropReason::MissingConditionHash);
    };

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
        negated: explicit_negation(node),
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

/// Whether a person/behavioral leaf is negated: `negation: true` only. A bare `operator: "not_in"`
/// is a value-list predicate compiled into the bytecode, not a composition negation.
fn explicit_negation(node: &Value) -> bool {
    node.get("negation")
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

/// Whether a cohort-reference leaf is negated: `negation: true` or `operator: "not_in"`. Unlike a
/// person/behavioral leaf, a cohort ref has no bytecode to compile `not_in` into.
fn cohort_ref_negation(node: &Value) -> bool {
    explicit_negation(node) || node.get("operator").and_then(Value::as_str) == Some("not_in")
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
        negated: explicit_negation(node),
    }))
}

/// The 16 ASCII bytes of the hex `conditionHash` string, or `None` if not exactly 16 bytes.
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

fn bytecode_array(value: Option<&Value>) -> Option<Arc<Vec<Value>>> {
    let array = value?.as_array()?;
    let mut bytecode = array.clone();
    bytecode.push(Value::from(OP_RETURN));
    Some(Arc::new(bytecode))
}

/// A referenced cohort id as a JSON number or string-encoded int.
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

    /// A representative bytecode program, as compiled (no trailing `RETURN`).
    fn bytecode() -> Value {
        json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
    }

    /// The stored form of [`bytecode`]: the loader appends a trailing `RETURN` (opcode 38).
    fn bytecode_loaded() -> Vec<Value> {
        let mut bc = bytecode().as_array().unwrap().clone();
        bc.push(json!(OP_RETURN));
        bc
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
        assert_eq!(leaf.bytecode.as_ref(), &bytecode_loaded());
        assert_eq!(
            leaf.state_variant,
            Some(crate::stage1::state::StateVariant::BehavioralSingle),
        );
    }

    #[test]
    fn performed_event_multiple_daily_window_is_kept_as_daily_buckets() {
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
        let LeafClass::Keep(CohortLeaf::Behavioral(leaf)) = classify_leaf(&node) else {
            panic!("a daily-window multiple is now kept");
        };
        assert_eq!(leaf.value, BehavioralValue::PerformedEventMultiple);
        assert_eq!(leaf.operator.as_deref(), Some("gte"));
        assert_eq!(leaf.operator_value, Some(3));
        assert_eq!(
            leaf.state_variant,
            Some(crate::stage1::state::StateVariant::BehavioralDailyBuckets),
        );
    }

    #[test]
    fn performed_event_multiple_sub_day_window_is_dropped() {
        for (time_value, time_interval, why) in [
            (5, "hour", "hour,5 = 0 whole days"),
            (30, "minute", "minute,30 = 0 whole days"),
        ] {
            let node = json!({
                "type": "behavioral",
                "value": "performed_event_multiple",
                "key": "$pageview",
                "time_value": time_value,
                "time_interval": time_interval,
                "operator": "gte",
                "operator_value": 3,
                "conditionHash": HASH,
                "bytecode": bytecode(),
            });
            assert!(
                matches!(
                    classify_leaf(&node),
                    LeafClass::Drop(LeafDropReason::UnsupportedStateVariant)
                ),
                "{why}",
            );
        }
    }

    #[test]
    fn performed_event_multiple_over_180_day_window_is_kept_as_compressed() {
        for (time_value, time_interval, why) in [
            (1, "year", "year,1 = 365 days"),
            (365, "day", "day,365 = 365 days"),
            (181, "day", "day,181 just over the daily boundary"),
        ] {
            let node = json!({
                "type": "behavioral",
                "value": "performed_event_multiple",
                "key": "$pageview",
                "time_value": time_value,
                "time_interval": time_interval,
                "operator": "gte",
                "operator_value": 3,
                "conditionHash": HASH,
                "bytecode": bytecode(),
            });
            let LeafClass::Keep(CohortLeaf::Behavioral(leaf)) = classify_leaf(&node) else {
                panic!("a >180-day multiple is kept as compressed: {why}");
            };
            assert_eq!(
                leaf.state_variant,
                Some(crate::stage1::state::StateVariant::BehavioralCompressedHistory),
                "{why}",
            );
        }
    }

    #[test]
    fn performed_event_multiple_explicit_relative_lower_window_is_kept() {
        use crate::stage1::state::StateVariant;
        // The cohort UI stores "in the last N days" as `explicit_datetime: "-Nd"` with no
        // time_interval/time_value; the multiple path must resolve it like the single path does.
        for (explicit_datetime, expected_variant, why) in [
            (
                "-7d",
                StateVariant::BehavioralDailyBuckets,
                "-7d → 7 days → daily",
            ),
            (
                "-1y",
                StateVariant::BehavioralCompressedHistory,
                "-1y → 365 days → compressed",
            ),
        ] {
            let node = json!({
                "type": "behavioral",
                "value": "performed_event_multiple",
                "key": "$pageview",
                "explicit_datetime": explicit_datetime,
                "operator": "gte",
                "operator_value": 3,
                "conditionHash": HASH,
                "bytecode": bytecode(),
            });
            let LeafClass::Keep(CohortLeaf::Behavioral(leaf)) = classify_leaf(&node) else {
                panic!("an explicit relative-lower multiple is kept: {why}");
            };
            assert_eq!(leaf.value, BehavioralValue::PerformedEventMultiple);
            assert_eq!(leaf.explicit_datetime.as_deref(), Some(explicit_datetime));
            assert_eq!(leaf.state_variant, Some(expected_variant), "{why}");
        }
    }

    #[test]
    fn performed_event_multiple_explicit_unrepresentable_window_is_dropped() {
        // Sub-day and absolute-range explicit windows have no whole-day sliding form, so the leaf
        // drops exactly as it did before explicit_datetime was consulted (which dropped all of them).
        for (from, to, why) in [
            (
                "-2h",
                Value::Null,
                "sub-day relative window → unsupported variant",
            ),
            (
                "2026-01-01",
                json!("2026-12-31"),
                "absolute range → unsupported variant",
            ),
        ] {
            let node = json!({
                "type": "behavioral",
                "value": "performed_event_multiple",
                "key": "$pageview",
                "explicit_datetime": from,
                "explicit_datetime_to": to,
                "operator": "gte",
                "operator_value": 3,
                "conditionHash": HASH,
                "bytecode": bytecode(),
            });
            assert!(
                matches!(
                    classify_leaf(&node),
                    LeafClass::Drop(LeafDropReason::UnsupportedStateVariant)
                ),
                "{why}",
            );
        }
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
        assert_eq!(leaf.bytecode.as_ref(), &bytecode_loaded());
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

    #[test]
    fn behavioral_leaf_with_negation_true_is_kept_negated() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "time_value": 7,
            "time_interval": "day",
            "conditionHash": HASH,
            "bytecode": bytecode(),
            "negation": true,
        });
        let LeafClass::Keep(CohortLeaf::Behavioral(leaf)) = classify_leaf(&node) else {
            panic!("expected a kept behavioral leaf");
        };
        assert!(leaf.negated);
    }

    #[test]
    fn behavioral_leaf_without_negation_is_not_negated() {
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
        assert!(!leaf.negated);
    }

    #[test]
    fn person_leaf_with_negation_true_is_kept_negated() {
        let node = json!({
            "type": "person",
            "key": "email",
            "value": "a@b.com",
            "conditionHash": HASH,
            "bytecode": bytecode(),
            "negation": true,
        });
        let LeafClass::Keep(CohortLeaf::PersonProperty(leaf)) = classify_leaf(&node) else {
            panic!("expected a kept person leaf");
        };
        assert!(leaf.negated);
    }

    #[test]
    fn person_leaf_without_negation_is_not_negated() {
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
        assert!(!leaf.negated);
    }

    #[test]
    fn behavioral_negation_false_is_not_negated() {
        let node = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "time_value": 7,
            "time_interval": "day",
            "conditionHash": HASH,
            "bytecode": bytecode(),
            "negation": false,
        });
        let LeafClass::Keep(CohortLeaf::Behavioral(leaf)) = classify_leaf(&node) else {
            panic!("expected a kept behavioral leaf");
        };
        assert!(!leaf.negated);
    }
}
