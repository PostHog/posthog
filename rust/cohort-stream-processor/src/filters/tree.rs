//! The service's own filter-tree types and parser.
//!
//! These types deliberately do not depend on the feature-flags crate — they borrow only the serde
//! field names. The tree is parsed as-is (no `_merge_sibling_single_property_groups`, no
//! `_preprocess_property_groups`) so Stage 2 can re-walk the original leaves later. Each kept leaf
//! caches its [`LeafStateKey`] and (for behavioral leaves) its [`StateVariant`] so the hot path
//! never re-derives them.

use std::sync::Arc;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::filters::leaf_classifier::{classify_leaf, LeafClass, LeafDropReason};
use crate::filters::{CohortId, FilterError, TeamId};
use crate::stage1::key::LeafStateKey;
use crate::stage1::state::StateVariant;

/// The seven cohort behavioral predicate types (`BehavioralPropertyType` in
/// `posthog/models/property/property.py`). Only [`PerformedEvent`](Self::PerformedEvent) and
/// [`PerformedEventMultiple`](Self::PerformedEventMultiple) produce realtime bytecode.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BehavioralValue {
    PerformedEvent,
    PerformedEventMultiple,
    PerformedEventFirstTime,
    PerformedEventSequence,
    PerformedEventRegularly,
    StoppedPerformingEvent,
    RestartedPerformingEvent,
}

impl BehavioralValue {
    /// The wire string stored in the cohort filter JSON. Hashed into the [`LeafStateKey`], so it is
    /// part of the cross-runtime contract.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::PerformedEvent => "performed_event",
            Self::PerformedEventMultiple => "performed_event_multiple",
            Self::PerformedEventFirstTime => "performed_event_first_time",
            Self::PerformedEventSequence => "performed_event_sequence",
            Self::PerformedEventRegularly => "performed_event_regularly",
            Self::StoppedPerformingEvent => "stopped_performing_event",
            Self::RestartedPerformingEvent => "restarted_performing_event",
        }
    }

    /// Whether this value produces realtime bytecode (and a `conditionHash`). Only the two
    /// non-temporal types do; the rest cannot be evaluated incrementally at Stage 1. Mirrors
    /// `build_behavioral_event_expr` (`posthog/cdp/filters.py:329-350`).
    pub fn contributes_bytecode(self) -> bool {
        matches!(self, Self::PerformedEvent | Self::PerformedEventMultiple)
    }

    /// Parse a wire string, or `None` for an unrecognized (schema-drift) string.
    pub fn from_wire(s: &str) -> Option<Self> {
        let value = match s {
            "performed_event" => Self::PerformedEvent,
            "performed_event_multiple" => Self::PerformedEventMultiple,
            "performed_event_first_time" => Self::PerformedEventFirstTime,
            "performed_event_sequence" => Self::PerformedEventSequence,
            "performed_event_regularly" => Self::PerformedEventRegularly,
            "stopped_performing_event" => Self::StoppedPerformingEvent,
            "restarted_performing_event" => Self::RestartedPerformingEvent,
            _ => return None,
        };
        Some(value)
    }
}

/// A behavioral leaf, carrying every input to [`LeafStateKey::for_behavioral`]. `operator` is a raw
/// string because the LSK hashes the raw string and the feature-flags `OperatorType` enum lacks
/// `eq` (which `performed_event_multiple` uses).
#[derive(Debug, Clone)]
pub struct BehavioralLeafConfig {
    pub condition_hash: [u8; 16],
    pub value: BehavioralValue,
    pub event_key: String,
    pub time_value: Option<i32>,
    pub operator_value: Option<i32>,
    pub time_interval: Option<String>,
    pub operator: Option<String>,
    pub explicit_datetime: Option<String>,
    pub explicit_datetime_to: Option<String>,
    /// Derived once via [`with_state_key`](Self::with_state_key), then immutable.
    pub leaf_state_key: LeafStateKey,
    /// [`None`] only while the struct is mid-construction (literal-then-builder); a kept leaf always
    /// carries `Some`, since an unsupported variant is dropped rather than kept.
    pub state_variant: Option<StateVariant>,
    /// The leaf's inline bytecode fed to [`crate::hogvm::evaluate`]. `Arc` so tree clones / ArcSwap
    /// snapshots share one allocation. Excluded from [`LeafStateKey`], which hashes `condition_hash`
    /// (already `sha256(bytecode)`).
    pub bytecode: Arc<Vec<Value>>,
}

impl BehavioralLeafConfig {
    /// Derive and cache the [`LeafStateKey`]. The only correct way to finish constructing the type:
    /// the cached key must stay consistent with the fields it hashes, so callers build the struct
    /// literal and end with this call.
    #[must_use]
    pub fn with_state_key(mut self) -> Self {
        self.leaf_state_key = LeafStateKey::for_behavioral(&self);
        self
    }

    /// Record the leaf's resolved [`StateVariant`].
    #[must_use]
    pub fn with_state_variant(mut self, variant: StateVariant) -> Self {
        self.state_variant = Some(variant);
        self
    }
}

/// A person-property leaf. The raw JSON is retained so Stage 2 can re-walk the original predicate.
#[derive(Debug, Clone)]
pub struct PersonLeafConfig {
    pub condition_hash: [u8; 16],
    pub leaf_state_key: LeafStateKey,
    /// See [`BehavioralLeafConfig::bytecode`].
    pub bytecode: Arc<Vec<Value>>,
    pub raw: Value,
}

/// A reference to another cohort. No `conditionHash` at Stage 1 — cohort refs are skipped during
/// HogVM evaluation (`manager.ts:142`).
#[derive(Debug, Clone)]
pub struct CohortRefLeafConfig {
    pub referenced_cohort_id: CohortId,
    pub negation: bool,
}

/// A classified, kept leaf in the filter tree.
#[derive(Debug, Clone)]
pub enum CohortLeaf {
    PersonProperty(PersonLeafConfig),
    Behavioral(BehavioralLeafConfig),
    CohortRef(CohortRefLeafConfig),
}

impl CohortLeaf {
    /// The leaf's Stage 1 state key, or `None` for a cohort reference (not state-keyed).
    pub fn leaf_state_key(&self) -> Option<LeafStateKey> {
        match self {
            Self::PersonProperty(leaf) => Some(leaf.leaf_state_key),
            Self::Behavioral(leaf) => Some(leaf.leaf_state_key),
            Self::CohortRef(_) => None,
        }
    }

    /// The leaf's `conditionHash`, or `None` for a cohort reference (no bytecode).
    pub fn condition_hash(&self) -> Option<[u8; 16]> {
        match self {
            Self::PersonProperty(leaf) => Some(leaf.condition_hash),
            Self::Behavioral(leaf) => Some(leaf.condition_hash),
            Self::CohortRef(_) => None,
        }
    }

    /// The leaf's inline bytecode, or `None` for a cohort reference (no bytecode).
    pub fn bytecode(&self) -> Option<&Arc<Vec<Value>>> {
        match self {
            Self::PersonProperty(leaf) => Some(&leaf.bytecode),
            Self::Behavioral(leaf) => Some(&leaf.bytecode),
            Self::CohortRef(_) => None,
        }
    }
}

/// Boolean combinator for a property group.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BoolOp {
    And,
    Or,
}

/// A node in a cohort's filter tree: either a boolean group or a leaf.
#[derive(Debug, Clone)]
pub enum FilterNode {
    Group {
        op: BoolOp,
        children: Vec<FilterNode>,
    },
    Leaf(CohortLeaf),
}

/// A parsed cohort filter tree, retained for Stage 2 re-walk.
#[derive(Debug, Clone)]
pub struct CohortTree {
    pub cohort_id: CohortId,
    pub team_id: TeamId,
    pub root: FilterNode,
}

/// Receives the indexable side effects of a parse so parsing and index-building happen in one pass.
/// [`crate::filters::reverse_index::TeamFiltersBuilder`] is the production implementation; tests use
/// a lightweight collecting sink.
pub trait LeafSink {
    /// Records a kept, state-keyed leaf's `condition_hash → {leaf_state_key, cohort_id, bytecode}`
    /// edges and its `conditionHash` dedup membership. `bytecode` is borrowed; the implementation
    /// clones the `Arc` only on first insert per `conditionHash`.
    fn record_state_keyed(
        &mut self,
        cohort_id: CohortId,
        condition_hash: [u8; 16],
        leaf_state_key: LeafStateKey,
        bytecode: &Arc<Vec<Value>>,
    );

    /// A dropped leaf, for the skip counter.
    fn record_dropped(&mut self, reason: LeafDropReason);
}

/// Parse a cohort's `filters` JSON into a [`CohortTree`], emitting index side effects through
/// `sink`. Returns [`FilterError::MissingProperties`] if `filters.properties` is absent.
///
/// A node is a group iff its `type` is `"AND"`/`"OR"` and `values` is an array; anything else is a
/// leaf. Dropped leaves produce no node; an empty group after drops is **kept** to preserve the
/// AND/OR identity for Stage 2.
pub fn parse_cohort_tree(
    cohort_id: CohortId,
    team_id: TeamId,
    filters: &Value,
    sink: &mut dyn LeafSink,
) -> Result<CohortTree, FilterError> {
    let properties = filters
        .get("properties")
        .ok_or(FilterError::MissingProperties {
            cohort_id: cohort_id.0,
        })?;

    // A degenerate single-leaf root that drops out leaves no node; fall back to an empty AND group
    // rather than failing the cohort.
    let root = parse_node(cohort_id, properties, sink).unwrap_or_else(|| FilterNode::Group {
        op: BoolOp::And,
        children: Vec::new(),
    });

    Ok(CohortTree {
        cohort_id,
        team_id,
        root,
    })
}

fn parse_node(cohort_id: CohortId, node: &Value, sink: &mut dyn LeafSink) -> Option<FilterNode> {
    if let Some(op) = group_op(node) {
        if let Some(values) = node.get("values").and_then(Value::as_array) {
            let children = values
                .iter()
                .filter_map(|child| parse_node(cohort_id, child, sink))
                .collect();
            return Some(FilterNode::Group { op, children });
        }
    }

    match classify_leaf(node) {
        LeafClass::Keep(leaf) => {
            // Kept leaves always carry all three; the guard is defensive against a future variant.
            if let (Some(hash), Some(lsk), Some(bytecode)) = (
                leaf.condition_hash(),
                leaf.leaf_state_key(),
                leaf.bytecode(),
            ) {
                sink.record_state_keyed(cohort_id, hash, lsk, bytecode);
            }
            Some(FilterNode::Leaf(leaf))
        }
        LeafClass::CohortRef(config) => Some(FilterNode::Leaf(CohortLeaf::CohortRef(config))),
        LeafClass::Drop(reason) => {
            sink.record_dropped(reason);
            None
        }
    }
}

fn group_op(node: &Value) -> Option<BoolOp> {
    match node.get("type").and_then(Value::as_str) {
        Some("AND") => Some(BoolOp::And),
        Some("OR") => Some(BoolOp::Or),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const HASH_A: [u8; 16] = *b"aaaaaaaaaaaaaaaa";
    const HASH_B: [u8; 16] = *b"bbbbbbbbbbbbbbbb";

    #[derive(Default)]
    struct CollectingSink {
        state_keyed: Vec<(CohortId, [u8; 16], LeafStateKey)>,
        dropped: Vec<LeafDropReason>,
    }

    // Bytecode capture is covered against the real `TeamFiltersBuilder` elsewhere; this sink only
    // observes the state-keyed/dropped edges, so it ignores the bytecode argument.
    impl LeafSink for CollectingSink {
        fn record_state_keyed(
            &mut self,
            cohort_id: CohortId,
            hash: [u8; 16],
            lsk: LeafStateKey,
            _bytecode: &Arc<Vec<Value>>,
        ) {
            self.state_keyed.push((cohort_id, hash, lsk));
        }
        fn record_dropped(&mut self, reason: LeafDropReason) {
            self.dropped.push(reason);
        }
    }

    fn person_leaf(hash: &[u8; 16]) -> Value {
        json!({
            "type": "person",
            "key": "email",
            "value": "a@b.com",
            "operator": "exact",
            "conditionHash": String::from_utf8(hash.to_vec()).unwrap(),
            "bytecode": ["_H", 1, 29],
        })
    }

    fn parse(value: &Value, sink: &mut CollectingSink) -> CohortTree {
        parse_cohort_tree(CohortId(1), TeamId(7), value, sink).expect("parse")
    }

    #[test]
    fn behavioral_value_str_and_wire_round_trip() {
        for value in [
            BehavioralValue::PerformedEvent,
            BehavioralValue::PerformedEventMultiple,
            BehavioralValue::PerformedEventFirstTime,
            BehavioralValue::PerformedEventSequence,
            BehavioralValue::PerformedEventRegularly,
            BehavioralValue::StoppedPerformingEvent,
            BehavioralValue::RestartedPerformingEvent,
        ] {
            assert_eq!(BehavioralValue::from_wire(value.as_str()), Some(value));
        }
        assert_eq!(BehavioralValue::from_wire("not_a_real_value"), None);
    }

    #[test]
    fn only_two_values_contribute_bytecode() {
        assert!(BehavioralValue::PerformedEvent.contributes_bytecode());
        assert!(BehavioralValue::PerformedEventMultiple.contributes_bytecode());
        assert!(!BehavioralValue::PerformedEventSequence.contributes_bytecode());
        assert!(!BehavioralValue::StoppedPerformingEvent.contributes_bytecode());
    }

    #[test]
    fn missing_properties_is_an_error() {
        let mut sink = CollectingSink::default();
        let err = parse_cohort_tree(CohortId(3), TeamId(7), &json!({}), &mut sink).unwrap_err();
        assert!(matches!(
            err,
            FilterError::MissingProperties { cohort_id: 3 }
        ));
    }

    #[test]
    fn or_group_of_two_person_leaves_is_not_sibling_merged() {
        let filters = json!({
            "properties": {
                "type": "OR",
                "values": [person_leaf(&HASH_A), person_leaf(&HASH_B)],
            }
        });
        let mut sink = CollectingSink::default();
        let tree = parse(&filters, &mut sink);

        match tree.root {
            FilterNode::Group { op, children } => {
                assert_eq!(op, BoolOp::Or);
                assert_eq!(children.len(), 2, "siblings must not be merged");
            }
            FilterNode::Leaf(_) => panic!("root should be a group"),
        }
        assert_eq!(sink.state_keyed.len(), 2);
    }

    #[test]
    fn cohort_ref_is_kept_in_tree_but_not_indexed() {
        let filters = json!({
            "properties": {
                "type": "AND",
                "values": [{ "type": "cohort", "value": 42, "negation": true }],
            }
        });
        let mut sink = CollectingSink::default();
        let tree = parse(&filters, &mut sink);

        let FilterNode::Group { children, .. } = tree.root else {
            panic!("root should be a group");
        };
        assert_eq!(children.len(), 1);
        match &children[0] {
            FilterNode::Leaf(CohortLeaf::CohortRef(config)) => {
                assert_eq!(config.referenced_cohort_id, CohortId(42));
                assert!(config.negation);
            }
            other => panic!("expected a cohort ref, got {other:?}"),
        }
        assert!(
            sink.state_keyed.is_empty(),
            "cohort refs are not state-keyed"
        );
    }

    #[test]
    fn dropped_leaf_produces_no_node_but_keeps_the_group() {
        let filters = json!({
            "properties": {
                "type": "AND",
                "values": [{ "type": "behavioral", "key": "$pageview", "value": "performed_event" }],
            }
        });
        let mut sink = CollectingSink::default();
        let tree = parse(&filters, &mut sink);

        let FilterNode::Group { children, .. } = tree.root else {
            panic!("root should be a group");
        };
        assert!(
            children.is_empty(),
            "dropped leaf leaves an empty (but kept) group"
        );
        assert_eq!(sink.dropped, vec![LeafDropReason::MissingConditionHash]);
    }

    #[test]
    fn nested_groups_recurse() {
        let filters = json!({
            "properties": {
                "type": "AND",
                "values": [{
                    "type": "OR",
                    "values": [person_leaf(&HASH_A)],
                }],
            }
        });
        let mut sink = CollectingSink::default();
        let tree = parse(&filters, &mut sink);

        let FilterNode::Group { op, children } = tree.root else {
            panic!("root should be a group");
        };
        assert_eq!(op, BoolOp::And);
        assert!(matches!(
            children.as_slice(),
            [FilterNode::Group { op: BoolOp::Or, .. }]
        ));
        assert_eq!(sink.state_keyed.len(), 1);
    }
}
