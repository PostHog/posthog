//! App layer: the per-run index of the newest day scanned for each (person, condition) pair, which
//! lets an older day's chunk skip the tiles the processor would merge away. Depends on `domain` and
//! `app::prepare`.
//!
//! The state is process-local, like the run breakers. Losing an index, on a restart or when an idle
//! run drops out of one refresh's eligible set, only sends more tiles.

use std::collections::HashMap;
use std::num::NonZeroUsize;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use dashmap::mapref::entry::Entry;
use dashmap::DashMap;
use metrics::gauge;
use uuid::Uuid;

use crate::domain::{ConditionSlot, DayIdx, NewestDayConditions, PinnedRun, RunId, SeedTile};
use crate::observability::metrics::NEWEST_DAY_INDEX_ENTRIES;

use super::prepare::PreparedRun;

type Key = (Uuid, ConditionSlot);

/// The newest-day indexes of the runs this process seeds, and the entry budget they share.
pub(super) struct NewestDayIndexes {
    budget: IndexBudget,
    by_run: HashMap<RunId, Arc<NewestDayIndex>>,
}

impl NewestDayIndexes {
    pub(super) fn new(max_entries: NonZeroUsize) -> Self {
        Self {
            budget: IndexBudget {
                used: Arc::default(),
                max: max_entries,
            },
            by_run: HashMap::new(),
        }
    }

    /// Built on the run's first claim. A run's frozen catalog only loses leaves after the run is
    /// created, so a `NewestDayConditions` built then can miss a skip but never allow a wrong one.
    pub(super) fn for_run(&mut self, run: &PinnedRun) -> Arc<NewestDayIndex> {
        let budget = &self.budget;
        self.by_run
            .entry(run.run_id)
            .or_insert_with(|| {
                let conditions = NewestDayConditions::of(&run.conditions, &run.filters);
                Arc::new(NewestDayIndex::new(conditions, budget.clone()))
            })
            .clone()
    }

    /// Keeps an index while a chunk task holds it, because a discovery error yields an empty
    /// eligible set, and a second index for the run would split its days and its budget. The gauge
    /// is set only here, so two chunk tasks can never set it out of order.
    pub(super) fn release_idle(&mut self, eligible: &HashMap<RunId, PreparedRun>) {
        self.by_run
            .retain(|run_id, index| eligible.contains_key(run_id) || Arc::strong_count(index) > 1);
        gauge!(NEWEST_DAY_INDEX_ENTRIES).set(self.budget.used.load(Ordering::Relaxed) as f64);
    }
}

/// One run's newest recorded day for each person on each qualifying condition.
///
/// It must stay per run: an index shared across runs would let one run's readiness depend on a
/// tile that only another run sends.
pub(super) struct NewestDayIndex {
    conditions: NewestDayConditions,
    newest: DashMap<Key, DayIdx>,
    budget: IndexBudget,
}

impl NewestDayIndex {
    fn new(conditions: NewestDayConditions, budget: IndexBudget) -> Self {
        Self {
            conditions,
            newest: DashMap::new(),
            budget,
        }
    }

    /// Max-merges each qualifying tile's day. A new pair takes one budget entry, and past the
    /// budget it is not recorded, so its older days are sent.
    pub(super) fn record(&self, tiles: &[SeedTile]) {
        for tile in tiles {
            let Some(key) = self.key(tile) else {
                continue;
            };
            match self.newest.entry(key) {
                Entry::Occupied(mut newest) => {
                    let newest = newest.get_mut();
                    *newest = (*newest).max(tile.day_idx());
                }
                Entry::Vacant(vacant) => {
                    if self.budget.try_take() {
                        vacant.insert(tile.day_idx());
                    }
                }
            }
        }
    }

    /// Only a strictly newer day counts, so a retried chunk never skips its own tiles, and the
    /// chunk holding a pair's newest day always sends it, unless events deleted before its retry
    /// remove the pair.
    pub(super) fn has_newer_day(&self, tile: &SeedTile) -> bool {
        self.key(tile).is_some_and(|key| {
            self.newest
                .get(&key)
                .is_some_and(|newest| *newest > tile.day_idx())
        })
    }

    fn key(&self, tile: &SeedTile) -> Option<Key> {
        self.conditions
            .slot(tile.condition_hash())
            .map(|slot| (tile.person_id(), slot))
    }
}

/// Gives this index's entries back, so a finished run frees its share of the budget.
impl Drop for NewestDayIndex {
    fn drop(&mut self) {
        self.budget
            .used
            .fetch_sub(self.newest.len(), Ordering::Relaxed);
    }
}

/// The entries all indexes may hold together. Every entry an index holds took one from here.
#[derive(Clone)]
struct IndexBudget {
    used: Arc<AtomicUsize>,
    max: NonZeroUsize,
}

impl IndexBudget {
    fn try_take(&self) -> bool {
        self.used
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |used| {
                (used < self.max.get()).then_some(used + 1)
            })
            .is_ok()
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU32;

    use chrono_tz::UTC;
    use cohort_core::filters::{CohortId, TeamId};

    use super::*;
    use crate::domain::row_filter::test_catalog::{catalog, event_is, hash, Leaf};
    use crate::domain::{
        Boundary, ClaimEpoch, EventNameSet, Lookback, PinnedCondition, SChunkMs, ScanTable,
        TriggerKind, UtcMillis,
    };

    const SLIDING: &str = "aaaaaaaaaaaaaaaa";
    /// Pinned, but absent from the frozen catalog, so it does not qualify.
    const UNCATALOGUED: &str = "bbbbbbbbbbbbbbbb";

    fn budget(max: usize) -> IndexBudget {
        IndexBudget {
            used: Arc::default(),
            max: NonZeroUsize::new(max).unwrap(),
        }
    }

    fn run(id: u128) -> PinnedRun {
        PinnedRun {
            run_id: RunId(Uuid::from_u128(id)),
            team_id: TeamId(2),
            trigger: TriggerKind::TeamEnablement,
            tz: UTC,
            boundary: Boundary::new(UtcMillis::new(0), UTC),
            conditions: [SLIDING, UNCATALOGUED]
                .map(|value| PinnedCondition {
                    cohort_id: CohortId(1),
                    hash: hash(value),
                    event_name: "$pageview".to_owned(),
                    lookback: Lookback::SlidingDays(7),
                })
                .to_vec(),
            event_names: EventNameSet::new(["$pageview".to_owned()]),
            filters: catalog(&[Leaf {
                cohort: 1,
                key: "$pageview",
                hash: SLIDING,
                body: event_is("$pageview"),
            }]),
            flag_calls_table: ScanTable::Events,
        }
    }

    fn index(budget: &IndexBudget) -> NewestDayIndex {
        let run = run(0);
        let conditions = NewestDayConditions::of(&run.conditions, &run.filters);
        NewestDayIndex::new(conditions, budget.clone())
    }

    fn tile(person: u128, condition: &str, day: DayIdx) -> SeedTile {
        SeedTile::new(
            TeamId(2),
            Uuid::from_u128(person),
            hash(condition),
            NonZeroU32::MIN,
            day,
            SChunkMs(0),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
    }

    #[test]
    fn only_a_strictly_newer_day_for_the_same_person_and_condition_skips_a_tile() {
        let index = index(&budget(10));
        index.record(&[tile(1, SLIDING, 10), tile(1, UNCATALOGUED, 10)]);
        index.record(&[tile(1, SLIDING, 9)]);

        for (case, tile, skipped) in [
            ("the recorded day", tile(1, SLIDING, 10), false),
            ("an older day", tile(1, SLIDING, 9), true),
            ("another person's older day", tile(2, SLIDING, 9), false),
            (
                "an older day on a non-qualifying condition",
                tile(1, UNCATALOGUED, 9),
                false,
            ),
        ] {
            assert_eq!(index.has_newer_day(&tile), skipped, "{case}");
        }
    }

    #[test]
    fn a_full_budget_sends_new_pairs_until_another_index_gives_its_entries_back() {
        let budget = budget(1);
        let first = index(&budget);
        first.record(&[tile(1, SLIDING, 10), tile(2, SLIDING, 10)]);
        assert!(
            !first.has_newer_day(&tile(2, SLIDING, 9)),
            "a pair past the budget was recorded"
        );
        first.record(&[tile(1, SLIDING, 11)]);
        assert!(
            first.has_newer_day(&tile(1, SLIDING, 10)),
            "a recorded pair stopped updating at a full budget"
        );

        drop(first);
        let second = index(&budget);
        second.record(&[tile(2, SLIDING, 10)]);
        assert!(
            second.has_newer_day(&tile(2, SLIDING, 9)),
            "a dropped index kept its budget"
        );
    }

    #[test]
    fn a_run_keeps_one_index_until_it_drops_out_and_no_chunk_task_holds_it() {
        let mut indexes = NewestDayIndexes::new(NonZeroUsize::MIN);
        let (held, idle) = (run(1), run(2));
        let task = indexes.for_run(&held);
        task.record(&[tile(1, SLIDING, 10)]);
        assert!(
            indexes.for_run(&held).has_newer_day(&tile(1, SLIDING, 9)),
            "a run's next claim got a new index"
        );
        let idle_index = Arc::downgrade(&indexes.for_run(&idle));
        assert!(
            !indexes.for_run(&idle).has_newer_day(&tile(1, SLIDING, 9)),
            "another run's day skipped a tile"
        );

        // A discovery error yields an empty eligible set.
        indexes.release_idle(&HashMap::new());
        assert!(
            Arc::ptr_eq(&indexes.for_run(&held), &task),
            "a held index was released, so the run's next chunk gets a second one"
        );
        assert!(
            idle_index.upgrade().is_none(),
            "an idle index outlived its run and kept its budget"
        );
    }
}
