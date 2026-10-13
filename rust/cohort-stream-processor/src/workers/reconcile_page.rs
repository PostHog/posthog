//! Reading and evaluating one reconcile settlement page in bounded blocking sections.
//!
//! Reconcile scans a whole cohort, so every row of a page composes the same tree: one
//! [`CompositionReadPlan`] serves the page, and each row only binds it to a person. That lets a
//! section carry many rows through one handoff instead of one row per handoff, which is the whole
//! point of this module.
//!
//! What a section must not become is unbounded. A started blocking task cannot be cancelled and
//! shutdown joins it, so each section stops at [`MAX_ROWS`] rows, [`MAX_KEYS`] keys, or
//! [`MAX_BYTES`] of returned values, releases the maintenance permit, and resumes from the row it
//! stopped in. Rows and keys are hard stops. Bytes are not: the budget is consulted between reads,
//! so the peak a section can hold is [`MAX_BYTES`] plus whatever one more read of up to
//! [`MAX_KEYS`] values returns. Sizing memory from [`MAX_BYTES`] alone understates it.
//!
//! The page stays the settlement boundary: [`read_page`] returns one diff per row or an error, so no
//! caller can produce half a page. Only decoded inputs cross a section boundary, never a raw value.

use std::sync::Arc;

use metrics::{counter, histogram};

use crate::filters::reverse_index::TeamFilters;
use crate::filters::tree::CohortTree;
use crate::filters::CohortId;
use crate::observability::metrics::{
    RECONCILE_KEYS_FETCHED_TOTAL, RECONCILE_READ_BYTES, RECONCILE_ROWS_ATTEMPTED_TOTAL,
};
use crate::stage2::evaluator::evaluate_tree;
use crate::store::{BehavioralKey, CohortStore, Stage2Key, StoreError, StoreHandle};
use crate::workers::composition_inputs::{
    raw_bytes, CompositionReadPlan, PersonScope, ResolvedPersonInputs,
};
use crate::workers::stage2_path::RecomputeDiff;

/// Rows one section may settle before handing the page back. Caps how much of a page one
/// uncancellable blocking task owns, and with it the store permit it holds. Visible to
/// [`reconcile`](super::reconcile) so its retry test can size a page that spans sections.
pub(super) const MAX_ROWS: usize = 32;
/// Keys one section may fetch, counting every state source. A fresh section always has its whole
/// allowance, so every section issues at least one read and the page cannot stall.
const MAX_KEYS: usize = 1_024;
/// Returned value bytes after which a section stops issuing **further** reads. Not a ceiling: the
/// read that crosses it has already returned, and the next read is handed the whole remaining key
/// allowance, so a section's peak is this plus one read of up to [`MAX_KEYS`] values. Behavioral
/// values grow with their window, which is why no key count bounds bytes, and why a single value
/// larger than the whole budget still has to make progress rather than deadlock its row.
/// [`RECONCILE_READ_BYTES`] measures what a read actually cost.
const MAX_BYTES: usize = 4 * 1024 * 1024;

const SECTION_OP: &str = "reconcile_page";

/// Compose and diff every row of `page` against the bit the store holds, in sections that release
/// the maintenance permit between them.
///
/// Reconcile's reads belong on [`ReadLane::Maintenance`](crate::store::ReadLane), which is the
/// permit [`StoreHandle::run_section`] draws, so a cohort scan cannot contend with live event reads.
///
/// Diffs come back in scan order, one per row including the rows that did not change: the caller
/// emits a full snapshot, not only flips.
///
/// # Panics
/// `filters` must be the same frozen snapshot the drain guard passed, in which `cohort_id` has a
/// tree. Reconcile's guard proves that before it scans; a caller that passes another snapshot
/// panics in [`PageReader::evaluate`].
pub(super) async fn read_page(
    handle: &StoreHandle,
    filters: &Arc<TeamFilters>,
    cohort_id: CohortId,
    page: &[Stage2Key],
) -> Result<Vec<RecomputeDiff>, StoreError> {
    // Dirty verification reaches here with every row of its page deleted. Those pages still have
    // markers to clear, so the caller runs on; there is just nothing to take a store permit for.
    if page.is_empty() {
        return Ok(Vec::new());
    }
    let plan = Arc::new(CompositionReadPlan::for_cohorts([cohort_id], filters));
    let mut reader = PageReader::new(Arc::clone(filters), plan, cohort_id, page.to_vec());
    loop {
        match handle
            .run_section(SECTION_OP, move |store| reader.run_section(store))
            .await??
        {
            PageRead::Complete(diffs) => return Ok(diffs),
            PageRead::Reading(resumed) => reader = resumed,
        }
    }
}

/// One section's outcome. `Complete` is the only way to reach the diffs, so a page whose reads are
/// unfinished cannot be settled.
enum PageRead {
    /// Keys are still outstanding. The reader carries every diff settled so far, and at most one
    /// row's decoded inputs.
    Reading(PageReader),
    /// One diff per requested row, in scan order.
    Complete(Vec<RecomputeDiff>),
}

struct PageReader {
    filters: Arc<TeamFilters>,
    plan: Arc<CompositionReadPlan>,
    cohort_id: CohortId,
    /// The rows to settle, in scan order.
    page: Vec<Stage2Key>,
    /// One diff per row already evaluated, so `page[diffs.len()]` is the row being read.
    diffs: Vec<RecomputeDiff>,
    /// Set only while that row's keys span a section boundary.
    pending: Option<RowRead>,
}

impl PageReader {
    fn new(
        filters: Arc<TeamFilters>,
        plan: Arc<CompositionReadPlan>,
        cohort_id: CohortId,
        page: Vec<Stage2Key>,
    ) -> Self {
        // The prior bit is read under `cohort_id` while the key written back comes from the row, so
        // a row from another cohort's prefix would read one key and write another.
        debug_assert!(
            page.iter().all(|row| row.cohort_id == cohort_id.0 as u64),
            "a reconcile page is one cohort's prefix scan",
        );
        Self {
            filters,
            plan,
            cohort_id,
            diffs: Vec::with_capacity(page.len()),
            page,
            pending: None,
        }
    }

    /// Read, decode and evaluate rows until a budget stops the section or the page is finished.
    /// Raw values are dropped inside this call, so only the diffs and one row's decoded inputs
    /// survive it.
    fn run_section(mut self, store: &CohortStore) -> Result<PageRead, StoreError> {
        let plan = Arc::clone(&self.plan);
        let filters = Arc::clone(&self.filters);
        // Hoisted out of the row loop, so the section states the catalog precondition once.
        let tree = filters
            .cohorts
            .get(&self.cohort_id)
            .expect("the drain guard proved this cohort has a tree in the frozen catalog");
        let mut budget = SectionBudget::default();
        while self.diffs.len() < self.page.len() {
            if !budget.accepts_row() {
                return Ok(PageRead::Reading(self));
            }
            let row = self.page[self.diffs.len()];
            let mut read = self.pending.take().unwrap_or_else(|| {
                // Counted on the blocking thread with the keys, so a section whose caller future
                // was dropped still records the rows it read.
                counter!(RECONCILE_ROWS_ATTEMPTED_TOTAL).increment(1);
                RowRead::new(&plan)
            });
            let scope = PersonScope::new(row.partition_id, row.team_id, row.person_id);
            while let Some(next) = read.next {
                let Some(key_limit) = budget.key_allowance() else {
                    self.pending = Some(read);
                    return Ok(PageRead::Reading(self));
                };
                read.next = RowSection {
                    store,
                    plan: &plan,
                    scope,
                    inputs: &mut read.inputs,
                    budget: &mut budget,
                }
                .read(next, key_limit)?;
            }
            let diff = self.evaluate(tree, row, &read.inputs);
            self.diffs.push(diff);
            budget.row_settled();
        }
        Ok(PageRead::Complete(self.diffs))
    }

    /// Compose the row and diff it against the bit the store holds. Runs in the section that
    /// finished the row's reads, so the decoded inputs are spent here rather than retained for the
    /// page.
    fn evaluate(
        &self,
        tree: &CohortTree,
        row: Stage2Key,
        inputs: &ResolvedPersonInputs,
    ) -> RecomputeDiff {
        let references = self.plan.reference_membership(inputs);
        let new_bit = evaluate_tree(&tree.root, inputs.membership(), &references);
        RecomputeDiff::new(new_bit, inputs.prior_stage2(self.cohort_id), row)
    }
}

/// What one section has spent.
#[derive(Debug, Default)]
struct SectionBudget {
    rows: usize,
    keys: usize,
    bytes: usize,
}

impl SectionBudget {
    fn accepts_row(&self) -> bool {
        self.rows < MAX_ROWS
    }

    /// How many keys the next read may fetch, or `None` once the section is out of work.
    fn key_allowance(&self) -> Option<usize> {
        (self.keys < MAX_KEYS && self.bytes < MAX_BYTES).then(|| MAX_KEYS - self.keys)
    }

    fn spend(&mut self, keys: usize, bytes: usize) {
        self.keys += keys;
        self.bytes += bytes;
    }

    fn row_settled(&mut self) {
        self.rows += 1;
    }
}

/// One row's read in progress.
struct RowRead {
    inputs: ResolvedPersonInputs,
    /// `None` once every key the plan names is decoded.
    next: Option<NextRead>,
}

impl RowRead {
    fn new(plan: &CompositionReadPlan) -> Self {
        Self {
            inputs: ResolvedPersonInputs::with_capacity_for(plan),
            next: Some(NextRead::RecordAndBehavioral),
        }
    }
}

/// The next keys one row needs, in source order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum NextRead {
    /// Nothing read yet: the person record rides along the first batch of behavioral keys, in the
    /// one mixed-CF lookup the event fold already issues.
    RecordAndBehavioral,
    /// Behavioral keys from this offset on; the record is decoded.
    Behavioral(usize),
    /// Stage 2 rows from this offset on.
    Stage2(usize),
}

impl NextRead {
    /// Where a row stands with `offset` behavioral keys decoded: the rest of them, else the next
    /// source. [`RowRead::new`] names the first source; these two name every step after it.
    fn behavioral_at(offset: usize, plan: &CompositionReadPlan) -> Option<Self> {
        if offset < plan.behavioral().len() {
            Some(Self::Behavioral(offset))
        } else {
            Self::stage2_at(0, plan)
        }
    }

    fn stage2_at(offset: usize, plan: &CompositionReadPlan) -> Option<Self> {
        (offset < plan.stage2_cohorts().len()).then_some(Self::Stage2(offset))
    }
}

/// One section's reads for one row: holds what the whole section shares, so each read takes only
/// what varies.
struct RowSection<'a> {
    store: &'a CohortStore,
    plan: &'a CompositionReadPlan,
    scope: PersonScope,
    inputs: &'a mut ResolvedPersonInputs,
    budget: &'a mut SectionBudget,
}

// The sanctioned sync context: these reads already run on the blocking pool, inside the section
// `StoreHandle::run_section` offloaded.
#[allow(clippy::disallowed_methods)]
impl RowSection<'_> {
    /// Fetch at most `key_limit` of the row's outstanding keys, decode them, and drop the raw
    /// values. `None` once every key the plan names is decoded.
    fn read(&mut self, next: NextRead, key_limit: usize) -> Result<Option<NextRead>, StoreError> {
        match next {
            NextRead::RecordAndBehavioral => self.record_and_behavioral(key_limit),
            NextRead::Behavioral(from) => self.behavioral(from, key_limit),
            NextRead::Stage2(from) => self.stage2(from, key_limit),
        }
    }

    /// The person record rides along the first behavioral batch in one mixed-CF `multi_get`, so a
    /// row costs one RocksDB lookup fewer. A row whose cohort reads no person condition asks for no
    /// record.
    fn record_and_behavioral(&mut self, key_limit: usize) -> Result<Option<NextRead>, StoreError> {
        let record_key =
            (!self.plan.person_leaves().is_empty()).then(|| self.scope.person_record_key());
        let batch = batch_from(
            self.plan.behavioral(),
            0,
            key_limit.saturating_sub(usize::from(record_key.is_some())),
        );
        let keys: Vec<BehavioralKey> = batch
            .iter()
            .map(|&(lsk, _)| self.scope.behavioral_key(lsk))
            .collect();
        let snapshot = self.store.read_event_snapshot(&keys, record_key.as_ref())?;
        if let Some(record) = snapshot.record {
            self.spend(
                ReadSource::PersonRecord,
                1,
                record.as_ref().map_or(0, Vec::len),
            );
            self.inputs
                .absorb_person_record(self.plan.person_leaves(), record);
        }
        if !batch.is_empty() {
            self.spend(
                ReadSource::Behavioral,
                batch.len(),
                raw_bytes(&snapshot.behavioral),
            );
            self.inputs.absorb_behavioral(batch, snapshot.behavioral);
        }
        Ok(NextRead::behavioral_at(batch.len(), self.plan))
    }

    fn behavioral(
        &mut self,
        from: usize,
        key_limit: usize,
    ) -> Result<Option<NextRead>, StoreError> {
        let batch = batch_from(self.plan.behavioral(), from, key_limit);
        let keys: Vec<BehavioralKey> = batch
            .iter()
            .map(|&(lsk, _)| self.scope.behavioral_key(lsk))
            .collect();
        let raw = self.store.multi_get_behavioral(&keys)?;
        self.spend(ReadSource::Behavioral, batch.len(), raw_bytes(&raw));
        self.inputs.absorb_behavioral(batch, raw);
        Ok(NextRead::behavioral_at(from + batch.len(), self.plan))
    }

    /// The row's own prior bit and every composed referent's bit come from one key set, so a
    /// referent is read as stored rather than substituted with a bit this page is about to write.
    fn stage2(&mut self, from: usize, key_limit: usize) -> Result<Option<NextRead>, StoreError> {
        let batch = batch_from(self.plan.stage2_cohorts(), from, key_limit);
        let keys: Vec<Stage2Key> = batch
            .iter()
            .map(|&cohort_id| self.scope.stage2_key(cohort_id))
            .collect();
        let raw = self.store.multi_get_stage2(&keys)?;
        self.spend(ReadSource::Stage2, batch.len(), raw_bytes(&raw));
        self.inputs.absorb_stage2(batch, raw);
        Ok(NextRead::stage2_at(from + batch.len(), self.plan))
    }

    fn spend(&mut self, source: ReadSource, keys: usize, bytes: usize) {
        source.record(keys, bytes);
        self.budget.spend(keys, bytes);
    }
}

/// At most `limit` entries of `source` from `from`.
fn batch_from<T>(source: &[T], from: usize, limit: usize) -> &[T] {
    &source[from..source.len().min(from + limit)]
}

/// The closed set of `source` label values on the page counters.
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
        counter!(RECONCILE_KEYS_FETCHED_TOTAL, "source" => self.label()).increment(keys as u64);
        histogram!(RECONCILE_READ_BYTES, "source" => self.label()).record(bytes as f64);
    }
}

#[cfg(test)]
// Tests seed the store directly through `CohortStore`, the sanctioned direct-store surface for tests.
#[allow(clippy::disallowed_methods)]
mod tests {
    use super::*;
    use chrono_tz::UTC;
    use serde_json::{json, Value};
    use tempfile::TempDir;
    use uuid::Uuid;

    use crate::filters::{TeamFiltersBuilder, TeamId};
    use crate::stage1::key::LeafStateKey;
    use crate::stage1::person_record::{MatchedSet, PersonRecord};
    use crate::stage1::state::{AppliedOffsets, Stage1State, StatefulRecord};
    use crate::stage2::state::Stage2State;
    use crate::store::{
        Behavioral, OffloadConfig, OffloadMode, PersonRecordKey, PersonRecords, ReadLane,
        StoreConfig,
    };
    use crate::workers::stage2_path::recompute_and_diff;

    const TEAM: u64 = 7;
    const PARTITION: u16 = 0;
    const COHORT: CohortId = CohortId(1);
    /// Composable, so cohort 1 reads it as a stored row.
    const COMPOSED_REF: CohortId = CohortId(2);
    /// One leaf, so cohort 1 reads it through that leaf's comparator.
    const SINGLE_LEAF_REF: CohortId = CohortId(3);
    const PERSON_HASH: [u8; 16] = *b"fedcba9876543210";
    const EVENT_MS: i64 = 1_700_000_000_000;

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    /// Wraps the store so `read_page` exercises the same blocking-pool transport as production.
    fn handle(store: &CohortStore) -> StoreHandle {
        StoreHandle::new(
            store.clone(),
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        )
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
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "u@p.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn cohort_ref(target: CohortId, negation: bool) -> Value {
        json!({ "type": "cohort", "value": target.0, "negation": negation })
    }

    fn hash(text: &str) -> [u8; 16] {
        text.as_bytes().try_into().expect("a 16-byte hash")
    }

    fn freeze(cohorts: Vec<(CohortId, Vec<Value>)>) -> Arc<TeamFilters> {
        let mut builder = TeamFiltersBuilder::default();
        for (id, values) in cohorts {
            let cohort = json!({ "properties": { "type": "AND", "values": values } });
            builder
                .add_cohort(id, TeamId(TEAM as i32), &cohort)
                .unwrap();
        }
        Arc::new(builder.freeze_with(UTC, true))
    }

    /// Cohort 1 over every reference kind and both leaf stores, so one page exercises each state
    /// source a reconcile read has.
    fn mixed_cohort() -> Arc<TeamFilters> {
        freeze(vec![
            (
                COHORT,
                vec![
                    behavioral_leaf("own0000000000001"),
                    person_leaf(),
                    cohort_ref(COMPOSED_REF, false),
                    cohort_ref(SINGLE_LEAF_REF, false),
                    // Absent from the catalog, so it reads as a non-member and the negation lets
                    // the AND through.
                    cohort_ref(CohortId(404), true),
                ],
            ),
            (
                COMPOSED_REF,
                vec![behavioral_leaf("ref0000000000002"), person_leaf()],
            ),
            (SINGLE_LEAF_REF, vec![behavioral_leaf("ref0000000000003")]),
        ])
    }

    fn person(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn stage2_key(cohort: CohortId, who: Uuid) -> Stage2Key {
        Stage2Key {
            partition_id: PARTITION,
            team_id: TEAM,
            cohort_id: cohort.0 as u64,
            person_id: who,
        }
    }

    fn behavioral_match() -> Stage1State {
        Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms: EVENT_MS,
            earliest_eviction_at_ms: i64::MAX,
        }
    }

    fn behavioral_miss() -> Stage1State {
        Stage1State::BehavioralSingle {
            has_match: false,
            last_event_at_ms: EVENT_MS,
            earliest_eviction_at_ms: i64::MAX,
        }
    }

    fn write_behavioral(store: &CohortStore, lsk: LeafStateKey, who: Uuid, state: Stage1State) {
        let record = StatefulRecord::new(state, AppliedOffsets::default());
        write_behavioral_bytes(store, lsk, who, &record.encode());
    }

    fn write_behavioral_bytes(store: &CohortStore, lsk: LeafStateKey, who: Uuid, bytes: &[u8]) {
        let key = BehavioralKey::new(PARTITION, TEAM, who, lsk);
        store
            .write_batch(|b| b.put::<Behavioral>(&key, bytes))
            .unwrap();
    }

    fn write_person_record(store: &CohortStore, who: Uuid, matched: &[[u8; 16]]) {
        let key = PersonRecordKey::new(PARTITION, TEAM, who);
        let mut record = PersonRecord::absent();
        record.matched = MatchedSet::from_iter(matched.iter().copied());
        store
            .write_batch(|b| b.put::<PersonRecords>(&key, &record.encode()))
            .unwrap();
    }

    fn write_corrupt_person_record(store: &CohortStore, who: Uuid) {
        let key = PersonRecordKey::new(PARTITION, TEAM, who);
        store
            .write_batch(|b| b.put::<PersonRecords>(&key, b"not a person record"))
            .unwrap();
    }

    fn write_stage2(store: &CohortStore, cohort: CohortId, who: Uuid, in_cohort: bool) {
        let state = Stage2State {
            in_cohort,
            last_evaluated_at_ms: EVENT_MS,
        };
        write_stage2_bytes(store, cohort, who, &state.encode());
    }

    /// A bit a merge transfer carried over, which a receiver-side evaluation must claim even when
    /// the logical membership is unchanged.
    fn write_transferred_fallback(store: &CohortStore, cohort: CohortId, who: Uuid, bit: bool) {
        let state = Stage2State {
            in_cohort: bit,
            last_evaluated_at_ms: EVENT_MS,
        };
        write_stage2_bytes(store, cohort, who, &state.encode_transferred_fallback());
    }

    fn write_stage2_bytes(store: &CohortStore, cohort: CohortId, who: Uuid, bytes: &[u8]) {
        let key = stage2_key(cohort, who);
        store.write_batch(|b| b.put_stage2(&key, bytes)).unwrap();
    }

    /// Everything the settlement path reads off one diff.
    fn settled(diff: &RecomputeDiff) -> (Stage2Key, bool, bool, bool, bool) {
        (
            diff.stage2_key,
            diff.new_bit,
            diff.prior_bit,
            diff.flipped(),
            diff.requires_write(),
        )
    }

    /// Drive the reader the way [`read_page`] does, but synchronously, so a test can see exactly
    /// where the section boundaries fell: one entry per section, holding the rows it settled and
    /// where the next section resumes. `None` means it stopped between rows, not inside one.
    fn read_in_sections(
        store: &CohortStore,
        filters: &Arc<TeamFilters>,
        page: &[Stage2Key],
    ) -> (Vec<RecomputeDiff>, Vec<(usize, Option<NextRead>)>) {
        let plan = Arc::new(CompositionReadPlan::for_cohorts([COHORT], filters));
        let mut reader = PageReader::new(Arc::clone(filters), plan, COHORT, page.to_vec());
        let mut sections = Vec::new();
        let mut settled = 0;
        loop {
            match reader.run_section(store).unwrap() {
                PageRead::Complete(diffs) => {
                    sections.push((diffs.len() - settled, None));
                    return (diffs, sections);
                }
                PageRead::Reading(resumed) => {
                    let resume = resumed.pending.as_ref().and_then(|read| read.next);
                    sections.push((resumed.diffs.len() - settled, resume));
                    settled = resumed.diffs.len();
                    reader = resumed;
                }
            }
        }
    }

    async fn per_row(
        store: &CohortStore,
        filters: &Arc<TeamFilters>,
        page: &[Stage2Key],
    ) -> Vec<RecomputeDiff> {
        let handle = handle(store);
        let tree = filters.cohorts.get(&COHORT).expect("the cohort is frozen");
        let mut diffs = Vec::with_capacity(page.len());
        for key in page {
            diffs.push(
                recompute_and_diff(
                    PARTITION,
                    key.person_id,
                    tree,
                    filters,
                    &handle,
                    ReadLane::Maintenance,
                )
                .await
                .unwrap(),
            );
        }
        diffs
    }

    /// One person per state shape a reconcile scan meets. Returns the page in scan order.
    fn seed_every_state_shape(store: &CohortStore, filters: &TeamFilters) -> Vec<Stage2Key> {
        let own = filters.by_condition_to_lsk[&hash("own0000000000001")][0];
        let referent = filters.by_condition_to_lsk[&hash("ref0000000000003")][0];

        // Everything matches over a non-member row: enters.
        let entering = person(1);
        write_behavioral(store, own, entering, behavioral_match());
        write_person_record(store, entering, &[PERSON_HASH]);
        write_behavioral(store, referent, entering, behavioral_match());
        write_stage2(store, COMPOSED_REF, entering, true);
        write_stage2(store, COHORT, entering, false);

        // No state at all, and no row of its own: stays a non-member and writes nothing.
        let absent = person(2);
        write_stage2(store, COHORT, absent, false);

        // Everything matches over a member row: unchanged.
        let unchanged = person(3);
        write_behavioral(store, own, unchanged, behavioral_match());
        write_person_record(store, unchanged, &[PERSON_HASH]);
        write_behavioral(store, referent, unchanged, behavioral_match());
        write_stage2(store, COMPOSED_REF, unchanged, true);
        write_stage2(store, COHORT, unchanged, true);

        // A corrupt behavioral value reads as a non-member, so a stale member bit is fixed.
        let corrupt_leaf = person(4);
        write_behavioral_bytes(store, own, corrupt_leaf, b"not a stage 1 record");
        write_person_record(store, corrupt_leaf, &[PERSON_HASH]);
        write_behavioral(store, referent, corrupt_leaf, behavioral_match());
        write_stage2(store, COMPOSED_REF, corrupt_leaf, true);
        write_stage2(store, COHORT, corrupt_leaf, true);

        // A corrupt person record reads every person leaf as a non-member, over a transferred
        // fallback the evaluation must claim even though the bit does not move.
        let corrupt_record = person(5);
        write_behavioral(store, own, corrupt_record, behavioral_match());
        write_corrupt_person_record(store, corrupt_record);
        write_behavioral(store, referent, corrupt_record, behavioral_match());
        write_stage2(store, COMPOSED_REF, corrupt_record, true);
        write_transferred_fallback(store, COHORT, corrupt_record, false);

        // A corrupt own row reads as a non-member prior, so a real member enters again.
        let corrupt_prior = person(6);
        write_behavioral(store, own, corrupt_prior, behavioral_match());
        write_person_record(store, corrupt_prior, &[PERSON_HASH]);
        write_behavioral(store, referent, corrupt_prior, behavioral_match());
        write_stage2(store, COMPOSED_REF, corrupt_prior, true);
        write_stage2_bytes(store, COHORT, corrupt_prior, b"not a stage 2 row");

        // The composed referent is a non-member, so the AND fails on the reference alone.
        let referent_missing = person(7);
        write_behavioral(store, own, referent_missing, behavioral_match());
        write_person_record(store, referent_missing, &[PERSON_HASH]);
        write_behavioral(store, referent, referent_missing, behavioral_match());
        write_stage2(store, COHORT, referent_missing, true);

        // The single-leaf referent misses, which only its own comparator can tell.
        let leaf_referent_miss = person(8);
        write_behavioral(store, own, leaf_referent_miss, behavioral_match());
        write_person_record(store, leaf_referent_miss, &[PERSON_HASH]);
        write_behavioral(store, referent, leaf_referent_miss, behavioral_miss());
        write_stage2(store, COMPOSED_REF, leaf_referent_miss, true);
        write_stage2(store, COHORT, leaf_referent_miss, true);

        (1..=8).map(|n| stage2_key(COHORT, person(n))).collect()
    }

    /// The page reader is the only reconcile read path, so what keeps it honest is agreement with
    /// `recompute_and_diff` — the per-row path it replaced, still live on the cascade.
    #[tokio::test]
    async fn a_page_agrees_with_the_per_row_path_on_every_state_shape() {
        let (_dir, store) = temp_store();
        let filters = mixed_cohort();
        let page = seed_every_state_shape(&store, &filters);

        let by_page = read_page(&handle(&store), &filters, COHORT, &page)
            .await
            .unwrap();
        let by_row = per_row(&store, &filters, &page).await;

        assert_eq!(
            by_page.iter().map(settled).collect::<Vec<_>>(),
            by_row.iter().map(settled).collect::<Vec<_>>(),
        );
        assert_eq!(
            by_page.iter().map(|diff| diff.new_bit).collect::<Vec<_>>(),
            [true, false, true, false, false, true, false, false],
            "the fixture has to exercise both bits, or agreement proves nothing",
        );
        assert_eq!(
            by_page
                .iter()
                .map(|diff| diff.requires_write())
                .collect::<Vec<_>>(),
            [true, false, false, true, true, true, true, true],
            "an unchanged transferred fallback still settles its ownership",
        );
    }

    /// Page widths derived from the row budget, so the test sits on the boundary wherever it moves:
    /// exactly the budget is one section, one more splits it.
    const ROW_BOUNDARY_PAGES: [usize; 2] = [MAX_ROWS, MAX_ROWS + 1];

    #[tokio::test]
    async fn a_page_wider_than_the_row_budget_settles_every_row_across_sections() {
        for (rows, expected) in ROW_BOUNDARY_PAGES
            .into_iter()
            .zip([vec![(MAX_ROWS, None)], vec![(MAX_ROWS, None), (1, None)]])
        {
            let (_dir, store) = temp_store();
            let filters = freeze(vec![(COHORT, vec![behavioral_leaf("own0000000000001")])]);
            let own = filters.by_condition_to_lsk[&hash("own0000000000001")][0];
            let page: Vec<Stage2Key> = (0..rows)
                .map(|index| {
                    let who = person(index as u128 + 1);
                    write_behavioral(&store, own, who, behavioral_match());
                    write_stage2(&store, COHORT, who, false);
                    stage2_key(COHORT, who)
                })
                .collect();

            let (diffs, sections) = read_in_sections(&store, &filters, &page);

            assert_eq!(
                sections, expected,
                "{rows} rows: the row budget stops a section between rows, never inside one",
            );
            assert_eq!(
                diffs.iter().map(settled).collect::<Vec<_>>(),
                per_row(&store, &filters, &page)
                    .await
                    .iter()
                    .map(settled)
                    .collect::<Vec<_>>(),
                "{rows} rows",
            );
        }
    }

    /// Leaf counts derived from the key budget. A row reads its person record, its behavioral
    /// leaves and its one Stage 2 row, so `MAX_KEYS - 2` leaves is exactly one section's allowance
    /// and one more splits the row.
    const KEY_BOUNDARY_WIDTHS: [usize; 2] = [MAX_KEYS - 2, MAX_KEYS - 1];

    fn wide_leaf(index: usize) -> Value {
        behavioral_leaf(&format!("beh{index:013}"))
    }

    /// A leaf the read skipped would leave the AND short, so the entry proves every key landed.
    #[tokio::test]
    async fn a_row_wider_than_the_key_budget_reads_every_key_across_sections() {
        let expectations = [
            vec![(1, None)],
            // One key short: the row's own Stage 2 read is what spills into a second section.
            vec![(0, Some(NextRead::Stage2(0))), (1, None)],
        ];
        for (leaves, expected) in KEY_BOUNDARY_WIDTHS.into_iter().zip(expectations) {
            let (_dir, store) = temp_store();
            let mut values: Vec<Value> = (0..leaves).map(wide_leaf).collect();
            values.push(person_leaf());
            let filters = freeze(vec![(COHORT, values)]);
            let lsks: Vec<LeafStateKey> = (0..leaves)
                .map(|index| filters.by_condition_to_lsk[&hash(&format!("beh{index:013}"))][0])
                .collect();

            let alice = person(1);
            for &lsk in &lsks {
                write_behavioral(&store, lsk, alice, behavioral_match());
            }
            write_person_record(&store, alice, &[PERSON_HASH]);
            let page = vec![stage2_key(COHORT, alice)];

            let (entered, sections) = read_in_sections(&store, &filters, &page);
            assert_eq!(sections, expected, "{leaves} leaves");
            assert!(entered[0].new_bit, "{leaves} leaves");

            // The entry above proves every batch landed. This half pins that the last leaf's value
            // is read, not just its key.
            write_behavioral(&store, lsks[leaves - 1], alice, behavioral_miss());
            let (left, _) = read_in_sections(&store, &filters, &page);
            assert!(!left[0].new_bit, "{leaves} leaves");
        }
    }

    /// A value bigger than the whole byte budget: the read that crosses it is already issued, so
    /// the section has to stop after it rather than refuse to make progress.
    #[tokio::test]
    async fn a_value_larger_than_the_byte_budget_stops_the_section_after_it() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![(COHORT, vec![behavioral_leaf("own0000000000001")])]);
        let own = filters.by_condition_to_lsk[&hash("own0000000000001")][0];
        let oversized = vec![b'x'; MAX_BYTES + 1];
        let page: Vec<Stage2Key> = (1..=2)
            .map(|index| {
                let who = person(index);
                write_behavioral_bytes(&store, own, who, &oversized);
                write_stage2(&store, COHORT, who, true);
                stage2_key(COHORT, who)
            })
            .collect();

        let (diffs, sections) = read_in_sections(&store, &filters, &page);

        // Per row: the oversized behavioral read crosses the budget and ends the section with the
        // row unsettled, then the next section reads its Stage 2 row.
        assert_eq!(
            sections,
            [
                (0, Some(NextRead::Stage2(0))),
                (1, Some(NextRead::Stage2(0))),
                (1, None),
            ],
        );
        assert_eq!(
            diffs.iter().map(settled).collect::<Vec<_>>(),
            per_row(&store, &filters, &page)
                .await
                .iter()
                .map(settled)
                .collect::<Vec<_>>(),
            "an undecodable oversized value still reads as a non-member",
        );
    }

    /// A cohort whose tree names only references reads no behavioral key and no person record, so
    /// its first source is empty. Skipping an empty source has to advance the read; a reader that
    /// re-entered it would spin on a section that spends nothing.
    #[tokio::test]
    async fn a_cohort_with_no_leaves_reads_only_its_stage_2_rows() {
        let (_dir, store) = temp_store();
        let filters = freeze(vec![
            (
                COHORT,
                vec![
                    cohort_ref(COMPOSED_REF, false),
                    cohort_ref(CohortId(404), true),
                ],
            ),
            (
                COMPOSED_REF,
                vec![behavioral_leaf("ref0000000000002"), person_leaf()],
            ),
        ]);
        let alice = person(1);
        write_stage2(&store, COMPOSED_REF, alice, true);
        write_stage2(&store, COHORT, alice, false);
        let page = vec![stage2_key(COHORT, alice)];

        let (diffs, sections) = read_in_sections(&store, &filters, &page);

        assert_eq!(sections, [(1, None)]);
        assert!(
            diffs[0].new_bit,
            "the referent's stored bit is the only input this cohort has",
        );
        assert_eq!(
            diffs.iter().map(settled).collect::<Vec<_>>(),
            per_row(&store, &filters, &page)
                .await
                .iter()
                .map(settled)
                .collect::<Vec<_>>(),
        );
    }

    /// The row that starts with one key left in the section reads its person record alone. Charging
    /// the record to the row's own allowance is what keeps that read non-empty — a section that
    /// handed out a zero allowance would spin instead of yielding.
    #[tokio::test]
    async fn a_row_that_starts_with_one_key_left_reads_its_record_alone() {
        // A row costs its record, its behavioral leaves and its one Stage 2 row. Size the cohort so
        // that every row but the last spends the key allowance down to exactly one.
        let full_rows = MAX_ROWS - 1;
        let keys_per_row = (MAX_KEYS - 1) / full_rows;
        assert_eq!(
            full_rows * keys_per_row,
            MAX_KEYS - 1,
            "the budgets no longer divide into the corner this test exists for",
        );
        let leaves = keys_per_row - 2;

        let (_dir, store) = temp_store();
        let mut values: Vec<Value> = (0..leaves).map(wide_leaf).collect();
        values.push(person_leaf());
        let filters = freeze(vec![(COHORT, values)]);
        let lsks: Vec<LeafStateKey> = (0..leaves)
            .map(|index| filters.by_condition_to_lsk[&hash(&format!("beh{index:013}"))][0])
            .collect();
        let page: Vec<Stage2Key> = (0..MAX_ROWS)
            .map(|index| {
                let who = person(index as u128 + 1);
                for &lsk in &lsks {
                    write_behavioral(&store, lsk, who, behavioral_match());
                }
                write_person_record(&store, who, &[PERSON_HASH]);
                write_stage2(&store, COHORT, who, false);
                stage2_key(COHORT, who)
            })
            .collect();

        let (diffs, sections) = read_in_sections(&store, &filters, &page);

        assert_eq!(
            sections,
            [(full_rows, Some(NextRead::Behavioral(0))), (1, None)],
            "the one key left buys the record alone, so the behavioral read resumes at 0",
        );
        assert!(
            diffs.iter().all(|diff| diff.new_bit),
            "a row split across sections still reads every leaf",
        );
    }

    /// Bytes accumulate across rows, not only within one read. A page of many moderate values is
    /// what the byte budget exists for; the oversized-value case above crosses it inside one read.
    #[tokio::test]
    async fn bytes_accumulate_across_rows_until_the_budget_stops_the_section() {
        // Sized so a whole number of rows fits under the budget, with rows to spare after it.
        let value_bytes = MAX_BYTES / 8 + 1;
        let rows_within_budget = MAX_BYTES / value_bytes;
        let rows = rows_within_budget + 3;

        let (_dir, store) = temp_store();
        let filters = freeze(vec![(COHORT, vec![behavioral_leaf("own0000000000001")])]);
        let own = filters.by_condition_to_lsk[&hash("own0000000000001")][0];
        let value = vec![b'x'; value_bytes];
        let page: Vec<Stage2Key> = (0..rows)
            .map(|index| {
                let who = person(index as u128 + 1);
                write_behavioral_bytes(&store, own, who, &value);
                write_stage2(&store, COHORT, who, true);
                stage2_key(COHORT, who)
            })
            .collect();

        let (diffs, sections) = read_in_sections(&store, &filters, &page);

        // The budget is consulted between reads, so the row that crosses it has already issued one
        // read and finishes in the next section — it is not held back whole.
        assert_eq!(
            sections,
            [
                (rows_within_budget, Some(NextRead::Stage2(0))),
                (rows - rows_within_budget, None),
            ],
            "the crossing row settles in the next section, not the one that read it",
        );
        assert_eq!(
            diffs.iter().map(settled).collect::<Vec<_>>(),
            per_row(&store, &filters, &page)
                .await
                .iter()
                .map(settled)
                .collect::<Vec<_>>(),
        );
    }

    /// Benchmark, not a test. Run it in release:
    ///
    /// ```text
    /// cargo test -p cohort-stream-processor --release --lib \
    ///     reconcile_page_benchmark -- --ignored --nocapture
    /// ```
    ///
    /// It asserts agreement only, because a wall-time threshold would flake on a slower box. It
    /// times the read and evaluation alone: acknowledgments are the settlement half, measured in
    /// production off `cohort_reconcile_page_duration_seconds`. Handoffs per row come from
    /// `store_offload_exec_duration_seconds{op="reconcile_page"}_count` over
    /// `cohort_reconcile_rows_attempted_total`.
    #[tokio::test]
    #[ignore = "benchmark; run in release with --ignored --nocapture"]
    async fn reconcile_page_benchmark() {
        use std::time::Instant;

        println!(
            "{:>5}  {:>12}  {:>12}  {:>7}",
            "page", "per-row", "by-page", "ratio"
        );
        for rows in [256, 512] {
            let (_dir, store) = temp_store();
            let filters = mixed_cohort();
            let own = filters.by_condition_to_lsk[&hash("own0000000000001")][0];
            let referent = filters.by_condition_to_lsk[&hash("ref0000000000003")][0];
            let page: Vec<Stage2Key> = (0..rows)
                .map(|index| {
                    let who = person(index as u128 + 1);
                    write_behavioral(&store, own, who, year_long_history());
                    write_behavioral(&store, referent, who, year_long_history());
                    write_person_record(&store, who, &[PERSON_HASH]);
                    write_stage2(&store, COMPOSED_REF, who, true);
                    // Half the rows disagree with the truth, so half the page really flips.
                    write_stage2(&store, COHORT, who, index % 2 == 0);
                    stage2_key(COHORT, who)
                })
                .collect();
            let handle = handle(&store);

            // Warm the block cache, so the timed passes measure the read shape and not the first
            // touch of every SST.
            let warm_by_page = read_page(&handle, &filters, COHORT, &page).await.unwrap();
            let warm_per_row = per_row(&store, &filters, &page).await;
            assert_eq!(
                warm_by_page.iter().map(settled).collect::<Vec<_>>(),
                warm_per_row.iter().map(settled).collect::<Vec<_>>(),
            );

            let started = Instant::now();
            per_row(&store, &filters, &page).await;
            let per_row_elapsed = started.elapsed();

            let started = Instant::now();
            read_page(&handle, &filters, COHORT, &page).await.unwrap();
            let by_page_elapsed = started.elapsed();

            println!(
                "{:>5}  {:>10.1?}  {:>10.1?}  {:>6.2}x",
                rows,
                per_row_elapsed,
                by_page_elapsed,
                per_row_elapsed.as_secs_f64() / by_page_elapsed.as_secs_f64(),
            );
        }
    }

    /// One entry per day of a year-long window, so each value is kilobytes rather than bytes.
    fn year_long_history() -> Stage1State {
        Stage1State::BehavioralCompressedHistory {
            entries: (0..365).map(|day| (20_600 + day, 1)).collect(),
            window_start_day: 20_600,
            last_event_at_ms: EVENT_MS,
            earliest_eviction_at_ms: i64::MAX,
        }
    }
}
