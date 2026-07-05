//! Per-team reverse indices, dedup set, and eligibility classification.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use chrono_tz::{Tz, UTC};
use metrics::counter;
use serde_json::Value;
use tracing::warn;

use crate::filters::cohort_graph;
use crate::filters::leaf_classifier::LeafDropReason;
use crate::filters::tree::{parse_cohort_tree, CohortLeaf, CohortTree, FilterNode, LeafSink};
use crate::filters::{CohortId, FilterError, TeamId};
use crate::observability::metrics::{
    COHORT_ELIGIBILITY_TOTAL, COHORT_IN_CYCLE_TOTAL, FILTER_CATALOG_SKIPPED_LEAVES,
};
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::CatalogFingerprint;
use crate::stage1::pick_state::{
    effective_window_days, pick_state_variant, EvictionWindow, PredicateOp,
};
use crate::stage1::state::StateVariant;
use crate::stage2::eligibility::refine_ref_bearing;
use crate::stage2::{classify, CohortEligibility, CohortParseFlags};

#[derive(Debug, Clone, Copy)]
pub struct LeafStateMeta {
    pub variant: StateVariant,
    /// The leaf's `conditionHash` (the event-matcher hash).
    pub condition_hash: [u8; 16],
    /// `BehavioralSingle` only; `None` for bucket and person variants.
    pub window: Option<EvictionWindow>,
    /// Window length in days — `Some` for daily-bucket and compressed variants, `None` otherwise.
    pub window_days: Option<u32>,
    /// Count comparator for a window's sum — `Some` for daily-bucket and compressed, `None` otherwise.
    pub predicate_op: Option<PredicateOp>,
}

#[derive(Debug)]
pub struct TeamFilters {
    pub by_condition_to_lsk: HashMap<[u8; 16], Vec<LeafStateKey>>,
    /// `conditionHash → [CohortId]` for the Stage 2 walk back to owning cohorts.
    pub by_condition_to_cohorts: HashMap<[u8; 16], Vec<CohortId>>,
    /// `conditionHash → bytecode`. One entry per conditionHash.
    pub by_condition_to_bytecode: HashMap<[u8; 16], Arc<Vec<Value>>>,
    pub unique_condition_hashes: HashSet<[u8; 16]>,
    pub by_lsk: HashMap<LeafStateKey, LeafStateMeta>,
    /// conditionHashes whose leaves are behavioral. Disjoint from person-property conditions.
    pub behavioral_conditions: HashSet<[u8; 16]>,
    /// Event name → the behavioral conditionHashes whose bytecode roots at `event == <name>`; the
    /// fan-out gate evaluates only the incoming event's bucket.
    pub behavioral_by_event_name: HashMap<String, Vec<[u8; 16]>>,
    pub person_property_conditions: HashSet<[u8; 16]>,
    /// `person_property_conditions` sorted — the stable order the person record's catalog fingerprint
    /// is computed over.
    pub person_conditions_ordered: Vec<[u8; 16]>,
    /// SHA-256 over `person_conditions_ordered`, computed once at freeze. A content fingerprint of the
    /// team's person conditions: a stored [`PersonRecord`](crate::stage1::PersonRecord) whose catalog
    /// fingerprint matches this needs no re-evaluation, and a no-op catalog refresh (same conditions)
    /// leaves it unchanged, so records are not needlessly invalidated.
    pub catalog_fingerprint: CatalogFingerprint,
    /// `LeafStateKey → [CohortId]` for single-leaf cohorts.
    pub by_lsk_to_single_leaf_cohorts: HashMap<LeafStateKey, Vec<CohortId>>,
    /// `LeafStateKey → [CohortId]` for `Stage2Composable` cohorts.
    pub by_lsk_to_composable_cohorts: HashMap<LeafStateKey, Vec<CohortId>>,
    /// `referenced cohort → [referrer cohorts]`, sorted. The structural inverse of the reference
    /// graph; read via [`TeamFilters::cohorts_referencing`].
    pub by_referenced_cohort: HashMap<CohortId, Vec<CohortId>>,
    /// Each cohort's composition class, computed once at freeze.
    pub eligibility: HashMap<CohortId, CohortEligibility>,
    /// Parsed trees by cohort, retained for the Stage 2 re-walk.
    pub cohorts: HashMap<CohortId, CohortTree>,
    /// The team's resolved IANA timezone, used by bucket variants for calendar-day computation.
    pub timezone: Tz,
}

/// Hand-written because [`Tz`] has no [`Default`].
impl Default for TeamFilters {
    fn default() -> Self {
        Self {
            by_condition_to_lsk: HashMap::new(),
            by_condition_to_cohorts: HashMap::new(),
            by_condition_to_bytecode: HashMap::new(),
            unique_condition_hashes: HashSet::new(),
            by_lsk: HashMap::new(),
            behavioral_conditions: HashSet::new(),
            behavioral_by_event_name: HashMap::new(),
            person_property_conditions: HashSet::new(),
            person_conditions_ordered: Vec::new(),
            // Fingerprint of the empty condition set, matching a `freeze` of no person conditions.
            catalog_fingerprint: CatalogFingerprint::of_sorted(&[]),
            by_lsk_to_single_leaf_cohorts: HashMap::new(),
            by_lsk_to_composable_cohorts: HashMap::new(),
            by_referenced_cohort: HashMap::new(),
            eligibility: HashMap::new(),
            cohorts: HashMap::new(),
            timezone: UTC,
        }
    }
}

impl TeamFilters {
    /// Cohorts that reference `id`, sorted ascending; empty when none.
    pub fn cohorts_referencing(&self, id: CohortId) -> &[CohortId] {
        self.by_referenced_cohort
            .get(&id)
            .map_or(&[], Vec::as_slice)
    }
}

/// Accumulates a team's filters across its cohorts, then freezes into an immutable [`TeamFilters`].
#[derive(Debug, Default)]
pub struct TeamFiltersBuilder {
    by_condition_to_lsk: HashMap<[u8; 16], HashSet<LeafStateKey>>,
    by_condition_to_cohorts: HashMap<[u8; 16], HashSet<CohortId>>,
    by_condition_to_bytecode: HashMap<[u8; 16], Arc<Vec<Value>>>,
    unique_condition_hashes: HashSet<[u8; 16]>,
    cohorts: HashMap<CohortId, CohortTree>,
    /// Per-cohort eligibility signals captured during parse.
    flags: HashMap<CohortId, CohortParseFlags>,
}

impl LeafSink for TeamFiltersBuilder {
    fn record_state_keyed(
        &mut self,
        cohort_id: CohortId,
        condition_hash: [u8; 16],
        leaf_state_key: LeafStateKey,
        bytecode: &Arc<Vec<Value>>,
    ) {
        self.by_condition_to_lsk
            .entry(condition_hash)
            .or_default()
            .insert(leaf_state_key);
        self.by_condition_to_cohorts
            .entry(condition_hash)
            .or_default()
            .insert(cohort_id);
        self.by_condition_to_bytecode
            .entry(condition_hash)
            .or_insert_with(|| Arc::clone(bytecode));
        self.unique_condition_hashes.insert(condition_hash);

        let flags = self.flags.entry(cohort_id).or_default();
        flags.state_keyed_leaf_count += 1;
    }

    fn record_cohort_ref(&mut self, cohort_id: CohortId) {
        self.flags.entry(cohort_id).or_default().has_cohort_ref = true;
    }

    fn record_dropped(&mut self, cohort_id: CohortId, reason: LeafDropReason) {
        counter!(FILTER_CATALOG_SKIPPED_LEAVES, "reason" => reason.as_str()).increment(1);
        self.flags.entry(cohort_id).or_default().has_dropped_leaf = true;
    }
}

impl TeamFiltersBuilder {
    pub fn add_cohort(
        &mut self,
        cohort_id: CohortId,
        team_id: TeamId,
        filters: &Value,
    ) -> Result<(), FilterError> {
        let tree = parse_cohort_tree(cohort_id, team_id, filters, self)?;
        self.cohorts.insert(cohort_id, tree);
        Ok(())
    }

    /// Equivalent to `freeze_with(timezone, false)`.
    pub fn freeze(self, timezone: Tz) -> TeamFilters {
        self.freeze_with(timezone, false)
    }

    /// Freeze into an immutable [`TeamFilters`]. When `cascade_enabled`, resolvable cycle-free
    /// ref-bearing cohorts become [`CohortEligibility::Stage2ComposableRef`] and join the composable
    /// emit-map by their own leaves; otherwise they stay `Excluded(HasCohortRef)`.
    pub fn freeze_with(self, timezone: Tz, cascade_enabled: bool) -> TeamFilters {
        let mut by_lsk = HashMap::new();
        let mut behavioral_conditions = HashSet::new();
        let mut behavioral_by_event_name: HashMap<String, HashSet<[u8; 16]>> = HashMap::new();
        let mut person_property_conditions = HashSet::new();

        let mut eligibility: HashMap<CohortId, CohortEligibility> = HashMap::new();
        for tree in self.cohorts.values() {
            collect_leaf_meta(
                &tree.root,
                &mut by_lsk,
                &mut behavioral_conditions,
                &mut behavioral_by_event_name,
                &mut person_property_conditions,
            );
            let flags = self.flags.get(&tree.cohort_id).copied().unwrap_or_default();
            eligibility.insert(tree.cohort_id, classify(tree, &flags));
        }

        let mut by_referenced_cohort: HashMap<CohortId, Vec<CohortId>> = HashMap::new();
        if self.flags.values().any(|flags| flags.has_cohort_ref) {
            let analysis = cohort_graph::analyze(&self.cohorts);
            refine_ref_bearing(&mut eligibility, &analysis, cascade_enabled);
            // Invert the reference graph (referenced → [referrers]). Not filtered by eligibility, so
            // it stays populated even though referrers are excluded from composition.
            for (&referrer, targets) in &analysis.ref_targets {
                for &target in targets {
                    by_referenced_cohort
                        .entry(target)
                        .or_default()
                        .push(referrer);
                }
            }
            for referrers in by_referenced_cohort.values_mut() {
                referrers.sort_unstable();
            }
            if !analysis.in_cycle.is_empty() {
                counter!(COHORT_IN_CYCLE_TOTAL).increment(analysis.in_cycle.len() as u64);
                let mut cycle_ids: Vec<i32> = analysis.in_cycle.iter().map(|id| id.0).collect();
                cycle_ids.sort_unstable();
                // One builder holds exactly one team, so any cohort's `team_id` is the team's.
                let team_id = self
                    .cohorts
                    .values()
                    .next()
                    .map_or(0, |tree| tree.team_id.0);
                warn!(
                    team_id,
                    ?cycle_ids,
                    "cohort reference cycle detected; excluding members from composition",
                );
            }
        }

        let mut by_lsk_to_single_leaf_cohorts: HashMap<LeafStateKey, Vec<CohortId>> =
            HashMap::new();
        let mut by_lsk_to_composable_cohorts: HashMap<LeafStateKey, Vec<CohortId>> = HashMap::new();
        for tree in self.cohorts.values() {
            let class = eligibility[&tree.cohort_id];
            counter!(COHORT_ELIGIBILITY_TOTAL, "class" => class.metric_class()).increment(1);
            match class {
                CohortEligibility::SingleLeaf(lsk) => {
                    by_lsk_to_single_leaf_cohorts
                        .entry(lsk)
                        .or_default()
                        .push(tree.cohort_id);
                }
                // Both composable classes index their own state-keyed leaves; a pure-ref cohort has
                // none, so it contributes nothing here.
                CohortEligibility::Stage2Composable | CohortEligibility::Stage2ComposableRef => {
                    let mut leaf_keys = HashSet::new();
                    collect_leaf_state_keys(&tree.root, &mut leaf_keys);
                    for lsk in leaf_keys {
                        by_lsk_to_composable_cohorts
                            .entry(lsk)
                            .or_default()
                            .push(tree.cohort_id);
                    }
                }
                CohortEligibility::Excluded(_) => {}
            }
        }
        for cohorts in by_lsk_to_single_leaf_cohorts.values_mut() {
            cohorts.sort_unstable();
        }
        for cohorts in by_lsk_to_composable_cohorts.values_mut() {
            cohorts.sort_unstable();
        }

        let mut person_conditions_ordered: Vec<[u8; 16]> =
            person_property_conditions.iter().copied().collect();
        person_conditions_ordered.sort_unstable();
        let catalog_fingerprint = CatalogFingerprint::of_sorted(&person_conditions_ordered);

        let behavioral_by_event_name = behavioral_by_event_name
            .into_iter()
            .map(|(name, hashes)| {
                let mut hashes: Vec<[u8; 16]> = hashes.into_iter().collect();
                hashes.sort_unstable();
                (name, hashes)
            })
            .collect();

        TeamFilters {
            by_condition_to_lsk: sorted_vec_map(self.by_condition_to_lsk),
            by_condition_to_cohorts: sorted_vec_map(self.by_condition_to_cohorts),
            by_condition_to_bytecode: self.by_condition_to_bytecode,
            unique_condition_hashes: self.unique_condition_hashes,
            by_lsk,
            behavioral_conditions,
            behavioral_by_event_name,
            person_property_conditions,
            person_conditions_ordered,
            catalog_fingerprint,
            by_lsk_to_single_leaf_cohorts,
            by_lsk_to_composable_cohorts,
            by_referenced_cohort,
            eligibility,
            cohorts: self.cohorts,
            timezone,
        }
    }
}

/// The distinct [`LeafStateKey`]s of every state-keyed leaf in a tree.
fn collect_leaf_state_keys(node: &FilterNode, out: &mut HashSet<LeafStateKey>) {
    match node {
        FilterNode::Group { children, .. } => {
            for child in children {
                collect_leaf_state_keys(child, out);
            }
        }
        FilterNode::Leaf(leaf) => {
            if let Some(lsk) = leaf.leaf_state_key() {
                out.insert(lsk);
            }
        }
    }
}

fn collect_leaf_meta(
    node: &FilterNode,
    by_lsk: &mut HashMap<LeafStateKey, LeafStateMeta>,
    behavioral_conditions: &mut HashSet<[u8; 16]>,
    behavioral_by_event_name: &mut HashMap<String, HashSet<[u8; 16]>>,
    person_property_conditions: &mut HashSet<[u8; 16]>,
) {
    match node {
        FilterNode::Group { children, .. } => {
            for child in children {
                collect_leaf_meta(
                    child,
                    by_lsk,
                    behavioral_conditions,
                    behavioral_by_event_name,
                    person_property_conditions,
                );
            }
        }
        FilterNode::Leaf(CohortLeaf::Behavioral(leaf)) => {
            if let Ok((variant, window)) = pick_state_variant(leaf) {
                let (window_days, predicate_op) = match variant {
                    StateVariant::BehavioralDailyBuckets
                    | StateVariant::BehavioralCompressedHistory => (
                        Some(effective_window_days(leaf)),
                        Some(PredicateOp::from_leaf(
                            leaf.operator.as_deref(),
                            leaf.operator_value,
                        )),
                    ),
                    StateVariant::BehavioralSingle | StateVariant::PersonProperty => (None, None),
                };
                by_lsk.insert(
                    leaf.leaf_state_key,
                    LeafStateMeta {
                        variant,
                        condition_hash: leaf.condition_hash,
                        window,
                        window_days,
                        predicate_op,
                    },
                );
                behavioral_conditions.insert(leaf.condition_hash);
                behavioral_by_event_name
                    .entry(leaf.event_key.clone())
                    .or_default()
                    .insert(leaf.condition_hash);
            }
        }
        FilterNode::Leaf(CohortLeaf::PersonProperty(leaf)) => {
            by_lsk.insert(
                leaf.leaf_state_key,
                LeafStateMeta {
                    variant: StateVariant::PersonProperty,
                    condition_hash: leaf.condition_hash,
                    window: None,
                    window_days: None,
                    predicate_op: None,
                },
            );
            person_property_conditions.insert(leaf.condition_hash);
        }
        FilterNode::Leaf(CohortLeaf::CohortRef(_)) => {}
    }
}

/// Vec-ify a `conditionHash → HashSet<V>` map, sorting each value list for determinism.
fn sorted_vec_map<V: Ord>(map: HashMap<[u8; 16], HashSet<V>>) -> HashMap<[u8; 16], Vec<V>> {
    map.into_iter()
        .map(|(hash, set)| {
            let mut values: Vec<V> = set.into_iter().collect();
            values.sort_unstable();
            (hash, values)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    use crate::stage2::ExcludedReason;

    const HASH: [u8; 16] = *b"0123456789abcdef";

    const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";

    fn behavioral_bytecode() -> Value {
        json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
    }

    /// HogVM `RETURN` opcode, appended to stored bytecode by the catalog loader.
    const OP_RETURN: i64 = 38;

    /// The stored form of [`behavioral_bytecode`]: the loader appends a trailing `RETURN` (opcode 38).
    fn behavioral_bytecode_loaded() -> Vec<Value> {
        let mut bc = behavioral_bytecode().as_array().unwrap().clone();
        bc.push(json!(OP_RETURN));
        bc
    }

    /// A `performed_event` leaf on `$pageview` with a tunable window.
    fn behavioral_performed_event(time_value: i64) -> Value {
        json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "time_value": time_value,
            "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            // Identical across windows: leaves sharing a conditionHash share bytecode.
            "bytecode": behavioral_bytecode(),
        })
    }

    fn behavioral_performed_event_multiple(
        time_value: i64,
        time_interval: &str,
        operator: &str,
        operator_value: i64,
    ) -> Value {
        json!({
            "type": "behavioral",
            "value": "performed_event_multiple",
            "key": "$pageview",
            "time_value": time_value,
            "time_interval": time_interval,
            "operator": operator,
            "operator_value": operator_value,
            "conditionHash": "0123456789abcdef",
            "bytecode": behavioral_bytecode(),
        })
    }

    /// A `performed_event_multiple` leaf whose window comes from `explicit_datetime`(_to) rather than
    /// `time_value`/`time_interval` (pass `Value::Null` for an absent `_to`).
    fn behavioral_performed_event_multiple_explicit(
        explicit_datetime: &str,
        explicit_datetime_to: Value,
        operator: &str,
        operator_value: i64,
    ) -> Value {
        json!({
            "type": "behavioral",
            "value": "performed_event_multiple",
            "key": "$pageview",
            "explicit_datetime": explicit_datetime,
            "explicit_datetime_to": explicit_datetime_to,
            "operator": operator,
            "operator_value": operator_value,
            "conditionHash": "0123456789abcdef",
            "bytecode": behavioral_bytecode(),
        })
    }

    fn person_leaf() -> Value {
        json!({
            "type": "person",
            "key": "email",
            "value": "a@b.com",
            "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn wrap(values: Vec<Value>) -> Value {
        json!({ "properties": { "type": "AND", "values": values } })
    }

    #[test]
    fn freeze_carries_the_timezone_and_default_is_utc() {
        use chrono_tz::America::New_York;
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        assert_eq!(builder.freeze(New_York).timezone, New_York);
        assert_eq!(
            TeamFilters::default().timezone,
            UTC,
            "an empty filter set defaults to UTC",
        );
    }

    #[test]
    fn identical_leaves_dedupe_to_single_entries() {
        let mut builder = TeamFiltersBuilder::default();
        let filters = wrap(vec![
            behavioral_performed_event(7),
            behavioral_performed_event(7),
        ]);
        builder
            .add_cohort(CohortId(1), TeamId(7), &filters)
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(frozen.by_condition_to_lsk[&HASH].len(), 1);
        assert_eq!(frozen.by_condition_to_cohorts[&HASH], vec![CohortId(1)]);
        assert_eq!(frozen.unique_condition_hashes.len(), 1);
    }

    #[test]
    fn same_hash_different_windows_fan_out_to_distinct_leaf_state_keys() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(30)]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(frozen.by_condition_to_lsk[&HASH].len(), 2);
        assert_eq!(
            frozen.by_condition_to_cohorts[&HASH],
            vec![CohortId(1), CohortId(2)]
        );
        assert_eq!(frozen.unique_condition_hashes.len(), 1);
        assert_eq!(frozen.by_condition_to_bytecode.len(), 1);
    }

    #[test]
    fn bytecode_is_captured_under_its_condition_hash() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        let bytecode = frozen
            .by_condition_to_bytecode
            .get(&HASH)
            .expect("bytecode captured under the conditionHash");
        assert_eq!(bytecode.as_ref(), &behavioral_bytecode_loaded());
    }

    #[test]
    fn freeze_builds_by_lsk_with_variant_and_window() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), person_leaf()]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(frozen.by_lsk.len(), 2);

        let beh_lsk = frozen.by_condition_to_lsk[&HASH][0];
        let beh_meta = frozen.by_lsk[&beh_lsk];
        assert_eq!(beh_meta.variant, StateVariant::BehavioralSingle);
        assert_eq!(
            beh_meta.window,
            Some(EvictionWindow::RelativeDays { days: 7 })
        );

        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        let per_meta = frozen.by_lsk[&per_lsk];
        assert_eq!(per_meta.variant, StateVariant::PersonProperty);
        assert_eq!(per_meta.window, None);
        assert_eq!(per_meta.window_days, None);
        assert_eq!(per_meta.predicate_op, None);
    }

    #[test]
    fn freeze_daily_bucket_leaf_carries_window_days_and_op() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event_multiple(
                    7, "day", "gte", 3,
                )]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        let lsk = frozen.by_condition_to_lsk[&HASH][0];
        let meta = frozen.by_lsk[&lsk];
        assert_eq!(meta.variant, StateVariant::BehavioralDailyBuckets);
        assert_eq!(meta.window, None, "daily buckets carry no relative window");
        assert_eq!(meta.window_days, Some(7));
        assert_eq!(meta.predicate_op, Some(PredicateOp::Gte(3)));
        assert!(
            frozen.behavioral_conditions.contains(&HASH),
            "the multiple leaf's conditionHash is behavioral",
        );
    }

    #[test]
    fn freeze_compressed_leaf_carries_window_days_and_op() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event_multiple(
                    1, "year", "gte", 3,
                )]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        let lsk = frozen.by_condition_to_lsk[&HASH][0];
        let meta = frozen.by_lsk[&lsk];
        assert_eq!(meta.variant, StateVariant::BehavioralCompressedHistory);
        assert_eq!(meta.window, None, "compressed carries no relative window");
        assert_eq!(meta.window_days, Some(365), "year = 365 days");
        assert_eq!(meta.predicate_op, Some(PredicateOp::Gte(3)));
        assert!(frozen.behavioral_conditions.contains(&HASH));
    }

    #[test]
    fn freeze_drops_an_hourly_deferred_multiple() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event_multiple(
                    5, "hour", "gte", 3,
                )]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);
        assert!(
            frozen.by_lsk.is_empty(),
            "an hourly-deferred multiple leaves no worker metadata",
        );
    }

    #[test]
    fn freeze_explicit_relative_lower_multiple_carries_window_days_and_op() {
        // The UI stores "in the last N days" as `explicit_datetime: "-Nd"`; the frozen metadata must
        // carry the resolved window days and predicate op so the worker can bucket and compare.
        for (explicit_datetime, expected_variant, expected_days, why) in [
            (
                "-30d",
                StateVariant::BehavioralDailyBuckets,
                30,
                "-30d → 30 days → daily",
            ),
            (
                "-1y",
                StateVariant::BehavioralCompressedHistory,
                365,
                "-1y → 365 days → compressed",
            ),
        ] {
            let mut builder = TeamFiltersBuilder::default();
            builder
                .add_cohort(
                    CohortId(1),
                    TeamId(7),
                    &wrap(vec![behavioral_performed_event_multiple_explicit(
                        explicit_datetime,
                        Value::Null,
                        "gte",
                        3,
                    )]),
                )
                .unwrap();
            let frozen = builder.freeze(UTC);

            let lsk = frozen.by_condition_to_lsk[&HASH][0];
            let meta = frozen.by_lsk[&lsk];
            assert_eq!(meta.variant, expected_variant, "{why}");
            assert_eq!(meta.window, None, "{why}");
            assert_eq!(meta.window_days, Some(expected_days), "{why}");
            assert_eq!(meta.predicate_op, Some(PredicateOp::Gte(3)), "{why}");
        }
    }

    #[test]
    fn freeze_drops_an_explicit_absolute_range_multiple() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event_multiple_explicit(
                    "2026-01-01",
                    json!("2026-12-31"),
                    "gte",
                    3,
                )]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);
        assert!(
            frozen.by_lsk.is_empty(),
            "an absolute-range multiple has no sliding window and leaves no worker metadata",
        );
    }

    #[test]
    fn freeze_explicit_relative_lower_matches_the_time_value_interval_window_days() {
        // A relative `explicit_datetime` and the equivalent `time_value`/`time_interval` resolve to the
        // same frozen window metadata — they are the same oracle query.
        let mut explicit_builder = TeamFiltersBuilder::default();
        explicit_builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event_multiple_explicit(
                    "-30d",
                    Value::Null,
                    "gte",
                    3,
                )]),
            )
            .unwrap();
        let explicit = explicit_builder.freeze(UTC);
        let explicit_meta = explicit.by_lsk[&explicit.by_condition_to_lsk[&HASH][0]];

        let mut interval_builder = TeamFiltersBuilder::default();
        interval_builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event_multiple(
                    30, "day", "gte", 3,
                )]),
            )
            .unwrap();
        let interval = interval_builder.freeze(UTC);
        let interval_meta = interval.by_lsk[&interval.by_condition_to_lsk[&HASH][0]];

        assert_eq!(explicit_meta.window_days, Some(30));
        assert_eq!(explicit_meta.window_days, interval_meta.window_days);
        assert_eq!(explicit_meta.variant, interval_meta.variant);
        assert_eq!(explicit_meta.predicate_op, interval_meta.predicate_op);
    }

    #[test]
    fn freeze_partitions_conditions_by_kind() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), person_leaf()]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.behavioral_conditions,
            HashSet::from([HASH]),
            "the performed_event conditionHash is behavioral",
        );
        assert_eq!(
            frozen.person_property_conditions,
            HashSet::from([PERSON_HASH]),
            "the person conditionHash is person-property",
        );
        assert!(frozen
            .behavioral_conditions
            .is_disjoint(&frozen.person_property_conditions));
    }

    #[test]
    fn person_conditions_ordered_is_the_sorted_person_condition_set() {
        let mut other_person = person_leaf();
        other_person
            .as_object_mut()
            .unwrap()
            .insert("conditionHash".to_string(), json!("0011223344556677"));
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![
                    person_leaf(),
                    other_person,
                    behavioral_performed_event(7),
                ]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        let mut expected: Vec<[u8; 16]> =
            frozen.person_property_conditions.iter().copied().collect();
        expected.sort_unstable();
        assert_eq!(frozen.person_conditions_ordered, expected);
        assert!(
            frozen
                .person_conditions_ordered
                .windows(2)
                .all(|w| w[0] < w[1]),
            "the order is strictly ascending and carries no behavioral hash",
        );
    }

    /// Build a person leaf carrying a specific conditionHash literal.
    fn person_leaf_with_hash(hash: &str) -> Value {
        let mut leaf = person_leaf();
        leaf.as_object_mut()
            .unwrap()
            .insert("conditionHash".to_string(), json!(hash));
        leaf
    }

    fn freeze_person_conditions(leaves: Vec<Value>) -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(leaves))
            .unwrap();
        builder.freeze(UTC)
    }

    #[test]
    fn catalog_fingerprint_matches_the_sorted_conditions_and_is_freeze_stable() {
        let a = freeze_person_conditions(vec![
            person_leaf_with_hash("aaaaaaaaaaaaaaaa"),
            person_leaf_with_hash("bbbbbbbbbbbbbbbb"),
        ]);
        assert_eq!(
            a.catalog_fingerprint,
            CatalogFingerprint::of_sorted(&a.person_conditions_ordered),
        );
        let b = freeze_person_conditions(vec![
            person_leaf_with_hash("aaaaaaaaaaaaaaaa"),
            person_leaf_with_hash("bbbbbbbbbbbbbbbb"),
        ]);
        assert_eq!(a.catalog_fingerprint, b.catalog_fingerprint);
    }

    #[test]
    fn catalog_fingerprint_is_invariant_to_insertion_order() {
        let ordered = freeze_person_conditions(vec![
            person_leaf_with_hash("aaaaaaaaaaaaaaaa"),
            person_leaf_with_hash("bbbbbbbbbbbbbbbb"),
        ]);
        let reversed = freeze_person_conditions(vec![
            person_leaf_with_hash("bbbbbbbbbbbbbbbb"),
            person_leaf_with_hash("aaaaaaaaaaaaaaaa"),
        ]);
        assert_eq!(ordered.catalog_fingerprint, reversed.catalog_fingerprint);
    }

    #[test]
    fn catalog_fingerprint_changes_when_a_condition_is_added_or_removed() {
        let two = freeze_person_conditions(vec![
            person_leaf_with_hash("aaaaaaaaaaaaaaaa"),
            person_leaf_with_hash("bbbbbbbbbbbbbbbb"),
        ]);
        let one = freeze_person_conditions(vec![person_leaf_with_hash("aaaaaaaaaaaaaaaa")]);
        let three = freeze_person_conditions(vec![
            person_leaf_with_hash("aaaaaaaaaaaaaaaa"),
            person_leaf_with_hash("bbbbbbbbbbbbbbbb"),
            person_leaf_with_hash("cccccccccccccccc"),
        ]);
        assert_ne!(two.catalog_fingerprint, one.catalog_fingerprint);
        assert_ne!(two.catalog_fingerprint, three.catalog_fingerprint);
    }

    #[test]
    fn catalog_fingerprint_of_no_person_conditions_is_the_empty_constant() {
        // A team with only a behavioral leaf has no person conditions.
        let behavioral_only = freeze_person_conditions(vec![behavioral_performed_event(7)]);
        assert!(behavioral_only.person_conditions_ordered.is_empty());
        assert_eq!(
            behavioral_only.catalog_fingerprint,
            CatalogFingerprint::of_sorted(&[]),
            "no person conditions ⇒ the stable empty-input fingerprint",
        );
        assert_eq!(
            behavioral_only.catalog_fingerprint,
            TeamFilters::default().catalog_fingerprint,
        );
    }

    #[test]
    fn behavioral_by_event_name_buckets_each_name_and_unions_to_behavioral_conditions() {
        const PURCHASE_HASH: [u8; 16] = *b"purchasehash0002";
        let purchase = json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "purchase",
            "time_value": 7,
            "time_interval": "day",
            "conditionHash": "purchasehash0002",
            "bytecode": ["_H", 1, 32, "purchase", 32, "event", 1, 1, 11],
        });
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), purchase, person_leaf()]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(frozen.behavioral_by_event_name["$pageview"], vec![HASH]);
        assert_eq!(
            frozen.behavioral_by_event_name["purchase"],
            vec![PURCHASE_HASH],
        );
        assert!(
            !frozen.behavioral_by_event_name.contains_key("email"),
            "a person leaf is not bucketed by event name",
        );

        let union: HashSet<[u8; 16]> = frozen
            .behavioral_by_event_name
            .values()
            .flatten()
            .copied()
            .collect();
        assert_eq!(
            union, frozen.behavioral_conditions,
            "the buckets partition exactly the behavioral conditions",
        );
    }

    #[test]
    fn same_event_name_collects_distinct_hashes_deduped_and_sorted() {
        const HASH2: [u8; 16] = *b"0011223344556677";
        let mut other = behavioral_performed_event_multiple(7, "day", "gte", 3);
        other
            .as_object_mut()
            .unwrap()
            .insert("conditionHash".to_string(), json!("0011223344556677"));
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![
                    behavioral_performed_event(7),
                    behavioral_performed_event(7),
                    other,
                ]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        let mut expected = [HASH, HASH2];
        expected.sort_unstable();
        assert_eq!(
            frozen.behavioral_by_event_name["$pageview"],
            expected.to_vec(),
            "the bucket dedupes the repeated leaf and sorts its two distinct hashes",
        );
    }

    #[test]
    fn freeze_recurses_into_nested_groups() {
        let mut builder = TeamFiltersBuilder::default();
        let filters = json!({
            "properties": {
                "type": "OR",
                "values": [{
                    "type": "AND",
                    "values": [behavioral_performed_event(7)],
                }],
            }
        });
        builder
            .add_cohort(CohortId(1), TeamId(7), &filters)
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(frozen.by_lsk.len(), 1);
        assert_eq!(frozen.behavioral_conditions, HashSet::from([HASH]));
    }

    fn cohort_ref() -> Value {
        json!({ "type": "cohort", "value": 99, "negation": false })
    }

    fn cohort_ref_to(target: i32) -> Value {
        json!({ "type": "cohort", "value": target, "negation": false })
    }

    /// A negated cohort-reference leaf (`NOT in target`).
    fn cohort_ref_to_negated(target: i32) -> Value {
        json!({ "type": "cohort", "value": target, "negation": true })
    }

    #[test]
    fn single_leaf_cohort_is_indexed_by_its_lsk() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        let lsk = frozen.by_condition_to_lsk[&HASH][0];
        assert_eq!(
            frozen.by_lsk_to_single_leaf_cohorts.get(&lsk),
            Some(&vec![CohortId(1)]),
        );
        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::SingleLeaf(lsk),
        );
    }

    #[test]
    fn c1_two_single_leaf_cohorts_same_hash_different_windows_map_to_their_own_lsk() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(30)]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.by_condition_to_cohorts[&HASH],
            vec![CohortId(1), CohortId(2)]
        );

        let lsks = &frozen.by_condition_to_lsk[&HASH];
        assert_eq!(lsks.len(), 2);
        let mut owners: Vec<Vec<CohortId>> = lsks
            .iter()
            .map(|lsk| frozen.by_lsk_to_single_leaf_cohorts[lsk].clone())
            .collect();
        owners.sort();
        assert_eq!(owners, vec![vec![CohortId(1)], vec![CohortId(2)]]);
    }

    #[test]
    fn identical_single_leaf_cohorts_share_one_lsk_sorted() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        let lsk = frozen.by_condition_to_lsk[&HASH][0];
        assert_eq!(
            frozen.by_lsk_to_single_leaf_cohorts[&lsk],
            vec![CohortId(1), CohortId(2)],
        );
    }

    #[test]
    fn multi_leaf_cohort_is_not_indexed() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), person_leaf()]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert!(
            frozen.by_lsk_to_single_leaf_cohorts.is_empty(),
            "multi-leaf cohort contributes no single-leaf mapping",
        );
        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Stage2Composable,
            "two positive state leaves are composable",
        );
    }

    #[test]
    fn single_cohort_ref_cohort_is_not_indexed() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![cohort_ref()]))
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert!(frozen.by_lsk_to_single_leaf_cohorts.is_empty());
        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::UnresolvedRef),
        );
    }

    #[test]
    fn nested_single_leaf_cohort_is_indexed() {
        let mut builder = TeamFiltersBuilder::default();
        let filters = json!({
            "properties": {
                "type": "OR",
                "values": [{ "type": "AND", "values": [behavioral_performed_event(7)] }],
            }
        });
        builder
            .add_cohort(CohortId(1), TeamId(7), &filters)
            .unwrap();
        let frozen = builder.freeze(UTC);

        let lsk = frozen.by_condition_to_lsk[&HASH][0];
        assert_eq!(
            frozen.by_lsk_to_single_leaf_cohorts[&lsk],
            vec![CohortId(1)]
        );
        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::SingleLeaf(lsk),
        );
    }

    #[test]
    fn empty_all_dropped_cohort_is_not_indexed() {
        let mut builder = TeamFiltersBuilder::default();
        let dropped =
            json!({ "type": "behavioral", "key": "$pageview", "value": "performed_event" });
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![dropped]))
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert!(frozen.by_lsk_to_single_leaf_cohorts.is_empty());
        assert!(
            frozen.by_lsk.is_empty(),
            "the dropped leaf left no state metadata"
        );
        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::HasDroppedLeaf),
        );
    }

    #[test]
    fn collapse_shape_with_dropped_sibling_is_excluded_not_single_leaf() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![
                    behavioral_performed_event_multiple(5, "hour", "gte", 3),
                    behavioral_performed_event(7),
                ]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::HasDroppedLeaf),
        );
        assert!(
            frozen.by_lsk_to_single_leaf_cohorts.is_empty(),
            "the surviving leaf must NOT map the dropped-sibling cohort as single-leaf",
        );
        assert_eq!(
            frozen.by_lsk.len(),
            1,
            "the surviving leaf still carries meta"
        );
    }

    #[test]
    fn negated_single_behavioral_leaf_is_excluded_top_level_negation() {
        let mut leaf = behavioral_performed_event(7);
        leaf.as_object_mut()
            .unwrap()
            .insert("negation".to_string(), json!(true));
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![leaf]))
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation),
        );
        assert!(
            frozen.by_lsk_to_single_leaf_cohorts.is_empty(),
            "an explicitly negated single leaf must not map as single-leaf",
        );
    }

    #[test]
    fn not_in_operator_alone_does_not_negate_a_state_keyed_leaf() {
        // `operator: "not_in"` on a person/behavioral leaf is a value-list predicate compiled into
        // the bytecode, not a composition negation. Only the cohort-ref form treats `not_in` as negation.
        let mut leaf = person_leaf();
        leaf.as_object_mut()
            .unwrap()
            .insert("operator".to_string(), json!("not_in"));
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![leaf]))
            .unwrap();
        let frozen = builder.freeze(UTC);

        let lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::SingleLeaf(lsk),
            "a person `not_in` predicate is positive membership, not a negated cohort",
        );
        assert_eq!(
            frozen.by_lsk_to_single_leaf_cohorts[&lsk],
            vec![CohortId(1)]
        );
    }

    #[test]
    fn negated_single_person_leaf_is_excluded_top_level_negation() {
        let mut leaf = person_leaf();
        leaf.as_object_mut()
            .unwrap()
            .insert("negation".to_string(), json!(true));
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![leaf]))
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::TopLevelNegation),
        );
        assert!(frozen.by_lsk_to_single_leaf_cohorts.is_empty());
    }

    #[test]
    fn composable_cohort_indexes_each_distinct_leaf_to_itself() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), person_leaf()]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Stage2Composable,
        );
        let beh_lsk = frozen.by_condition_to_lsk[&HASH][0];
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        assert_eq!(
            frozen.by_lsk_to_composable_cohorts[&beh_lsk],
            vec![CohortId(1)],
        );
        assert_eq!(
            frozen.by_lsk_to_composable_cohorts[&per_lsk],
            vec![CohortId(1)],
        );
        assert!(
            frozen.by_lsk_to_single_leaf_cohorts.is_empty(),
            "a composable cohort contributes no single-leaf mapping",
        );
    }

    #[test]
    fn composable_same_hash_different_windows_index_distinct_lsks_not_the_condition_hash() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![
                    behavioral_performed_event(7),
                    behavioral_performed_event(30),
                ]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        let lsks = &frozen.by_condition_to_lsk[&HASH];
        assert_eq!(
            lsks.len(),
            2,
            "two windows fan out to two LSKs under one hash"
        );
        for lsk in lsks {
            assert_eq!(
                frozen.by_lsk_to_composable_cohorts[lsk],
                vec![CohortId(1)],
                "each window's LSK maps to the composable cohort",
            );
        }
    }

    #[test]
    fn composable_cohort_with_duplicate_leaf_is_indexed_once() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![
                    behavioral_performed_event(7),
                    behavioral_performed_event(7),
                ]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Stage2Composable,
        );
        let lsk = frozen.by_condition_to_lsk[&HASH][0];
        assert_eq!(
            frozen.by_lsk_to_composable_cohorts[&lsk],
            vec![CohortId(1)],
            "a duplicated leaf indexes the cohort once, not twice",
        );
    }

    #[test]
    fn leaf_shared_by_single_leaf_and_composable_cohorts_appears_in_both_maps() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), person_leaf()]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        let beh_lsk = frozen.by_condition_to_lsk[&HASH][0];
        assert_eq!(
            frozen.by_lsk_to_single_leaf_cohorts[&beh_lsk],
            vec![CohortId(1)],
            "the bare leaf drives cohort 1's whole membership",
        );
        assert_eq!(
            frozen.by_lsk_to_composable_cohorts[&beh_lsk],
            vec![CohortId(2)],
            "the same leaf, as one input to cohort 2, fans Stage 2 back to cohort 2",
        );
    }

    #[test]
    fn and_a_neg_b_is_composable_with_both_lsks_in_composable_map() {
        let mut neg_person = person_leaf();
        neg_person
            .as_object_mut()
            .unwrap()
            .insert("negation".to_string(), json!(true));
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7), neg_person]),
            )
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Stage2Composable,
            "AND(A, ¬B) is composable — the root is not all-negated",
        );
        let beh_lsk = frozen.by_condition_to_lsk[&HASH][0];
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        assert_eq!(
            frozen.by_lsk_to_composable_cohorts[&beh_lsk],
            vec![CohortId(1)],
        );
        assert_eq!(
            frozen.by_lsk_to_composable_cohorts[&per_lsk],
            vec![CohortId(1)],
        );
        assert!(
            frozen.by_lsk.contains_key(&per_lsk),
            "the negated leaf carries state metadata",
        );
    }

    #[test]
    fn and_leaf_empty_or_is_excluded_empty_group() {
        let filters = json!({
            "properties": {
                "type": "AND",
                "values": [
                    behavioral_performed_event(7),
                    { "type": "OR", "values": [] },
                ],
            }
        });
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(7), &filters)
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::EmptyGroup),
        );
        assert!(
            frozen.by_lsk_to_single_leaf_cohorts.is_empty(),
            "an empty-group cohort must not map as single-leaf",
        );
    }

    #[test]
    fn single_leaf_and_excluded_cohorts_contribute_nothing_to_the_composable_map() {
        let mut builder = TeamFiltersBuilder::default();
        // Single-leaf.
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        // Excluded (cohort ref).
        builder
            .add_cohort(CohortId(2), TeamId(7), &wrap(vec![cohort_ref()]))
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert!(
            frozen.by_lsk_to_composable_cohorts.is_empty(),
            "neither a single-leaf nor an excluded cohort is composable",
        );
    }

    #[test]
    fn reverse_index_inverts_ref_targets() {
        let mut builder = TeamFiltersBuilder::default();
        // A(1) → B(2), D(4); C(3) → B(2).
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![cohort_ref_to(2), cohort_ref_to(4)]),
            )
            .unwrap();
        builder
            .add_cohort(CohortId(3), TeamId(7), &wrap(vec![cohort_ref_to(2)]))
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.cohorts_referencing(CohortId(2)),
            [CohortId(1), CohortId(3)].as_slice(),
            "B is referenced by A and C, sorted",
        );
        assert_eq!(
            frozen.cohorts_referencing(CohortId(4)),
            [CohortId(1)].as_slice(),
        );
        assert!(
            frozen.cohorts_referencing(CohortId(5)).is_empty(),
            "an unreferenced cohort has no referrers",
        );
    }

    #[test]
    fn ref_bearing_cohort_is_reverse_indexed_but_stays_dormant() {
        let mut builder = TeamFiltersBuilder::default();
        // B: a resolvable single-leaf cohort.
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        // A references B: ref-bearing, so excluded but still reverse-indexed.
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![cohort_ref_to(2)]))
            .unwrap();
        let frozen = builder.freeze(UTC);

        assert_eq!(
            frozen.cohorts_referencing(CohortId(2)),
            [CohortId(1)].as_slice(),
        );
        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::HasCohortRef),
        );
        assert!(
            frozen
                .by_lsk_to_composable_cohorts
                .values()
                .all(|cohorts| !cohorts.contains(&CohortId(1))),
            "a ref-bearing cohort must not compose",
        );
    }

    #[test]
    fn cascade_on_pure_ref_cohort_is_composable_ref_but_indexes_no_lsk() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        // 1 is a pure cohort-ref to the single-leaf 2: no own state-keyed leaves.
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![cohort_ref_to(2)]))
            .unwrap();
        let frozen = builder.freeze_with(UTC, true);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Stage2ComposableRef,
            "a resolvable, cycle-free ref cohort is promoted when the gate is on",
        );
        assert!(
            frozen
                .by_lsk_to_composable_cohorts
                .values()
                .all(|cohorts| !cohorts.contains(&CohortId(1))),
            "a pure-ref cohort has no own leaves, so it joins no composable LSK",
        );
        assert_eq!(
            frozen.cohorts_referencing(CohortId(2)),
            [CohortId(1)].as_slice(),
            "the reverse-reference index still points B's referrer back at A",
        );
    }

    #[test]
    fn cascade_on_ref_with_own_leaves_is_composable_ref_and_indexes_its_own_lsk() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(2),
                TeamId(7),
                &wrap(vec![behavioral_performed_event(7)]),
            )
            .unwrap();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![person_leaf(), cohort_ref_to(2)]),
            )
            .unwrap();
        let frozen = builder.freeze_with(UTC, true);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Stage2ComposableRef,
        );
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        assert_eq!(
            frozen.by_lsk_to_composable_cohorts[&per_lsk],
            vec![CohortId(1)],
            "the ref cohort's own person leaf re-triggers it on the event path",
        );
    }

    #[test]
    fn cascade_on_cycle_members_stay_excluded() {
        let mut builder = TeamFiltersBuilder::default();
        // 1 → 2 → 1 cycle.
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![cohort_ref_to(2)]))
            .unwrap();
        builder
            .add_cohort(CohortId(2), TeamId(7), &wrap(vec![cohort_ref_to(1)]))
            .unwrap();
        let frozen = builder.freeze_with(UTC, true);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::CycleDetected),
        );
        assert_eq!(
            frozen.eligibility[&CohortId(2)],
            CohortEligibility::Excluded(ExcludedReason::CycleDetected),
        );
    }

    #[test]
    fn cascade_on_unresolved_ref_stays_excluded() {
        let mut builder = TeamFiltersBuilder::default();
        // 99 is never added to the catalog.
        builder
            .add_cohort(CohortId(1), TeamId(7), &wrap(vec![cohort_ref_to(99)]))
            .unwrap();
        let frozen = builder.freeze_with(UTC, true);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::UnresolvedRef),
        );
    }

    #[test]
    fn cascade_on_negated_missing_ref_with_own_leaf_is_composable_ref_and_reads_true() {
        use crate::stage2::evaluator::evaluate_tree;

        let mut builder = TeamFiltersBuilder::default();
        // 1 = AND(own person leaf, NOT in 99). 99 is never added: an absent negated ref reads
        // `true`, so the missing target must not exclude 1 (oracle: `false ^ true = true`).
        builder
            .add_cohort(
                CohortId(1),
                TeamId(7),
                &wrap(vec![person_leaf(), cohort_ref_to_negated(99)]),
            )
            .unwrap();
        let frozen = builder.freeze_with(UTC, true);

        assert_eq!(
            frozen.eligibility[&CohortId(1)],
            CohortEligibility::Stage2ComposableRef,
            "a negated ref to a missing target never blocks composition",
        );
        let per_lsk = LeafStateKey::for_person_property(&PERSON_HASH);
        assert_eq!(
            frozen.by_lsk_to_composable_cohorts[&per_lsk],
            vec![CohortId(1)],
            "the cohort's own person leaf indexes it for re-evaluation on the event path",
        );

        // The composer fills a missing referent as `false`; the negated leaf flips it to `true`,
        // so the cohort's membership tracks its own leaf alone.
        let root = &frozen.cohorts[&CohortId(1)].root;
        let ref_membership = HashMap::from([(CohortId(99), false)]);
        let off = evaluate_tree(root, &HashMap::from([(per_lsk, false)]), &ref_membership);
        let on = evaluate_tree(root, &HashMap::from([(per_lsk, true)]), &ref_membership);
        assert!(
            !off,
            "own leaf off ⇒ non-member even though the negated ref reads true"
        );
        assert!(
            on,
            "own leaf flipping on ⇒ member, the Entered the cascade slice must emit"
        );
    }

    #[test]
    fn freeze_equals_freeze_with_false_on_a_ref_bearing_team() {
        let build = || {
            let mut builder = TeamFiltersBuilder::default();
            builder
                .add_cohort(
                    CohortId(2),
                    TeamId(7),
                    &wrap(vec![behavioral_performed_event(7)]),
                )
                .unwrap();
            builder
                .add_cohort(
                    CohortId(1),
                    TeamId(7),
                    &wrap(vec![person_leaf(), cohort_ref_to(2)]),
                )
                .unwrap();
            builder
        };
        let via_freeze = build().freeze(UTC);
        let via_freeze_with = build().freeze_with(UTC, false);

        assert_eq!(via_freeze.eligibility, via_freeze_with.eligibility);
        assert_eq!(
            via_freeze.by_lsk_to_composable_cohorts,
            via_freeze_with.by_lsk_to_composable_cohorts,
        );
        assert_eq!(
            via_freeze.by_lsk_to_single_leaf_cohorts,
            via_freeze_with.by_lsk_to_single_leaf_cohorts,
        );
        assert_eq!(
            via_freeze.by_referenced_cohort,
            via_freeze_with.by_referenced_cohort,
        );
        assert_eq!(
            via_freeze.eligibility[&CohortId(1)],
            CohortEligibility::Excluded(ExcludedReason::HasCohortRef),
            "gate off leaves the resolvable ref cohort excluded, not promoted",
        );
    }
}
