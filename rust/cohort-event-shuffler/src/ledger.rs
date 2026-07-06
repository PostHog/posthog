//! Pure per-partition offset ledger for the pipelined consume → produce → commit loop.
//!
//! Encodes the at-least-once commit rule: a source offset is committable only when every
//! forwarded event at or below it has resolved (acked or abandoned). No Kafka, no I/O, no
//! locks — owned (`&mut`) by the single pipeline task.
//!
//! # Watermark rule (per partition)
//!
//! `committable = in_flight.is_empty() ? high_watermark + 1 : min(in_flight)`. Settled events
//! only lift `high_watermark`. Gaps (offsets never observed, e.g. transaction markers) are
//! covered when the next observed message lifts the watermark past them.
//!
//! # Rebalance stance (eager, no `ConsumerContext` — deliberate PoC scope)
//!
//! Explicit-TPL commits are fenced by group generation, not per-partition ownership, so a stale
//! commit for a revoked partition can succeed. Defenses, all in [`Ledger::commit_plan`]:
//! (1) partitions absent from the current assignment snapshot are pruned; (2) delta suppression —
//! only committable > confirmed-committed is emitted; (3) commit values derive only from
//! self-consumed + resolved positions. Residual race (revoke lands between snapshot and commit):
//! the stale value ≤ what this pod actually consumed **and acked**, so a new owner resuming there
//! skips only events this pod already forwarded — at-least-once holds; worst case is bounded
//! duplicates.

use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SourcePartition(pub i32);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct SourceOffset(pub i64);

/// The offset Kafka resumes from (last-fully-done + 1). This is what gets committed — the
/// newtype prevents ever confusing "message offset" with "commit value".
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct NextOffset(pub i64);

/// How a consumed message enters the ledger: the rule "only forwards block the watermark".
#[derive(Debug, Clone, Copy)]
pub enum Observation {
    /// Done when seen: dropped (no person_id), skipped (team gate), or unparseable.
    Settled,
    /// Enqueued to the producer; blocks the commit watermark until resolved.
    InFlight,
}

/// Why an in-flight forward stopped blocking the watermark. Both advance it: `Abandoned` IS the
/// drop-on-produce-failure policy (parity with the pre-pipeline behavior), encoded in the type —
/// the seam where a hold/replay policy could slot in post-PoC.
#[derive(Debug, Clone, Copy)]
pub enum DeliveryOutcome {
    Acked,
    Abandoned,
}

/// [`Ledger::resolve`] result: `Untracked` = straggler ack for a pruned (revoked) partition —
/// dropped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Resolution {
    Resolved,
    Untracked,
}

#[derive(Debug)]
struct PartitionLedger {
    /// First offset this pod observed; stats baseline before the first confirmed commit.
    base: NextOffset,
    /// Highest observed offset, monotonic.
    high_watermark: SourceOffset,
    /// Unresolved forwards; the smallest blocks the commit watermark.
    in_flight: BTreeSet<SourceOffset>,
    /// Last broker-confirmed commit, monotonic.
    committed: Option<NextOffset>,
}

impl PartitionLedger {
    fn new(first: SourceOffset) -> Self {
        Self {
            base: NextOffset(first.0),
            high_watermark: first,
            in_flight: BTreeSet::new(),
            committed: None,
        }
    }

    fn committable(&self) -> NextOffset {
        match self.in_flight.first() {
            Some(oldest) => NextOffset(oldest.0),
            None => NextOffset(self.high_watermark.0 + 1),
        }
    }

    fn has_committable(&self) -> bool {
        self.committed
            .is_none_or(|committed| self.committable() > committed)
    }

    /// Observed-but-unconfirmed span; gap offsets inside it inflate the count slightly.
    fn uncommitted(&self) -> u64 {
        let done_through = self.committed.unwrap_or(self.base);
        (self.high_watermark.0 + 1)
            .saturating_sub(done_through.0)
            .max(0) as u64
    }
}

#[derive(Debug, Default)]
pub struct Ledger {
    partitions: BTreeMap<SourcePartition, PartitionLedger>,
    /// Denormalized Σ in_flight so the intake backpressure guard is O(1).
    total_in_flight: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommitPlan {
    pub offsets: Vec<(SourcePartition, NextOffset)>,
    pub pruned: Vec<SourcePartition>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LedgerStats {
    pub partitions: usize,
    pub in_flight: usize,
    pub uncommitted_events: u64,
}

impl Ledger {
    pub fn observe(
        &mut self,
        partition: SourcePartition,
        offset: SourceOffset,
        observation: Observation,
    ) {
        let ledger = self
            .partitions
            .entry(partition)
            .or_insert_with(|| PartitionLedger::new(offset));
        ledger.high_watermark = ledger.high_watermark.max(offset);
        if let Observation::InFlight = observation {
            if ledger.in_flight.insert(offset) {
                self.total_in_flight += 1;
            }
        }
    }

    /// `_outcome` is deliberately unused for advancement — see [`DeliveryOutcome`].
    pub fn resolve(
        &mut self,
        partition: SourcePartition,
        offset: SourceOffset,
        _outcome: DeliveryOutcome,
    ) -> Resolution {
        let removed = self
            .partitions
            .get_mut(&partition)
            .is_some_and(|ledger| ledger.in_flight.remove(&offset));
        if removed {
            self.total_in_flight -= 1;
            Resolution::Resolved
        } else {
            Resolution::Untracked
        }
    }

    /// Prunes partitions not in `assigned`, then returns offsets where committable > committed
    /// (delta suppression). Does NOT mark committed — see [`Ledger::confirm_committed`].
    pub fn commit_plan(&mut self, assigned: &BTreeSet<SourcePartition>) -> CommitPlan {
        let pruned: Vec<SourcePartition> = self
            .partitions
            .keys()
            .filter(|partition| !assigned.contains(partition))
            .copied()
            .collect();
        for partition in &pruned {
            if let Some(removed) = self.partitions.remove(partition) {
                self.total_in_flight -= removed.in_flight.len();
            }
        }

        let offsets = self
            .partitions
            .iter()
            .filter(|(_, ledger)| ledger.has_committable())
            .map(|(&partition, ledger)| (partition, ledger.committable()))
            .collect();
        CommitPlan { offsets, pruned }
    }

    /// Only after the broker commit succeeded; failed commits are retried next tick because the
    /// unconfirmed delta keeps being emitted by [`Ledger::commit_plan`].
    pub fn confirm_committed(&mut self, offsets: &[(SourcePartition, NextOffset)]) {
        for &(partition, next) in offsets {
            if let Some(ledger) = self.partitions.get_mut(&partition) {
                ledger.committed = Some(ledger.committed.map_or(next, |current| current.max(next)));
            }
        }
    }

    /// Backpressure input for the intake guard.
    pub fn in_flight(&self) -> usize {
        self.total_in_flight
    }

    /// True when a commit tick would emit something — the liveness gate's "committable work
    /// exists" input. Read-only: unlike [`Ledger::commit_plan`], never prunes.
    pub fn has_committable(&self) -> bool {
        self.partitions
            .values()
            .any(PartitionLedger::has_committable)
    }

    pub fn stats(&self) -> LedgerStats {
        LedgerStats {
            partitions: self.partitions.len(),
            in_flight: self.total_in_flight,
            uncommitted_events: self
                .partitions
                .values()
                .map(PartitionLedger::uncommitted)
                .sum(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    const P0: SourcePartition = SourcePartition(0);

    fn assigned(partitions: &[i32]) -> BTreeSet<SourcePartition> {
        partitions.iter().copied().map(SourcePartition).collect()
    }

    fn plan_offsets(ledger: &mut Ledger, partitions: &[i32]) -> Vec<(i32, i64)> {
        ledger
            .commit_plan(&assigned(partitions))
            .offsets
            .into_iter()
            .map(|(p, n)| (p.0, n.0))
            .collect()
    }

    #[test]
    fn empty_ledger_emits_nothing() {
        let mut ledger = Ledger::default();
        assert_eq!(
            ledger.commit_plan(&assigned(&[0, 1])),
            CommitPlan {
                offsets: vec![],
                pruned: vec![],
            }
        );
        assert!(!ledger.has_committable());
        assert_eq!(
            ledger.stats(),
            LedgerStats {
                partitions: 0,
                in_flight: 0,
                uncommitted_events: 0,
            }
        );
    }

    #[test]
    fn settled_events_commit_past_gaps() {
        let mut ledger = Ledger::default();
        for offset in [0, 2, 5] {
            ledger.observe(P0, SourceOffset(offset), Observation::Settled);
        }
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![(0, 6)]);
    }

    #[test]
    fn oldest_in_flight_blocks_the_watermark() {
        let mut ledger = Ledger::default();
        ledger.observe(P0, SourceOffset(0), Observation::Settled);
        ledger.observe(P0, SourceOffset(1), Observation::InFlight);
        ledger.observe(P0, SourceOffset(2), Observation::Settled);
        ledger.observe(P0, SourceOffset(3), Observation::InFlight);
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![(0, 1)]);

        // Out-of-order resolution: the newest ack alone does not unblock the oldest.
        ledger.resolve(P0, SourceOffset(3), DeliveryOutcome::Acked);
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![(0, 1)]);
        ledger.resolve(P0, SourceOffset(1), DeliveryOutcome::Acked);
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![(0, 4)]);
    }

    #[test]
    fn unconfirmed_commit_is_reemitted_and_confirmed_commit_is_suppressed() {
        let mut ledger = Ledger::default();
        ledger.observe(P0, SourceOffset(0), Observation::Settled);

        // Failed broker commit = no confirm: the same plan comes back next tick.
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![(0, 1)]);
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![(0, 1)]);

        ledger.confirm_committed(&[(P0, NextOffset(1))]);
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![]);
        assert!(!ledger.has_committable());

        ledger.observe(P0, SourceOffset(1), Observation::Settled);
        assert!(ledger.has_committable());
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![(0, 2)]);
    }

    #[test]
    fn pruned_partition_is_forgotten_and_its_straggler_ack_is_untracked() {
        let mut ledger = Ledger::default();
        ledger.observe(P0, SourceOffset(7), Observation::InFlight);
        ledger.observe(SourcePartition(1), SourceOffset(3), Observation::Settled);

        let plan = ledger.commit_plan(&assigned(&[1]));
        assert_eq!(plan.pruned, vec![P0]);
        assert_eq!(plan.offsets, vec![(SourcePartition(1), NextOffset(4))]);
        assert_eq!(ledger.in_flight(), 0);
        assert_eq!(
            ledger.resolve(P0, SourceOffset(7), DeliveryOutcome::Acked),
            Resolution::Untracked
        );
    }

    #[test]
    fn confirm_and_watermark_are_monotonic() {
        let mut ledger = Ledger::default();
        ledger.observe(P0, SourceOffset(5), Observation::Settled);
        // A re-observed lower offset (post-rebalance replay without a prune in between) must not
        // regress the watermark.
        ledger.observe(P0, SourceOffset(2), Observation::Settled);
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![(0, 6)]);

        ledger.confirm_committed(&[(P0, NextOffset(6))]);
        ledger.confirm_committed(&[(P0, NextOffset(4))]); // late/duplicate confirm
        assert_eq!(plan_offsets(&mut ledger, &[0]), vec![]);
    }

    // --- model-based property tests ----------------------------------------------------------

    const PARTITIONS: i32 = 3;

    #[derive(Debug, Clone)]
    enum Op {
        Observe {
            partition: i32,
            gap: u8,
            in_flight: bool,
        },
        ResolveNth {
            partition: i32,
            nth: u8,
        },
        Commit {
            assigned_mask: u8,
            confirm: bool,
        },
    }

    fn op_strategy() -> impl Strategy<Value = Op> {
        prop_oneof![
            5 => (0..PARTITIONS, 0u8..3, any::<bool>())
                .prop_map(|(partition, gap, in_flight)| Op::Observe { partition, gap, in_flight }),
            3 => (0..PARTITIONS, any::<u8>())
                .prop_map(|(partition, nth)| Op::ResolveNth { partition, nth }),
            2 => (0u8..(1 << PARTITIONS), any::<bool>())
                .prop_map(|(assigned_mask, confirm)| Op::Commit { assigned_mask, confirm }),
        ]
    }

    /// Naive reference: every observed offset with its resolution state, brute-forced plans.
    #[derive(Debug, Default)]
    struct ModelPartition {
        first_observed: i64,
        observed_max: i64,
        unresolved: BTreeSet<i64>,
        committed: Option<i64>,
    }

    impl ModelPartition {
        fn committable(&self) -> i64 {
            self.unresolved
                .first()
                .copied()
                .unwrap_or(self.observed_max + 1)
        }
    }

    #[derive(Debug, Default)]
    struct Model {
        partitions: BTreeMap<i32, ModelPartition>,
        next_offset: BTreeMap<i32, i64>,
    }

    impl Model {
        fn plan(&mut self, assigned_mask: u8) -> (Vec<(i32, i64)>, Vec<i32>) {
            let pruned: Vec<i32> = self
                .partitions
                .keys()
                .filter(|p| assigned_mask & (1 << **p) == 0)
                .copied()
                .collect();
            for p in &pruned {
                self.partitions.remove(p);
            }
            let offsets = self
                .partitions
                .iter()
                .filter(|(_, part)| part.committed.is_none_or(|c| part.committable() > c))
                .map(|(&p, part)| (p, part.committable()))
                .collect();
            (offsets, pruned)
        }
    }

    fn apply(ledger: &mut Ledger, model: &mut Model, op: Op) -> Result<(), TestCaseError> {
        match op {
            Op::Observe {
                partition,
                gap,
                in_flight,
            } => {
                let next = model.next_offset.entry(partition).or_insert(0);
                let offset = *next + i64::from(gap);
                *next = offset + 1;

                let part = model
                    .partitions
                    .entry(partition)
                    .or_insert_with(|| ModelPartition {
                        first_observed: offset,
                        observed_max: offset,
                        ..ModelPartition::default()
                    });
                part.observed_max = part.observed_max.max(offset);
                let observation = if in_flight {
                    part.unresolved.insert(offset);
                    Observation::InFlight
                } else {
                    Observation::Settled
                };
                ledger.observe(
                    SourcePartition(partition),
                    SourceOffset(offset),
                    observation,
                );
            }
            Op::ResolveNth { partition, nth } => {
                let Some(part) = model.partitions.get_mut(&partition) else {
                    return Ok(());
                };
                if part.unresolved.is_empty() {
                    return Ok(());
                }
                let offset = *part
                    .unresolved
                    .iter()
                    .nth(usize::from(nth) % part.unresolved.len())
                    .unwrap();
                part.unresolved.remove(&offset);
                let resolution = ledger.resolve(
                    SourcePartition(partition),
                    SourceOffset(offset),
                    DeliveryOutcome::Acked,
                );
                prop_assert_eq!(resolution, Resolution::Resolved);
            }
            Op::Commit {
                assigned_mask,
                confirm,
            } => {
                let assigned: BTreeSet<SourcePartition> = (0..PARTITIONS)
                    .filter(|p| assigned_mask & (1 << p) != 0)
                    .map(SourcePartition)
                    .collect();
                let plan = ledger.commit_plan(&assigned);
                let (model_offsets, model_pruned) = model.plan(assigned_mask);

                // Equivalence with the naive model (subsumes the watermark rule).
                let plan_raw: Vec<(i32, i64)> =
                    plan.offsets.iter().map(|&(p, n)| (p.0, n.0)).collect();
                let pruned_raw: Vec<i32> = plan.pruned.iter().map(|p| p.0).collect();
                prop_assert_eq!(&plan_raw, &model_offsets);
                prop_assert_eq!(pruned_raw, model_pruned);

                for &(partition, next) in &plan_raw {
                    let part = &model.partitions[&partition];
                    // P5: pruned/unassigned partitions never emitted.
                    prop_assert!(assigned_mask & (1 << partition) != 0);
                    // P2: safety — never commit past an unresolved forward.
                    if let Some(&oldest) = part.unresolved.first() {
                        prop_assert!(next <= oldest);
                    }
                    // P3: all-resolved ⇒ committable = high_watermark + 1.
                    if part.unresolved.is_empty() {
                        prop_assert_eq!(next, part.observed_max + 1);
                    }
                    // P1: emitted values strictly exceed the confirmed commit.
                    if let Some(committed) = part.committed {
                        prop_assert!(next > committed);
                    }
                }

                if confirm {
                    ledger.confirm_committed(&plan.offsets);
                    for (partition, next) in plan_raw {
                        model.partitions.get_mut(&partition).unwrap().committed = Some(next);
                    }
                }
            }
        }

        // Denormalized counter and stats stay consistent with the model.
        let model_in_flight: usize = model.partitions.values().map(|p| p.unresolved.len()).sum();
        prop_assert_eq!(ledger.in_flight(), model_in_flight);
        let model_uncommitted: u64 = model
            .partitions
            .values()
            .map(|p| (p.observed_max + 1 - p.committed.unwrap_or(p.first_observed)).max(0) as u64)
            .sum();
        prop_assert_eq!(
            ledger.stats(),
            LedgerStats {
                partitions: model.partitions.len(),
                in_flight: model_in_flight,
                uncommitted_events: model_uncommitted,
            }
        );
        Ok(())
    }

    proptest! {
        #[test]
        fn ledger_matches_reference_model(ops in proptest::collection::vec(op_strategy(), 1..200)) {
            let mut ledger = Ledger::default();
            let mut model = Model::default();
            for op in ops {
                apply(&mut ledger, &mut model, op)?;
            }
        }

        /// P4: `Abandoned` advances the watermark exactly like `Acked`.
        #[test]
        fn abandoned_is_equivalent_to_acked(ops in proptest::collection::vec(op_strategy(), 1..100)) {
            let mut acked = Ledger::default();
            let mut abandoned = Ledger::default();
            let all = (0..PARTITIONS).map(SourcePartition).collect::<BTreeSet<_>>();
            let mut next_offset: BTreeMap<i32, i64> = BTreeMap::new();
            let mut unresolved: BTreeMap<i32, BTreeSet<i64>> = BTreeMap::new();

            for op in ops {
                match op {
                    Op::Observe { partition, gap, in_flight } => {
                        let next = next_offset.entry(partition).or_insert(0);
                        let offset = *next + i64::from(gap);
                        *next = offset + 1;
                        let observation = if in_flight {
                            unresolved.entry(partition).or_default().insert(offset);
                            Observation::InFlight
                        } else {
                            Observation::Settled
                        };
                        acked.observe(SourcePartition(partition), SourceOffset(offset), observation);
                        abandoned.observe(SourcePartition(partition), SourceOffset(offset), observation);
                    }
                    Op::ResolveNth { partition, nth } => {
                        let Some(pending) = unresolved.get_mut(&partition) else { continue };
                        if pending.is_empty() { continue }
                        let offset = *pending.iter().nth(usize::from(nth) % pending.len()).unwrap();
                        pending.remove(&offset);
                        acked.resolve(SourcePartition(partition), SourceOffset(offset), DeliveryOutcome::Acked);
                        abandoned.resolve(SourcePartition(partition), SourceOffset(offset), DeliveryOutcome::Abandoned);
                    }
                    Op::Commit { confirm, .. } => {
                        let plan_a = acked.commit_plan(&all);
                        let plan_b = abandoned.commit_plan(&all);
                        prop_assert_eq!(&plan_a, &plan_b);
                        if confirm {
                            acked.confirm_committed(&plan_a.offsets);
                            abandoned.confirm_committed(&plan_b.offsets);
                        }
                    }
                }
            }
        }
    }
}
