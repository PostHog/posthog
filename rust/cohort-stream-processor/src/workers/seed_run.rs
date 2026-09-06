//! Run boundaries for the batched seed apply: a channel batch's seeds become runs of one kind,
//! and each run reaches exactly one mark or one hold.
//!
//! Applying seeds one at a time costs one awaited produce per seed that flips anything, so a
//! worker spends its time waiting on Kafka instead of folding. A run amortizes that: one read
//! pass, one register diff, one stage-1 commit, one recompute, one produce round trip, one
//! stage-2 commit, one mark. This module owns only the boundaries; the pipeline lives in
//! [`seed_apply`](super::seed_apply) and the two folds with their seed kinds.
//!
//! Pure: no I/O, no clock.

use std::collections::HashMap;
use std::num::NonZeroUsize;

use cohort_core::seed::{ConditionHash, PersonSeed, ReconcileTile, SeedTile};
use uuid::Uuid;

use crate::consumers::seeds::{SeedSkipReason, SeedWork};
use crate::filters::reverse_index::TeamFilters;
use crate::filters::{FilterCatalog, TeamId};
use crate::stage1::key::LeafStateKey;

/// One message's offset on `cohort_stream_seed_events`. A newtype so the seed tracker can never be
/// handed another topic's offset.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) struct SeedOffset(pub i64);

/// The offsets a run acts on: `first` is what a failure holds, `last` is what a success marks.
///
/// `first` is the run's *lowest* offset, not its leading one. The consumer delivers in offset
/// order, but a hold above the true minimum would pin the commit floor past a seed that was never
/// applied, so the span is derived from the items rather than assumed from delivery order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct OffsetSpan {
    pub first: SeedOffset,
    pub last: SeedOffset,
}

/// One seed with the offset that must be marked or held for it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Admitted<T> {
    pub work: T,
    pub offset: SeedOffset,
}

/// A non-empty run of one seed kind, applied as one unit. Construction is the only place emptiness
/// is checked, so [`span`](Self::span) can never be asked about a run with no offsets.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SeedRun<T> {
    items: Vec<Admitted<T>>,
    span: OffsetSpan,
}

impl<T> SeedRun<T> {
    /// `None` for an empty run: a group with no offsets could neither mark nor hold.
    pub(crate) fn new(items: Vec<Admitted<T>>) -> Option<Self> {
        let first = items.iter().map(|item| item.offset).min()?;
        let last = items
            .iter()
            .map(|item| item.offset)
            .max()
            .expect("a run with a lowest offset has a highest one too");
        Some(Self {
            items,
            span: OffsetSpan { first, last },
        })
    }

    pub(crate) fn span(&self) -> OffsetSpan {
        self.span
    }

    pub(crate) fn len(&self) -> usize {
        self.items.len()
    }

    pub(crate) fn into_items(self) -> Vec<Admitted<T>> {
        self.items
    }
}

/// A channel batch's seeds, split so each group is applied by exactly one handler.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum SeedGroup {
    Tiles(SeedRun<SeedTile>),
    Persons(SeedRun<PersonSeed>),
    /// Control tiles stay single: admission defers one offset and orders one queue entry, which a
    /// run of them could not express.
    Reconcile(Admitted<ReconcileTile>),
    /// Consume-side skips stay single: each one commits its own offset and does no work.
    Skip(Admitted<SeedSkipReason>),
}

impl SeedGroup {
    /// The lowest offset this group acts on — the order groups are applied in.
    fn first_offset(&self) -> SeedOffset {
        match self {
            Self::Tiles(run) => run.span().first,
            Self::Persons(run) => run.span().first,
            Self::Reconcile(admitted) => admitted.offset,
            Self::Skip(admitted) => admitted.offset,
        }
    }
}

/// Which apply pipeline a run belongs to; also the `kind` metric label.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum SeedKind {
    Tile,
    Person,
}

impl SeedKind {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Tile => "tile",
            Self::Person => "person",
        }
    }
}

/// Both ceilings on one run. `seeds` bounds messages; `rows` bounds the run's footprint, so a hash
/// resolving to many leaves, a leaf backing many cohorts, or a 1,024-hash person seed cannot make
/// a run arbitrarily heavy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RunBudget {
    /// Seeds per run. `1` restores the per-seed apply, which is the hatch if batching misbehaves.
    pub seeds: NonZeroUsize,
    /// Store rows per run, as [`row_weight`] weighs them. A run closes before the seed that would
    /// exceed it; a seed heavier than the whole budget still runs alone.
    pub rows: NonZeroUsize,
}

impl Default for RunBudget {
    /// Mirrors the `COHORT_SEED_APPLY_BATCH_MAX*` defaults, for deps built without explicit config.
    fn default() -> Self {
        Self {
            seeds: NonZeroUsize::new(256).expect("256 > 0"),
            rows: NonZeroUsize::new(4096).expect("4096 > 0"),
        }
    }
}

/// How much of a run one seed can occupy, against the catalog snapshot the run will fold with: one
/// unit per leaf it reaches, plus one per stage-2 register each of those leaves backs, plus the
/// person seed's own record row. Every per-run structure — the overlay, the folded leaves, the
/// recompose set, the register read, the membership output and its cascades — holds at most one
/// entry per unit, so the budget this feeds is a ceiling on all of them, not on the overlay alone.
///
/// Both kinds charge for a leaf that backs no register, because the fold still retains one entry
/// for it. A person seed carries up to 1,024 hashes, so charging only its registers would let a
/// full run of leaves that can emit nothing slip under the ceiling.
///
/// It is a ceiling on what a run retains and emits, not on the reads inside each composed
/// evaluation: those scale with that cohort's tree exactly as under the per-seed apply, and the
/// maintenance lane's permits are what meter them.
///
/// A seed the catalog cannot place weighs one, so a run of them is still bounded by the seed cap
/// rather than by nothing. Control and skip seeds weigh nothing: they are always their own group.
pub(crate) fn row_weight(catalog: &FilterCatalog, work: &SeedWork) -> usize {
    let rows = match work {
        SeedWork::Tile(tile) => catalog.team(tile.team_id()).map_or(0, |filters| {
            leaves_of(filters, tile.condition_hash())
                .map(|lsk| 1 + registers_backed_by(filters, lsk))
                .sum::<usize>()
        }),
        SeedWork::Person(seed) => catalog.team(seed.team_id()).map_or(0, |filters| {
            1 + seed
                .evaluated()
                .iter()
                .flat_map(|&hash| leaves_of(filters, hash))
                .map(|lsk| 1 + registers_backed_by(filters, lsk))
                .sum::<usize>()
        }),
        SeedWork::Reconcile(_) | SeedWork::Skip(_) => return 0,
    };
    rows.max(1)
}

/// The leaves a condition hash resolves to: one per window the catalog keeps over it.
fn leaves_of(filters: &TeamFilters, hash: ConditionHash) -> impl Iterator<Item = &LeafStateKey> {
    filters
        .by_condition_to_lsk
        .get(&hash.as_bytes())
        .into_iter()
        .flatten()
}

/// The `cf_stage2` rows one leaf reaches for one person: one per single-leaf cohort the register
/// diff keys on it, one per composable cohort the recompute re-walks for it.
fn registers_backed_by(filters: &TeamFilters, lsk: &LeafStateKey) -> usize {
    let single = filters
        .by_lsk_to_single_leaf_cohorts
        .get(lsk)
        .map_or(0, Vec::len);
    let composable = filters
        .by_lsk_to_composable_cohorts
        .get(lsk)
        .map_or(0, Vec::len);
    single + composable
}

/// Split `seeds` into runs of one kind, in offset order, each within `budget` under `weigh`.
///
/// One open run per kind: a tile does not close the open person run and vice versa, so an
/// interleaved stream still forms full runs. A reconcile seed closes both open runs first because
/// it orders a queue entry; a skip has no durable effect and does not split them. A budget closes
/// only the run it bounds.
///
/// Runs apply in first-offset order, so two open runs could apply one person's seeds out of offset
/// order when both kinds touch them, and a composed cohort would then emit flips the per-seed
/// apply never emits. A seed joins its kind's open run only if that run starts above the other
/// kind's latest run for its person; otherwise it starts a new run. Different persons keep
/// batching, which is the ordinary shape.
///
/// Residue: a tombstone redirects a seed to the merge survivor, and routing runs after grouping, so
/// two seeds that meet only on the survivor are not seen to share a person here. That window is a
/// straggler seed for a person merged mid-backfill, and it degrades to the reorder above, not to a
/// wrong final membership.
///
/// Pure and total: every input seed lands in exactly one group, groups are emitted in the order of
/// their first offset, and offset order is preserved within each kind.
pub(crate) fn group_seeds(
    seeds: Vec<Admitted<SeedWork>>,
    budget: RunBudget,
    weigh: impl Fn(&SeedWork) -> usize,
) -> Vec<SeedGroup> {
    let mut groups = Vec::new();
    let mut tiles = OpenRun::new(SeedGroup::Tiles);
    let mut persons = OpenRun::new(SeedGroup::Persons);

    for Admitted { work, offset } in seeds {
        let weight = weigh(&work);
        match work {
            SeedWork::Tile(tile) => {
                let person = (tile.team_id(), tile.person_id());
                let other_kind_run_start = persons.run_start_for(person);
                tiles.admit(
                    Admitted { work: tile, offset },
                    person,
                    other_kind_run_start,
                    weight,
                    budget,
                    &mut groups,
                );
            }
            SeedWork::Person(seed) => {
                let person = (seed.team_id(), seed.person_id());
                let other_kind_run_start = tiles.run_start_for(person);
                persons.admit(
                    Admitted { work: seed, offset },
                    person,
                    other_kind_run_start,
                    weight,
                    budget,
                    &mut groups,
                );
            }
            SeedWork::Reconcile(tile) => {
                tiles.close(&mut groups);
                persons.close(&mut groups);
                groups.push(SeedGroup::Reconcile(Admitted { work: tile, offset }));
            }
            SeedWork::Skip(reason) => {
                groups.push(SeedGroup::Skip(Admitted {
                    work: reason,
                    offset,
                }));
            }
        }
    }

    tiles.close(&mut groups);
    persons.close(&mut groups);
    // Two open runs close at the end in kind order, which is not offset order. Sorting restores the
    // contract callers read the groups under; it does not make a group's span disjoint from its
    // neighbours', which is why the mark is buffered rather than published per group.
    groups.sort_by_key(SeedGroup::first_offset);
    groups
}

/// One person of one team, the unit both seed kinds order against: stage-1 rows, stage-2 registers
/// and cascades are all keyed on it, so runs that share no person cannot observe each other.
type TeamPerson = (TeamId, Uuid);

/// A run of one kind still accepting seeds, with the row weight it has admitted.
struct OpenRun<T> {
    into: fn(SeedRun<T>) -> SeedGroup,
    items: Vec<Admitted<T>>,
    rows: usize,
    /// Per person, the first offset of the latest run of this kind that took them. Kept across
    /// closes: a closed run still applies at its own first offset.
    run_start_by_person: HashMap<TeamPerson, SeedOffset>,
}

impl<T> OpenRun<T> {
    fn new(into: fn(SeedRun<T>) -> SeedGroup) -> Self {
        Self {
            into,
            items: Vec::new(),
            rows: 0,
            run_start_by_person: HashMap::new(),
        }
    }

    /// The start of the latest run of this kind for this person.
    fn run_start_for(&self, person: TeamPerson) -> Option<SeedOffset> {
        self.run_start_by_person.get(&person).copied()
    }

    /// Admit one seed. The run closes first when the other kind's run for this person starts above
    /// it or the weight would overflow the row budget, and after when the seed count fills. An
    /// empty run always admits, so a seed heavier than the whole budget still runs alone.
    fn admit(
        &mut self,
        item: Admitted<T>,
        person: TeamPerson,
        other_kind_run_start: Option<SeedOffset>,
        weight: usize,
        budget: RunBudget,
        groups: &mut Vec<SeedGroup>,
    ) {
        let start = self.items.first().map(|first| first.offset);
        let reorders = start
            .zip(other_kind_run_start)
            .is_some_and(|(start, since)| start < since);
        let overflows = self.rows.saturating_add(weight) > budget.rows.get();
        if reorders || (overflows && !self.items.is_empty()) {
            self.close(groups);
        }
        self.items.push(item);
        self.rows = self.rows.saturating_add(weight);
        let start = self.items[0].offset;
        self.run_start_by_person.insert(person, start);
        if self.items.len() >= budget.seeds.get() {
            self.close(groups);
        }
    }

    /// Close the run, if non-empty, as one group.
    fn close(&mut self, groups: &mut Vec<SeedGroup>) {
        let Some(run) = SeedRun::new(std::mem::take(&mut self.items)) else {
            return;
        };
        self.rows = 0;
        groups.push((self.into)(run));
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU32;

    use cohort_core::seed::{
        BehavioralShapeHash, ClaimEpoch, ConditionHash, ReconcileScope, RunId, SChunkMs,
        ScannedAtMs,
    };
    use serde_json::{json, Value};
    use uuid::Uuid;

    use crate::filters::{CohortId, TeamFiltersBuilder, TeamId};

    use super::*;

    const TEAM: TeamId = TeamId(7);
    const BEHAVIORAL: &str = "0123456789abcdef";
    const PERSON: &str = "person0000000001";

    fn hash(value: &str) -> ConditionHash {
        ConditionHash::parse(value).unwrap()
    }

    fn tile() -> SeedTile {
        tile_with(TEAM, BEHAVIORAL)
    }

    fn tile_for(person: Uuid) -> SeedTile {
        SeedTile::new(
            TEAM,
            person,
            hash(BEHAVIORAL),
            NonZeroU32::new(1).unwrap(),
            20_614,
            SChunkMs(1),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
    }

    fn tile_with(team: TeamId, condition_hash: &str) -> SeedTile {
        SeedTile::new(
            team,
            Uuid::from_u128(1),
            hash(condition_hash),
            NonZeroU32::new(1).unwrap(),
            20_614,
            SChunkMs(1),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
    }

    fn person_seed(evaluated: &[&str]) -> PersonSeed {
        person_seed_for(Uuid::from_u128(2), evaluated)
    }

    fn person_seed_for(person: Uuid, evaluated: &[&str]) -> PersonSeed {
        PersonSeed::new(
            TEAM,
            person,
            evaluated.iter().copied().map(hash).collect(),
            vec![],
            ScannedAtMs(1),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
        .unwrap()
    }

    fn reconcile() -> ReconcileTile {
        ReconcileTile::new(
            TEAM,
            CohortId(1),
            ReconcileScope::Behavioral(BehavioralShapeHash::parse(BEHAVIORAL).unwrap()),
            RunId(Uuid::nil()),
        )
    }

    fn admitted(work: SeedWork, offset: i64) -> Admitted<SeedWork> {
        Admitted {
            work,
            offset: SeedOffset(offset),
        }
    }

    /// The offsets each group would act on: `(first, last)` per group, in group order.
    fn spans(groups: &[SeedGroup]) -> Vec<(i64, i64)> {
        groups
            .iter()
            .map(|group| match group {
                SeedGroup::Tiles(run) => (run.span().first.0, run.span().last.0),
                SeedGroup::Persons(run) => (run.span().first.0, run.span().last.0),
                SeedGroup::Reconcile(admitted) => (admitted.offset.0, admitted.offset.0),
                SeedGroup::Skip(admitted) => (admitted.offset.0, admitted.offset.0),
            })
            .collect()
    }

    fn budget(seeds: usize, rows: usize) -> RunBudget {
        RunBudget {
            seeds: NonZeroUsize::new(seeds).unwrap(),
            rows: NonZeroUsize::new(rows).unwrap(),
        }
    }

    /// Group under the seed cap alone: every seed weighs one and the row budget is unbounded.
    fn group_by_count(seeds: Vec<Admitted<SeedWork>>, max_seeds: usize) -> Vec<SeedGroup> {
        group_seeds(seeds, budget(max_seeds, usize::MAX), |_| 1)
    }

    fn tiles(offsets: std::ops::Range<i64>) -> Vec<Admitted<SeedWork>> {
        offsets
            .map(|offset| admitted(SeedWork::Tile(tile()), offset))
            .collect()
    }

    /// Reconcile must stay behind preceding data, while a no-op skip must not fragment a data run.
    #[test]
    fn reconcile_closes_both_runs_while_skip_stays_nonbarrier() {
        let groups = group_by_count(
            vec![
                admitted(SeedWork::Tile(tile()), 0),
                admitted(SeedWork::Person(person_seed(&[PERSON])), 1),
                admitted(SeedWork::Reconcile(reconcile()), 2),
                admitted(SeedWork::Tile(tile()), 3),
                admitted(SeedWork::Skip(SeedSkipReason::UnknownKind), 4),
                admitted(SeedWork::Tile(tile()), 5),
            ],
            256,
        );

        assert_eq!(
            spans(&groups),
            vec![(0, 0), (1, 1), (2, 2), (3, 5), (4, 4)],
            "reconcile closes both runs, while skip leaves the tile run open",
        );
        assert!(matches!(groups[0], SeedGroup::Tiles(_)));
        assert!(matches!(groups[1], SeedGroup::Persons(_)));
        assert!(matches!(groups[2], SeedGroup::Reconcile(_)));
        assert!(matches!(groups[3], SeedGroup::Tiles(ref run) if run.len() == 2));
        assert!(matches!(groups[4], SeedGroup::Skip(_)));
    }

    /// An interleaved tile/person stream degraded to runs of one under #93822's kind-change close,
    /// which is the whole win lost. `tile()` and `person_seed()` name different persons, so the
    /// two runs cannot observe each other and both stay open.
    #[test]
    fn an_interleaved_stream_of_distinct_persons_still_forms_one_run_per_kind() {
        let groups = group_by_count(
            vec![
                admitted(SeedWork::Tile(tile()), 0),
                admitted(SeedWork::Person(person_seed(&[PERSON])), 1),
                admitted(SeedWork::Tile(tile()), 2),
                admitted(SeedWork::Person(person_seed(&[PERSON])), 3),
            ],
            256,
        );

        assert_eq!(groups.len(), 2, "one run per kind, not four runs of one");
        assert!(matches!(groups[0], SeedGroup::Tiles(ref run) if run.len() == 2));
        assert!(matches!(groups[1], SeedGroup::Persons(ref run) if run.len() == 2));
        assert_eq!(
            spans(&groups),
            vec![(0, 2), (1, 3)],
            "each kind keeps its own offset order",
        );
    }

    /// Two open runs apply in first-offset order, so a person both kinds touch would have the
    /// person seed at offset 2 applied before the tile at offset 1. Both leaves feed one composed
    /// cohort, so that reorder emits an entry and a retraction the per-seed apply never emits.
    #[test]
    fn a_person_both_kinds_touch_keeps_every_seed_in_offset_order() {
        let alice = Uuid::from_u128(11);
        let groups = group_by_count(
            vec![
                admitted(SeedWork::Person(person_seed_for(alice, &[PERSON])), 0),
                admitted(SeedWork::Tile(tile_for(alice)), 1),
                admitted(SeedWork::Person(person_seed_for(alice, &[PERSON])), 2),
            ],
            256,
        );

        assert_eq!(
            spans(&groups),
            vec![(0, 0), (1, 1), (2, 2)],
            "no group's span crosses another's",
        );
    }

    /// A run that starts above the other kind's run for its persons applies after it, so it
    /// batches.
    #[test]
    fn a_run_starting_above_the_other_kinds_run_batches_its_shared_persons() {
        let alice = Uuid::from_u128(11);
        let bob = Uuid::from_u128(12);
        let groups = group_by_count(
            vec![
                admitted(SeedWork::Person(person_seed_for(alice, &[PERSON])), 0),
                admitted(SeedWork::Person(person_seed_for(bob, &[PERSON])), 1),
                admitted(SeedWork::Tile(tile_for(bob)), 2),
                admitted(SeedWork::Tile(tile_for(alice)), 3),
            ],
            256,
        );

        assert_eq!(
            spans(&groups),
            vec![(0, 1), (2, 3)],
            "the tile run starts above the person run, so nothing closes",
        );
    }

    /// A closed run still applies at its own first offset, so forgetting its persons on close would
    /// let the tile at 3 join the run at 0 and apply before the person seeds at 1 and 2.
    #[test]
    fn a_person_admitted_by_a_closed_run_of_the_other_kind_still_orders_the_seed() {
        let alice = Uuid::from_u128(11);
        let bob = Uuid::from_u128(12);
        let groups = group_by_count(
            vec![
                admitted(SeedWork::Tile(tile_for(bob)), 0),
                admitted(SeedWork::Person(person_seed_for(alice, &[PERSON])), 1),
                admitted(SeedWork::Person(person_seed_for(alice, &[PERSON])), 2),
                admitted(SeedWork::Tile(tile_for(alice)), 3),
            ],
            2,
        );

        assert_eq!(
            spans(&groups),
            vec![(0, 0), (1, 2), (3, 3)],
            "the tile starts above the closed person run",
        );
    }

    #[test]
    fn a_run_longer_than_the_cap_splits_into_capped_groups() {
        assert_eq!(
            spans(&group_by_count(tiles(0..7), 3)),
            vec![(0, 2), (3, 5), (6, 6)]
        );
    }

    /// The zero-cost hatch: `COHORT_SEED_APPLY_BATCH_MAX=1` must reproduce the per-seed apply.
    #[test]
    fn a_cap_of_one_yields_one_group_per_seed() {
        assert_eq!(
            spans(&group_by_count(tiles(0..3), 1)),
            vec![(0, 0), (1, 1), (2, 2)]
        );
    }

    #[test]
    fn an_empty_batch_yields_no_groups() {
        assert!(group_by_count(Vec::new(), 256).is_empty());
    }

    /// The budget bounds what a run expands to, so it has to be checked before a seed is admitted:
    /// applied after, every run would overshoot by one seed's whole leaf set.
    #[test]
    fn a_run_closes_before_the_seed_that_would_exceed_the_row_budget() {
        let groups = group_seeds(tiles(0..5), budget(256, 10), |_| 4);

        assert_eq!(spans(&groups), vec![(0, 1), (2, 3), (4, 4)]);
    }

    /// A seed heavier than the whole budget can never fit, so an empty run must still admit it:
    /// refusing would leave the seed neither marked nor held, and the partition wedged behind it.
    #[test]
    fn a_seed_heavier_than_the_whole_budget_still_forms_a_run_of_one() {
        let groups = group_seeds(tiles(0..3), budget(256, 10), |_| 1000);

        assert_eq!(spans(&groups), vec![(0, 0), (1, 1), (2, 2)]);
    }

    /// A budget on one kind must not close the other kind's open run: it would undo the
    /// interleaving win without bounding anything the other run reads.
    #[test]
    fn a_budget_closes_only_the_run_it_bounds() {
        let groups = group_seeds(
            vec![
                admitted(SeedWork::Person(person_seed(&[PERSON])), 0),
                admitted(SeedWork::Tile(tile()), 1),
                admitted(SeedWork::Tile(tile()), 2),
                admitted(SeedWork::Person(person_seed(&[PERSON])), 3),
            ],
            budget(2, usize::MAX),
            |_| 1,
        );

        assert!(matches!(groups[0], SeedGroup::Persons(ref run) if run.len() == 2));
        assert!(matches!(groups[1], SeedGroup::Tiles(ref run) if run.len() == 2));
        assert_eq!(
            spans(&groups),
            vec![(0, 3), (1, 2)],
            "groups are emitted in first-offset order even when the budget closes one kind first",
        );
    }

    /// Callers apply groups in the order they come out, so the order has to be the offset order the
    /// consumer delivered in — not the order the two open runs happened to close in.
    #[test]
    fn groups_are_emitted_in_first_offset_order() {
        let groups = group_seeds(
            vec![
                admitted(SeedWork::Person(person_seed(&[PERSON])), 0),
                admitted(SeedWork::Tile(tile()), 1),
                admitted(SeedWork::Person(person_seed(&[PERSON])), 2),
                admitted(SeedWork::Reconcile(reconcile()), 3),
                admitted(SeedWork::Tile(tile()), 4),
            ],
            budget(256, usize::MAX),
            |_| 1,
        );

        let firsts: Vec<i64> = spans(&groups).into_iter().map(|(first, _)| first).collect();
        let mut sorted = firsts.clone();
        sorted.sort_unstable();
        assert_eq!(
            firsts, sorted,
            "groups came out out of offset order: {firsts:?}"
        );
    }

    /// The weight is the run's footprint, not its leaf count: a leaf backing many cohorts costs a
    /// register read, a recompute, and an emission per cohort, and that is what the budget has to
    /// bound for a run's memory and output to stay finite.
    #[test]
    fn row_weight_counts_stage1_rows_plus_backed_registers_and_floors_at_one() {
        let behavioral = |condition_hash: &str, window_days: i64| {
            json!({
                "type": "behavioral", "value": "performed_event", "key": "$pageview",
                "time_value": window_days, "time_interval": "day",
                "conditionHash": condition_hash,
                "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
            })
        };
        let person_property = json!({
            "type": "person", "key": "email", "value": "a@b.com", "operator": "exact",
            "conditionHash": PERSON,
            "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        });
        let cohort =
            |leaves: Vec<Value>| json!({ "properties": { "type": "AND", "values": leaves } });
        let mut builder = TeamFiltersBuilder::default();
        // Two windows over one condition hash: two leaves. Three single-leaf cohorts share the
        // 7-day one, a fourth keys on the 30-day one, and a composed cohort walks the 7-day one
        // together with the person leaf.
        for id in 1..=3 {
            builder
                .add_cohort(CohortId(id), TEAM, &cohort(vec![behavioral(BEHAVIORAL, 7)]))
                .unwrap();
        }
        builder
            .add_cohort(CohortId(4), TEAM, &cohort(vec![behavioral(BEHAVIORAL, 30)]))
            .unwrap();
        builder
            .add_cohort(CohortId(5), TEAM, &cohort(vec![person_property.clone()]))
            .unwrap();
        builder
            .add_cohort(
                CohortId(6),
                TEAM,
                &cohort(vec![behavioral(BEHAVIORAL, 7), person_property]),
            )
            .unwrap();
        let catalog = FilterCatalog::from_teams([(TEAM, builder.freeze(chrono_tz::UTC))]);

        assert_eq!(
            row_weight(&catalog, &SeedWork::Tile(tile_with(TEAM, BEHAVIORAL))),
            (1 + 3 + 1) + (1 + 1),
            "the 7-day leaf is its row, three single-leaf registers and one composed; the 30-day leaf its row and one register",
        );
        assert_eq!(
            row_weight(
                &catalog,
                &SeedWork::Tile(tile_with(TEAM, "no_such_cond0000"))
            ),
            1,
            "a hash the catalog no longer resolves still weighs one",
        );
        assert_eq!(
            row_weight(&catalog, &SeedWork::Tile(tile_with(TeamId(99), BEHAVIORAL))),
            1,
            "an unknown team still weighs one",
        );
        assert_eq!(
            row_weight(&catalog, &SeedWork::Person(person_seed(&[PERSON]))),
            1 + (1 + 1 + 1),
            "a person seed is one record, then its leaf and the two registers that leaf backs",
        );
        assert_eq!(
            row_weight(
                &catalog,
                &SeedWork::Person(person_seed(&[BEHAVIORAL, PERSON])),
            ),
            1 + (1 + 3 + 1) + (1 + 1) + (1 + 1 + 1),
            "every hash the seed evaluated counts, whatever the fold later drops",
        );
        assert_eq!(row_weight(&catalog, &SeedWork::Reconcile(reconcile())), 0);
        assert_eq!(
            row_weight(&catalog, &SeedWork::Skip(SeedSkipReason::UnknownKind)),
            0,
        );
    }

    /// The fold keeps one entry per evaluated hash, not per register, and a person seed carries up
    /// to 1,024 hashes. Charging only registers would let a run of seeds whose leaves can emit
    /// nothing measure its seed count while retaining hash-count entries.
    #[test]
    fn a_leaf_that_backs_no_register_still_bounds_the_run() {
        // A ref-bearing cohort is excluded from composition while cascade is off, so its person
        // leaf is indexed but keys neither register map.
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TEAM,
                &json!({ "properties": { "type": "AND", "values": [
                    {
                        "type": "person", "key": "email", "value": "a@b.com", "operator": "exact",
                        "conditionHash": PERSON,
                        "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
                    },
                    { "type": "cohort", "value": 99, "negation": false },
                ] } }),
            )
            .unwrap();
        let catalog = FilterCatalog::from_teams([(TEAM, builder.freeze(chrono_tz::UTC))]);

        assert_eq!(
            row_weight(&catalog, &SeedWork::Person(person_seed(&[PERSON]))),
            1 + 1,
            "the record and the leaf the fold retains, with no register behind it",
        );

        let seeds: Vec<Admitted<SeedWork>> = (0..4)
            .map(|offset| admitted(SeedWork::Person(person_seed(&[PERSON])), offset))
            .collect();
        let groups = group_seeds(seeds, budget(256, 4), |work| row_weight(&catalog, work));

        assert_eq!(
            spans(&groups),
            vec![(0, 1), (2, 3)],
            "the row ceiling still splits a run that backs no register at all",
        );
    }

    #[test]
    fn an_empty_run_has_no_span_so_it_cannot_become_a_group() {
        assert!(SeedRun::<SeedTile>::new(Vec::new()).is_none());
    }
}
