//! Stage 2 recomputation for a seed run, sharing each person's store inputs across their cohorts.
//!
//! Same output as [`recompute_stage2`](super::stage2_path::recompute_stage2), reached by reading
//! each person once rather than once per affected cohort.
//!
//! Two boundaries the sharing must not cross:
//!
//! - A composed referent resolves from the bit the store holds, even when that referent recomputes
//!   in this same group. A freshly computed bit would emit a cascade nothing has acknowledged.
//! - Behavioral values carry whole event histories, so a section reads at most one chunk per source
//!   and drops its raw buffers before the next. A wide person releases the maintenance permit
//!   between chunks instead of holding it across all of them.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use metrics::{counter, histogram};
use uuid::Uuid;

use crate::filters::reverse_index::{LeafStateMeta, TeamFilters};
use crate::filters::{CohortId, TeamId};
use crate::observability::metrics::{
    SEED_RECOMPUTE_CHUNK_BYTES, SEED_RECOMPUTE_KEYS_FETCHED_TOTAL, SEED_RECOMPUTE_PERSONS_TOTAL,
    STAGE2_STATE_DECODE_ERROR,
};
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::PersonRecord;
use crate::stage1::state::StateVariant;
use crate::stage2::evaluator::{evaluate_tree, leaf_membership};
use crate::stage2::CohortEligibility;
use crate::store::{
    BehavioralKey, CohortStore, PersonRecordKey, Stage2Key, StoreError, StoreHandle,
};
use crate::workers::stage2_path::{
    collect_cohort_refs, collect_leaf_state_keys, decode_stage1_state, read_prior_stage2,
    PriorStage2State, RecomputeDiff, RecomputedPair, Stage2Recompute,
};

/// Keys per batched read, the same chunk the sweep prefetch uses. A chunk is decoded and dropped
/// before the next is read, so this bounds the raw buffers one section holds and with them the
/// drain time a started section can add. It is not a byte bound, because behavioral values vary
/// in size with their window; [`SEED_RECOMPUTE_CHUNK_BYTES`] measures what a chunk actually cost.
pub(super) const READ_CHUNK_KEYS: usize = 1024;

const SECTION_OP: &str = "stage2_person_inputs";

/// Recompute one seed group's composable cohorts, sharing each person's reads across their cohorts.
///
/// Seed-only by construction: the reads run through [`StoreHandle::run_section`], which draws the
/// maintenance permit. The live, sweep, cascade and reconcile paths compose on
/// [`ReadLane::Event`](crate::store::ReadLane) and cannot move here without putting hot-path reads
/// behind the backfill lane.
///
/// `team_id` is the key `filters` sit under in the frozen catalog, so every cohort here composes
/// from that team's keyspace.
///
/// Changes and writes come back in `(cohort, person)` order, matching the cohort-ordered path.
///
/// A read failure returns before any output exists, so the held run publishes nothing partial.
pub(crate) async fn recompute_stage2_by_person(
    partition_id: u16,
    handle: &StoreHandle,
    team_id: TeamId,
    filters: &TeamFilters,
    affected_leaves: &[(LeafStateKey, Uuid)],
    event_ms: i64,
    last_updated: &str,
) -> Result<Stage2Recompute, StoreError> {
    let mut affected: BTreeMap<Uuid, BTreeSet<CohortId>> = BTreeMap::new();
    for &(leaf_state_key, person_id) in affected_leaves {
        if let Some(cohorts) = filters.by_lsk_to_composable_cohorts.get(&leaf_state_key) {
            affected
                .entry(person_id)
                .or_default()
                .extend(cohorts.iter().copied());
        }
    }

    // A map rather than pushes. No consumer needs cohort order (changes are keyed by person and
    // writes by row), but the differential tests compare this path with the cohort-ordered one
    // verbatim, and the map also collapses a duplicate pair into one `record_pair`.
    let mut pairs: BTreeMap<(CohortId, Uuid), RecomputeDiff> = BTreeMap::new();
    // Persons run one at a time on purpose. Every partition worker applies its own runs against
    // this one maintenance lane, whose permits are already contended across partitions and shared
    // with the sweep, merge and GC sections. Overlapping persons inside one run would add
    // contenders to that lane without adding permits.
    for (person_id, cohorts) in affected {
        let plan = PersonReadPlan::build(partition_id, team_id, person_id, &cohorts, filters);
        if plan.is_empty() {
            continue;
        }

        let mut reader = PersonInputReader::new(plan);
        loop {
            reader = handle
                .run_section(SECTION_OP, move |store| {
                    reader.read_section(store)?;
                    Ok(reader)
                })
                .await??;
            if reader.is_done() {
                break;
            }
        }
        let (plan, inputs) = reader.finish();

        let references = plan.reference_membership(&inputs);
        for &cohort_id in &plan.cohorts {
            let tree = filters
                .cohorts
                .get(&cohort_id)
                .expect("the plan keeps only cohorts this frozen catalog has a tree for");
            // The cohort-ordered path stamps changes from the tree; this one from the group. The
            // catalog keys one `TeamFilters` per team and stamps its trees with that same id, so
            // the two stamps agree.
            debug_assert_eq!(
                tree.team_id, team_id,
                "a team's catalog holds only that team's cohorts",
            );
            let new_bit = evaluate_tree(&tree.root, &inputs.membership, &references);
            pairs.insert(
                (cohort_id, person_id),
                RecomputeDiff::new(
                    new_bit,
                    inputs.prior_stage2(cohort_id),
                    plan.stage2_key(cohort_id),
                ),
            );
        }
    }

    let mut recompute = Stage2Recompute::default();
    for ((cohort_id, person_id), diff) in pairs {
        recompute.record_pair(
            RecomputedPair {
                team_id: team_id.0,
                cohort_id,
                person_id,
            },
            &diff,
            event_ms,
            last_updated,
        );
    }
    Ok(recompute)
}

// ---- What one person's cohorts read ----

/// How a referenced cohort's membership resolves for one person. Both recompute orders classify
/// through [`Self::classify`], so a referent cannot resolve from one store on the seed path and
/// another on the live path.
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

/// Everything one person's affected cohorts read from the store. Owned, so the read can run in
/// blocking sections.
#[derive(Debug)]
struct PersonReadPlan {
    partition_id: u16,
    team_id: u64,
    person_id: Uuid,
    /// Ascending. Every id here has a tree in the frozen catalog.
    cohorts: Vec<CohortId>,
    behavioral: Vec<(LeafStateKey, LeafStateMeta)>,
    person_leaves: Vec<LeafStateKey>,
    /// Each recomputed pair's own prior row, plus every composed referent. One row serves both when
    /// a referent also recomputes here.
    stage2_cohorts: Vec<CohortId>,
    references: BTreeMap<CohortId, ReferenceSource>,
}

impl PersonReadPlan {
    /// Reads the frozen catalog only, so the plan is settled before the run holds a store permit.
    fn build(
        partition_id: u16,
        team_id: TeamId,
        person_id: Uuid,
        cohorts: &BTreeSet<CohortId>,
        filters: &TeamFilters,
    ) -> Self {
        let mut plan = Self {
            partition_id,
            team_id: team_id.0 as u64,
            person_id,
            cohorts: Vec::with_capacity(cohorts.len()),
            behavioral: Vec::new(),
            person_leaves: Vec::new(),
            stage2_cohorts: Vec::with_capacity(cohorts.len()),
            references: BTreeMap::new(),
        };

        let mut lsks = Vec::new();
        let mut refs = Vec::new();
        for &cohort_id in cohorts {
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
        self.behavioral.sort_unstable_by_key(|(lsk, _)| *lsk);
        self.behavioral.dedup_by_key(|(lsk, _)| *lsk);
        self.person_leaves.sort_unstable();
        self.person_leaves.dedup();
        self.stage2_cohorts.sort_unstable();
        self.stage2_cohorts.dedup();
    }

    fn is_empty(&self) -> bool {
        self.cohorts.is_empty()
    }

    fn person_record_key(&self) -> PersonRecordKey {
        PersonRecordKey::new(self.partition_id, self.team_id, self.person_id)
    }

    fn behavioral_key(&self, lsk: LeafStateKey) -> BehavioralKey {
        BehavioralKey::new(self.partition_id, self.team_id, self.person_id, lsk)
    }

    fn stage2_key(&self, cohort_id: CohortId) -> Stage2Key {
        Stage2Key {
            partition_id: self.partition_id,
            team_id: self.team_id,
            cohort_id: cohort_id.0 as u64,
            person_id: self.person_id,
        }
    }

    /// One bit per referenced cohort, shared by every cohort of this person that names it. Entries
    /// a given tree does not reference are inert, because `evaluate_tree` reads only its own ids.
    fn reference_membership(&self, inputs: &ResolvedPersonInputs) -> HashMap<CohortId, bool> {
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

// ---- Reading them ----

/// One person's decoded inputs. Compact enough to outlive the sections that read them, because each
/// chunk's raw values are dropped as they decode.
#[derive(Debug, Default)]
struct ResolvedPersonInputs {
    membership: HashMap<LeafStateKey, bool>,
    stage2: HashMap<CohortId, PriorStage2State>,
}

impl ResolvedPersonInputs {
    /// A leaf the frozen catalog did not back was never read, and reads as a non-member.
    fn leaf_membership(&self, lsk: LeafStateKey) -> bool {
        self.membership.get(&lsk).copied().unwrap_or(false)
    }

    /// A row the plan did not ask for takes the same fail-closed reading as an absent one.
    fn prior_stage2(&self, cohort_id: CohortId) -> PriorStage2State {
        self.stage2.get(&cohort_id).copied().unwrap_or_default()
    }

    /// A person leaf's state key *is* its condition hash, so its bit is
    /// `record.matched.contains(hash)`. An absent or corrupt record reads every person leaf as a
    /// non-member, and a corrupt one counts once per person rather than once per cohort.
    fn absorb_person_record(&mut self, person_leaves: &[LeafStateKey], bytes: Option<Vec<u8>>) {
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

    fn absorb_behavioral(
        &mut self,
        chunk: &[(LeafStateKey, LeafStateMeta)],
        raw: Vec<Option<Vec<u8>>>,
    ) {
        for (&(lsk, ref meta), bytes) in chunk.iter().zip(raw) {
            let state = decode_stage1_state(bytes);
            self.membership
                .insert(lsk, leaf_membership(state.as_ref(), meta));
        }
    }
}

/// Executes one [`PersonReadPlan`] across as many [`StoreHandle::run_section`] calls as its width
/// needs.
///
/// Each section draws the maintenance permit, so backfill cannot contend with live event reads.
///
/// A started section cannot be cancelled and shutdown joins it, so [`Self::read_section`] bounds one
/// section to the person record plus one [`READ_CHUNK_KEYS`] chunk of each batched source.
struct PersonInputReader {
    plan: PersonReadPlan,
    inputs: ResolvedPersonInputs,
    started: bool,
    behavioral_read: usize,
    stage2_read: usize,
}

#[allow(clippy::disallowed_methods)]
impl PersonInputReader {
    fn new(plan: PersonReadPlan) -> Self {
        let inputs = ResolvedPersonInputs {
            membership: HashMap::with_capacity(plan.behavioral.len() + plan.person_leaves.len()),
            stage2: HashMap::with_capacity(plan.stage2_cohorts.len()),
        };
        Self {
            plan,
            inputs,
            started: false,
            behavioral_read: 0,
            stage2_read: 0,
        }
    }

    fn read_section(&mut self, store: &CohortStore) -> Result<(), StoreError> {
        if self.started {
            self.read_behavioral_chunk(store)?;
        } else {
            self.started = true;
            // Counted on the blocking thread with the keys. A started section completes even when
            // the caller future is dropped, so counting outside would record keys for a person the
            // cancelled offload never counted.
            counter!(SEED_RECOMPUTE_PERSONS_TOTAL).increment(1);
            self.read_record_with_first_behavioral_chunk(store)?;
        }
        self.read_stage2_chunk(store)
    }

    fn is_done(&self) -> bool {
        self.started
            && self.behavioral_read == self.plan.behavioral.len()
            && self.stage2_read == self.plan.stage2_cohorts.len()
    }

    fn finish(self) -> (PersonReadPlan, ResolvedPersonInputs) {
        (self.plan, self.inputs)
    }

    /// The person record rides along the first behavioral chunk in one mixed-CF `multi_get`, the
    /// read the event fold already issues, so a person costs one RocksDB lookup fewer.
    fn read_record_with_first_behavioral_chunk(
        &mut self,
        store: &CohortStore,
    ) -> Result<(), StoreError> {
        let chunk = self
            .plan
            .behavioral
            .chunks(READ_CHUNK_KEYS)
            .next()
            .unwrap_or(&[]);
        let keys: Vec<BehavioralKey> = chunk
            .iter()
            .map(|&(lsk, _)| self.plan.behavioral_key(lsk))
            .collect();
        let record_key =
            (!self.plan.person_leaves.is_empty()).then(|| self.plan.person_record_key());
        let snapshot = store.read_event_snapshot(&keys, record_key.as_ref())?;
        if let Some(record) = snapshot.record {
            ReadSource::PersonRecord.record(1, record.as_ref().map_or(0, Vec::len));
            self.inputs
                .absorb_person_record(&self.plan.person_leaves, record);
        }
        if !keys.is_empty() {
            ReadSource::Behavioral.record(keys.len(), raw_bytes(&snapshot.behavioral));
            self.inputs.absorb_behavioral(chunk, snapshot.behavioral);
            self.behavioral_read += chunk.len();
        }
        Ok(())
    }

    fn read_behavioral_chunk(&mut self, store: &CohortStore) -> Result<(), StoreError> {
        let rest = &self.plan.behavioral[self.behavioral_read..];
        let Some(chunk) = rest.chunks(READ_CHUNK_KEYS).next() else {
            return Ok(());
        };
        let keys: Vec<BehavioralKey> = chunk
            .iter()
            .map(|&(lsk, _)| self.plan.behavioral_key(lsk))
            .collect();
        let raw = store.multi_get_behavioral(&keys)?;
        ReadSource::Behavioral.record(keys.len(), raw_bytes(&raw));
        self.inputs.absorb_behavioral(chunk, raw);
        self.behavioral_read += chunk.len();
        Ok(())
    }

    /// Prior rows and composed referents share one key set, so a referent that also recomputes here
    /// is read once, and read as stored.
    fn read_stage2_chunk(&mut self, store: &CohortStore) -> Result<(), StoreError> {
        let rest = &self.plan.stage2_cohorts[self.stage2_read..];
        let Some(chunk) = rest.chunks(READ_CHUNK_KEYS).next() else {
            return Ok(());
        };
        let keys: Vec<Stage2Key> = chunk
            .iter()
            .map(|&cohort_id| self.plan.stage2_key(cohort_id))
            .collect();
        let raw = store.multi_get_stage2(&keys)?;
        ReadSource::Stage2.record(keys.len(), raw_bytes(&raw));
        for (&cohort_id, bytes) in chunk.iter().zip(raw) {
            self.inputs
                .stage2
                .insert(cohort_id, read_prior_stage2(bytes));
        }
        self.stage2_read += chunk.len();
        Ok(())
    }
}

/// The closed set of `source` label values on the section counters.
#[derive(Debug, Clone, Copy)]
enum ReadSource {
    Behavioral,
    PersonRecord,
    Stage2,
}

impl ReadSource {
    fn label(self) -> &'static str {
        match self {
            Self::Behavioral => "behavioral",
            Self::PersonRecord => "person_record",
            Self::Stage2 => "stage2",
        }
    }

    fn record(self, keys: usize, bytes: usize) {
        counter!(SEED_RECOMPUTE_KEYS_FETCHED_TOTAL, "source" => self.label())
            .increment(keys as u64);
        histogram!(SEED_RECOMPUTE_CHUNK_BYTES, "source" => self.label()).record(bytes as f64);
    }
}

fn raw_bytes(values: &[Option<Vec<u8>>]) -> usize {
    values.iter().flatten().map(Vec::len).sum()
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};

    use crate::filters::{TeamFiltersBuilder, TeamId};

    const PARTITION: u16 = 0;
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
        json!({ "type": "cohort", "value": target, "negation": false })
    }

    fn freeze(cohorts: Vec<(i32, Vec<Value>)>) -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        for (id, values) in cohorts {
            let cohort = json!({ "properties": { "type": "AND", "values": values } });
            builder.add_cohort(CohortId(id), TEAM, &cohort).unwrap();
        }
        builder.freeze_with(UTC, true)
    }

    fn plan_for(filters: &TeamFilters, cohorts: &[i32]) -> PersonReadPlan {
        let cohorts: BTreeSet<CohortId> = cohorts.iter().map(|&id| CohortId(id)).collect();
        PersonReadPlan::build(PARTITION, TEAM, Uuid::from_u128(1), &cohorts, filters)
    }

    fn behavioral_lsks(plan: &PersonReadPlan) -> Vec<LeafStateKey> {
        plan.behavioral.iter().map(|&(lsk, _)| lsk).collect()
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

        assert_eq!(plan.cohorts, [CohortId(1), CohortId(2), CohortId(3)]);
        assert_eq!(
            plan.person_leaves,
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
            plan.stage2_cohorts,
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
            plan.stage2_cohorts,
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
            plan.stage2_cohorts,
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

        assert_eq!(plan.cohorts, [CohortId(1)]);
        assert_eq!(plan.stage2_cohorts, [CohortId(1)]);
    }
}
