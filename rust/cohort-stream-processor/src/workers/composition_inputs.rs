//! What Stage 2 composition reads from the store for one person, and how those reads decode.
//!
//! A [`CompositionReadPlan`] is settled from a frozen catalog and names no person, so one plan
//! serves every person it is bound to: the seed path builds one per person's affected cohorts,
//! reconcile builds one per page. [`PersonScope`] turns it into keys;
//! [`ResolvedPersonInputs`] is what the raw values decode to, compact enough to outlive the
//! sections that read them.
//!
//! Both recompute orders classify references through [`ReferenceSource`], so a referent cannot
//! resolve from one store on one path and another on the other.

use std::collections::{BTreeMap, HashMap};

use metrics::counter;
use uuid::Uuid;

use crate::filters::reverse_index::{LeafStateMeta, TeamFilters};
use crate::filters::CohortId;
use crate::observability::metrics::STAGE2_STATE_DECODE_ERROR;
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::PersonRecord;
use crate::stage1::state::StateVariant;
use crate::stage2::evaluator::leaf_membership;
use crate::stage2::CohortEligibility;
use crate::store::{BehavioralKey, PersonRecordKey, Stage2Key};
use crate::workers::stage2_path::{
    collect_cohort_refs, collect_leaf_state_keys, decode_stage1_state, read_prior_stage2,
    PriorStage2State,
};

/// How a referenced cohort's membership resolves for one person.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum ReferenceSource {
    /// Membership is the leaf's own bit, read through that leaf's comparator.
    Leaf(LeafStateKey),
    /// Membership is the composed row the store holds.
    Stored,
    /// Excluded, cyclic, or absent from the frozen catalog.
    NonMember,
}

impl ReferenceSource {
    pub(super) fn classify(filters: &TeamFilters, ref_id: CohortId) -> Self {
        match filters.eligibility.get(&ref_id) {
            Some(CohortEligibility::SingleLeaf(lsk)) => Self::Leaf(*lsk),
            Some(eligibility) if eligibility.writes_cf_stage2() => Self::Stored,
            _ => Self::NonMember,
        }
    }
}

/// Everything composing a set of cohorts reads from the store, minus the person. Owned, so a reader
/// can carry it into blocking sections.
#[derive(Debug)]
pub(super) struct CompositionReadPlan {
    /// Ascending and deduplicated. Every id here has a tree in the frozen catalog.
    cohorts: Vec<CohortId>,
    behavioral: Vec<(LeafStateKey, LeafStateMeta)>,
    person_leaves: Vec<LeafStateKey>,
    /// Each composed cohort's own prior row, plus every composed referent. One row serves both when
    /// a referent is also composed here.
    stage2_cohorts: Vec<CohortId>,
    references: BTreeMap<CohortId, ReferenceSource>,
}

impl CompositionReadPlan {
    /// Reads the frozen catalog only, so the plan is settled before anything holds a store permit.
    pub(super) fn for_cohorts(
        cohorts: impl IntoIterator<Item = CohortId>,
        filters: &TeamFilters,
    ) -> Self {
        let mut plan = Self {
            cohorts: Vec::new(),
            behavioral: Vec::new(),
            person_leaves: Vec::new(),
            stage2_cohorts: Vec::new(),
            references: BTreeMap::new(),
        };

        let mut lsks = Vec::new();
        let mut refs = Vec::new();
        for cohort_id in cohorts {
            let Some(tree) = filters.cohorts.get(&cohort_id) else {
                continue;
            };
            plan.cohorts.push(cohort_id);
            // The diff needs the prior row whether or not the cohort flips.
            plan.stage2_cohorts.push(cohort_id);

            lsks.clear();
            collect_leaf_state_keys(&tree.root, &mut lsks);
            for &lsk in &lsks {
                plan.route_leaf(lsk, filters);
            }

            refs.clear();
            collect_cohort_refs(&tree.root, &mut refs);
            for &ref_id in &refs {
                plan.route_reference(ref_id, filters);
            }
        }

        plan.dedup_read_sets();
        plan
    }

    /// A key the frozen catalog does not carry is routed nowhere, so composition reads it as a
    /// non-member.
    fn route_leaf(&mut self, lsk: LeafStateKey, filters: &TeamFilters) {
        let Some(meta) = filters.by_lsk.get(&lsk) else {
            return;
        };
        match meta.variant {
            StateVariant::PersonProperty => self.person_leaves.push(lsk),
            // No wildcard, so a future membership source reading from another store fails to
            // compile here instead of being misrouted into `cf_behavioral`.
            StateVariant::BehavioralSingle
            | StateVariant::BehavioralDailyBuckets
            | StateVariant::BehavioralCompressedHistory => self.behavioral.push((lsk, *meta)),
        }
    }

    fn route_reference(&mut self, ref_id: CohortId, filters: &TeamFilters) {
        if self.references.contains_key(&ref_id) {
            return;
        }
        let source = ReferenceSource::classify(filters, ref_id);
        match source {
            ReferenceSource::Leaf(lsk) => self.route_leaf(lsk, filters),
            ReferenceSource::Stored => self.stage2_cohorts.push(ref_id),
            ReferenceSource::NonMember => {}
        }
        self.references.insert(ref_id, source);
    }

    fn dedup_read_sets(&mut self) {
        self.cohorts.sort_unstable();
        self.cohorts.dedup();
        self.behavioral.sort_unstable_by_key(|(lsk, _)| *lsk);
        self.behavioral.dedup_by_key(|(lsk, _)| *lsk);
        self.person_leaves.sort_unstable();
        self.person_leaves.dedup();
        self.stage2_cohorts.sort_unstable();
        self.stage2_cohorts.dedup();
    }

    pub(super) fn is_empty(&self) -> bool {
        self.cohorts.is_empty()
    }

    pub(super) fn cohorts(&self) -> &[CohortId] {
        &self.cohorts
    }

    pub(super) fn behavioral(&self) -> &[(LeafStateKey, LeafStateMeta)] {
        &self.behavioral
    }

    pub(super) fn person_leaves(&self) -> &[LeafStateKey] {
        &self.person_leaves
    }

    pub(super) fn stage2_cohorts(&self) -> &[CohortId] {
        &self.stage2_cohorts
    }

    /// One bit per referenced cohort, shared by every cohort here that names it. Entries a given
    /// tree does not reference are inert, because `evaluate_tree` reads only its own ids.
    pub(super) fn reference_membership(
        &self,
        inputs: &ResolvedPersonInputs,
    ) -> HashMap<CohortId, bool> {
        self.references
            .iter()
            .map(|(&ref_id, source)| {
                let member = match source {
                    ReferenceSource::Leaf(lsk) => inputs.leaf_membership(*lsk),
                    ReferenceSource::Stored => inputs.prior_stage2(ref_id).in_cohort,
                    ReferenceSource::NonMember => false,
                };
                (ref_id, member)
            })
            .collect()
    }
}

/// One person's corner of the keyspace: what binds a [`CompositionReadPlan`] to store keys.
#[derive(Debug, Clone, Copy)]
pub(super) struct PersonScope {
    partition_id: u16,
    team_id: u64,
    person_id: Uuid,
}

impl PersonScope {
    pub(super) fn new(partition_id: u16, team_id: u64, person_id: Uuid) -> Self {
        Self {
            partition_id,
            team_id,
            person_id,
        }
    }

    pub(super) fn behavioral_key(&self, lsk: LeafStateKey) -> BehavioralKey {
        BehavioralKey::new(self.partition_id, self.team_id, self.person_id, lsk)
    }

    pub(super) fn person_record_key(&self) -> PersonRecordKey {
        PersonRecordKey::new(self.partition_id, self.team_id, self.person_id)
    }

    pub(super) fn stage2_key(&self, cohort_id: CohortId) -> Stage2Key {
        Stage2Key {
            partition_id: self.partition_id,
            team_id: self.team_id,
            cohort_id: cohort_id.0 as u64,
            person_id: self.person_id,
        }
    }
}

/// One person's decoded inputs. Compact enough to outlive the sections that read them, because each
/// batch's raw values are dropped as they decode.
#[derive(Debug, Default)]
pub(super) struct ResolvedPersonInputs {
    membership: HashMap<LeafStateKey, bool>,
    stage2: HashMap<CohortId, PriorStage2State>,
}

impl ResolvedPersonInputs {
    pub(super) fn with_capacity_for(plan: &CompositionReadPlan) -> Self {
        Self {
            membership: HashMap::with_capacity(plan.behavioral.len() + plan.person_leaves.len()),
            stage2: HashMap::with_capacity(plan.stage2_cohorts.len()),
        }
    }

    pub(super) fn membership(&self) -> &HashMap<LeafStateKey, bool> {
        &self.membership
    }

    /// A leaf the frozen catalog did not back was never read, and reads as a non-member.
    fn leaf_membership(&self, lsk: LeafStateKey) -> bool {
        self.membership.get(&lsk).copied().unwrap_or(false)
    }

    /// A row the plan did not ask for takes the same fail-closed reading as an absent one.
    pub(super) fn prior_stage2(&self, cohort_id: CohortId) -> PriorStage2State {
        self.stage2.get(&cohort_id).copied().unwrap_or_default()
    }

    /// A person leaf's state key *is* its condition hash, so its bit is
    /// `record.matched.contains(hash)`. An absent or corrupt record reads every person leaf as a
    /// non-member, and a corrupt one counts once per person rather than once per cohort.
    pub(super) fn absorb_person_record(
        &mut self,
        person_leaves: &[LeafStateKey],
        bytes: Option<Vec<u8>>,
    ) {
        let matched = match bytes {
            None => None,
            Some(bytes) => match PersonRecord::decode(&bytes) {
                Ok(record) => Some(record.matched),
                Err(_) => {
                    counter!(STAGE2_STATE_DECODE_ERROR).increment(1);
                    None
                }
            },
        };
        for &lsk in person_leaves {
            let member = matched
                .as_ref()
                .is_some_and(|matched| matched.contains(&lsk.0));
            self.membership.insert(lsk, member);
        }
    }

    pub(super) fn absorb_behavioral(
        &mut self,
        batch: &[(LeafStateKey, LeafStateMeta)],
        raw: Vec<Option<Vec<u8>>>,
    ) {
        for (&(lsk, ref meta), bytes) in batch.iter().zip(raw) {
            let state = decode_stage1_state(bytes);
            self.membership
                .insert(lsk, leaf_membership(state.as_ref(), meta));
        }
    }

    pub(super) fn absorb_stage2(&mut self, batch: &[CohortId], raw: Vec<Option<Vec<u8>>>) {
        for (&cohort_id, bytes) in batch.iter().zip(raw) {
            self.stage2.insert(cohort_id, read_prior_stage2(bytes));
        }
    }
}

/// What one batched read returned, for the byte histograms. A miss contributes a real `0`.
pub(super) fn raw_bytes(values: &[Option<Vec<u8>>]) -> usize {
    values.iter().flatten().map(Vec::len).sum()
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};

    use crate::filters::{TeamFiltersBuilder, TeamId};

    const TEAM: TeamId = TeamId(7);
    const PERSON_HASH: &str = "person0000000001";

    fn hash(text: &str) -> [u8; 16] {
        text.as_bytes()
            .try_into()
            .expect("a 16-byte condition hash")
    }

    fn behavioral_leaf(condition_hash: &str) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": 7, "time_interval": "day",
            "conditionHash": condition_hash,
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn person_leaf() -> Value {
        json!({
            "type": "person", "key": "email", "value": "u@p.com", "operator": "exact",
            "conditionHash": PERSON_HASH,
            "bytecode": ["_H", 1, 32, "u@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn cohort_ref(target: i32) -> Value {
        negated_cohort_ref(target, false)
    }

    fn negated_cohort_ref(target: i32, negation: bool) -> Value {
        json!({ "type": "cohort", "value": target, "negation": negation })
    }

    fn freeze(cohorts: Vec<(i32, Vec<Value>)>) -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        for (id, values) in cohorts {
            let cohort = json!({ "properties": { "type": "AND", "values": values } });
            builder.add_cohort(CohortId(id), TEAM, &cohort).unwrap();
        }
        builder.freeze_with(UTC, true)
    }

    fn plan_for(filters: &TeamFilters, cohorts: &[i32]) -> CompositionReadPlan {
        CompositionReadPlan::for_cohorts(cohorts.iter().map(|&id| CohortId(id)), filters)
    }

    fn behavioral_lsks(plan: &CompositionReadPlan) -> Vec<LeafStateKey> {
        plan.behavioral().iter().map(|&(lsk, _)| lsk).collect()
    }

    /// Whatever the fan-out, one person is one record read and one key per distinct row.
    #[test]
    fn a_person_reads_one_record_and_one_key_per_distinct_row() {
        let filters = freeze(vec![
            (1, vec![behavioral_leaf("shared0000000001"), person_leaf()]),
            (2, vec![behavioral_leaf("shared0000000001"), person_leaf()]),
            (3, vec![behavioral_leaf("own0000000000003"), person_leaf()]),
        ]);
        let plan = plan_for(&filters, &[1, 2, 3]);

        assert_eq!(plan.cohorts(), [CohortId(1), CohortId(2), CohortId(3)]);
        assert_eq!(
            plan.person_leaves(),
            [LeafStateKey::for_person_property(&hash(PERSON_HASH))],
            "three cohorts naming one person condition still read one record",
        );
        assert_eq!(
            behavioral_lsks(&plan),
            {
                let mut want = vec![
                    filters.by_condition_to_lsk[&hash("shared0000000001")][0],
                    filters.by_condition_to_lsk[&hash("own0000000000003")][0],
                ];
                want.sort_unstable();
                want
            },
            "the leaf two cohorts share is one key, not two",
        );
        assert_eq!(
            plan.stage2_cohorts(),
            [CohortId(1), CohortId(2), CohortId(3)],
            "each pair's own prior row, and nothing else",
        );
        assert!(plan.references.is_empty());
    }

    /// A referent recomputing in the same group is still one stored row, read alongside the pairs'
    /// own priors rather than substituted with the bit this run is about to write.
    #[test]
    fn a_referent_recomputed_in_the_same_group_is_planned_as_one_stored_row() {
        let filters = freeze(vec![
            (1, vec![person_leaf(), cohort_ref(2)]),
            (2, vec![behavioral_leaf("shared0000000001"), person_leaf()]),
        ]);
        let plan = plan_for(&filters, &[1, 2]);

        assert_eq!(
            plan.references,
            BTreeMap::from([(CohortId(2), ReferenceSource::Stored)]),
        );
        assert_eq!(
            plan.stage2_cohorts(),
            [CohortId(1), CohortId(2)],
            "cohort 2's row serves both its own diff and cohort 1's reference",
        );
    }

    /// Each reference kind reaches the state source that answers it, and only the composed kind
    /// adds a row.
    #[test]
    fn each_reference_kind_routes_to_its_own_state_source() {
        let single_leaf_hash = "singleleaf000003";
        let filters = freeze(vec![
            (
                1,
                vec![person_leaf(), cohort_ref(2), cohort_ref(3), cohort_ref(404)],
            ),
            (2, vec![behavioral_leaf("shared0000000001"), person_leaf()]),
            (3, vec![behavioral_leaf(single_leaf_hash)]),
        ]);
        let referent_lsk = filters.by_condition_to_lsk[&hash(single_leaf_hash)][0];
        let plan = plan_for(&filters, &[1]);

        assert_eq!(
            plan.references,
            BTreeMap::from([
                (CohortId(2), ReferenceSource::Stored),
                (CohortId(3), ReferenceSource::Leaf(referent_lsk)),
                (CohortId(404), ReferenceSource::NonMember),
            ]),
        );
        assert_eq!(
            plan.stage2_cohorts(),
            [CohortId(1), CohortId(2)],
            "only the composed referent adds a row; the single-leaf one is read as a leaf",
        );
        assert!(
            behavioral_lsks(&plan).contains(&referent_lsk),
            "the single-leaf referent joins the behavioral batch, comparator and all",
        );
    }

    /// A cohort the frozen catalog no longer carries is dropped before any read, so it costs no key
    /// and composes no pair.
    #[test]
    fn a_cohort_the_catalog_dropped_is_not_planned() {
        let filters = freeze(vec![(
            1,
            vec![behavioral_leaf("shared0000000001"), person_leaf()],
        )]);
        let plan = plan_for(&filters, &[1, 2]);

        assert_eq!(plan.cohorts(), [CohortId(1)]);
        assert_eq!(plan.stage2_cohorts(), [CohortId(1)]);
    }

    /// Negation belongs to the leaf, not to the row, so a referent named twice under opposite
    /// negations is one key and one bit. Reading it twice would let the two leaves disagree.
    #[test]
    fn a_referent_named_twice_under_opposite_negations_is_one_row() {
        let filters = freeze(vec![
            (
                1,
                vec![person_leaf(), cohort_ref(2), negated_cohort_ref(2, true)],
            ),
            (2, vec![behavioral_leaf("shared0000000001"), person_leaf()]),
        ]);
        let plan = plan_for(&filters, &[1]);

        assert_eq!(
            plan.references,
            BTreeMap::from([(CohortId(2), ReferenceSource::Stored)]),
        );
        assert_eq!(plan.stage2_cohorts(), [CohortId(1), CohortId(2)]);
    }

    /// A caller naming the same cohort twice plans it once, so a repeated id costs no extra key.
    #[test]
    fn a_repeated_cohort_is_planned_once() {
        let filters = freeze(vec![(
            1,
            vec![behavioral_leaf("shared0000000001"), person_leaf()],
        )]);
        let plan = plan_for(&filters, &[1, 1]);

        assert_eq!(plan.cohorts(), [CohortId(1)]);
        assert_eq!(plan.stage2_cohorts(), [CohortId(1)]);
        assert_eq!(behavioral_lsks(&plan).len(), 1);
    }
}
