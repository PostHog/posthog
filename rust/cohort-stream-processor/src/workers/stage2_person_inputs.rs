//! Stage 2 recomputation for a seed run, sharing each person's store inputs across their cohorts.
//!
//! [`recompute_stage2_by_person`] answers exactly what
//! [`recompute_stage2`](super::stage2_path::recompute_stage2) answers over the same store — the same
//! pairs, the same flips, the same `cf_stage2` rows owed — but reaches it person by person. The
//! cohort-ordered path re-reads a person's record, their behavioral leaves, and their prior
//! membership once per affected cohort; a wide person seed touching a dozen composable cohorts pays
//! that a dozen times over, and each read is its own blocking-pool handoff.
//!
//! Here a [`PersonReadPlan`] resolves each person's needs from the frozen catalog first, then one
//! [`PersonInputReader`] fetches them in as few store sections as their width needs: one person
//! record, each distinct behavioral key once, and one `cf_stage2` key set covering both the pairs'
//! own prior rows and every composed referent.
//!
//! Two boundaries the sharing must not cross:
//!
//! - **Stored, not pending.** A composed referent resolves from the bit the store holds, even when
//!   that referent recomputes in this same group. Substituting a freshly computed bit would emit a
//!   cascade the referent has not acknowledged.
//! - **One chunk at a time.** Behavioral values carry whole event histories, so the union is read in
//!   bounded chunks and each chunk's raw buffers are decoded and dropped before the next is read.
//!   The person's residue is their decoded membership bits, not their rows. A section reads at most
//!   one chunk per source, so a wide person releases the maintenance permit between chunks instead
//!   of holding it across all of them.

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

/// Keys per batched read. A key count is not a byte bound — a behavioral value holds a window's
/// history, and a person's leaves vary widely in size — so this caps the raw buffers held at once
/// without promising a fixed footprint. [`SEED_RECOMPUTE_CHUNK_BYTES`] measures what it cost.
const READ_CHUNK_KEYS: usize = 64;

/// The `op` label these sections report their offload timings under.
const SECTION_OP: &str = "stage2_person_inputs";

/// Recompute one seed group's composable cohorts, sharing each person's reads across their cohorts.
///
/// `team_id` is the group's team, which is also the key its `filters` sit under in the frozen
/// catalog, so every cohort reached here composes from that team's keyspace.
///
/// Changes and writes come back in `(cohort, person)` order, matching the cohort-ordered path, so a
/// caller cannot tell the two apart by the shape of what it produces.
///
/// One store read failure holds the whole run: the error propagates before any output exists, so the
/// caller has nothing partial to publish.
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

    // Collected before emitting, so the pairs come out in cohort order however they were grouped
    // for reading.
    let mut pairs: BTreeMap<(CohortId, Uuid), RecomputeDiff> = BTreeMap::new();
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
            // they agree — and this is the only thing still saying so.
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

/// How one referenced cohort resolves for a person.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ReferenceSource {
    /// A single-leaf referent: its membership is that leaf's own bit, read through the same
    /// comparator the referrer's own leaves use.
    Leaf(LeafStateKey),
    /// A referent that composes its own row: read the membership the store holds.
    Stored,
    /// Excluded, cyclic, or absent from the frozen catalog.
    NonMember,
}

/// Everything one person's affected cohorts read from the store, resolved from the frozen catalog
/// before any I/O and owned, so the read runs in blocking sections.
#[derive(Debug)]
struct PersonReadPlan {
    partition_id: u16,
    team_id: u64,
    person_id: Uuid,
    /// The pairs to recompute, ascending. Every id here has a tree in the frozen catalog.
    cohorts: Vec<CohortId>,
    /// The distinct behavioral leaves the cohorts read, each with the metadata its comparator needs.
    behavioral: Vec<(LeafStateKey, LeafStateMeta)>,
    /// The distinct person-property leaves, which all resolve from the one person record.
    person_leaves: Vec<LeafStateKey>,
    /// The cohorts whose stored membership row is read: each recomputed pair's own prior row, plus
    /// every composed referent. One row serves both when a referent also recomputes here.
    stage2_cohorts: Vec<CohortId>,
    /// Every cohort the trees reference, and how each resolves.
    references: BTreeMap<CohortId, ReferenceSource>,
}

impl PersonReadPlan {
    /// Walk one person's affected cohort trees once and collect what they read. Pure: it consults
    /// the frozen catalog only, so the plan is settled before the run holds a store permit.
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
            // The pair's own prior row, which the diff needs whether or not the cohort flips.
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

    /// Route one leaf to the state source its variant reads from. A key the frozen catalog does not
    /// carry is routed nowhere, so composition reads it as a non-member.
    fn route_leaf(&mut self, lsk: LeafStateKey, filters: &TeamFilters) {
        let Some(meta) = filters.by_lsk.get(&lsk) else {
            return;
        };
        match meta.variant {
            StateVariant::PersonProperty => self.person_leaves.push(lsk),
            // Exhaustive (no wildcard) so a future membership source resolving from another store
            // fails to compile here instead of being silently misrouted into `cf_behavioral`.
            StateVariant::BehavioralSingle
            | StateVariant::BehavioralDailyBuckets
            | StateVariant::BehavioralCompressedHistory => self.behavioral.push((lsk, *meta)),
        }
    }

    /// Classify one referenced cohort, and add whatever resolving it will need. Repeats are free:
    /// a referent named by several of the person's cohorts, or twice in one tree, is classified and
    /// read once.
    fn route_reference(&mut self, ref_id: CohortId, filters: &TeamFilters) {
        if self.references.contains_key(&ref_id) {
            return;
        }
        let source = match filters.eligibility.get(&ref_id) {
            Some(CohortEligibility::SingleLeaf(lsk)) => ReferenceSource::Leaf(*lsk),
            Some(eligibility) if eligibility.writes_cf_stage2() => ReferenceSource::Stored,
            _ => ReferenceSource::NonMember,
        };
        match source {
            ReferenceSource::Leaf(lsk) => self.route_leaf(lsk, filters),
            ReferenceSource::Stored => self.stage2_cohorts.push(ref_id),
            ReferenceSource::NonMember => {}
        }
        self.references.insert(ref_id, source);
    }

    /// Cohorts sharing a leaf route it once each, so the read sets arrive with duplicates. Order and
    /// deduplicate them once here, which is what makes the read one key per distinct row.
    fn dedup_read_sets(&mut self) {
        self.behavioral.sort_unstable_by_key(|(lsk, _)| *lsk);
        self.behavioral.dedup_by_key(|(lsk, _)| *lsk);
        self.person_leaves.sort_unstable();
        self.person_leaves.dedup();
        self.stage2_cohorts.sort_unstable();
        self.stage2_cohorts.dedup();
    }

    /// No cohort of this person survived the frozen catalog, so there is nothing to read.
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

    /// Resolve each referenced cohort to one bit, shared by every cohort of this person that names
    /// it. Entries a given tree does not reference are inert: `evaluate_tree` reads only the ids its
    /// own leaves carry.
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

/// One person's decoded inputs. Compact enough to outlive the sections that produced them: the raw
/// values behind them were dropped chunk by chunk as they were decoded.
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
}

/// Executes one [`PersonReadPlan`] against the store, accumulating the decoded result across as
/// many sections as the plan's width needs.
///
/// Sync by design: it runs on the blocking pool inside [`StoreHandle::run_section`], so its direct
/// [`CohortStore`] I/O is already off the runtime threads. Each section draws the maintenance
/// permit, as the seed paths did read by read before through
/// [`ReadLane::Maintenance`](crate::store::ReadLane), so backfill still cannot contend with live
/// event reads.
///
/// A section cannot be cancelled once started, and shutdown joins started sections, so its length
/// matters. [`Self::read_section`] bounds it to the person record plus one [`READ_CHUNK_KEYS`] chunk
/// of each batched source. A person within one chunk per source costs one permit and one handoff.
/// A wider person resumes in further sections and releases the permit between them instead of
/// holding it for every chunk.
struct PersonInputReader {
    plan: PersonReadPlan,
    inputs: ResolvedPersonInputs,
    started: bool,
    /// How far into `plan.behavioral` and `plan.stage2_cohorts` the sections so far have read.
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

    /// Read one bounded section: the person record on the first call, then the next chunk of each
    /// batched source.
    fn read_section(&mut self, store: &CohortStore) -> Result<(), StoreError> {
        if !self.started {
            self.started = true;
            // Counted with the first section's keys, on the same blocking thread. A started blocking
            // task runs to completion even if the caller future is dropped, so counting outside
            // would let a cancelled offload record keys for a person it never recorded, skewing
            // keys-per-person by exactly the reads that went missing.
            counter!(SEED_RECOMPUTE_PERSONS_TOTAL).increment(1);
            self.read_person_leaves(store)?;
        }
        self.read_behavioral_chunk(store)?;
        self.read_stage2_chunk(store)
    }

    fn is_done(&self) -> bool {
        self.behavioral_read == self.plan.behavioral.len()
            && self.stage2_read == self.plan.stage2_cohorts.len()
    }

    fn finish(self) -> (PersonReadPlan, ResolvedPersonInputs) {
        (self.plan, self.inputs)
    }

    /// Resolve every person-property leaf from the one durable record: a person leaf's state key
    /// *is* its condition hash, so its bit is `record.matched.contains(hash)`. An absent or corrupt
    /// record reads every person leaf as a non-member; a corrupt one counts once here rather than
    /// once per cohort that would have read it.
    fn read_person_leaves(&mut self, store: &CohortStore) -> Result<(), StoreError> {
        if self.plan.person_leaves.is_empty() {
            return Ok(());
        }
        let bytes = store.get_person_record(&self.plan.person_record_key())?;
        ReadSource::PersonRecord.record(1, bytes.as_ref().map_or(0, Vec::len));

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
        for &lsk in &self.plan.person_leaves {
            let member = matched
                .as_ref()
                .is_some_and(|matched| matched.contains(&lsk.0));
            self.inputs.membership.insert(lsk, member);
        }
        Ok(())
    }

    /// Read the next chunk of distinct behavioral leaves, decoding it and releasing its raw values
    /// before the section ends.
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
        for (&(lsk, ref meta), bytes) in chunk.iter().zip(raw) {
            let state = decode_stage1_state(bytes);
            self.inputs
                .membership
                .insert(lsk, leaf_membership(state.as_ref(), meta));
        }
        self.behavioral_read += chunk.len();
        Ok(())
    }

    /// Read the next chunk of the pairs' own prior membership rows and composed referents' rows.
    /// They are one key set, so a referent that also recomputes here is read once, and read as
    /// stored.
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

/// The state source one batched read drew from. Closed, so the `source` label on the section
/// counters stays a fixed set of three.
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

    /// Record one batched read: the keys it asked for, and the raw bytes it brought back.
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

    /// The whole point of planning first: whatever the fan-out, one person is one record read and
    /// one key per distinct row. A regression here silently restores the per-cohort read.
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
