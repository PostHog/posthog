//! Bounded, resumable eviction sweeps: turning one `Sweep` request into small batches the worker
//! interleaves with live traffic.
//!
//! A `Sweep` message records a request on [`SweepSchedule`], which the worker's turn loop drains one
//! [`SweepBatch`] at a time, alternating with live batches so a wave of tz-midnight deadlines cannot
//! hold the partition. Each batch reads, produces, commits and recomposes on its own, so peak memory
//! tracks the batch rather than the whole wave.
//!
//! Selection and claim are split across [`EvictionQueue::due_keys`] and
//! [`EvictionQueue::take_due`]: a pass plans over candidates but the queue stays authoritative, so
//! an event that reschedules a candidate or a merge that cancels one wins over the plan. The
//! per-key eviction arithmetic itself is unchanged, in [`super::sweep_callback`].

use std::collections::{BTreeMap, VecDeque};
use std::sync::Arc;
use std::time::Instant;

use metrics::{counter, gauge, histogram};
use tracing::warn;

use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::observability::metrics::{
    STAGE1_TRANSITIONS, SWEEP_BATCH_DURATION_SECONDS, SWEEP_BATCH_KEYS_CLAIMED,
    SWEEP_BATCH_PRODUCE_SECONDS, SWEEP_KEYS_DROPPED_TOTAL, SWEEP_KEYS_EVICTED_TOTAL,
    SWEEP_KEYS_NOT_CLAIMED_TOTAL, SWEEP_QUEUE_LAG_SECONDS, SWEEP_READ_CHUNK_BYTES,
};
use crate::producer::{map_transition, CohortMembershipChange, LastUpdatedClock, MembershipSink};
use crate::stage1::key::LeafStateKey;
use crate::stage1::state::StateVariant;
use crate::stage1::transition::LeafTransition;
use crate::stage2::{single_leaf_transition_register_writes, stage_register_writes};
use crate::store::{
    Behavioral, BehavioralKey, PersonPrefix, ReadLane, StagedBatch, StoreError, StoreHandle,
};
use crate::sweep::EvictionQueue;
use crate::workers::merge_path::MergeWorkerDeps;
use crate::workers::stage2_path::compose_stage2;
use crate::workers::sweep_callback::{
    sweep_evict, EvictionAction, EvictionResult, SweepDropReason, SweepEvictions,
};
use crate::workers::worker::{
    affected_leaves, first_cascades, produce_cascades, produce_membership, transition_metric_label,
};

/// Max eviction keys one request plans over. Daily-bucket deadlines cluster on tz-midnight, so a
/// large team's whole wave can come due on one tick; capping selection bounds how far ahead of the
/// queue a pass can plan. Leftover due keys stay scheduled and drain on the next request.
///
/// The budget is spent on selection, not on eviction: a candidate an event reschedules or a merge
/// cancels between selection and claim still counts against it, so a pass on a churning partition
/// can evict well under this many keys. Do not read it as a per-tick drain rate.
const MAX_SWEEP_KEYS_PER_PASS: usize = 10_000;

/// Keys one batch aims to claim, and the widest `cf_behavioral` read it issues. Person groups pack
/// whole, so a batch can overshoot this by one group: a batch under half full takes the next group
/// whatever its size, and a person with more leaves than this otherwise starts a batch and runs
/// alone. This bounds the ordinary batch; it is not a byte limit, because one behavioral value grows
/// with window length.
///
/// Whole-group packing holds **within** a pass. [`MAX_SWEEP_KEYS_PER_PASS`] cuts the flat,
/// deadline-ordered candidate list before grouping, so a person whose leaves carry different
/// deadlines can still straddle two passes and compose against half their eviction in between. The
/// next pass picks up the rest and the composition converges.
const SWEEP_BATCH_KEYS: usize = 256;

/// The worker's eviction-sweep state: at most one pass in flight and one coalesced follow-up cutoff.
///
/// Owned by the partition worker, mutated only from its turn loop.
pub(crate) struct SweepSchedule {
    partition_label: Arc<str>,
    active: Option<SweepPass>,
    /// The greatest cutoff requested that no pass has started on yet. One slot is enough: a later
    /// cutoff subsumes an earlier one over the same queue, so requests coalesce.
    pending_cutoff: Option<i64>,
    /// A live batch has run since the last sweep batch, so the sweep is owed the next turn.
    turn_owed: bool,
}

impl SweepSchedule {
    pub(crate) fn new(partition_id: u16) -> Self {
        Self {
            partition_label: Arc::from(partition_id.to_string()),
            active: None,
            pending_cutoff: None,
            turn_owed: false,
        }
    }

    /// Record an eviction request for `due_before_ms`. Never runs anything: the turn loop decides
    /// when the work happens.
    pub(crate) fn request(&mut self, due_before_ms: i64, queue: &EvictionQueue<BehavioralKey>) {
        self.pending_cutoff = Some(
            self.pending_cutoff
                .map_or(due_before_ms, |pending| pending.max(due_before_ms)),
        );
        self.record_queue_lag(queue);
    }

    /// Whether a batch is still available to run.
    pub(crate) fn has_work(&self) -> bool {
        self.pending_cutoff.is_some()
            || self
                .active
                .as_ref()
                .is_some_and(|pass| !pass.is_exhausted())
    }

    /// Whether the sweep must take this turn ahead of a ready live batch. True only after a live
    /// batch has run, which is what makes the two lanes alternate instead of live starving eviction.
    pub(crate) fn owes_turn(&self) -> bool {
        self.turn_owed && self.has_work()
    }

    /// A live batch finished its output and progress handling, so the sweep is owed the next turn.
    pub(crate) fn live_batch_done(&mut self) {
        self.turn_owed = true;
    }

    /// Claim the next batch, starting a pass from the pending cutoff and retiring an exhausted one
    /// as needed. [`None`] once nothing is due.
    fn next_batch(&mut self, queue: &mut EvictionQueue<BehavioralKey>) -> Option<SweepBatch> {
        // The turn is spent whether or not it yields work, so a retired pass cannot re-enter the
        // loop on the same alternation slot.
        self.turn_owed = false;
        loop {
            if self.active.is_none() {
                let cutoff = self.pending_cutoff.take()?;
                self.active = Some(SweepPass::select(queue, cutoff));
            }
            let pass = self.active.as_mut().expect("a pass was just started");
            if let Some(batch) = pass.next_batch(queue) {
                return Some(batch);
            }
            self.active = None;
        }
    }

    /// The newest cutoff the sweep knows about: the pending request, or the pass in flight.
    fn newest_cutoff(&self) -> Option<i64> {
        let active = self.active.as_ref().map(|pass| pass.due_before_ms);
        match (active, self.pending_cutoff) {
            (Some(active), Some(pending)) => Some(active.max(pending)),
            (active, pending) => active.or(pending),
        }
    }

    fn record_queue_lag(&self, queue: &EvictionQueue<BehavioralKey>) {
        let lag_ms = match (queue.peek_next_deadline(), self.newest_cutoff()) {
            (Some(oldest), Some(cutoff)) => cutoff.saturating_sub(oldest).max(0),
            _ => 0,
        };
        gauge!(SWEEP_QUEUE_LAG_SECONDS, "partition" => self.partition_label.clone())
            .set(lag_ms as f64 / 1_000.0);
    }
}

impl Drop for SweepSchedule {
    /// Zero the partition's lag gauge when the worker exits, so a revoked partition's last value
    /// does not pin. A frozen series reads exactly like the backlog the gauge exists to warn about.
    fn drop(&mut self) {
        gauge!(SWEEP_QUEUE_LAG_SECONDS, "partition" => self.partition_label.clone()).set(0.0);
    }
}

/// One request's candidates: a fixed cutoff and the persons selected from the queue when the pass
/// started, at most [`MAX_SWEEP_KEYS_PER_PASS`] keys across them.
///
/// Holds no state values and no deadlines. `PersonPrefix` orders by `(partition, team, person)`, so
/// popping from the front walks one team at a time.
struct SweepPass {
    due_before_ms: i64,
    groups: VecDeque<(PersonPrefix, Vec<LeafStateKey>)>,
}

impl SweepPass {
    fn select(queue: &EvictionQueue<BehavioralKey>, due_before_ms: i64) -> Self {
        let mut by_person: BTreeMap<PersonPrefix, Vec<LeafStateKey>> = BTreeMap::new();
        for key in queue.due_keys(due_before_ms, MAX_SWEEP_KEYS_PER_PASS) {
            by_person.entry(key.prefix).or_default().push(key.lsk);
        }
        Self {
            due_before_ms,
            groups: by_person.into_iter().collect(),
        }
    }

    fn is_exhausted(&self) -> bool {
        self.groups.is_empty()
    }

    /// Pack whole person groups from one team up to [`SWEEP_BATCH_KEYS`] and claim each of their
    /// keys out of the queue. Skips over persons whose keys all stopped being due.
    fn next_batch(&mut self, queue: &mut EvictionQueue<BehavioralKey>) -> Option<SweepBatch> {
        loop {
            let team_id = self.groups.front().map(|(prefix, _)| prefix.team_id)?;
            let mut claimed: Vec<(BehavioralKey, i64)> = Vec::with_capacity(SWEEP_BATCH_KEYS);
            loop {
                let Some((prefix, leaves)) = self.groups.front() else {
                    break;
                };
                // One team per batch: the filter snapshot and the Stage 2 composition are per team.
                if prefix.team_id != team_id {
                    break;
                }
                // Whole groups only, so composition sees a person's combined eviction. The cap
                // applies once the batch is at least half full: `leaves` counts selections, not
                // claims, so a run of persons whose keys mostly went stale would otherwise shrink
                // a batch to a key or two. A person wider than the target therefore starts a batch
                // and runs alone, unless an under-half batch takes it.
                if claimed.len() >= SWEEP_BATCH_KEYS / 2
                    && claimed.len() + leaves.len() > SWEEP_BATCH_KEYS
                {
                    break;
                }
                let (prefix, leaves) = self.groups.pop_front().expect("the front was just read");
                let mut not_claimed = 0u64;
                for lsk in leaves {
                    let key = prefix.behavioral_key(lsk);
                    match queue.take_due(&key, self.due_before_ms) {
                        Some(deadline) => claimed.push((key, deadline)),
                        // Rescheduled past the cutoff, or cancelled by a merge, since selection.
                        // A rescheduled key stays queued on its live deadline and a cancelled one
                        // was retired deliberately, so either way this is a skipped plan rather
                        // than a lost eviction.
                        None => not_claimed += 1,
                    }
                }
                // Once per person, not per key: this loop can walk a whole stale pass in one call.
                if not_claimed > 0 {
                    counter!(SWEEP_KEYS_NOT_CLAIMED_TOTAL).increment(not_claimed);
                }
            }
            if !claimed.is_empty() {
                return Some(SweepBatch {
                    team_id,
                    due_before_ms: self.due_before_ms,
                    claimed,
                });
            }
            // Every person in that run had gone stale. Keep packing rather than spending the turn
            // on an empty batch.
        }
    }
}

/// The keys one turn claimed: whole person groups from a single team, each with the deadline it was
/// claimed at so a failed batch can put them back exactly where they were.
///
/// Constructed only by [`SweepPass::next_batch`], so the single-team, whole-person boundary the
/// composition depends on cannot be bypassed.
pub(crate) struct SweepBatch {
    team_id: u64,
    due_before_ms: i64,
    claimed: Vec<(BehavioralKey, i64)>,
}

/// What one batch's reads produced, before any of it is applied: the writes to commit, the changes
/// to produce, the transitions Stage 2 recomposes from, the deadlines to re-arm, and the outcome
/// records for the counters. Values read from the store are decoded into this and dropped, so a
/// batch retains prepared writes rather than raw rows.
#[derive(Default)]
struct PreparedSweep {
    staged: StagedBatch,
    changes: Vec<CohortMembershipChange>,
    transitions: Vec<LeafTransition>,
    reschedules: Vec<(BehavioralKey, i64)>,
    evicted: Vec<StateVariant>,
    drops: Vec<SweepDropReason>,
}

impl PreparedSweep {
    fn absorb(
        &mut self,
        partition_id: u16,
        filters: &TeamFilters,
        evictions: SweepEvictions,
        due_before_ms: i64,
        last_updated: &str,
    ) {
        for result in evictions.results {
            let EvictionResult {
                key,
                variant,
                transition,
                action,
                reschedule,
            } = result;
            match action {
                EvictionAction::Write(bytes) => self.staged.put_owned::<Behavioral>(&key, bytes),
                EvictionAction::Delete => self.staged.delete::<Behavioral>(&key),
            }
            if let Some(transition) = transition {
                if let Some(kind) = transition_metric_label(filters, &transition) {
                    counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
                }
                self.changes
                    .extend(map_transition(filters, &transition, last_updated));
                // Keep this leg transition-based. The seed paths derive their single-leaf changes by
                // diffing this register, and between a seed's acked produce and its post-ack commit
                // the register reads `false` while downstream holds `Entered`. A register-diffed
                // sweep would compute `false == false` there and emit no `Left`, so the entry would
                // outlive the state that justified it. At most one of the path that emits an entry
                // and the path that retracts it may read the register.
                stage_register_writes(
                    &mut self.staged,
                    single_leaf_transition_register_writes(
                        filters,
                        partition_id,
                        &transition,
                        due_before_ms,
                    ),
                );
                self.transitions.push(transition);
            }
            if let Some(deadline) = reschedule {
                self.reschedules.push((key, deadline));
            }
            self.evicted.push(variant);
        }
        self.drops.extend(evictions.drops);
    }
}

/// Run at most one sweep batch, then return so the worker can select again. No-op when nothing is
/// due.
#[allow(clippy::too_many_arguments)]
pub(crate) async fn run_sweep_turn(
    partition_id: u16,
    handle: &StoreHandle,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut EvictionQueue<BehavioralKey>,
    clock: &mut LastUpdatedClock,
    schedule: &mut SweepSchedule,
) {
    let Some(batch) = schedule.next_batch(queue) else {
        return;
    };
    let started = Instant::now();
    run_batch(
        partition_id,
        handle,
        catalog,
        sink,
        merge,
        queue,
        clock,
        &batch,
    )
    .await;
    histogram!(SWEEP_BATCH_DURATION_SECONDS).record(started.elapsed().as_secs_f64());
    schedule.record_queue_lag(queue);
}

#[allow(clippy::too_many_arguments)]
async fn run_batch(
    partition_id: u16,
    handle: &StoreHandle,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut EvictionQueue<BehavioralKey>,
    clock: &mut LastUpdatedClock,
    batch: &SweepBatch,
) {
    histogram!(SWEEP_BATCH_KEYS_CLAIMED).record(batch.claimed.len() as f64);
    // One snapshot held to the end: a catalog refresh mid-batch must not split one person's eviction
    // across two views of the team.
    let snapshot = catalog.load();
    let Some(filters) = snapshot.team(TeamId(batch.team_id as i32)) else {
        // Terminal, unlike the three legs below: with the team gone from the snapshot there is
        // nothing to evict against, and a rescheduled key would be re-selected and re-dropped on
        // every pass.
        counter!(SWEEP_KEYS_DROPPED_TOTAL, "reason" => SweepDropReason::TeamDrift.as_str())
            .increment(batch.claimed.len() as u64);
        return;
    };
    let filters: &TeamFilters = filters;
    // Taken per batch, after whatever live output ran in between, so a resumed sweep never stamps a
    // change older than one a later live batch already emitted.
    let last_updated = clock.next();

    let prepared = match prepare(partition_id, handle, filters, batch, &last_updated).await {
        Ok(prepared) => prepared,
        Err(error) => {
            warn!(
                partition_id,
                team_id = batch.team_id,
                error = %error,
                "sweep state read failed; rescheduling the batch's keys for retry",
            );
            reschedule(queue, batch);
            return;
        }
    };
    let PreparedSweep {
        staged,
        changes,
        transitions,
        reschedules,
        evicted,
        drops,
    } = prepared;

    if !changes.is_empty() {
        let produce_started = Instant::now();
        let errors = produce_membership(sink, changes).await;
        histogram!(SWEEP_BATCH_PRODUCE_SECONDS).record(produce_started.elapsed().as_secs_f64());
        if errors > 0 {
            warn!(
                partition_id,
                errors, "sweep produce to the membership topic failed; rescheduling for replay",
            );
            reschedule(queue, batch);
            return;
        }
    }

    if !staged.is_empty() {
        if let Err(error) = handle.commit(staged).await {
            warn!(
                partition_id,
                error = %error,
                "sweep state write failed; rescheduling claimed keys to retry the eviction",
            );
            reschedule(queue, batch);
            return;
        }
    }

    for (key, deadline) in reschedules {
        queue.schedule(key, deadline);
    }
    for variant in evicted {
        counter!(SWEEP_KEYS_EVICTED_TOTAL, "variant" => variant.as_str()).increment(1);
    }
    for reason in drops {
        counter!(SWEEP_KEYS_DROPPED_TOTAL, "reason" => reason.as_str()).increment(1);
    }

    if transitions.is_empty() {
        return;
    }
    let stage2_changes = match compose_stage2(
        partition_id,
        handle,
        filters,
        &affected_leaves(&transitions),
        batch.due_before_ms,
        &last_updated,
        ReadLane::Event,
    )
    .await
    {
        Ok(changes) => changes,
        Err(error) => {
            warn!(
                partition_id,
                team_id = batch.team_id,
                error = %error,
                "sweep stage 2 composition failed; skipping (self-heals on the person's next event)",
            );
            return;
        }
    };
    if stage2_changes.is_empty() {
        return;
    }

    // Only Stage 2 membership changes cascade; single-leaf evictions self-heal on the referrer's next event.
    let cascades = first_cascades(merge, &stage2_changes, 0);
    let errors = produce_membership(sink, stage2_changes).await;
    if errors > 0 {
        warn!(
            partition_id,
            errors,
            "sweep stage 2 produce to the membership topic failed; dropping (cf_stage2 already committed, at-most-once)",
        );
        return;
    }
    let cascade_errors = produce_cascades(merge, cascades).await;
    if cascade_errors > 0 {
        warn!(
            partition_id,
            errors = cascade_errors,
            "sweep cascade produce failed; dropping (at-most-once). Recovery depends on each referrer being re-evaluated on its next event; the sweep does not re-evaluate cohort-ref shapes with no behavioral leaf",
        );
    }
}

/// Read the batch's states and fold them into the writes, changes and schedules they imply. An
/// ordinary batch is one read, because it was packed to [`SWEEP_BATCH_KEYS`], which is also the read
/// width. Only a batch that overshot the target reads in several chunks, each decoded and dropped
/// before the next is fetched.
async fn prepare(
    partition_id: u16,
    handle: &StoreHandle,
    filters: &TeamFilters,
    batch: &SweepBatch,
    last_updated: &str,
) -> Result<PreparedSweep, StoreError> {
    let mut prepared = PreparedSweep::default();
    for chunk in batch.claimed.chunks(SWEEP_BATCH_KEYS) {
        let keys: Vec<BehavioralKey> = chunk.iter().map(|&(key, _)| key).collect();
        // Cloned, not moved: the read takes its keys by value so its closure is `'static`, and the
        // eviction pass below still needs them to align each value with its key.
        let values = handle
            .multi_get_behavioral(keys.clone(), ReadLane::Maintenance)
            .await?;
        let raw_bytes: usize = values.iter().flatten().map(Vec::len).sum();
        histogram!(SWEEP_READ_CHUNK_BYTES).record(raw_bytes as f64);
        let evictions = sweep_evict(filters, &keys, values, batch.due_before_ms);
        prepared.absorb(
            partition_id,
            filters,
            evictions,
            batch.due_before_ms,
            last_updated,
        );
    }
    Ok(prepared)
}

/// Put a failed batch's keys back on the deadlines they were claimed at, so a later request retries
/// them. Batches that already settled stay settled. The deadline is restored exactly; the position
/// within its tier is not, because [`EvictionQueue::schedule`] mints a fresh tiebreaker.
fn reschedule(queue: &mut EvictionQueue<BehavioralKey>, batch: &SweepBatch) {
    for &(key, deadline) in &batch.claimed {
        queue.schedule(key, deadline);
    }
}

#[cfg(test)]
mod tests {
    use uuid::Uuid;

    use super::*;

    const TEAM: u64 = 7;
    const OTHER_TEAM: u64 = 8;
    const CUTOFF: i64 = 1_000;

    fn key(team_id: u64, person: u128, leaf: u128) -> BehavioralKey {
        BehavioralKey::new(
            0,
            team_id,
            Uuid::from_u128(person),
            LeafStateKey(leaf.to_le_bytes()),
        )
    }

    fn queue_of(entries: &[(BehavioralKey, i64)]) -> EvictionQueue<BehavioralKey> {
        let mut queue = EvictionQueue::new();
        for &(key, deadline) in entries {
            queue.schedule(key, deadline);
        }
        queue
    }

    fn drain_batches(
        pass: &mut SweepPass,
        queue: &mut EvictionQueue<BehavioralKey>,
    ) -> Vec<SweepBatch> {
        let mut out = Vec::new();
        while let Some(batch) = pass.next_batch(queue) {
            out.push(batch);
        }
        out
    }

    #[test]
    fn a_batch_never_spans_two_teams() {
        let entries: Vec<(BehavioralKey, i64)> = [TEAM, OTHER_TEAM]
            .into_iter()
            .flat_map(|team| (0..4).map(move |person| (key(team, person, 0), 100)))
            .collect();
        let mut queue = queue_of(&entries);
        let mut pass = SweepPass::select(&queue, CUTOFF);

        let batches = drain_batches(&mut pass, &mut queue);
        assert_eq!(
            batches.len(),
            2,
            "one batch per team, both well under the target"
        );
        assert_eq!(batches[0].team_id, TEAM);
        assert_eq!(batches[1].team_id, OTHER_TEAM);
        assert!(queue.is_empty(), "every due key was claimed");
    }

    #[test]
    fn a_persons_leaves_are_never_split_across_batches() {
        // Two persons of 200 leaves each: packing whole groups puts them in separate batches rather
        // than filling the first to exactly 256.
        let entries: Vec<(BehavioralKey, i64)> = (0..2)
            .flat_map(|person| (0..200).map(move |leaf| (key(TEAM, person, leaf), 100)))
            .collect();
        let mut queue = queue_of(&entries);
        let mut pass = SweepPass::select(&queue, CUTOFF);

        let batches = drain_batches(&mut pass, &mut queue);
        let sizes: Vec<usize> = batches.iter().map(|batch| batch.claimed.len()).collect();
        assert_eq!(sizes, vec![200, 200]);
        for batch in &batches {
            let persons: Vec<Uuid> = batch
                .claimed
                .iter()
                .map(|&(key, _)| key.person_id())
                .collect();
            assert!(
                persons.windows(2).all(|pair| pair[0] == pair[1]),
                "a batch carries one person's whole group",
            );
        }
    }

    #[test]
    fn a_person_wider_than_the_target_runs_alone() {
        let wide: Vec<(BehavioralKey, i64)> = (0..SWEEP_BATCH_KEYS + 50)
            .map(|leaf| (key(TEAM, 1, leaf as u128), 100))
            .collect();
        let mut entries = wide.clone();
        entries.push((key(TEAM, 2, 0), 100));
        let mut queue = queue_of(&entries);
        let mut pass = SweepPass::select(&queue, CUTOFF);

        let batches = drain_batches(&mut pass, &mut queue);
        assert_eq!(batches.len(), 2);
        assert_eq!(
            batches[0].claimed.len(),
            wide.len(),
            "the wide person is not split"
        );
        assert_eq!(batches[1].claimed.len(), 1);
    }

    #[test]
    fn stale_selections_do_not_count_against_the_batch_cap() {
        // Four persons selected at the target width each, all but one leaf rescheduled since. A cap
        // measured against selections would refuse the second person next to a single claim and
        // ship four one-key batches.
        let live: Vec<(BehavioralKey, i64)> =
            (0..4).map(|person| (key(TEAM, person, 0), 100)).collect();
        let stale: Vec<(BehavioralKey, i64)> = (0..4)
            .flat_map(|person| {
                (1..SWEEP_BATCH_KEYS).map(move |leaf| (key(TEAM, person, leaf as u128), 100))
            })
            .collect();
        let mut queue = queue_of(&[live.clone(), stale.clone()].concat());
        let mut pass = SweepPass::select(&queue, CUTOFF);
        for &(key, _) in &stale {
            queue.schedule(key, CUTOFF + 500);
        }

        let batches = drain_batches(&mut pass, &mut queue);
        let sizes: Vec<usize> = batches.iter().map(|batch| batch.claimed.len()).collect();
        assert_eq!(
            sizes,
            vec![live.len()],
            "the four claims pack into one batch"
        );
    }

    #[test]
    fn selection_caps_at_the_pass_limit_and_leaves_the_rest_queued() {
        let total = MAX_SWEEP_KEYS_PER_PASS + 10;
        // One shared deadline, the tz-midnight shape: selection order is then insertion order.
        let entries: Vec<(BehavioralKey, i64)> = (0..total)
            .map(|person| (key(TEAM, person as u128, 0), 100))
            .collect();
        let mut queue = queue_of(&entries);
        let mut pass = SweepPass::select(&queue, CUTOFF);

        let claimed: usize = drain_batches(&mut pass, &mut queue)
            .iter()
            .map(|batch| batch.claimed.len())
            .sum();
        assert_eq!(claimed, MAX_SWEEP_KEYS_PER_PASS);
        assert_eq!(queue.len(), 10, "the over-cap keys stay scheduled");
    }

    #[test]
    fn a_candidate_rescheduled_past_the_cutoff_is_not_claimed() {
        let stale = key(TEAM, 1, 0);
        let live = key(TEAM, 2, 0);
        let mut queue = queue_of(&[(stale, 100), (live, 100)]);
        let mut pass = SweepPass::select(&queue, CUTOFF);

        // An event lands for person 1 between selection and the batch, sliding its window forward.
        queue.schedule(stale, CUTOFF + 500);

        let batches = drain_batches(&mut pass, &mut queue);
        assert_eq!(batches.len(), 1);
        assert_eq!(
            batches[0]
                .claimed
                .iter()
                .map(|&(key, _)| key)
                .collect::<Vec<_>>(),
            vec![live],
        );
        assert_eq!(queue.len(), 1, "the rescheduled key stays queued");
        assert_eq!(queue.peek_next_deadline(), Some(CUTOFF + 500));
    }

    #[test]
    fn a_candidate_cancelled_before_its_batch_is_not_claimed() {
        let cancelled = key(TEAM, 1, 0);
        let live = key(TEAM, 2, 0);
        let mut queue = queue_of(&[(cancelled, 100), (live, 100)]);
        let mut pass = SweepPass::select(&queue, CUTOFF);

        // A merge drained person 1 and cancelled its keys.
        queue.cancel(&cancelled);

        let batches = drain_batches(&mut pass, &mut queue);
        assert_eq!(batches.len(), 1);
        assert_eq!(batches[0].claimed.len(), 1);
        assert!(queue.is_empty());
    }

    #[test]
    fn a_team_whose_every_candidate_went_stale_is_skipped_for_the_next_team() {
        // The inner loop yields an empty claim for the whole first team, so the pass must keep
        // packing into the next team rather than returning an empty batch and spending a turn.
        let stale = key(TEAM, 1, 0);
        let live = key(OTHER_TEAM, 1, 0);
        let mut queue = queue_of(&[(stale, 100), (live, 100)]);
        let mut pass = SweepPass::select(&queue, CUTOFF);

        queue.cancel(&stale);

        let batches = drain_batches(&mut pass, &mut queue);
        assert_eq!(batches.len(), 1, "no empty batch for the drained team");
        assert_eq!(batches[0].team_id, OTHER_TEAM);
        assert_eq!(batches[0].claimed.len(), 1);
    }

    #[test]
    fn a_failed_batch_returns_its_keys_on_the_deadlines_it_claimed() {
        // Two deliberately different deadlines: restoring both at the batch's soonest, or at one
        // shared value, is the easy way to get this wrong, so check each key's own deadline back.
        let (early, late) = (key(TEAM, 1, 0), key(TEAM, 1, 1));
        let mut queue = queue_of(&[(early, 100), (late, 250)]);
        let mut pass = SweepPass::select(&queue, CUTOFF);
        let batch = pass.next_batch(&mut queue).expect("one batch");
        assert!(queue.is_empty(), "claiming removes the keys");

        reschedule(&mut queue, &batch);
        assert_eq!(queue.len(), 2);
        assert_eq!(
            queue.take_due(&early, 101),
            Some(100),
            "the early key is due again one ms past its own deadline",
        );
        assert_eq!(
            queue.take_due(&late, 101),
            None,
            "the late key is not due there, so it did not inherit the early deadline",
        );
        assert_eq!(queue.take_due(&late, 251), Some(250));
    }

    #[test]
    fn requests_coalesce_onto_the_greatest_cutoff() {
        let mut queue = queue_of(&[(key(TEAM, 1, 0), 100)]);
        let mut schedule = SweepSchedule::new(0);
        assert!(!schedule.has_work());

        schedule.request(500, &queue);
        schedule.request(900, &queue);
        schedule.request(700, &queue);
        assert_eq!(schedule.newest_cutoff(), Some(900));

        let batch = schedule.next_batch(&mut queue).expect("one batch");
        assert_eq!(
            batch.due_before_ms, 900,
            "the pass runs at the greatest cutoff"
        );
        assert!(!schedule.has_work(), "one request yields one pass");
    }

    #[test]
    fn a_request_arriving_mid_pass_starts_a_second_pass_after_the_first_drains() {
        // Two teams, so the first pass takes two batches and a request can land between them.
        let entries: Vec<(BehavioralKey, i64)> = [TEAM, OTHER_TEAM]
            .into_iter()
            .map(|team| (key(team, 1, 0), 100))
            .collect();
        let mut queue = queue_of(&entries);
        let mut schedule = SweepSchedule::new(0);
        schedule.request(500, &queue);

        let first = schedule.next_batch(&mut queue).expect("first batch");
        assert_eq!(first.team_id, TEAM);

        // A later tick arrives while the pass is still draining, and a new key comes due with it.
        queue.schedule(key(TEAM, 2, 0), 600);
        schedule.request(700, &queue);

        let second = schedule
            .next_batch(&mut queue)
            .expect("second batch of the first pass");
        assert_eq!(second.team_id, OTHER_TEAM);
        assert_eq!(second.due_before_ms, 500, "the pass keeps its own cutoff");

        let third = schedule
            .next_batch(&mut queue)
            .expect("the coalesced request starts a second pass");
        assert_eq!(third.due_before_ms, 700);
        assert_eq!(third.claimed.len(), 1, "the key that came due at 600");
        assert!(!schedule.has_work());
    }

    #[test]
    fn the_sweep_is_owed_a_turn_only_after_a_live_batch_and_only_while_work_remains() {
        let mut queue = queue_of(&[(key(TEAM, 1, 0), 100)]);
        let mut schedule = SweepSchedule::new(0);

        schedule.live_batch_done();
        assert!(!schedule.owes_turn(), "no request, so nothing is owed");

        schedule.request(500, &queue);
        assert!(schedule.owes_turn());

        schedule.next_batch(&mut queue).expect("one batch");
        assert!(
            !schedule.owes_turn(),
            "the sweep spent its turn; live goes next",
        );
    }
}
