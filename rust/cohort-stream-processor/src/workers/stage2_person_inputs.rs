//! Stage 2 recomputation for a seed run, sharing each person's store inputs across their cohorts.
//!
//! Same output as [`recompute_stage2`](super::stage2_path::recompute_stage2), reached by reading
//! each person once rather than once per affected cohort. The plan and the decoded inputs are
//! [`composition_inputs`](super::composition_inputs); this module is the seed-side reader over them.
//!
//! Two boundaries the sharing must not cross:
//!
//! - A composed referent resolves from the bit the store holds, even when that referent recomputes
//!   in this same group. A freshly computed bit would emit a cascade nothing has acknowledged.
//! - Behavioral values carry whole event histories, so a section reads at most one chunk per source
//!   and drops its raw buffers before the next. A wide person releases the maintenance permit
//!   between chunks instead of holding it across all of them.

use std::collections::{BTreeMap, BTreeSet};

use metrics::{counter, histogram};
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::{CohortId, TeamId};
use crate::observability::metrics::{
    SEED_RECOMPUTE_CHUNK_BYTES, SEED_RECOMPUTE_KEYS_FETCHED_TOTAL, SEED_RECOMPUTE_PERSONS_TOTAL,
};
use crate::stage1::key::LeafStateKey;
use crate::stage2::evaluator::evaluate_tree;
use crate::store::{BehavioralKey, CohortStore, Stage2Key, StoreError, StoreHandle};
use crate::workers::composition_inputs::{
    raw_bytes, CompositionReadPlan, PersonScope, ResolvedPersonInputs,
};
use crate::workers::stage2_path::{RecomputeDiff, RecomputedPair, Stage2Recompute};

/// Keys per batched read, the same chunk the sweep prefetch uses. A chunk is decoded and dropped
/// before the next is read, so this bounds the raw buffers one section holds and with them the
/// drain time a started section can add. It is not a byte bound, because behavioral values vary
/// in size with their window; [`SEED_RECOMPUTE_CHUNK_BYTES`] measures what a chunk actually cost.
pub(super) const READ_CHUNK_KEYS: usize = 1024;

const SECTION_OP: &str = "stage2_person_inputs";

/// Recompute one seed group's composable cohorts, sharing each person's reads across their cohorts.
///
/// Seed-only by construction: the reads run through [`StoreHandle::run_section`], which draws the
/// maintenance permit. The live, sweep and cascade paths compose on
/// [`ReadLane::Event`](crate::store::ReadLane) and cannot move here without putting hot-path reads
/// behind the backfill lane; reconcile already reads on the maintenance lane and has its own
/// page-wide reader in [`reconcile_page`](super::reconcile_page).
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
        let plan = CompositionReadPlan::for_cohorts(cohorts.iter().copied(), filters);
        if plan.is_empty() {
            continue;
        }
        let scope = PersonScope::new(partition_id, team_id.0 as u64, person_id);

        let mut reader = PersonInputReader::new(plan, scope);
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
        for &cohort_id in plan.cohorts() {
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
            let new_bit = evaluate_tree(&tree.root, inputs.membership(), &references);
            pairs.insert(
                (cohort_id, person_id),
                RecomputeDiff::new(
                    new_bit,
                    inputs.prior_stage2(cohort_id),
                    scope.stage2_key(cohort_id),
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

/// Executes one person's [`CompositionReadPlan`] across as many [`StoreHandle::run_section`] calls
/// as its width needs.
///
/// Each section draws the maintenance permit, so backfill cannot contend with live event reads.
///
/// A started section cannot be cancelled and shutdown joins it, so [`Self::read_section`] bounds one
/// section to the person record plus one [`READ_CHUNK_KEYS`] chunk of each batched source.
struct PersonInputReader {
    plan: CompositionReadPlan,
    scope: PersonScope,
    inputs: ResolvedPersonInputs,
    started: bool,
    behavioral_read: usize,
    stage2_read: usize,
}

#[allow(clippy::disallowed_methods)]
impl PersonInputReader {
    fn new(plan: CompositionReadPlan, scope: PersonScope) -> Self {
        let inputs = ResolvedPersonInputs::with_capacity_for(&plan);
        Self {
            plan,
            scope,
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
            && self.behavioral_read == self.plan.behavioral().len()
            && self.stage2_read == self.plan.stage2_cohorts().len()
    }

    fn finish(self) -> (CompositionReadPlan, ResolvedPersonInputs) {
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
            .behavioral()
            .chunks(READ_CHUNK_KEYS)
            .next()
            .unwrap_or(&[]);
        let keys: Vec<BehavioralKey> = chunk
            .iter()
            .map(|&(lsk, _)| self.scope.behavioral_key(lsk))
            .collect();
        let record_key =
            (!self.plan.person_leaves().is_empty()).then(|| self.scope.person_record_key());
        let snapshot = store.read_event_snapshot(&keys, record_key.as_ref())?;
        if let Some(record) = snapshot.record {
            ReadSource::PersonRecord.record(1, record.as_ref().map_or(0, Vec::len));
            self.inputs
                .absorb_person_record(self.plan.person_leaves(), record);
        }
        if !keys.is_empty() {
            ReadSource::Behavioral.record(keys.len(), raw_bytes(&snapshot.behavioral));
            self.inputs.absorb_behavioral(chunk, snapshot.behavioral);
            self.behavioral_read += chunk.len();
        }
        Ok(())
    }

    fn read_behavioral_chunk(&mut self, store: &CohortStore) -> Result<(), StoreError> {
        let rest = &self.plan.behavioral()[self.behavioral_read..];
        let Some(chunk) = rest.chunks(READ_CHUNK_KEYS).next() else {
            return Ok(());
        };
        let keys: Vec<BehavioralKey> = chunk
            .iter()
            .map(|&(lsk, _)| self.scope.behavioral_key(lsk))
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
        let rest = &self.plan.stage2_cohorts()[self.stage2_read..];
        let Some(chunk) = rest.chunks(READ_CHUNK_KEYS).next() else {
            return Ok(());
        };
        let keys: Vec<Stage2Key> = chunk
            .iter()
            .map(|&cohort_id| self.scope.stage2_key(cohort_id))
            .collect();
        let raw = store.multi_get_stage2(&keys)?;
        ReadSource::Stage2.record(keys.len(), raw_bytes(&raw));
        self.inputs.absorb_stage2(chunk, raw);
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
