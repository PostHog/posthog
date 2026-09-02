//! Pure per-run fold of observed `reconcile_complete` markers into per-cohort partition bitmaps.
//!
//! The marker watcher's dedicated task reads *all* marker partitions and hands each marker
//! to the ledger of the run it names. Folding is a monotone set-union: a partition's bit, once set,
//! never clears, so replaying the same marker stream in any order yields the same bitmaps. The final
//! per-cohort outcome (complete / partial) is reachable only through [`MarkerLedger::settle`], which
//! consumes a [`SettleProof`] — the capability minted in [`super::completion`] once the watcher has
//! read past the marker-topic end-watermarks captured at the liveness pass. No proof, no negative
//! verdict.

use std::collections::BTreeMap;

use cohort_core::filters::{CohortId, TeamId};

use super::completion::{MarkerNovelty, ObservedMarker, PartitionBitmap, SettleProof};
use super::ids::RunId;

/// How one observed marker was routed. Only [`Novel`](MarkerFold::Novel) mutates a bitmap; the rest
/// are accounted (via the `fold` metric label) and dropped, never errors — the watcher reads a shared
/// topic carrying every run's and team's markers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MarkerFold {
    /// A marker for one of this run's cohorts, setting a bit for the first time.
    Novel,
    /// A marker for one of this run's cohorts whose bit was already set.
    Duplicate,
    /// This run's team, but a different run — folded into another ledger.
    ForeignRun,
    /// A different team entirely.
    ForeignTeam,
    /// This run, but a cohort it does not track (superseded and excluded by the caller, or garbage).
    UnknownCohort,
    /// No ledger names this run. Decided by the watcher before any ledger sees the marker, and the
    /// dominant outcome since the watcher tails a topic carrying every run's markers.
    Unwatched,
}

impl MarkerFold {
    /// The metric label for `seeder_reconcile_markers_observed_total{fold}`.
    pub const fn label(self) -> &'static str {
        match self {
            Self::Novel => "novel",
            Self::Duplicate => "duplicate",
            Self::ForeignRun => "foreign_run",
            Self::ForeignTeam => "foreign_team",
            Self::UnknownCohort => "unknown_cohort",
            Self::Unwatched => "unwatched",
        }
    }
}

/// The settled per-cohort verdict for a run, reachable only with a [`SettleProof`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SettledVerdict {
    /// Every tracked cohort reached its full partition set.
    AllComplete,
    /// A mix: `complete` reached the full set, `incomplete` did not (each with its observed bitmap so
    /// the caller can name the missing partitions).
    Partial {
        complete: Vec<CohortId>,
        incomplete: Vec<(CohortId, PartitionBitmap)>,
    },
    /// Not a single marker was observed for any tracked cohort — the degenerate all-empty case that
    /// signals a fleet-wide reconcile gate-off.
    NoMarkers,
}

/// One tracked cohort's fold state.
#[derive(Debug, Clone, Copy)]
struct CohortFold {
    bitmap: PartitionBitmap,
    /// A bit was set since the last [`MarkerLedger::clear_dirty`]. Drives incremental flushes.
    dirty: bool,
    /// The bitmap reached its full set since the last [`MarkerLedger::clear_dirty`]. Drives the
    /// flush-on-completion trigger.
    newly_complete: bool,
}

/// A run's marker fold: its identity plus the per-cohort bitmaps it accumulates. Seeded from the bits
/// already persisted so a resumed watcher continues the fold rather than restarting it.
#[derive(Debug, Clone)]
pub struct MarkerLedger {
    run_id: RunId,
    team_id: TeamId,
    cohorts: BTreeMap<CohortId, CohortFold>,
}

impl MarkerLedger {
    /// Build a ledger for one run over its non-superseded cohorts and their already-persisted bitmaps.
    /// A cohort absent from `seeded` is not tracked; a marker for it folds as [`MarkerFold::UnknownCohort`].
    pub fn new(
        run_id: RunId,
        team_id: TeamId,
        seeded: impl IntoIterator<Item = (CohortId, PartitionBitmap)>,
    ) -> Self {
        let cohorts = seeded
            .into_iter()
            .map(|(cohort_id, bitmap)| {
                (
                    cohort_id,
                    CohortFold {
                        bitmap,
                        dirty: false,
                        newly_complete: false,
                    },
                )
            })
            .collect();
        Self {
            run_id,
            team_id,
            cohorts,
        }
    }

    pub const fn run_id(&self) -> RunId {
        self.run_id
    }

    /// Fold one observed marker. Routing is pure: team, then run, then cohort membership. Only a
    /// marker naming this run and a tracked cohort touches a bitmap.
    pub fn observe(&mut self, marker: &ObservedMarker) -> MarkerFold {
        if marker.team_id != self.team_id {
            return MarkerFold::ForeignTeam;
        }
        if marker.run_id != self.run_id {
            return MarkerFold::ForeignRun;
        }
        let Some(fold) = self.cohorts.get_mut(&marker.cohort_id) else {
            return MarkerFold::UnknownCohort;
        };
        match fold.bitmap.set(marker.partition) {
            MarkerNovelty::Duplicate => MarkerFold::Duplicate,
            MarkerNovelty::Novel => {
                fold.dirty = true;
                if fold.bitmap.is_complete() {
                    fold.newly_complete = true;
                }
                MarkerFold::Novel
            }
        }
    }

    /// Every tracked cohort is complete. Monotone (bits never clear) and usable without a proof: it
    /// only ever flips from false to true, so it is safe as an early-exit signal. A ledger with no
    /// tracked cohorts is vacuously complete.
    pub fn all_complete(&self) -> bool {
        self.cohorts.values().all(|fold| fold.bitmap.is_complete())
    }

    /// The cohorts whose bitmap changed since the last [`Self::clear_dirty`], with their current bits.
    /// Flushed through the idempotent OR-merge persist, so re-flushing the same bits is a no-op.
    pub fn dirty_bitmaps(&self) -> Vec<(CohortId, PartitionBitmap)> {
        self.cohorts
            .iter()
            .filter(|(_, fold)| fold.dirty)
            .map(|(cohort_id, fold)| (*cohort_id, fold.bitmap))
            .collect()
    }

    pub fn has_dirty(&self) -> bool {
        self.cohorts.values().any(|fold| fold.dirty)
    }

    /// A cohort reached its full partition set since the last [`Self::clear_dirty`]. The watcher
    /// flushes immediately on this so a completed cohort's outcome is durable without waiting a tick.
    pub fn completed_since_flush(&self) -> bool {
        self.cohorts.values().any(|fold| fold.newly_complete)
    }

    /// Clear the incremental-flush flags after a successful persist. Bitmaps are untouched.
    pub fn clear_dirty(&mut self) {
        for fold in self.cohorts.values_mut() {
            fold.dirty = false;
            fold.newly_complete = false;
        }
    }

    /// Settle the run: split tracked cohorts into complete and incomplete. Consumes the ledger and the
    /// [`SettleProof`], so a caller cannot record a negative outcome without first proving the marker
    /// set for this dispatch was fully observed.
    pub fn settle(self, _proof: SettleProof) -> SettledVerdict {
        let mut complete = Vec::new();
        let mut incomplete = Vec::new();
        let mut any_bit = false;
        for (cohort_id, fold) in self.cohorts {
            if !fold.bitmap.is_empty() {
                any_bit = true;
            }
            if fold.bitmap.is_complete() {
                complete.push(cohort_id);
            } else {
                incomplete.push((cohort_id, fold.bitmap));
            }
        }
        if incomplete.is_empty() {
            SettledVerdict::AllComplete
        } else if !any_bit {
            SettledVerdict::NoMarkers
        } else {
            SettledVerdict::Partial {
                complete,
                incomplete,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cohort_core::partitioner::COHORT_PARTITION_COUNT;
    use uuid::Uuid;

    use crate::domain::MarkerPartition;

    fn marker(team: i32, cohort: i32, run: RunId, partition: u32) -> ObservedMarker {
        ObservedMarker {
            team_id: TeamId(team),
            cohort_id: CohortId(cohort),
            partition: MarkerPartition::new(partition).unwrap(),
            run_id: run,
        }
    }

    fn run(seed: u128) -> RunId {
        RunId(Uuid::from_u128(seed))
    }

    fn ledger(cohorts: &[i32]) -> MarkerLedger {
        MarkerLedger::new(
            run(1),
            TeamId(2),
            cohorts
                .iter()
                .map(|&cohort| (CohortId(cohort), PartitionBitmap::default())),
        )
    }

    fn complete_cohort(ledger: &mut MarkerLedger, cohort: i32) {
        for partition in 0..COHORT_PARTITION_COUNT {
            ledger.observe(&marker(2, cohort, run(1), partition));
        }
    }

    #[test]
    fn observe_routes_every_fold_variant() {
        let mut ledger = ledger(&[10]);
        assert_eq!(ledger.observe(&marker(2, 10, run(1), 0)), MarkerFold::Novel);
        assert_eq!(
            ledger.observe(&marker(2, 10, run(1), 0)),
            MarkerFold::Duplicate
        );
        assert_eq!(
            ledger.observe(&marker(2, 10, run(9), 0)),
            MarkerFold::ForeignRun
        );
        assert_eq!(
            ledger.observe(&marker(7, 10, run(1), 0)),
            MarkerFold::ForeignTeam
        );
        assert_eq!(
            ledger.observe(&marker(2, 99, run(1), 0)),
            MarkerFold::UnknownCohort
        );
    }

    #[test]
    fn fold_is_order_independent() {
        let markers = [
            marker(2, 10, run(1), 3),
            marker(2, 11, run(1), 0),
            marker(2, 10, run(1), 1),
            marker(2, 10, run(1), 3),
            marker(2, 11, run(1), 5),
        ];

        let mut forward = ledger(&[10, 11]);
        for m in &markers {
            forward.observe(m);
        }
        let mut backward = ledger(&[10, 11]);
        for m in markers.iter().rev() {
            backward.observe(m);
        }

        assert_eq!(forward.dirty_bitmaps(), backward.dirty_bitmaps());
    }

    #[test]
    fn all_complete_is_monotone_and_ignores_untracked_state() {
        let mut both = ledger(&[10, 11]);
        assert!(!both.all_complete());
        complete_cohort(&mut both, 10);
        assert!(!both.all_complete(), "one cohort short is not complete");
        complete_cohort(&mut both, 11);
        assert!(both.all_complete());

        // Vacuously complete with nothing to track.
        assert!(ledger(&[]).all_complete());
    }

    #[test]
    fn dirty_and_completion_flags_track_flushes() {
        let mut ledger = ledger(&[10, 11]);
        assert!(!ledger.has_dirty());

        ledger.observe(&marker(2, 10, run(1), 0));
        assert!(ledger.has_dirty());
        assert!(!ledger.completed_since_flush());
        assert_eq!(ledger.dirty_bitmaps().len(), 1);

        complete_cohort(&mut ledger, 10);
        assert!(ledger.completed_since_flush());

        ledger.clear_dirty();
        assert!(!ledger.has_dirty());
        assert!(!ledger.completed_since_flush());
        assert!(
            ledger.dirty_bitmaps().is_empty(),
            "cleared flags hide already-persisted bits"
        );
    }

    #[test]
    fn settle_discriminates_all_complete_partial_and_no_markers() {
        // Reach the proof through the real caught-up path so the ZST stays un-forgeable in tests:
        // one partition read up to its captured end, minting a fresh proof for each settle.
        let proof = || {
            use crate::domain::{NextOffset, ObservationEnds, WatchPartition, WatchPositions};
            let partition = WatchPartition::new(0);
            let at = NextOffset::from_high_watermark(10);
            let mut ends = ObservationEnds::new();
            ends.insert(partition, at);
            let mut positions = WatchPositions::new();
            positions.insert(partition, at);
            ends.caught_up(&positions)
                .expect("positions at the captured end are caught up")
        };

        let mut all = ledger(&[10, 11]);
        complete_cohort(&mut all, 10);
        complete_cohort(&mut all, 11);
        assert_eq!(all.settle(proof()), SettledVerdict::AllComplete);

        let mut partial = ledger(&[10, 11]);
        complete_cohort(&mut partial, 10);
        partial.observe(&marker(2, 11, run(1), 0));
        match partial.settle(proof()) {
            SettledVerdict::Partial {
                complete,
                incomplete,
            } => {
                assert_eq!(complete, vec![CohortId(10)]);
                assert_eq!(incomplete.len(), 1);
                assert_eq!(incomplete[0].0, CohortId(11));
            }
            other => panic!("expected partial, got {other:?}"),
        }

        let empty = ledger(&[10, 11]);
        assert_eq!(empty.settle(proof()), SettledVerdict::NoMarkers);
    }
}
