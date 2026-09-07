//! The seed-tile apply path: a pure, clock-free core ([`merge_tile_into_leaf`]) that mirrors the
//! live fold minus dedup (slide-before-evaluate, max-merge of the tile's absolute count,
//! structural-equality `Unchanged` — the whole of tile idempotency), and [`TileHead`], which routes
//! a run of tiles, reads every leaf they can touch in one batch, and folds them into an overlay.
//!
//! [`seed_apply`](crate::workers::seed_apply) owns everything after the fold: register diff →
//! stage-1 commit → schedule → recompute → produce → stage-2 commit → mark.
//! Before an emission, this path records the retired membership with stage 1 and advances it only
//! after the produce acks. A failed produce is therefore re-derived while replay still folds the
//! leaf. If the leaf expires before replay and the fold drops it, this repair no longer applies;
//! eviction and reconcile remain its recovery paths. Composed bits come from
//! [`recompute_stage2`](crate::workers::stage2_path::recompute_stage2); single-leaf ones from
//! [`diff_single_leaf_registers`](crate::workers::stage2_path::diff_single_leaf_registers), which
//! is why `Unchanged` leaves still take part. The replay mints no transition, so the persisted
//! register is the only record of what downstream was told. Store and produce failures hold the
//! run's first seed offset.

use std::collections::{BTreeMap, HashMap};
use std::num::NonZeroU32;

use chrono_tz::Tz;
use metrics::counter;
use tracing::warn;
use uuid::Uuid;

use cohort_core::seed::{PersonSeed, RunId, SeedTile};

use crate::filters::reverse_index::{LeafStateMeta, TeamFilters};
use crate::filters::TeamId;
use crate::merge::tombstone_redirect::{Resolution, MAX_CROSS_PARTITION_REDIRECT_HOPS};
use crate::observability::metrics::{SEED_REKEY_HOP_CAPPED_TOTAL, STAGE1_STATE_DECODE_ERROR};
use crate::stage1::bucket_tz::{
    daily_bucket_len, day_idx_in_tz, start_of_day_ms_in_tz, window_start_for_now, DayIdx,
};
use crate::stage1::compressed_history;
use crate::stage1::daily::{daily_eviction_deadline, slide_window_forward};
use crate::stage1::key::LeafStateKey;
use crate::stage1::pick_state::{EvictionWindow, PredicateOp};
use crate::stage1::predicate::{compressed_predicate, daily_predicate, predicate};
use crate::stage1::state::{Stage1State, StateVariant, StatefulRecord};
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::stage2::leaf_membership;
use crate::store::{Behavioral, BehavioralKey, PersonPrefix, ReadLane, StagedBatch};
use crate::workers::seed_apply::{
    record_stage1_transition, resolve_run_persons, ApplyDeps, ApplyStage, Decoded, Folded, Outcome,
    Overlay, ReKeys, RunStamp, SeedHead, SeedHold, StageClock, Tally, TouchedPersons,
};
use crate::workers::seed_run::{Admitted, OffsetSpan, SeedKind, SeedRun};
use crate::workers::stage2_path::FoldedLeaf;

/// A seed kind that can be re-keyed onto a merge survivor.
pub(crate) trait RekeyableSeed: Sized {
    fn person_id(&self) -> Uuid;
    fn rekeyed_to(&self, survivor: Uuid, cap: u8) -> Option<Self>;
}

impl RekeyableSeed for SeedTile {
    fn person_id(&self) -> Uuid {
        SeedTile::person_id(self)
    }

    fn rekeyed_to(&self, survivor: Uuid, cap: u8) -> Option<Self> {
        SeedTile::rekeyed_to(self, survivor, cap)
    }
}

impl RekeyableSeed for PersonSeed {
    fn person_id(&self) -> Uuid {
        PersonSeed::person_id(self)
    }

    fn rekeyed_to(&self, survivor: Uuid, cap: u8) -> Option<Self> {
        PersonSeed::rekeyed_to(self, survivor, cap)
    }
}

/// Where a seed applies after tombstone resolution; an exhausted hop budget is unrepresentable
/// as a re-produce, forcing the degraded inline arm.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum SeedRoute<T> {
    ApplyLocal { person: Uuid },
    ReProduce { seed: T },
    CapExhausted { person: Uuid },
}

/// Total routing of a seed through its tombstone [`Resolution`].
pub(crate) fn route_seed<T: RekeyableSeed>(
    seed: &T,
    resolution: Resolution,
    cap: u8,
) -> SeedRoute<T> {
    match resolution {
        Resolution::NotMerged => SeedRoute::ApplyLocal {
            person: seed.person_id(),
        },
        Resolution::Inline { final_person, .. } => SeedRoute::ApplyLocal {
            person: final_person,
        },
        Resolution::CrossPartition { target_person, .. } => {
            match seed.rekeyed_to(target_person, cap) {
                Some(rekeyed) => SeedRoute::ReProduce { seed: rekeyed },
                None => SeedRoute::CapExhausted {
                    person: target_person,
                },
            }
        }
    }
}

/// Why a tile's apply to one leaf was dropped without a write. Each arm is a metric label.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum SeedDropReason {
    /// The leaf's `explicit_datetime` range excludes the tile's day (the bounds are not in the
    /// bytecode, so the reverse index over-delivers).
    ExplicitRangeExcludesDay,
    /// Below the window after the slide to "now"; applying would resurrect an expired record.
    DayBelowWindow,
    /// The Single analog of the slide-drop: the recomputed deadline is already due.
    WindowElapsed,
    /// The stored record or leaf variant does not match what the tile can merge into.
    VariantMismatch,
    /// The catalog meta lacks the window/op the variant requires.
    MetaIncomplete,
    /// A sub-day window: a whole-day tile cannot represent it, so hourly leaves are not seeded.
    SubDayWindow,
}

impl SeedDropReason {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::ExplicitRangeExcludesDay => "explicit_range_excludes_day",
            Self::DayBelowWindow => "day_below_window",
            Self::WindowElapsed => "window_elapsed",
            Self::VariantMismatch => "variant_mismatch",
            Self::MetaIncomplete => "meta_incomplete",
            Self::SubDayWindow => "sub_day_window",
        }
    }
}

/// One leaf's merge outcome; `Unchanged` carries the post-merge record so idempotent seed delivery
/// can still repair the single-leaf membership register.
#[must_use]
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum LeafMergeOutcome {
    Merged {
        record: StatefulRecord,
        transition: Option<LeafTransition>,
        /// The recomputed eviction deadline ([`i64::MAX`] = permanent, never scheduled).
        deadline_ms: i64,
    },
    Unchanged {
        record: StatefulRecord,
    },
    Dropped(SeedDropReason),
}

/// Identity of the leaf being merged into, so the pure core can mint transitions.
#[derive(Debug, Clone, Copy)]
pub(crate) struct LeafIdentity {
    pub team_id: TeamId,
    pub lsk: LeafStateKey,
    pub person_id: Uuid,
    pub condition_hash: [u8; 16],
}

impl LeafIdentity {
    fn transition(&self, kind: TransitionKind) -> LeafTransition {
        LeafTransition {
            team_id: self.team_id,
            leaf_state_key: self.lsk,
            person_id: self.person_id,
            condition_hash: self.condition_hash,
            kind,
        }
    }
}

/// Merge one day-tile into one leaf's state. Total: every mismatch is a counted drop, never a
/// panic.
#[allow(clippy::too_many_arguments)]
pub(crate) fn merge_tile_into_leaf(
    meta: &LeafStateMeta,
    tz: Tz,
    identity: LeafIdentity,
    tile_day: DayIdx,
    count: NonZeroU32,
    prev: Option<&StatefulRecord>,
    now_day: DayIdx,
    now_ms: i64,
) -> LeafMergeOutcome {
    match meta.variant {
        StateVariant::BehavioralSingle => {
            merge_single(meta.window, tz, identity, tile_day, prev, now_ms)
        }
        StateVariant::BehavioralDailyBuckets => merge_daily(
            meta.window_days,
            meta.predicate_op,
            tz,
            identity,
            tile_day,
            count,
            prev,
            now_day,
        ),
        StateVariant::BehavioralCompressedHistory => merge_compressed(
            meta.window_days,
            meta.predicate_op,
            tz,
            identity,
            tile_day,
            count,
            prev,
            now_day,
        ),
        StateVariant::PersonProperty => LeafMergeOutcome::Dropped(SeedDropReason::VariantMismatch),
    }
}

/// Last millisecond of `tile_day` in the team tz — for calendar-floored (`RelativeDays`) windows
/// exactly equivalent to any same-day live instant.
fn end_of_day_ms(tile_day: DayIdx, tz: Tz) -> i64 {
    start_of_day_ms_in_tz(tile_day.saturating_add(1), tz).saturating_sub(1)
}

fn merge_single(
    window: Option<EvictionWindow>,
    tz: Tz,
    identity: LeafIdentity,
    tile_day: DayIdx,
    prev: Option<&StatefulRecord>,
    now_ms: i64,
) -> LeafMergeOutcome {
    let Some(window) = window else {
        return LeafMergeOutcome::Dropped(SeedDropReason::MetaIncomplete);
    };
    match window {
        EvictionWindow::RelativeSeconds { .. } => {
            return LeafMergeOutcome::Dropped(SeedDropReason::SubDayWindow)
        }
        EvictionWindow::Explicit { from_day, to_day } => {
            // Day-granularity, inclusive — mirrors the event path's explicit-range check.
            let before_from = from_day.is_some_and(|from| tile_day < from);
            let after_to = to_day.is_some_and(|to| tile_day > to);
            if before_from || after_to {
                return LeafMergeOutcome::Dropped(SeedDropReason::ExplicitRangeExcludesDay);
            }
        }
        EvictionWindow::RelativeDays { .. } => {}
    }

    let (prev_last, predicate_before, applied, redirect) = match prev {
        None => (i64::MIN, false, Default::default(), Default::default()),
        Some(record) => {
            let before = predicate(&record.state);
            match &record.state {
                Stage1State::BehavioralSingle {
                    last_event_at_ms, ..
                } => (
                    *last_event_at_ms,
                    before,
                    record.applied_offsets.clone(),
                    record.redirect_dedup.clone(),
                ),
                _ => return LeafMergeOutcome::Dropped(SeedDropReason::VariantMismatch),
            }
        }
    };

    let last_event_at_ms = prev_last.max(end_of_day_ms(tile_day, tz));
    let earliest_eviction_at_ms = window.earliest_eviction_at_ms(last_event_at_ms, tz);
    if earliest_eviction_at_ms <= now_ms {
        return LeafMergeOutcome::Dropped(SeedDropReason::WindowElapsed);
    }

    let record = StatefulRecord {
        state: Stage1State::BehavioralSingle {
            has_match: true,
            last_event_at_ms,
            earliest_eviction_at_ms,
        },
        applied_offsets: applied,
        redirect_dedup: redirect,
    };
    finish(
        identity,
        prev.map(|record| &record.state),
        record,
        predicate_before,
        true,
        earliest_eviction_at_ms,
    )
}

#[allow(clippy::too_many_arguments)]
fn merge_daily(
    window_days: Option<u32>,
    op: Option<PredicateOp>,
    tz: Tz,
    identity: LeafIdentity,
    tile_day: DayIdx,
    count: NonZeroU32,
    prev: Option<&StatefulRecord>,
    now_day: DayIdx,
) -> LeafMergeOutcome {
    let (Some(window_days), Some(op)) = (window_days, op) else {
        return LeafMergeOutcome::Dropped(SeedDropReason::MetaIncomplete);
    };
    let len = daily_bucket_len(window_days);

    let (prior, predicate_before, applied, redirect) = match prev {
        None => (None, false, Default::default(), Default::default()),
        Some(record) => match &record.state {
            Stage1State::BehavioralDailyBuckets {
                buckets,
                window_start_day,
                last_event_at_ms,
                ..
            } => {
                let before = daily_predicate(buckets, op);
                (
                    // Cloned because the merge mutates it; the prior state itself stays borrowed
                    // for the `Unchanged` compare.
                    Some((buckets.clone(), *window_start_day, *last_event_at_ms)),
                    before,
                    record.applied_offsets.clone(),
                    record.redirect_dedup.clone(),
                )
            }
            _ => return LeafMergeOutcome::Dropped(SeedDropReason::VariantMismatch),
        },
    };

    // A future-dated tile extends the target like a client-skewed live event would, keeping
    // apply order commutative.
    let target_now_day = now_day.max(tile_day);
    let (mut buckets, mut window_start_day, prev_last) = match prior {
        Some((buckets, start, last)) if buckets.len() == len => (buckets, start, last),
        Some(_) => return LeafMergeOutcome::Dropped(SeedDropReason::VariantMismatch),
        None => (
            vec![0; len],
            window_start_for_now(target_now_day, window_days),
            i64::MIN,
        ),
    };
    slide_window_forward(
        &mut buckets,
        &mut window_start_day,
        window_days,
        target_now_day,
    );

    if tile_day < window_start_day {
        return LeafMergeOutcome::Dropped(SeedDropReason::DayBelowWindow);
    }
    let idx = (tile_day - window_start_day) as usize;
    let Some(bucket) = buckets.get_mut(idx) else {
        // Unreachable: tile_day ≤ target_now_day = window_start + window_days ⇒ idx < len.
        return LeafMergeOutcome::Dropped(SeedDropReason::DayBelowWindow);
    };
    *bucket = (*bucket).max(count.get());

    let last_event_at_ms = prev_last.max(end_of_day_ms(tile_day, tz));
    let earliest_eviction_at_ms =
        daily_eviction_deadline(&buckets, window_start_day, window_days, tz);
    let predicate_after = daily_predicate(&buckets, op);

    let record = StatefulRecord {
        state: Stage1State::BehavioralDailyBuckets {
            buckets,
            window_start_day,
            last_event_at_ms,
            earliest_eviction_at_ms,
        },
        applied_offsets: applied,
        redirect_dedup: redirect,
    };
    finish(
        identity,
        prev.map(|record| &record.state),
        record,
        predicate_before,
        predicate_after,
        earliest_eviction_at_ms,
    )
}

#[allow(clippy::too_many_arguments)]
fn merge_compressed(
    window_days: Option<u32>,
    op: Option<PredicateOp>,
    tz: Tz,
    identity: LeafIdentity,
    tile_day: DayIdx,
    count: NonZeroU32,
    prev: Option<&StatefulRecord>,
    now_day: DayIdx,
) -> LeafMergeOutcome {
    let (Some(window_days), Some(op)) = (window_days, op) else {
        return LeafMergeOutcome::Dropped(SeedDropReason::MetaIncomplete);
    };

    let (prior, predicate_before, applied, redirect) = match prev {
        None => (None, false, Default::default(), Default::default()),
        Some(record) => match &record.state {
            Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day,
                last_event_at_ms,
                ..
            } => {
                let before = compressed_predicate(entries, op);
                (
                    // Cloned because the merge mutates it; the prior state itself stays borrowed
                    // for the `Unchanged` compare.
                    Some((entries.clone(), *window_start_day, *last_event_at_ms)),
                    before,
                    record.applied_offsets.clone(),
                    record.redirect_dedup.clone(),
                )
            }
            _ => return LeafMergeOutcome::Dropped(SeedDropReason::VariantMismatch),
        },
    };

    let target_now_day = now_day.max(tile_day);
    let (mut entries, mut window_start_day, prev_last) = match prior {
        Some((entries, start, last)) => (entries, start, last),
        None => (
            Vec::new(),
            window_start_for_now(target_now_day, window_days),
            i64::MIN,
        ),
    };
    compressed_history::slide_window_forward(
        &mut entries,
        &mut window_start_day,
        window_days,
        target_now_day,
    );

    if tile_day < window_start_day {
        return LeafMergeOutcome::Dropped(SeedDropReason::DayBelowWindow);
    }
    compressed_history::merge_day_count(&mut entries, tile_day, count.get());

    let last_event_at_ms = prev_last.max(end_of_day_ms(tile_day, tz));
    let earliest_eviction_at_ms =
        compressed_history::compressed_eviction_deadline(&entries, window_days, tz);
    let predicate_after = compressed_predicate(&entries, op);

    let record = StatefulRecord {
        state: Stage1State::BehavioralCompressedHistory {
            entries,
            window_start_day,
            last_event_at_ms,
            earliest_eviction_at_ms,
        },
        applied_offsets: applied,
        redirect_dedup: redirect,
    };
    finish(
        identity,
        prev.map(|record| &record.state),
        record,
        predicate_before,
        predicate_after,
        earliest_eviction_at_ms,
    )
}

/// `Unchanged` detection + transition minting shared by all three variants.
fn finish(
    identity: LeafIdentity,
    prev_state: Option<&Stage1State>,
    record: StatefulRecord,
    predicate_before: bool,
    predicate_after: bool,
    deadline_ms: i64,
) -> LeafMergeOutcome {
    if prev_state == Some(&record.state) {
        return LeafMergeOutcome::Unchanged { record };
    }
    let kind = match (predicate_before, predicate_after) {
        (false, true) => Some(TransitionKind::Entered),
        (true, false) => Some(TransitionKind::Left),
        _ => None,
    };
    LeafMergeOutcome::Merged {
        record,
        transition: kind.map(|kind| identity.transition(kind)),
        deadline_ms,
    }
}

/// The tile head: route each seed, read every leaf it can touch in one batch, and fold the run
/// into an overlay. Everything after this is [`seed_apply`](crate::workers::seed_apply)'s.
pub(crate) struct TileHead;

impl SeedHead for TileHead {
    type Seed = SeedTile;
    const KIND: SeedKind = SeedKind::Tile;

    async fn fold(
        deps: ApplyDeps<'_>,
        run: SeedRun<SeedTile>,
        stamp: &RunStamp,
        clock: &mut StageClock,
    ) -> Result<Folded, SeedHold> {
        let span = run.span();
        let mut tally = Tally::default();

        let Routed { local, re_keys } = route_tiles(deps, run, &mut tally).await?;
        clock.mark(ApplyStage::Resolve);

        let overlay = read_leaf_state(deps, &local).await?;
        clock.mark(ApplyStage::Read);

        let folded = fold_tiles(span, local, re_keys, overlay, stamp, tally);
        clock.mark(ApplyStage::Fold);
        Ok(folded)
    }
}

/// One tile that applies on this partition, with everything its fold needs already resolved.
struct LocalTile<'a> {
    tile: SeedTile,
    person: Uuid,
    filters: &'a TeamFilters,
    /// The leaves this tile's condition reaches. Never empty: an empty set is a counted drop.
    lsks: &'a [LeafStateKey],
    prefix: PersonPrefix,
}

struct Routed<'a> {
    local: Vec<LocalTile<'a>>,
    re_keys: Vec<SeedTile>,
}

/// Resolve every distinct person's tombstone chain in one batched read, then split the run into
/// what applies here and what hands off.
///
/// A read failure is fail-stop: a tile mis-applied to a merged-away person is durable state
/// reconcile cannot retract, so a missing verdict holds the run rather than reading as not-merged.
async fn route_tiles<'a>(
    deps: ApplyDeps<'a>,
    run: SeedRun<SeedTile>,
    tally: &mut Tally,
) -> Result<Routed<'a>, SeedHold> {
    let mut placed: Vec<(SeedTile, &TeamFilters)> = Vec::with_capacity(run.len());
    for Admitted { work: tile, .. } in run.into_items() {
        let Some(filters) = deps.team(tile.team_id()) else {
            tally.add(Outcome::TileDropped("team_absent"));
            continue;
        };
        placed.push((tile, filters));
    }

    let persons: Vec<(TeamId, Uuid)> = placed
        .iter()
        .map(|(tile, _)| (tile.team_id(), tile.person_id()))
        .collect();
    let resolved = resolve_run_persons(deps, persons).await?;

    let mut local = Vec::with_capacity(placed.len());
    let mut re_keys = Vec::new();
    for (tile, filters) in placed {
        let resolution = resolved[&(tile.team_id(), tile.person_id())];
        let person = match route_seed(&tile, resolution, MAX_CROSS_PARTITION_REDIRECT_HOPS) {
            SeedRoute::ApplyLocal { person } => person,
            SeedRoute::ReProduce { seed: rekeyed } => {
                tally.add(Outcome::ReKeyed(SeedKind::Tile));
                re_keys.push(rekeyed);
                continue;
            }
            SeedRoute::CapExhausted { person } => {
                // On the attempt, with the warning: a run that a later hold keeps from settling
                // must not hide the anomaly.
                counter!(SEED_REKEY_HOP_CAPPED_TOTAL).increment(1);
                // Same degrade as the event path: orphaned-but-bounded state (the survivor's live
                // path never reads this slice) that ages out via eviction, preferred over a silent
                // tile loss.
                warn!(
                    partition_id = deps.partition_id,
                    team_id = tile.team_id().0,
                    %person,
                    hops = tile.redirect_hops(),
                    "seed redirect hop cap hit (corrupt tombstone cycle?); applying inline at the best-known target",
                );
                person
            }
        };
        let lsks: &[LeafStateKey] = filters
            .by_condition_to_lsk
            .get(&tile.condition_hash().as_bytes())
            .map_or(&[], Vec::as_slice);
        if lsks.is_empty() {
            // Expected for a stale/edited cohort: the hash no longer resolves.
            tally.add(Outcome::TileDropped("no_referencing_leaves"));
            continue;
        }
        let prefix = PersonPrefix::new(deps.partition_id, tile.team_id().0 as u64, person);
        local.push(LocalTile {
            tile,
            person,
            filters,
            lsks,
            prefix,
        });
    }
    Ok(Routed { local, re_keys })
}

/// One `multi_get` over every leaf the run can touch, on the maintenance lane so backfill never
/// contends with live event reads. A row that does not decode is counted here, at the read: a run
/// that a later hold keeps from settling must not hide it.
async fn read_leaf_state(
    deps: ApplyDeps<'_>,
    local: &[LocalTile<'_>],
) -> Result<Overlay<BehavioralKey, StatefulRecord>, SeedHold> {
    let mut keys: Vec<BehavioralKey> = local
        .iter()
        .flat_map(|tile| tile.lsks.iter().map(|&lsk| tile.prefix.behavioral_key(lsk)))
        .collect();
    keys.sort_unstable();
    keys.dedup();

    let values = deps
        .handle
        .multi_get_behavioral(keys.clone(), ReadLane::Maintenance)
        .await
        .map_err(SeedHold::store(ApplyStage::Read))?;
    let overlay =
        Overlay::from_read(
            ApplyStage::Read,
            keys,
            values,
            |bytes| match StatefulRecord::decode(bytes) {
                Ok(record) => Decoded::Value(record),
                Err(_) => Decoded::Corrupt,
            },
        )?;
    let corrupt = overlay.prior_corrupt_rows();
    if corrupt > 0 {
        counter!(STAGE1_STATE_DECODE_ERROR).increment(corrupt as u64);
    }
    Ok(overlay)
}

/// What the run left on one leaf, carried from the fold to the emit.
struct LeafTouch<'a> {
    team_id: TeamId,
    filters: &'a TeamFilters,
    meta: &'a LeafStateMeta,
    /// The run of the last seed that touched this leaf; stamped on the changes it emits.
    run_id: RunId,
    /// The last merge's deadline. [`i64::MAX`] = permanent, never scheduled.
    deadline_ms: i64,
}

/// Fold every local tile into the overlay in offset order, then read the run's durable intent off
/// the touched slots.
fn fold_tiles(
    span: OffsetSpan,
    local: Vec<LocalTile<'_>>,
    re_keys: Vec<SeedTile>,
    mut overlay: Overlay<BehavioralKey, StatefulRecord>,
    stamp: &RunStamp,
    mut tally: Tally,
) -> Folded {
    // Once per team: a run can span teams in different time zones.
    let mut now_days: HashMap<TeamId, DayIdx> = HashMap::new();
    let mut touches: BTreeMap<BehavioralKey, LeafTouch<'_>> = BTreeMap::new();
    let mut recompose = TouchedPersons::default();

    for tile in &local {
        let team_id = tile.tile.team_id();
        let now_day = *now_days
            .entry(team_id)
            .or_insert_with(|| day_idx_in_tz(stamp.now_ms, tile.filters.timezone));
        let count = tile.tile.count_nonzero();
        for &lsk in tile.lsks {
            let Some(meta) = tile.filters.by_lsk.get(&lsk) else {
                tally.add(Outcome::TileDropped(
                    SeedDropReason::MetaIncomplete.as_str(),
                ));
                continue;
            };
            let key = tile.prefix.behavioral_key(lsk);
            let slot = overlay
                .slot_mut(&key)
                .expect("the read pass keyed a slot for every leaf this run can touch");
            if slot.prior_corrupt() {
                tally.add(Outcome::TileDropped("corrupt_state"));
                continue;
            }
            let identity = LeafIdentity {
                team_id,
                lsk,
                person_id: tile.person,
                condition_hash: tile.tile.condition_hash().as_bytes(),
            };
            let outcome = merge_tile_into_leaf(
                meta,
                tile.filters.timezone,
                identity,
                tile.tile.day_idx(),
                count,
                slot.current(),
                now_day,
                stamp.now_ms,
            );
            let deadline_ms = match outcome {
                LeafMergeOutcome::Merged {
                    record,
                    deadline_ms,
                    ..
                } => {
                    tally.add(Outcome::TileApplied(record.state.variant().as_str()));
                    slot.advance(record);
                    deadline_ms
                }
                LeafMergeOutcome::Unchanged { .. } => {
                    tally.add(Outcome::TileUnchanged(meta.variant.as_str()));
                    i64::MAX
                }
                LeafMergeOutcome::Dropped(reason) => {
                    tally.add(Outcome::TileDropped(reason.as_str()));
                    continue;
                }
            };
            let touch = touches.entry(key).or_insert(LeafTouch {
                team_id,
                filters: tile.filters,
                meta,
                run_id: tile.tile.run_id(),
                deadline_ms,
            });
            touch.run_id = tile.tile.run_id();
            if deadline_ms != i64::MAX {
                touch.deadline_ms = deadline_ms;
            }
            // Merged and Unchanged alike, so a crash between the two commits self-heals on replay:
            // the replayed run mints no transition, but the leaf's folded truth still diffs against
            // what downstream was told. Here, in offset order, so the person's provenance is the
            // last seed that touched them rather than the last leaf in key order.
            recompose.touch(team_id, tile.person, tile.tile.run_id(), lsk);
        }
    }

    let mut records = StagedBatch::default();
    let mut leaves: BTreeMap<TeamId, Vec<FoldedLeaf>> = BTreeMap::new();
    let mut schedules = Vec::new();
    for (key, touch) in &touches {
        let slot = overlay
            .slot(key)
            .expect("every touch came from a slot the read pass keyed");
        let person_id = key.prefix.person_id;
        let in_cohort = leaf_membership(slot.current().map(|record| &record.state), touch.meta);
        // Net against the run-start read, not against the last seed: a run that enters and then
        // leaves the same leaf told downstream nothing.
        let minted_transition =
            leaf_membership(slot.before().map(|record| &record.state), touch.meta) != in_cohort;
        leaves.entry(touch.team_id).or_default().push(FoldedLeaf {
            leaf_state_key: key.lsk,
            person_id,
            in_cohort,
            minted_transition,
            run_id: touch.run_id,
        });
        if let Some(record) = slot.advanced() {
            records.put::<Behavioral>(key, &record.encode());
            if touch.deadline_ms != i64::MAX {
                schedules.push((*key, touch.deadline_ms));
            }
        }
        if minted_transition {
            let kind = if in_cohort {
                TransitionKind::Entered
            } else {
                TransitionKind::Left
            };
            let transition = LeafTransition {
                team_id: touch.team_id,
                leaf_state_key: key.lsk,
                person_id,
                condition_hash: touch.meta.condition_hash,
                kind,
            };
            // Stage-1 flips, not emissions: the register diff owns what downstream is told.
            record_stage1_transition(&mut tally, touch.filters, &transition);
        }
    }

    Folded {
        span,
        records,
        leaves,
        recompose,
        schedules,
        re_keys: ReKeys::Tiles(re_keys),
        tally,
    }
}

#[cfg(test)]
// Tests seed and assert against `CohortStore` directly, the sanctioned direct-store surface.
#[allow(clippy::disallowed_methods)]
mod tests {
    use std::collections::BTreeSet;
    use std::sync::Arc;

    use chrono_tz::America::New_York;
    use chrono_tz::Etc::GMTPlus12;
    use chrono_tz::Pacific::Kiritimati;
    use chrono_tz::UTC;
    use proptest::prelude::*;
    use serde_json::{json, Value};
    use tempfile::TempDir;

    use cohort_core::seed::{
        BehavioralShapeHash, ClaimEpoch, ConditionHash, ReconcileScope, ReconcileTile, SChunkMs,
        SeedTile,
    };

    use crate::consumers::seeds::{SeedSkipReason, SeedWork};
    use crate::filters::manager::CatalogHandle;
    use crate::filters::{CohortId, FilterCatalog, TeamFiltersBuilder};
    use crate::merge::transfer::Tombstone;
    use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
    use crate::partitions::OffsetTracker;
    use crate::producer::{
        CaptureReconcileMarkerSink, CaptureSeedTileSink, CaptureSink, ChangeOrigin,
        CohortMembershipChange, MembershipSink, MembershipStatus,
    };
    use crate::stage1::state::AppliedOffsets;
    use crate::stage2::state::Stage2State;
    use crate::store::{
        CohortStore, OffloadConfig, OffloadMode, Stage2Key, StoreConfig, StoreHandle, TombstoneKey,
    };
    use crate::sweep::EvictionQueue;
    use crate::workers::event_path::{process_event_gated, EventNameGating};
    use crate::workers::merge_path::MergeWorkerDeps;
    use crate::workers::reconcile::ReconcileQueue;
    use crate::workers::seed_apply::handle_seed_groups;
    use crate::workers::seed_run::{group_seeds, row_weight, RunBudget, SeedOffset};

    use super::*;

    const TEAM: TeamId = TeamId(7);

    const OTHER_TEAM: TeamId = TeamId(8);
    const HASH: [u8; 16] = *b"0123456789abcdef";
    /// A fixed "now": 2026-06-15 12:00:00 UTC.
    const NOW_MS: i64 = 1_781_524_800_000;

    fn now_day() -> DayIdx {
        day_idx_in_tz(NOW_MS, UTC)
    }

    fn identity() -> LeafIdentity {
        LeafIdentity {
            team_id: TEAM,
            lsk: LeafStateKey([0xAB; 16]),
            person_id: Uuid::from_u128(0xA11CE),
            condition_hash: HASH,
        }
    }

    fn single_meta(window: EvictionWindow) -> LeafStateMeta {
        LeafStateMeta {
            variant: StateVariant::BehavioralSingle,
            condition_hash: HASH,
            window: Some(window),
            window_days: None,
            predicate_op: None,
        }
    }

    fn daily_meta(window_days: u32, op: PredicateOp) -> LeafStateMeta {
        LeafStateMeta {
            variant: StateVariant::BehavioralDailyBuckets,
            condition_hash: HASH,
            window: None,
            window_days: Some(window_days),
            predicate_op: Some(op),
        }
    }

    fn compressed_meta(window_days: u32, op: PredicateOp) -> LeafStateMeta {
        LeafStateMeta {
            variant: StateVariant::BehavioralCompressedHistory,
            condition_hash: HASH,
            window: None,
            window_days: Some(window_days),
            predicate_op: Some(op),
        }
    }

    fn count(n: u32) -> NonZeroU32 {
        NonZeroU32::new(n).unwrap()
    }

    fn merge(
        meta: &LeafStateMeta,
        tile_day: DayIdx,
        n: u32,
        prev: Option<StatefulRecord>,
    ) -> LeafMergeOutcome {
        merge_tile_into_leaf(
            meta,
            UTC,
            identity(),
            tile_day,
            count(n),
            prev.as_ref(),
            now_day(),
            NOW_MS,
        )
    }

    fn merged(outcome: LeafMergeOutcome) -> (StatefulRecord, Option<LeafTransition>, i64) {
        match outcome {
            LeafMergeOutcome::Merged {
                record,
                transition,
                deadline_ms,
            } => (record, transition, deadline_ms),
            other => panic!("expected Merged, got {other:?}"),
        }
    }

    #[test]
    fn single_tile_enters_with_the_live_paths_exact_deadline_and_replays_unchanged() {
        let meta = single_meta(EvictionWindow::RelativeDays { days: 7 });
        let (record, transition, deadline) = merged(merge(&meta, now_day(), 1, None));

        assert_eq!(
            transition.map(|t| t.kind),
            Some(TransitionKind::Entered),
            "a fresh in-window tile enters",
        );
        // The end-of-day synthetic instant yields exactly the deadline any same-day live
        // instant would (RelativeDays calendar-floors its anchor).
        assert_eq!(
            deadline,
            EvictionWindow::RelativeDays { days: 7 }.earliest_eviction_at_ms(NOW_MS, UTC),
        );

        assert!(
            matches!(
                merge(&meta, now_day(), 1, Some(record)),
                LeafMergeOutcome::Unchanged { .. }
            ),
            "re-delivery is a structural no-op",
        );
    }

    #[test]
    fn single_sub_day_window_is_never_seeded() {
        let meta = single_meta(EvictionWindow::RelativeSeconds { seconds: 3_600 });
        assert_eq!(
            merge(&meta, now_day(), 1, None),
            LeafMergeOutcome::Dropped(SeedDropReason::SubDayWindow),
        );
    }

    #[test]
    fn single_elapsed_window_drops_instead_of_flapping() {
        // A 7-day window tile 9 days old: the recomputed deadline is already due, so applying
        // would enter → sweep → left. Prev state stays untouched (total no-op).
        let meta = single_meta(EvictionWindow::RelativeDays { days: 7 });
        assert_eq!(
            merge(&meta, now_day() - 9, 1, None),
            LeafMergeOutcome::Dropped(SeedDropReason::WindowElapsed),
        );
    }

    #[test]
    fn single_explicit_bounds_gate_the_tile_day_and_hold_forever_in_range() {
        let day = now_day();
        let cases = [
            (
                Some(day - 5),
                Some(day + 5),
                day,
                true,
                "inside both bounds",
            ),
            (Some(day - 5), Some(day + 5), day - 6, false, "before from"),
            (Some(day - 5), Some(day + 5), day + 6, false, "after to"),
            (
                Some(day - 5),
                Some(day + 5),
                day - 5,
                true,
                "inclusive from",
            ),
            (Some(day - 5), Some(day + 5), day + 5, true, "inclusive to"),
            (Some(day - 5), None, day + 400, true, "open above"),
            (None, Some(day + 5), day - 400, true, "open below"),
            (None, None, day - 1_000, true, "unbounded"),
        ];
        for (from_day, to_day, tile_day, in_range, why) in cases {
            let meta = single_meta(EvictionWindow::Explicit { from_day, to_day });
            let outcome = merge(&meta, tile_day, 1, None);
            if in_range {
                let (_, transition, deadline) = merged(outcome);
                assert_eq!(
                    deadline,
                    i64::MAX,
                    "{why}: explicit membership is permanent"
                );
                assert_eq!(
                    transition.map(|t| t.kind),
                    Some(TransitionKind::Entered),
                    "{why}"
                );
            } else {
                assert_eq!(
                    outcome,
                    LeafMergeOutcome::Dropped(SeedDropReason::ExplicitRangeExcludesDay),
                    "{why}",
                );
            }
        }
    }

    #[test]
    fn daily_fresh_tile_anchors_at_wall_clock_now_and_merges_at_the_right_index() {
        let meta = daily_meta(7, PredicateOp::Gte(3));
        let (record, transition, deadline) = merged(merge(&meta, now_day() - 2, 3, None));

        let Stage1State::BehavioralDailyBuckets {
            ref buckets,
            window_start_day,
            earliest_eviction_at_ms,
            ..
        } = record.state
        else {
            panic!("daily variant expected");
        };
        assert_eq!(
            window_start_day,
            now_day() - 7,
            "anchored at now, not the tile day"
        );
        let mut expected = vec![0u32; 8];
        expected[5] = 3; // (now − 2) − (now − 7)
        assert_eq!(*buckets, expected);
        assert_eq!(transition.map(|t| t.kind), Some(TransitionKind::Entered));
        assert_eq!(
            deadline,
            start_of_day_ms_in_tz(now_day() - 2 + 7 + 1, UTC),
            "deadline from the oldest (only) non-zero bucket",
        );
        assert_eq!(deadline, earliest_eviction_at_ms);
    }

    #[test]
    fn daily_below_window_tile_drops_without_resurrecting_after_a_sweep_delete() {
        let meta = daily_meta(7, PredicateOp::Gte(1));

        // First delivery, in-window: enters.
        let (_, transition, _) = merged(merge(&meta, now_day(), 1, None));
        assert_eq!(transition.map(|t| t.kind), Some(TransitionKind::Entered));

        // The sweep later deletes the record; the tile is re-delivered once its day has left the
        // window. The fresh-path anchor at wall-clock "now" must classify it below-window and drop
        // before any write — no record, no `Entered`, no re-flap.
        let later_now_ms = NOW_MS + 10 * 86_400_000;
        let later_now_day = day_idx_in_tz(later_now_ms, UTC);
        assert_eq!(
            merge_tile_into_leaf(
                &meta,
                UTC,
                identity(),
                now_day(),
                count(1),
                None,
                later_now_day,
                later_now_ms,
            ),
            LeafMergeOutcome::Dropped(SeedDropReason::DayBelowWindow),
        );
    }

    #[test]
    fn daily_slide_before_evaluate_emits_the_slide_induced_left() {
        // Prev record: 3 matches on a day about to leave the window (predicate true under gte 3).
        // The tile lands on "now" with count 1; the slide zeroes the old day first, so the count
        // falls below the threshold and the merge emits `Left` — the pre-slide predicate is the
        // "before" side.
        let meta = daily_meta(7, PredicateOp::Gte(3));
        let old_anchor = now_day() - 12;
        let mut buckets = vec![0u32; 8];
        buckets[0] = 3; // day old_anchor − 7... window [old_anchor-7? no: [start ..= start+7]
        let prev = StatefulRecord::new(
            Stage1State::BehavioralDailyBuckets {
                buckets,
                window_start_day: old_anchor,
                last_event_at_ms: NOW_MS - 12 * 86_400_000,
                earliest_eviction_at_ms: start_of_day_ms_in_tz(old_anchor + 8, UTC),
            },
            AppliedOffsets::default(),
        );

        let (record, transition, _) = merged(merge(&meta, now_day(), 1, Some(prev)));
        assert_eq!(
            transition.map(|t| t.kind),
            Some(TransitionKind::Left),
            "slide-induced true→false must emit Left",
        );
        let Stage1State::BehavioralDailyBuckets {
            ref buckets,
            window_start_day,
            ..
        } = record.state
        else {
            panic!("daily variant expected");
        };
        assert_eq!(window_start_day, now_day() - 7, "the slide is persisted");
        assert_eq!(
            buckets.iter().sum::<u32>(),
            1,
            "only the tile's day remains"
        );
    }

    #[test]
    fn daily_max_merge_absorbs_live_overlap_exactly() {
        let meta = daily_meta(7, PredicateOp::Gte(10));
        let (live, _, _) = merged(merge(&meta, now_day(), 3, None));

        // A tile counting a subset (late-arrival overlap) is absorbed: max(3, 2) = 3 → Unchanged.
        assert!(matches!(
            merge(&meta, now_day(), 2, Some(live.clone())),
            LeafMergeOutcome::Unchanged { .. }
        ));
        // A tile counting a superset raises the bucket to the absolute count, never the sum.
        let (after, _, _) = merged(merge(&meta, now_day(), 5, Some(live)));
        let Stage1State::BehavioralDailyBuckets { ref buckets, .. } = after.state else {
            panic!("daily variant expected");
        };
        assert_eq!(buckets.iter().sum::<u32>(), 5);
    }

    #[test]
    fn compressed_merges_and_replays_unchanged() {
        let meta = compressed_meta(365, PredicateOp::Gte(2));
        let (record, transition, deadline) = merged(merge(&meta, now_day() - 30, 2, None));

        let Stage1State::BehavioralCompressedHistory {
            ref entries,
            window_start_day,
            ..
        } = record.state
        else {
            panic!("compressed variant expected");
        };
        assert_eq!(*entries, vec![(now_day() - 30, 2)]);
        assert_eq!(window_start_day, now_day() - 365);
        assert_eq!(transition.map(|t| t.kind), Some(TransitionKind::Entered));
        assert_eq!(
            deadline,
            start_of_day_ms_in_tz(now_day() - 30 + 365 + 1, UTC)
        );

        assert!(matches!(
            merge(&meta, now_day() - 30, 2, Some(record)),
            LeafMergeOutcome::Unchanged { .. }
        ));
    }

    #[test]
    fn mismatched_meta_and_state_drop_totally() {
        // A person-property LSK sharing the hash must never absorb a behavioral tile.
        let person_meta = LeafStateMeta {
            variant: StateVariant::PersonProperty,
            condition_hash: HASH,
            window: None,
            window_days: None,
            predicate_op: None,
        };
        assert_eq!(
            merge(&person_meta, now_day(), 1, None),
            LeafMergeOutcome::Dropped(SeedDropReason::VariantMismatch),
        );

        // Meta lacking its window/op is incomplete, not a panic.
        let broken = LeafStateMeta {
            variant: StateVariant::BehavioralDailyBuckets,
            condition_hash: HASH,
            window: None,
            window_days: None,
            predicate_op: None,
        };
        assert_eq!(
            merge(&broken, now_day(), 1, None),
            LeafMergeOutcome::Dropped(SeedDropReason::MetaIncomplete),
        );

        // A stored record of a different variant than the meta's is a mismatch drop.
        let single_record = StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: NOW_MS,
                earliest_eviction_at_ms: i64::MAX,
            },
            AppliedOffsets::default(),
        );
        assert_eq!(
            merge(
                &daily_meta(7, PredicateOp::Gte(1)),
                now_day(),
                1,
                Some(single_record)
            ),
            LeafMergeOutcome::Dropped(SeedDropReason::VariantMismatch),
        );
    }

    #[test]
    fn dedup_maps_ride_through_bit_identical() {
        // The tile never touches `applied_offsets`/`redirect_dedup`.
        let meta = daily_meta(7, PredicateOp::Gte(1));
        let mut applied = AppliedOffsets::default();
        applied.record(17, 42);
        applied.record(3, 9);
        let mut redirect: BTreeMap<Uuid, AppliedOffsets> = BTreeMap::new();
        let mut ancestor = AppliedOffsets::default();
        ancestor.record(5, 100);
        redirect.insert(Uuid::from_u128(1), ancestor);
        let prev = StatefulRecord {
            state: Stage1State::BehavioralDailyBuckets {
                buckets: vec![0; 8],
                window_start_day: now_day() - 7,
                last_event_at_ms: NOW_MS - 1,
                earliest_eviction_at_ms: i64::MAX,
            },
            applied_offsets: applied.clone(),
            redirect_dedup: redirect.clone(),
        };

        let (record, _, _) = merged(merge(&meta, now_day(), 4, Some(prev)));
        assert_eq!(record.applied_offsets, applied);
        assert_eq!(record.redirect_dedup, redirect);
    }

    #[test]
    fn route_seed_maps_each_resolution_and_caps_the_hop_budget() {
        let tile = tile_for(Uuid::from_u128(0xA11CE), now_day(), 1);
        let survivor = Uuid::from_u128(0xB0B);

        assert_eq!(
            route_seed(&tile, Resolution::NotMerged, 8),
            SeedRoute::ApplyLocal {
                person: tile.person_id()
            },
        );
        assert_eq!(
            route_seed(
                &tile,
                Resolution::Inline {
                    final_person: survivor,
                    origin: tile.person_id()
                },
                8,
            ),
            SeedRoute::ApplyLocal { person: survivor },
        );
        match route_seed(
            &tile,
            Resolution::CrossPartition {
                target_person: survivor,
                origin: tile.person_id(),
            },
            8,
        ) {
            SeedRoute::ReProduce { seed: rekeyed } => {
                assert_eq!(rekeyed.person_id(), survivor);
                assert_eq!(rekeyed.redirect_hops(), 1);
                assert_eq!(
                    rekeyed.s_chunk_ms(),
                    tile.s_chunk_ms(),
                    "fence input rides verbatim"
                );
            }
            other => panic!("expected ReProduce, got {other:?}"),
        }
        // Cap 0: an over-cap re-produce is unrepresentable — the cap arm is forced.
        assert_eq!(
            route_seed(
                &tile,
                Resolution::CrossPartition {
                    target_person: survivor,
                    origin: tile.person_id(),
                },
                0,
            ),
            SeedRoute::CapExhausted { person: survivor },
        );
    }

    /// Apply a tile multiset in order, threading the record through.
    fn apply_all(
        meta: &LeafStateMeta,
        tiles: &[(i32, u32)],
        now_day: DayIdx,
        now_ms: i64,
    ) -> Option<StatefulRecord> {
        let mut prev: Option<StatefulRecord> = None;
        for &(offset, n) in tiles {
            let outcome = merge_tile_into_leaf(
                meta,
                UTC,
                identity(),
                now_day - offset,
                count(n),
                prev.as_ref(),
                now_day,
                now_ms,
            );
            if let LeafMergeOutcome::Merged { record, .. } = outcome {
                prev = Some(record);
            }
        }
        prev
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(64))]

        /// The register diff and the stage-1 transition must agree over any tile sequence and
        /// comparator direction. Otherwise, a first apply can emit a change stage 1 never flipped
        /// or swallow one it did.
        #[test]
        fn leaf_membership_agrees_with_the_transition_the_merge_mints(
            tiles in prop::collection::vec((0i32..=12, 1u32..=5, 0i32..=3), 1..10),
            gte in any::<bool>(),
            threshold in 1u32..=4,
        ) {
            let op = if gte { PredicateOp::Gte(threshold) } else { PredicateOp::Lte(threshold) };
            let meta = daily_meta(7, op);
            let mut prev: Option<StatefulRecord> = None;
            // Wall time advances between applies, so the window slides and the slide-induced
            // transitions are in scope too.
            let mut today = now_day();
            let mut now_ms = NOW_MS;
            for &(offset, n, advance) in &tiles {
                today += advance;
                now_ms += advance as i64 * 86_400_000;
                let before = leaf_membership(prev.as_ref().map(|record| &record.state), &meta);
                match merge_tile_into_leaf(
                    &meta,
                    UTC,
                    identity(),
                    today - offset,
                    count(n),
                    prev.as_ref(),
                    today,
                    now_ms,
                ) {
                    LeafMergeOutcome::Merged { record, transition, .. } => {
                        let after = leaf_membership(Some(&record.state), &meta);
                        prop_assert_eq!(
                            transition.map(|transition| transition.kind),
                            match (before, after) {
                                (false, true) => Some(TransitionKind::Entered),
                                (true, false) => Some(TransitionKind::Left),
                                _ => None,
                            },
                        );
                        prev = Some(record);
                    }
                    LeafMergeOutcome::Unchanged { record } => {
                        prop_assert_eq!(
                            leaf_membership(Some(&record.state), &meta),
                            before,
                            "an Unchanged merge cannot move membership",
                        );
                    }
                    LeafMergeOutcome::Dropped(_) => {}
                }
            }
        }

        /// An arbitrary tile multiset applied in an arbitrary order (some tiles below the
        /// window) reaches one unique final state.
        #[test]
        fn daily_apply_order_commutes(
            (tiles, shuffled) in prop::collection::vec((0i32..=12, 1u32..=5), 1..10)
                .prop_flat_map(|tiles| {
                    let shuffled = Just(tiles.clone()).prop_shuffle();
                    (Just(tiles), shuffled)
                })
        ) {
            let meta = daily_meta(7, PredicateOp::Gte(3));
            prop_assert_eq!(
                apply_all(&meta, &tiles, now_day(), NOW_MS),
                apply_all(&meta, &shuffled, now_day(), NOW_MS),
            );
        }

        /// apply ∘ apply = apply: after a multiset lands, re-applying any of its tiles is never a
        /// `Merged` (only `Unchanged` or a below-window `Dropped`).
        #[test]
        fn daily_replay_is_never_a_second_merge(
            tiles in prop::collection::vec((0i32..=12, 1u32..=5), 1..10)
        ) {
            let meta = daily_meta(7, PredicateOp::Gte(3));
            let settled = apply_all(&meta, &tiles, now_day(), NOW_MS);
            for &(offset, n) in &tiles {
                let outcome = merge_tile_into_leaf(
                    &meta,
                    UTC,
                    identity(),
                    now_day() - offset,
                    count(n),
                    settled.as_ref(),
                    now_day(),
                    NOW_MS,
                );
                prop_assert!(
                    !matches!(outcome, LeafMergeOutcome::Merged { .. }),
                    "replay of ({}, {}) merged again: {:?}",
                    offset,
                    n,
                    outcome,
                );
            }
        }

        /// Same two properties for the sparse variant, whose merge op (`merge_day_count`) is new.
        #[test]
        fn compressed_apply_order_commutes_and_replays_unchanged(
            (tiles, shuffled) in prop::collection::vec((0i32..=400, 1u32..=5), 1..10)
                .prop_flat_map(|tiles| {
                    let shuffled = Just(tiles.clone()).prop_shuffle();
                    (Just(tiles), shuffled)
                })
        ) {
            let meta = compressed_meta(365, PredicateOp::Gte(3));
            let settled = apply_all(&meta, &tiles, now_day(), NOW_MS);
            prop_assert_eq!(
                settled.clone(),
                apply_all(&meta, &shuffled, now_day(), NOW_MS),
            );
            for &(offset, n) in &tiles {
                let outcome = merge_tile_into_leaf(
                    &meta,
                    UTC,
                    identity(),
                    now_day() - offset,
                    count(n),
                    settled.as_ref(),
                    now_day(),
                    NOW_MS,
                );
                let replay_merged = matches!(outcome, LeafMergeOutcome::Merged { .. });
                prop_assert!(!replay_merged, "replay merged again");
            }
        }
    }

    // ---- live-equivalence: tile (d, N) on empty ≡ N same-day live events ----

    fn temp_store() -> (TempDir, CohortStore) {
        let dir = TempDir::new().unwrap();
        let store = CohortStore::open(&StoreConfig {
            path: dir.path().join("db"),
            ..StoreConfig::default()
        })
        .unwrap();
        (dir, store)
    }

    fn test_handle(store: &CohortStore) -> StoreHandle {
        StoreHandle::new(
            store.clone(),
            OffloadConfig {
                mode: OffloadMode::All,
                event_read_permits: 16,
                maintenance_permits: 6,
            },
        )
    }

    fn behavioral_bytecode() -> Value {
        json!(["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11])
    }

    const PERSON_HASH: &str = "fedcba9876543210";

    fn person_leaf_json() -> Value {
        json!({
            "type": "person", "key": "email", "value": "a@b.com", "operator": "exact",
            "conditionHash": PERSON_HASH,
            "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn single_leaf_json(window_days: i64) -> Value {
        single_leaf_json_with("0123456789abcdef", window_days)
    }

    fn single_leaf_json_with(condition_hash: &str, window_days: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": window_days, "time_interval": "day",
            "conditionHash": condition_hash,
            "bytecode": behavioral_bytecode(),
        })
    }

    fn multiple_leaf_json(window_days: i64, op: &str, value: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event_multiple", "key": "$pageview",
            "time_value": window_days, "time_interval": "day",
            "operator": op, "operator_value": value,
            "conditionHash": "0123456789abcdef",
            "bytecode": behavioral_bytecode(),
        })
    }

    fn wrap(values: Vec<Value>) -> Value {
        json!({ "properties": { "type": "AND", "values": values } })
    }

    fn build_filters(cohorts: Vec<(i32, Value)>, tz: chrono_tz::Tz) -> TeamFilters {
        build_filters_for(TEAM, cohorts, tz)
    }

    fn build_filters_for(
        team: TeamId,
        cohorts: Vec<(i32, Value)>,
        tz: chrono_tz::Tz,
    ) -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        for (id, filters) in cohorts {
            builder.add_cohort(CohortId(id), team, &filters).unwrap();
        }
        builder.freeze(tz)
    }

    /// The ClickHouse-format timestamp of noon (team tz) on `day`.
    fn noon_ts(day: DayIdx, tz: chrono_tz::Tz) -> String {
        let ms = start_of_day_ms_in_tz(day, tz) + 12 * 3_600_000;
        chrono::DateTime::from_timestamp_millis(ms)
            .unwrap()
            .format("%Y-%m-%d %H:%M:%S%.6f")
            .to_string()
    }

    fn live_event(
        person: Uuid,
        timestamp: &str,
        source_offset: i64,
    ) -> crate::consumers::events::CohortStreamEvent {
        crate::consumers::events::CohortStreamEvent {
            team_id: TEAM.0,
            person_id: person.to_string(),
            distinct_id: "d".to_string(),
            uuid: "u".to_string(),
            event: "$pageview".to_string(),
            timestamp: timestamp.to_string(),
            properties: Some("{}".to_string()),
            person_properties: None,
            elements_chain: None,
            source_offset,
            source_partition: 0,
            redirected_from: None,
            redirect_hops: 0,
        }
    }

    /// One tile `(d, N)` merged onto empty state must equal `N` same-day events through the live
    /// fold — same buckets, window anchor, and deadline (`last_event_at_ms` and the dedup maps are
    /// the two designed differences). DST coverage via a non-UTC team tz.
    #[test]
    fn tile_on_empty_equals_n_live_same_day_events_for_every_variant() {
        for tz in [UTC, New_York] {
            let (_dir, store) = temp_store();
            let filters = build_filters(
                vec![
                    (1, wrap(vec![single_leaf_json(7)])),
                    (2, wrap(vec![multiple_leaf_json(7, "gte", 3)])),
                    (3, wrap(vec![multiple_leaf_json(365, "gte", 3)])),
                ],
                tz,
            );
            let person = Uuid::from_u128(0xE0);
            let n = 3u32;
            let now_ms = chrono::Utc::now().timestamp_millis();
            let today = day_idx_in_tz(now_ms, tz);
            let ts = noon_ts(today, tz);
            let event_ms = crate::stage1::clickhouse_timestamp_to_millis(&ts).unwrap();

            for offset in 0..n {
                process_event_gated(
                    0,
                    &store,
                    &filters,
                    &live_event(person, &ts, offset as i64),
                    EventNameGating::Disabled,
                )
                .unwrap();
            }

            for &lsk in &filters.by_condition_to_lsk[&HASH] {
                let meta = &filters.by_lsk[&lsk];
                let key = PersonPrefix::new(0, TEAM.0 as u64, person).behavioral_key(lsk);
                let live =
                    StatefulRecord::decode(&store.get_behavioral(&key).unwrap().unwrap()).unwrap();

                let seeded_identity = LeafIdentity {
                    team_id: TEAM,
                    lsk,
                    person_id: person,
                    condition_hash: HASH,
                };
                let (seeded, _, _) = merged(merge_tile_into_leaf(
                    meta,
                    tz,
                    seeded_identity,
                    today,
                    count(n),
                    None,
                    today,
                    now_ms,
                ));

                match (&live.state, &seeded.state) {
                    (
                        Stage1State::BehavioralSingle {
                            earliest_eviction_at_ms: live_deadline,
                            ..
                        },
                        Stage1State::BehavioralSingle {
                            has_match,
                            earliest_eviction_at_ms: seeded_deadline,
                            ..
                        },
                    ) => {
                        assert!(has_match);
                        // Exact deadline equality against a live instant.
                        assert_eq!(seeded_deadline, live_deadline, "single deadline, tz {tz}");
                        assert_eq!(
                            *seeded_deadline,
                            EvictionWindow::RelativeDays { days: 7 }
                                .earliest_eviction_at_ms(event_ms, tz),
                        );
                    }
                    (
                        Stage1State::BehavioralDailyBuckets {
                            buckets: live_buckets,
                            window_start_day: live_start,
                            earliest_eviction_at_ms: live_deadline,
                            ..
                        },
                        Stage1State::BehavioralDailyBuckets {
                            buckets: seeded_buckets,
                            window_start_day: seeded_start,
                            earliest_eviction_at_ms: seeded_deadline,
                            ..
                        },
                    ) => {
                        assert_eq!(seeded_buckets, live_buckets, "daily buckets, tz {tz}");
                        assert_eq!(seeded_start, live_start);
                        assert_eq!(seeded_deadline, live_deadline);
                    }
                    (
                        Stage1State::BehavioralCompressedHistory {
                            entries: live_entries,
                            window_start_day: live_start,
                            earliest_eviction_at_ms: live_deadline,
                            ..
                        },
                        Stage1State::BehavioralCompressedHistory {
                            entries: seeded_entries,
                            window_start_day: seeded_start,
                            earliest_eviction_at_ms: seeded_deadline,
                            ..
                        },
                    ) => {
                        assert_eq!(seeded_entries, live_entries, "compressed entries, tz {tz}");
                        assert_eq!(seeded_start, live_start);
                        assert_eq!(seeded_deadline, live_deadline);
                    }
                    (live_state, seeded_state) => {
                        panic!("variant mismatch: live {live_state:?} vs seeded {seeded_state:?}")
                    }
                }
            }
        }
    }

    // ---- shell tests: handle_seed against a temp store ----

    fn tile_for(person: Uuid, day: DayIdx, n: u32) -> SeedTile {
        tile_for_team(TEAM, person, day, n)
    }

    fn tile_for_team(team: TeamId, person: Uuid, day: DayIdx, n: u32) -> SeedTile {
        SeedTile::new(
            team,
            person,
            ConditionHash::parse("0123456789abcdef").unwrap(),
            count(n),
            day,
            SChunkMs(1_700_000_000_000),
            RunId(Uuid::from_u128(0xBF)),
            ClaimEpoch(1),
        )
    }

    fn tile_from_run(person: Uuid, condition_hash: &str, run: u128, day: DayIdx) -> SeedTile {
        SeedTile::new(
            TEAM,
            person,
            ConditionHash::parse(condition_hash).unwrap(),
            count(1),
            day,
            SChunkMs(1_700_000_000_000),
            RunId(Uuid::from_u128(run)),
            ClaimEpoch(1),
        )
    }

    fn person_seed_for(person: Uuid) -> PersonSeed {
        PersonSeed::new(
            TEAM,
            person,
            vec![ConditionHash::parse(PERSON_HASH).unwrap()],
            vec![ConditionHash::parse(PERSON_HASH).unwrap()],
            cohort_core::seed::ScannedAtMs(chrono::Utc::now().timestamp_millis()),
            RunId(Uuid::from_u128(0xBF)),
            ClaimEpoch(1),
        )
        .unwrap()
    }

    fn reconcile_for(cohort_id: i32, run_id: u128) -> ReconcileTile {
        ReconcileTile::new(
            TEAM,
            CohortId(cohort_id),
            ReconcileScope::Behavioral(BehavioralShapeHash::parse("0123456789abcdef").unwrap()),
            RunId(Uuid::from_u128(run_id)),
        )
    }

    struct Shell {
        _dir: TempDir,
        store: CohortStore,
        handle: StoreHandle,
        catalog: Arc<CatalogHandle>,
        sink: CaptureSink,
        seed_sink: CaptureSeedTileSink,
        cascade_sink: crate::producer::CaptureCascadeSink,
        marker_sink: CaptureReconcileMarkerSink,
        deps: MergeWorkerDeps,
        queue: EvictionQueue<BehavioralKey>,
        reconcile_queue: ReconcileQueue,
        /// Mints a strictly increasing stamp per run, the way a partition worker does, so a
        /// re-emission wins LWW against the change it replaces.
        clock: crate::producer::LastUpdatedClock,
        /// What `handle_seed` produces through. Defaults to `sink`; a test swaps it to reach an
        /// ack shape `CaptureSink` cannot produce.
        membership: Arc<dyn MembershipSink>,
    }

    impl Shell {
        fn new(cohorts: Vec<(i32, Value)>) -> Self {
            Self::with_sink(cohorts, CaptureSink::new(), CaptureSeedTileSink::new())
        }

        /// The same cohort shape under two teams, so a run can span them.
        fn with_two_teams(cohorts: Vec<(i32, Value)>) -> Self {
            let mut shell = Self::new(cohorts.clone());
            shell.catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([
                (TEAM, build_filters_for(TEAM, cohorts.clone(), UTC)),
                (OTHER_TEAM, build_filters_for(OTHER_TEAM, cohorts, New_York)),
            ])));
            shell
        }

        fn with_sink(
            cohorts: Vec<(i32, Value)>,
            sink: CaptureSink,
            seed_sink: CaptureSeedTileSink,
        ) -> Self {
            Self::build(
                cohorts,
                sink,
                seed_sink,
                crate::producer::CaptureCascadeSink::new(),
                crate::workers::CascadeConfig::default(),
            )
        }

        fn with_cascade(
            cohorts: Vec<(i32, Value)>,
            cascade_sink: crate::producer::CaptureCascadeSink,
        ) -> Self {
            Self::build(
                cohorts,
                CaptureSink::new(),
                CaptureSeedTileSink::new(),
                cascade_sink,
                crate::workers::CascadeConfig {
                    enabled: true,
                    depth_cap: 8,
                    fanout_cap: 1000,
                },
            )
        }

        fn build(
            cohorts: Vec<(i32, Value)>,
            sink: CaptureSink,
            seed_sink: CaptureSeedTileSink,
            cascade_sink: crate::producer::CaptureCascadeSink,
            cascade: crate::workers::CascadeConfig,
        ) -> Self {
            let (_dir, store) = temp_store();
            let handle = test_handle(&store);
            let catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
                TEAM,
                build_filters(cohorts, UTC),
            )])));
            let marker_sink = CaptureReconcileMarkerSink::new();
            let deps = MergeWorkerDeps {
                transfer_sink: Arc::new(crate::producer::CaptureTransferSink::new()),
                stream_event_sink: Arc::new(crate::producer::CaptureStreamEventSink::new()),
                merge_tracker: Arc::new(OffsetTracker::new()),
                transfer_tracker: Arc::new(OffsetTracker::new()),
                retry: crate::workers::TransferRetryPolicy::default(),
                gc_scan_limit: crate::workers::DEFAULT_MERGE_GC_SCAN_LIMIT,
                stage2_orphan_gc_enabled: true,
                cascade_sink: Arc::new(cascade_sink.clone()),
                cascade_tracker: Arc::new(OffsetTracker::new()),
                cascade,
                partition_count: COHORT_PARTITION_COUNT,
                seed_tile_sink: Arc::new(seed_sink.clone()),
                seed_tracker: Arc::new(OffsetTracker::new()),
                live_watermarks: Arc::new(crate::partitions::watermarks::LiveWatermarks::new()),
                register_transfer_enabled: false,
                reconcile: crate::workers::ReconcileDeps {
                    marker_sink: Arc::new(marker_sink.clone()),
                    ..crate::workers::ReconcileDeps::default()
                },
                person_seed: crate::workers::PersonSeedDeps::default(),
                seed_budget: crate::workers::seed_run::RunBudget::default(),
            };
            let reconcile_queue =
                ReconcileQueue::new(0, deps.reconcile.backlog.clone(), handle.clone());
            Self {
                _dir,
                store,
                handle,
                catalog,
                sink: sink.clone(),
                seed_sink,
                cascade_sink,
                marker_sink,
                deps,
                queue: EvictionQueue::new(),
                reconcile_queue,
                clock: crate::producer::LastUpdatedClock::default(),
                membership: Arc::new(sink),
            }
        }

        /// Apply one seed as a run of one, which is what a channel batch of one seed becomes.
        async fn run(&mut self, partition_id: u16, work: SeedWork, offset: i64) {
            self.run_batch(partition_id, vec![(work, offset)]).await;
        }

        /// Apply a channel batch's worth of seeds the way the worker does: group them into runs,
        /// then apply each group in order.
        async fn run_batch(&mut self, partition_id: u16, seeds: Vec<(SeedWork, i64)>) {
            let max = seeds.iter().map(|(_, offset)| *offset).max().unwrap();
            self.deps
                .seed_tracker
                .mark_dispatched(partition_id as i32, max + 1);
            let sink = self.membership.clone();
            let snapshot = self.catalog.load();
            let deps = ApplyDeps {
                partition_id,
                handle: &self.handle,
                catalog: &snapshot,
                sink: &sink,
                merge: &self.deps,
            };
            let admitted: Vec<Admitted<SeedWork>> = seeds
                .into_iter()
                .map(|(work, offset)| Admitted {
                    work,
                    offset: SeedOffset(offset),
                })
                .collect();
            let groups = group_seeds(admitted, RunBudget::default(), |work| {
                row_weight(&snapshot, work)
            });
            handle_seed_groups(
                deps,
                &mut self.queue,
                &mut self.reconcile_queue,
                &mut self.clock,
                groups,
            )
            .await;
        }

        /// A new tenure over the same store, catalog, and sinks: fresh offset trackers and
        /// in-memory queues, the way a restart or rebalance re-assigns the partition at
        /// `Offset::Stored` and replays whatever a hold pinned. The clock is kept: a real tenure
        /// mints a fresh one whose first stamp is wall time, later than anything the last tenure
        /// minted, which the shared clock also guarantees.
        fn restart(&mut self) {
            self.deps.seed_tracker = Arc::new(OffsetTracker::new());
            self.deps.merge_tracker = Arc::new(OffsetTracker::new());
            self.deps.transfer_tracker = Arc::new(OffsetTracker::new());
            self.deps.cascade_tracker = Arc::new(OffsetTracker::new());
            self.queue = EvictionQueue::new();
            self.reconcile_queue =
                ReconcileQueue::new(0, self.deps.reconcile.backlog.clone(), self.handle.clone());
        }

        /// Drain the queued reconcile to completion, one page per tick, the way the worker does.
        async fn drain_reconcile(&mut self, partition_id: u16) {
            let sink = self.membership.clone();
            for _ in 0..64 {
                if self.reconcile_queue.len() == 0 {
                    return;
                }
                let last_updated = self.clock.next();
                crate::workers::reconcile::handle_reconcile_drain(
                    partition_id,
                    &self.handle,
                    &self.catalog,
                    &sink,
                    &self.deps,
                    &mut self.reconcile_queue,
                    &last_updated,
                )
                .await;
            }
            panic!("the reconcile never completed");
        }

        fn register_key(&self, partition_id: u16, person: Uuid, cohort_id: u64) -> Stage2Key {
            Stage2Key {
                partition_id,
                team_id: TEAM.0 as u64,
                cohort_id,
                person_id: person,
            }
        }

        fn register(&self, partition_id: u16, person: Uuid, cohort_id: u64) -> Option<Stage2State> {
            self.store
                .get_stage2(&self.register_key(partition_id, person, cohort_id))
                .unwrap()
                .map(|bytes| Stage2State::decode(&bytes).unwrap())
        }

        fn committable(&self, partition_id: u16) -> Option<i64> {
            self.deps
                .seed_tracker
                .committable_offsets()
                .get(&(partition_id as i32))
                .copied()
        }
    }

    /// What the CDP consumer would hold after applying `changes` in produce order: the newest
    /// `last_updated` per `(cohort, person)` wins, ties to the later record.
    fn downstream(changes: &[CohortMembershipChange]) -> BTreeMap<(i32, String), MembershipStatus> {
        let mut model: BTreeMap<(i32, String), (String, MembershipStatus)> = BTreeMap::new();
        for change in changes {
            let entry = (change.cohort_id, change.person_id.clone());
            let beats = model
                .get(&entry)
                .is_none_or(|(seen, _)| change.last_updated >= *seen);
            if beats {
                model.insert(entry, (change.last_updated.clone(), change.status));
            }
        }
        model
            .into_iter()
            .map(|(entry, (_, status))| (entry, status))
            .collect()
    }

    fn today() -> DayIdx {
        day_idx_in_tz(chrono::Utc::now().timestamp_millis(), UTC)
    }

    #[tokio::test]
    async fn skip_work_marks_the_seed_offset_in_order() {
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        shell
            .run(0, SeedWork::Skip(SeedSkipReason::UnknownKind), 5)
            .await;
        assert_eq!(shell.committable(0), Some(6), "the skip's offset commits");
        assert!(shell.sink.changes().is_empty());
    }

    #[tokio::test]
    async fn disabled_reconcile_skips_and_commits_without_enqueuing() {
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);

        shell
            .run(0, SeedWork::Reconcile(reconcile_for(1, 1)), 5)
            .await;

        assert_eq!(shell.committable(0), Some(6));
        assert_eq!(shell.reconcile_queue.len(), 0);
        assert!(shell.deps.reconcile.backlog.is_empty());
        assert!(shell.sink.changes().is_empty());
        assert!(shell.marker_sink.markers().is_empty());
    }

    #[tokio::test]
    async fn enabled_reconcile_enqueues_and_pins_later_seed_progress() {
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        shell.deps.reconcile.enabled = true;

        shell
            .run(0, SeedWork::Reconcile(reconcile_for(1, 1)), 5)
            .await;
        shell
            .run(0, SeedWork::Skip(SeedSkipReason::UnknownKind), 6)
            .await;

        assert_eq!(shell.committable(0), Some(5));
        assert_eq!(shell.reconcile_queue.len(), 1);
        assert_eq!(shell.deps.reconcile.backlog.len(), 1);
    }

    #[tokio::test]
    async fn newer_reconcile_supersedes_the_same_cohort_and_completes_the_old_floor() {
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        shell.deps.reconcile.enabled = true;

        shell
            .run(0, SeedWork::Reconcile(reconcile_for(1, 1)), 5)
            .await;
        shell
            .run(0, SeedWork::Reconcile(reconcile_for(1, 2)), 6)
            .await;

        assert_eq!(shell.committable(0), Some(6));
        assert_eq!(shell.reconcile_queue.len(), 1);
        assert_eq!(shell.deps.reconcile.backlog.len(), 1);
        assert_eq!(
            shell.reconcile_queue.front_run_id(),
            Some(RunId(Uuid::from_u128(2))),
        );
    }

    #[tokio::test]
    async fn older_reconcile_replay_cannot_evict_a_newer_queued_run() {
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        shell.deps.reconcile.enabled = true;

        shell
            .run(0, SeedWork::Reconcile(reconcile_for(1, 2)), 6)
            .await;
        shell
            .run(0, SeedWork::Reconcile(reconcile_for(1, 1)), 5)
            .await;
        shell
            .run(0, SeedWork::Skip(SeedSkipReason::UnknownKind), 7)
            .await;

        assert_eq!(shell.committable(0), Some(6));
        assert_eq!(shell.reconcile_queue.len(), 1);
        assert_eq!(shell.deps.reconcile.backlog.len(), 1);
        assert_eq!(
            shell.reconcile_queue.front_run_id(),
            Some(RunId(Uuid::from_u128(2))),
        );
    }

    #[tokio::test]
    async fn tile_flip_emits_an_origin_tagged_change_and_schedules_eviction() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        let tile = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 9)
            .await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1, "the single-leaf cohort entered");
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].origin, Some(ChangeOrigin::Seed));
        assert_eq!(changes[0].run_id, Some(tile.run_id()));
        assert_eq!(changes[0].person_id, person.to_string());
        assert_eq!(shell.committable(partition_id), Some(10));
        assert_eq!(shell.queue.len(), 1, "the leaf's eviction was scheduled");

        let register_key = Stage2Key {
            partition_id,
            team_id: TEAM.0 as u64,
            cohort_id: 1,
            person_id: person,
        };
        assert!(
            Stage2State::decode(&shell.store.get_stage2(&register_key).unwrap().unwrap())
                .unwrap()
                .in_cohort,
            "the seed apply materializes the single-leaf register",
        );

        shell
            .store
            .write_batch(|batch| batch.delete_stage2(&register_key))
            .unwrap();

        // Re-delivery: the max-merge is a no-op, but a missing register reads as "downstream was
        // never told", so the entry is re-emitted and the row restored. The duplicate is what the
        // LWW sink is for.
        shell.run(partition_id, SeedWork::Tile(tile), 10).await;
        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 2);
        assert_eq!(changes[1].status, MembershipStatus::Entered);
        assert!(
            changes[1].last_updated > changes[0].last_updated,
            "the re-emission carries the newer stamp, so it wins downstream",
        );
        assert_eq!(shell.committable(partition_id), Some(11));
        assert!(
            Stage2State::decode(&shell.store.get_stage2(&register_key).unwrap().unwrap())
                .unwrap()
                .in_cohort,
            "an Unchanged seed replay restores the register from its post-merge record",
        );
    }

    // ---- runs of more than one seed ----

    /// A run of two tiles must reach the same state and the same output as the same two tiles in
    /// two runs. Without read-your-writes the second tile would fold against the run-start bytes
    /// and lose the first tile's day.
    #[tokio::test]
    async fn a_run_of_two_tiles_matches_the_same_tiles_applied_one_at_a_time() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let cohorts = vec![(1, wrap(vec![multiple_leaf_json(7, "gte", 2)]))];
        let day = today();

        let mut batched = Shell::new(cohorts.clone());
        batched
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(person, day - 1, 1)), 0),
                    (SeedWork::Tile(tile_for(person, day, 1)), 1),
                ],
            )
            .await;

        let mut serial = Shell::new(cohorts);
        serial
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, day - 1, 1)),
                0,
            )
            .await;
        serial
            .run(partition_id, SeedWork::Tile(tile_for(person, day, 1)), 1)
            .await;

        let lsk = *batched
            .catalog
            .load()
            .team(TEAM)
            .unwrap()
            .by_lsk
            .keys()
            .next()
            .unwrap();
        let key = PersonPrefix::new(partition_id, TEAM.0 as u64, person).behavioral_key(lsk);
        assert_eq!(
            batched.store.get_behavioral(&key).unwrap(),
            serial.store.get_behavioral(&key).unwrap(),
            "the run folds to the same bytes as the seeds one at a time",
        );
        assert_eq!(
            downstream(&batched.sink.changes()),
            downstream(&serial.sink.changes()),
            "and downstream converges on the same membership",
        );
        assert_eq!(
            batched.sink.changes().len(),
            1,
            "the run emits the net entry once, not once per tile",
        );
        assert_eq!(batched.committable(partition_id), Some(2));
    }

    #[tokio::test]
    async fn an_unchanged_later_tile_keeps_the_runs_eviction_deadline() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::new(vec![(1, wrap(vec![multiple_leaf_json(7, "gte", 1)]))]);
        let day = today();

        shell
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(person, day, 2)), 0),
                    (SeedWork::Tile(tile_for(person, day, 1)), 1),
                ],
            )
            .await;

        assert_eq!(
            shell.queue.len(),
            1,
            "the unchanged max-merge must not replace the earlier finite deadline",
        );
    }

    /// A run that enters and then leaves the same leaf told downstream nothing, so it must emit
    /// nothing and leave no register behind. Emitting the intermediate flip would make a run of
    /// two differ from a run of one over the same net state.
    #[tokio::test]
    async fn enter_then_leave_in_one_run_emits_nothing_and_writes_no_register() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::new(vec![(1, wrap(vec![multiple_leaf_json(7, "gte", 2)]))]);
        let day = today();

        shell
            .run_batch(
                partition_id,
                vec![
                    // Enters: two events on `day` meet `gte 2`.
                    (SeedWork::Tile(tile_for(person, day, 2)), 0),
                    // Leaves: a future-dated tile slides `day` out of the window and carries one.
                    (SeedWork::Tile(tile_for(person, day + 8, 1)), 1),
                ],
            )
            .await;

        assert!(
            shell.sink.changes().is_empty(),
            "the net transition is none, so downstream hears nothing",
        );
        assert_eq!(
            shell.register(partition_id, person, 1),
            None,
            "and no register is written for a person downstream was never told about",
        );
        assert_eq!(shell.committable(partition_id), Some(2));
    }

    /// The same run against a register that says the person is in: the stored bit disagrees with
    /// the run's truth, so exactly one retraction goes out.
    #[tokio::test]
    async fn enter_then_leave_in_one_run_emits_once_over_a_lagging_register() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::new(vec![(1, wrap(vec![multiple_leaf_json(7, "gte", 2)]))]);
        let day = today();
        shell
            .store
            .write_batch(|batch| {
                batch.put_stage2(
                    &shell.register_key(partition_id, person, 1),
                    &Stage2State {
                        in_cohort: true,
                        last_evaluated_at_ms: 1,
                    }
                    .encode(),
                )
            })
            .unwrap();

        shell
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(person, day, 2)), 0),
                    (SeedWork::Tile(tile_for(person, day + 8, 1)), 1),
                ],
            )
            .await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1, "one retraction, not an entry and a leave");
        assert_eq!(changes[0].status, MembershipStatus::Left);
        assert!(!shell.register(partition_id, person, 1).unwrap().in_cohort);
    }

    /// A run either lands whole or replays whole: the hold pins the run's *lowest* offset, and the
    /// redelivery emits each change exactly once. A hold at `last` would commit past a tile that
    /// was never applied. The trailing skip is what makes the floor observable: later groups in the
    /// same channel batch still run and mark, and the hold is what keeps their marks from
    /// leapfrogging it.
    #[tokio::test]
    async fn a_held_run_holds_its_first_offset_and_the_replay_emits_each_change_once() {
        let alice = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &alice, COHORT_PARTITION_COUNT) as u16;
        let bob = (0x5EEEu128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TEAM, p, COHORT_PARTITION_COUNT) as u16 == partition_id)
            .unwrap();
        let mut shell = Shell::with_sink(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        let batch = || {
            vec![
                (SeedWork::Tile(tile_for(alice, today(), 1)), 4),
                (SeedWork::Tile(tile_for(bob, today(), 1)), 5),
                (SeedWork::Skip(SeedSkipReason::UnknownKind), 6),
            ]
        };

        shell.run_batch(partition_id, batch()).await;

        assert!(shell.sink.changes().is_empty());
        assert_eq!(
            shell.committable(partition_id),
            Some(4),
            "the skip marked past the run, but the hold pins the floor at the run's first offset",
        );
        assert!(
            !shell.queue.is_empty(),
            "the schedules stay: the stage-1 rows they belong to are already durable",
        );

        shell.restart();
        shell.run_batch(partition_id, batch()).await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 2, "one entry per person, once");
        assert_eq!(
            downstream(&changes)
                .values()
                .filter(|status| **status == MembershipStatus::Entered)
                .count(),
            2,
        );
        assert_eq!(shell.committable(partition_id), Some(7));
    }

    /// Records the seed tracker's committable offset at every produce, which is what a crash or a
    /// rebalance at that instant would have left committed.
    #[derive(Clone)]
    struct FloorProbeSink {
        inner: CaptureSink,
        tracker: Arc<OffsetTracker>,
        partition_id: u16,
        floors: Arc<std::sync::Mutex<Vec<Option<i64>>>>,
    }

    #[async_trait::async_trait]
    impl MembershipSink for FloorProbeSink {
        async fn produce(
            &self,
            changes: Vec<CohortMembershipChange>,
        ) -> Vec<Result<(), common_kafka::kafka_producer::KafkaProduceError>> {
            let floor = self
                .tracker
                .committable_offsets()
                .get(&(self.partition_id as i32))
                .copied();
            self.floors.lock().unwrap().push(floor);
            self.inner.produce(changes).await
        }
    }

    /// Groups' spans interleave: one open run per kind means a tile run can span offsets a person
    /// run in the same collection still owes. Marking per group would let the consumer commit past
    /// that person seed while it is still unapplied, and a crash in that window loses it for good.
    #[tokio::test]
    async fn no_offset_becomes_committable_while_the_collection_still_owes_a_seed() {
        let alice = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &alice, COHORT_PARTITION_COUNT) as u16;
        let bob = (0x5EEEu128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TEAM, p, COHORT_PARTITION_COUNT) as u16 == partition_id)
            .unwrap();
        let mut shell = Shell::new(vec![
            (1, wrap(vec![single_leaf_json(7)])),
            (2, wrap(vec![person_leaf_json()])),
        ]);
        shell.deps.person_seed.enabled = true;
        let probe = FloorProbeSink {
            inner: shell.sink.clone(),
            tracker: shell.deps.seed_tracker.clone(),
            partition_id,
            floors: Arc::default(),
        };
        shell.membership = Arc::new(probe.clone());

        // Tiles at 0 and 2 straddle the person seed at 1, so the tile run's span covers an offset
        // the person run has not reached.
        shell
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(alice, today(), 1)), 0),
                    (SeedWork::Person(person_seed_for(bob)), 1),
                    (SeedWork::Tile(tile_for(alice, today() - 1, 1)), 2),
                ],
            )
            .await;

        assert_eq!(
            shell.sink.changes().len(),
            2,
            "one behavioral entry and one person entry",
        );
        let floors = probe.floors.lock().unwrap().clone();
        assert_eq!(floors.len(), 2, "one produce per group");
        assert!(
            floors.iter().all(Option::is_none),
            "an offset became committable mid-collection: {floors:?}",
        );
        assert_eq!(
            shell.committable(partition_id),
            Some(3),
            "and the whole collection commits once every group has run",
        );
    }

    /// A re-keyed seed has no other copy, so an ack vector shorter than the run's hand-offs must
    /// hold the run rather than read as a vacuous success.
    #[tokio::test]
    async fn a_short_rekey_ack_holds_the_whole_run() {
        let (p_old, partition_id, p_new) = cross_partition_pair();
        let other_old = (0xA11CEu128..)
            .map(Uuid::from_u128)
            .find(|p| {
                partition_of(TEAM, p, COHORT_PARTITION_COUNT) as u16 == partition_id && *p != p_old
            })
            .unwrap();
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        write_tombstone(&shell.store, partition_id, p_old, p_new);
        write_tombstone(&shell.store, partition_id, other_old, p_new);
        shell.deps.seed_tile_sink = Arc::new(EmptyAckSink);

        shell
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(p_old, today(), 1)), 7),
                    (SeedWork::Tile(tile_for(other_old, today(), 1)), 8),
                ],
            )
            .await;

        assert_eq!(
            shell.committable(partition_id),
            None,
            "a short ack vector must hold the run, never commit it",
        );
    }

    /// Every seed folds against its own team's catalog, and the register diff runs once per team.
    /// One catalog for the whole run would drop the other team's leaves.
    #[tokio::test]
    async fn a_multi_team_run_diffs_each_teams_registers_against_its_own_catalog() {
        let alice = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &alice, COHORT_PARTITION_COUNT) as u16;
        let bob = (0x5EEEu128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(OTHER_TEAM, p, COHORT_PARTITION_COUNT) as u16 == partition_id)
            .unwrap();
        let mut shell = Shell::with_two_teams(vec![(1, wrap(vec![single_leaf_json(7)]))]);

        shell
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(alice, today(), 1)), 0),
                    (
                        SeedWork::Tile(tile_for_team(OTHER_TEAM, bob, today(), 1)),
                        1,
                    ),
                ],
            )
            .await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 2, "both teams' single-leaf cohorts entered");
        assert_eq!(
            changes
                .iter()
                .map(|change| change.team_id)
                .collect::<BTreeSet<_>>(),
            BTreeSet::from([TEAM.0, OTHER_TEAM.0]),
        );
        assert!(shell.register(partition_id, alice, 1).unwrap().in_cohort);
        assert!(
            Stage2State::decode(
                &shell
                    .store
                    .get_stage2(&Stage2Key {
                        partition_id,
                        team_id: OTHER_TEAM.0 as u64,
                        cohort_id: 1,
                        person_id: bob,
                    })
                    .unwrap()
                    .unwrap()
            )
            .unwrap()
            .in_cohort,
            "the other team's register lands under its own team id",
        );
        assert_eq!(shell.committable(partition_id), Some(2));
    }

    #[test]
    fn a_multi_team_fold_uses_each_teams_day_index() {
        let cohorts = vec![(1, wrap(vec![multiple_leaf_json(1, "gte", 1)]))];
        let late_filters = build_filters_for(TEAM, cohorts.clone(), Kiritimati);
        let early_filters = build_filters_for(OTHER_TEAM, cohorts, GMTPlus12);
        let hash = ConditionHash::parse("0123456789abcdef").unwrap();
        let late_lsk = late_filters.by_condition_to_lsk[&hash.as_bytes()][0];
        let early_lsk = early_filters.by_condition_to_lsk[&hash.as_bytes()][0];
        let late_person = Uuid::from_u128(1);
        let early_person = Uuid::from_u128(2);
        let partition_id = 0;
        let stamp = RunStamp {
            now_ms: NOW_MS,
            last_updated: "fixed".to_string(),
        };
        let early_day = day_idx_in_tz(stamp.now_ms, GMTPlus12);
        assert!(day_idx_in_tz(stamp.now_ms, Kiritimati) > early_day);
        let tile_day = early_day - 1;
        let late_prefix = PersonPrefix::new(partition_id, TEAM.0 as u64, late_person);
        let early_prefix = PersonPrefix::new(partition_id, OTHER_TEAM.0 as u64, early_person);
        let late_lsks = [late_lsk];
        let early_lsks = [early_lsk];
        let local = vec![
            LocalTile {
                tile: tile_for_team(TEAM, late_person, tile_day, 1),
                person: late_person,
                filters: &late_filters,
                lsks: &late_lsks,
                prefix: late_prefix,
            },
            LocalTile {
                tile: tile_for_team(OTHER_TEAM, early_person, tile_day, 1),
                person: early_person,
                filters: &early_filters,
                lsks: &early_lsks,
                prefix: early_prefix,
            },
        ];
        let keys = vec![
            late_prefix.behavioral_key(late_lsk),
            early_prefix.behavioral_key(early_lsk),
        ];
        let overlay = Overlay::from_read(ApplyStage::Read, keys, vec![None, None], |_| {
            Decoded::Corrupt
        })
        .unwrap();

        let folded = fold_tiles(
            OffsetSpan {
                first: SeedOffset(0),
                last: SeedOffset(1),
            },
            local,
            Vec::new(),
            overlay,
            &stamp,
            Tally::default(),
        );

        assert!(
            !folded.leaves.contains_key(&TEAM),
            "the late timezone has already elapsed the tile",
        );
        assert_eq!(
            folded.leaves[&OTHER_TEAM][0].person_id, early_person,
            "the early timezone still includes the tile",
        );
        assert!(folded.leaves[&OTHER_TEAM][0].in_cohort);
    }

    /// A composed change carries the run of the last seed that touched the person, in offset
    /// order. Picking it in leaf-key order would stamp whichever leaf happens to sort last, so the
    /// test runs both orders: one of them is the key order, and both must answer alike. The
    /// register diff's lagging pass walks the same leaves in key order after the fold, so it must
    /// not move the provenance either.
    #[tokio::test]
    async fn a_composed_change_carries_the_run_of_the_last_seed_by_offset() {
        const FIRST_HASH: &str = "0123456789abcdef";
        const SECOND_HASH: &str = "fedcba0123456789";
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        // Each hash also backs a single-leaf cohort, so the register diff finds the person's rows
        // lagging (absent) and revisits their leaves after the fold has spoken.
        let cohorts = vec![
            (
                1,
                wrap(vec![
                    single_leaf_json_with(FIRST_HASH, 7),
                    single_leaf_json_with(SECOND_HASH, 7),
                ]),
            ),
            (2, wrap(vec![single_leaf_json_with(FIRST_HASH, 7)])),
            (3, wrap(vec![single_leaf_json_with(SECOND_HASH, 7)])),
        ];

        for [earlier, later] in [[FIRST_HASH, SECOND_HASH], [SECOND_HASH, FIRST_HASH]] {
            let mut shell = Shell::new(cohorts.clone());
            shell
                .run_batch(
                    partition_id,
                    vec![
                        (
                            SeedWork::Tile(tile_from_run(person, earlier, 0xA, today())),
                            0,
                        ),
                        (
                            SeedWork::Tile(tile_from_run(person, later, 0xB, today())),
                            1,
                        ),
                    ],
                )
                .await;

            let changes = shell.sink.changes();
            let composed: Vec<_> = changes
                .iter()
                .filter(|change| change.cohort_id == 1)
                .collect();
            assert_eq!(
                (changes.len(), composed.len()),
                (3, 1),
                "both single-leaf cohorts entered and the composed cohort flipped once",
            );
            assert_eq!(
                composed[0].run_id,
                Some(RunId(Uuid::from_u128(0xB))),
                "the later seed by offset owns the composed flip, whichever leaf sorts last",
            );
        }
    }

    /// `OffsetTracker::defer` panics on a second defer of one offset in a tenure. A held run
    /// followed by a reconcile must not turn its redelivery into that panic.
    #[tokio::test]
    async fn a_held_run_replayed_across_a_reconcile_seed_does_not_double_defer() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::with_sink(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        shell.deps.reconcile.enabled = true;
        let batch = || {
            vec![
                (SeedWork::Tile(tile_for(person, today(), 1)), 4),
                (SeedWork::Reconcile(reconcile_for(1, 1)), 5),
            ]
        };

        shell.run_batch(partition_id, batch()).await;
        assert_eq!(shell.committable(partition_id), None);
        assert_eq!(shell.reconcile_queue.len(), 1);

        // A new tenure clears the deferral, then the whole batch is redelivered.
        shell.restart();
        shell.run_batch(partition_id, batch()).await;

        assert_eq!(shell.sink.changes().len(), 1);
        assert_eq!(shell.reconcile_queue.len(), 1);
        assert_eq!(
            shell.committable(partition_id),
            Some(5),
            "the reconcile still pins the floor at its own deferred offset",
        );
    }

    /// A non-member downstream was never told about gets no register row: nothing downstream
    /// needs one, and a reconcile page has nothing to repair for it. The Unchanged replay is just
    /// as silent.
    #[tokio::test]
    async fn a_never_told_non_member_seed_writes_no_register_and_emits_nothing() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::new(vec![(1, wrap(vec![multiple_leaf_json(7, "gte", 3)]))]);
        let tile = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 0)
            .await;
        assert!(shell.register(partition_id, person, 1).is_none());
        assert!(shell.sink.changes().is_empty());

        shell.run(partition_id, SeedWork::Tile(tile), 1).await;
        assert!(shell.register(partition_id, person, 1).is_none());
        assert!(shell.sink.changes().is_empty());
        assert_eq!(shell.committable(partition_id), Some(2));
    }

    #[tokio::test]
    async fn unknown_team_and_unreferenced_hash_are_counted_drops_that_still_commit() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;

        // No cohorts at all: the team resolves but the hash references nothing.
        let mut shell = Shell::new(vec![]);
        shell
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, today(), 1)),
                3,
            )
            .await;
        assert!(shell.sink.changes().is_empty());
        assert_eq!(
            shell.committable(partition_id),
            Some(4),
            "a design-expected drop must not wedge the partition",
        );
    }

    fn write_tombstone(store: &CohortStore, partition_id: u16, old: Uuid, new: Uuid) {
        store
            .write_batch(|b| {
                b.put_tombstone(
                    &TombstoneKey {
                        partition_id,
                        team_id: TEAM.0 as u64,
                        person: old,
                    },
                    &Tombstone {
                        new_person: new,
                        merged_at_ms: 1,
                    }
                    .encode(),
                )
            })
            .unwrap();
    }

    fn cross_partition_pair() -> (Uuid, u16, Uuid) {
        let p_old = Uuid::from_u128(1);
        let partition_id = partition_of(TEAM, &p_old, COHORT_PARTITION_COUNT) as u16;
        let p_new = (10u128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TEAM, p, COHORT_PARTITION_COUNT) as u16 != partition_id)
            .expect("some uuid hashes off p_old's partition");
        (p_old, partition_id, p_new)
    }

    #[tokio::test]
    async fn inline_redirect_applies_the_tile_at_the_survivor() {
        let p_old = Uuid::from_u128(0xA11CE);
        let partition_id = partition_of(TEAM, &p_old, COHORT_PARTITION_COUNT) as u16;
        let p_new = (10u128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TEAM, p, COHORT_PARTITION_COUNT) as u16 == partition_id)
            .unwrap();
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        write_tombstone(&shell.store, partition_id, p_old, p_new);

        shell
            .run(partition_id, SeedWork::Tile(tile_for(p_old, today(), 1)), 0)
            .await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1);
        assert_eq!(
            changes[0].person_id,
            p_new.to_string(),
            "membership lands on the survivor, not the dead person",
        );
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    #[tokio::test]
    async fn cross_partition_redirect_re_produces_the_rekeyed_tile_before_marking() {
        let (p_old, partition_id, p_new) = cross_partition_pair();
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        write_tombstone(&shell.store, partition_id, p_old, p_new);
        let tile = tile_for(p_old, today(), 2);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 7)
            .await;

        let produced = shell.seed_sink.tiles();
        assert_eq!(produced.len(), 1, "one re-keyed tile produced");
        assert_eq!(produced[0].person_id(), p_new);
        assert_eq!(produced[0].redirect_hops(), 1);
        assert_eq!(produced[0].s_chunk_ms(), tile.s_chunk_ms());
        assert!(shell.sink.changes().is_empty(), "no local apply");
        assert_eq!(
            shell.committable(partition_id),
            Some(8),
            "the acked re-produce releases the seed offset",
        );
    }

    #[tokio::test]
    async fn rekey_produce_failure_holds_the_seed_offset_until_a_later_success() {
        let (p_old, partition_id, p_new) = cross_partition_pair();
        let mut shell = Shell::with_sink(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            CaptureSink::new(),
            CaptureSeedTileSink::failing_first(1),
        );
        write_tombstone(&shell.store, partition_id, p_old, p_new);
        let tile = tile_for(p_old, today(), 2);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 7)
            .await;
        assert_eq!(
            shell.committable(partition_id),
            None,
            "the failed re-produce holds the seed offset",
        );

        // Redelivery with the sink healthy: the re-key lands and the hold is honored by the floor.
        shell.run(partition_id, SeedWork::Tile(tile), 7).await;
        assert_eq!(shell.seed_sink.tiles().len(), 1);
        // The tenure-sticky hold pins the committable at the held offset (redelivery replays it).
        assert_eq!(shell.committable(partition_id), Some(7));
    }

    #[tokio::test]
    async fn hop_capped_tile_applies_inline_at_the_best_known_target() {
        let (p_old, partition_id, p_new) = cross_partition_pair();
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        write_tombstone(&shell.store, partition_id, p_old, p_new);

        // Exhaust the hop budget on the wire, then deliver: rekeyed_to returns None at the cap.
        let mut tile = tile_for(p_old, today(), 1);
        for _ in 0..MAX_CROSS_PARTITION_REDIRECT_HOPS {
            tile = tile
                .rekeyed_to(p_old, MAX_CROSS_PARTITION_REDIRECT_HOPS)
                .unwrap();
        }
        shell.run(partition_id, SeedWork::Tile(tile), 0).await;

        assert!(shell.seed_sink.tiles().is_empty(), "no further re-produce");
        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1, "applied inline instead");
        assert_eq!(changes[0].person_id, p_new.to_string());
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    /// Zero acks treated as success (the vacuous `all(is_ok)` on `[]`) would commit past a tile
    /// that was never re-produced.
    struct EmptyAckSink;

    #[async_trait::async_trait]
    impl crate::producer::SeedTileSink for EmptyAckSink {
        async fn produce(
            &self,
            _tiles: Vec<SeedTile>,
        ) -> Vec<Result<(), common_kafka::kafka_producer::KafkaProduceError>> {
            Vec::new()
        }

        async fn produce_person(
            &self,
            _seeds: Vec<PersonSeed>,
        ) -> Vec<Result<(), common_kafka::kafka_producer::KafkaProduceError>> {
            Vec::new()
        }
    }

    #[tokio::test]
    async fn an_empty_rekey_ack_vector_is_a_failure_not_a_vacuous_success() {
        let (p_old, partition_id, p_new) = cross_partition_pair();
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        write_tombstone(&shell.store, partition_id, p_old, p_new);
        shell.deps.seed_tile_sink = Arc::new(EmptyAckSink);

        shell
            .run(partition_id, SeedWork::Tile(tile_for(p_old, today(), 1)), 7)
            .await;

        assert_eq!(
            shell.committable(partition_id),
            None,
            "zero acks must hold the offset, never commit it",
        );
        assert!(shell.sink.changes().is_empty(), "no local apply either");
    }

    /// Stage 1 committed, then the membership produce failed. The redelivery merges to
    /// `Unchanged` and mints no transition, so only the register diff can tell that downstream was
    /// never told and re-emit.
    #[tokio::test]
    async fn membership_produce_failure_holds_and_the_redelivery_re_emits_the_single_leaf_change() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::with_sink(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        let tile = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 4)
            .await;

        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        assert!(shell.sink.changes().is_empty());
        assert_eq!(
            shell
                .register(partition_id, person, 1)
                .map(|state| state.in_cohort),
            Some(false),
            "the row exists for the reconcile scan, but reads `false`: downstream was never told",
        );

        shell.restart();
        shell.run(partition_id, SeedWork::Tile(tile), 4).await;

        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            1,
            "the redelivery re-derived the lost change"
        );
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].origin, Some(ChangeOrigin::Seed));
        assert!(
            shell.register(partition_id, person, 1).unwrap().in_cohort,
            "the bit advances once the produce acks",
        );
        assert_eq!(
            downstream(&changes),
            BTreeMap::from([((1, person.to_string()), MembershipStatus::Entered)]),
        );
        assert_eq!(shell.committable(partition_id), Some(5));
    }

    /// Acks the first record of one batch and fails the rest, which is what a broker does when
    /// its queue fills mid-batch. The acked record lands in the wrapped capture, so the model
    /// sees exactly what downstream got.
    #[derive(Clone)]
    struct PartialAckSink {
        inner: CaptureSink,
        split_next: Arc<std::sync::atomic::AtomicBool>,
    }

    #[async_trait::async_trait]
    impl MembershipSink for PartialAckSink {
        async fn produce(
            &self,
            changes: Vec<CohortMembershipChange>,
        ) -> Vec<Result<(), common_kafka::kafka_producer::KafkaProduceError>> {
            if !self
                .split_next
                .swap(false, std::sync::atomic::Ordering::SeqCst)
            {
                return self.inner.produce(changes).await;
            }
            let mut acks = Vec::with_capacity(changes.len());
            for (index, change) in changes.into_iter().enumerate() {
                if index == 0 {
                    acks.extend(self.inner.produce(vec![change]).await);
                } else {
                    acks.push(Err(
                        common_kafka::kafka_producer::KafkaProduceError::KafkaProduceCanceled,
                    ));
                }
            }
            acks
        }
    }

    /// One record of the batch acked, the rest failed. No bit advances, so the redelivery re-emits
    /// the whole batch and downstream converges on the store's truth.
    #[tokio::test]
    async fn a_partially_acked_produce_holds_and_the_redelivery_re_emits_the_whole_batch() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        // Two single-leaf cohorts on one leaf, so one tile produces a two-record batch.
        let mut shell = Shell::new(vec![
            (1, wrap(vec![single_leaf_json(7)])),
            (2, wrap(vec![single_leaf_json(7)])),
        ]);
        shell.membership = Arc::new(PartialAckSink {
            inner: shell.sink.clone(),
            split_next: Arc::new(std::sync::atomic::AtomicBool::new(true)),
        });
        let tile = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 4)
            .await;

        assert_eq!(shell.sink.changes().len(), 1, "only cohort 1 acked");
        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        for cohort_id in [1, 2] {
            assert_eq!(
                shell
                    .register(partition_id, person, cohort_id)
                    .map(|state| state.in_cohort),
                Some(false),
                "cohort {cohort_id}: a partial ack advances no bit at all",
            );
        }

        shell.restart();
        shell.run(partition_id, SeedWork::Tile(tile), 4).await;

        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            3,
            "the acked record duplicates, the failed one lands"
        );
        assert_eq!(
            downstream(&changes),
            BTreeMap::from([
                ((1, person.to_string()), MembershipStatus::Entered),
                ((2, person.to_string()), MembershipStatus::Entered),
            ]),
            "the model matches the store's truth for both cohorts",
        );
        assert!(shell.register(partition_id, person, 1).unwrap().in_cohort);
        assert!(shell.register(partition_id, person, 2).unwrap().in_cohort);
    }

    /// Membership acked, then the cascade leg failed. The single-leaf change is re-emitted with
    /// its cascade, so a cohort-of-cohort referrer is not left stale.
    #[tokio::test]
    async fn a_failed_cascade_re_emits_the_single_leaf_change_and_its_cascade_on_redelivery() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::with_cascade(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            crate::producer::CaptureCascadeSink::failing_first(1),
        );
        let tile = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 3)
            .await;

        assert_eq!(shell.sink.changes().len(), 1, "membership is the first leg");
        assert!(shell.cascade_sink.messages().is_empty());
        assert_eq!(shell.committable(partition_id), None, "held for redelivery");

        shell.restart();
        shell.run(partition_id, SeedWork::Tile(tile), 3).await;

        assert_eq!(shell.sink.changes().len(), 2, "the change re-emits with it");
        let cascades = shell.cascade_sink.messages();
        assert_eq!(cascades.len(), 1, "the lost single-leaf cascade lands");
        assert_eq!(cascades[0].change.cohort_id, 1);
        assert_eq!(cascades[0].change.origin, Some(ChangeOrigin::Seed));
    }

    /// A later tile on the same leaf advances the register before the held one is redelivered, so
    /// the redelivery has nothing to repair. Over-emission is the fix's own failure mode.
    #[tokio::test]
    async fn a_later_tiles_ack_silences_the_held_tiles_redelivery() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::with_sink(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        let held = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(held.clone()), 4)
            .await;
        assert!(shell.sink.changes().is_empty(), "held before any emission");

        // A hold pauses nothing, so the next tile on the partition still applies and acks.
        shell
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, today() - 1, 1)),
                5,
            )
            .await;
        assert_eq!(shell.sink.changes().len(), 1);

        shell.restart();
        shell.run(partition_id, SeedWork::Tile(held), 4).await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1, "the register already matched the truth");
        assert_eq!(
            downstream(&changes),
            BTreeMap::from([((1, person.to_string()), MembershipStatus::Entered)]),
        );
    }

    /// A cohort added over leaf state that predates it has no register row, so the next tile on
    /// that leaf tells downstream even though the merge is a no-op. Nothing minted a transition
    /// for this person, which is why only a register diff can reach the case.
    #[tokio::test]
    async fn a_cohort_added_over_existing_leaf_state_enters_on_the_next_unchanged_tile() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        let tile = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 0)
            .await;
        assert_eq!(shell.sink.changes().len(), 1, "cohort 1 entered");

        // Cohort 2 arrives keyed on the same leaf, over state it never saw evaluated.
        shell.catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
            TEAM,
            build_filters(
                vec![
                    (1, wrap(vec![single_leaf_json(7)])),
                    (2, wrap(vec![single_leaf_json(7)])),
                ],
                UTC,
            ),
        )])));

        shell.run(partition_id, SeedWork::Tile(tile), 1).await;

        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            2,
            "the replay is Unchanged but cohort 2 is new"
        );
        assert_eq!(changes[1].cohort_id, 2);
        assert_eq!(changes[1].status, MembershipStatus::Entered);
        assert!(shell.register(partition_id, person, 2).unwrap().in_cohort);
        assert_eq!(shell.committable(partition_id), Some(2));
    }

    /// Membership acked, then the cascade leg failed, then a later tile in the same tenure retracts
    /// the leaf. The register still reads the `false` the held apply pre-wrote and never advanced,
    /// so a register-only diff would read `false == false` and stay silent; the minted `Left` is
    /// what retires the entry downstream holds, and the redelivery then has nothing to repair.
    #[tokio::test]
    async fn a_minted_retraction_is_emitted_after_an_acked_entry_held_on_its_cascade() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        // `lte 3`: one event is a member, nine are not.
        let mut shell = Shell::with_cascade(
            vec![(1, wrap(vec![multiple_leaf_json(7, "lte", 3)]))],
            crate::producer::CaptureCascadeSink::failing_first(1),
        );

        shell
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, today(), 1)),
                0,
            )
            .await;
        assert_eq!(
            shell.sink.changes().len(),
            1,
            "the Entered acked downstream"
        );
        assert_eq!(shell.committable(partition_id), None, "held on the cascade");
        assert_eq!(
            shell
                .register(partition_id, person, 1)
                .map(|state| state.in_cohort),
            Some(false),
            "the bit never advanced past the failed cascade",
        );

        // A hold pauses nothing: the next tile on the partition still applies, and stage 1 mints
        // `Left` because the count now exceeds the comparator.
        shell
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, today(), 9)),
                1,
            )
            .await;
        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 2, "the retraction is emitted");
        assert_eq!(changes[1].status, MembershipStatus::Left);

        // The redelivery merges to `Unchanged`, mints nothing, and finds the register in agreement.
        shell.restart();
        shell
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, today(), 1)),
                0,
            )
            .await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 2, "nothing left to repair");
        assert_eq!(
            downstream(&changes),
            BTreeMap::from([((1, person.to_string()), MembershipStatus::Left)]),
        );
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    /// A reconcile page drained over a held tile finds the row stage 1 recorded and repairs it,
    /// which is why an emitting apply records its row before the produce. The redelivery then
    /// finds the register in agreement and stays silent.
    #[tokio::test]
    async fn a_reconcile_page_repairs_a_held_tile_and_its_redelivery_is_silent() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::with_sink(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        shell.deps.reconcile.enabled = true;
        // The reconcile guard pins the run to the cohort's behavioral shape.
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TEAM, &wrap(vec![single_leaf_json(7)]))
            .unwrap();
        builder.set_behavioral_shape_hash(
            CohortId(1),
            BehavioralShapeHash::parse("0123456789abcdef").unwrap(),
        );
        shell.catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
            TEAM,
            builder.freeze(UTC),
        )])));
        let tile = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 4)
            .await;
        assert!(shell.sink.changes().is_empty(), "held before any emission");
        assert_eq!(
            shell
                .register(partition_id, person, 1)
                .map(|state| state.in_cohort),
            Some(false),
            "the row the page has to find",
        );

        shell
            .run(partition_id, SeedWork::Reconcile(reconcile_for(1, 1)), 5)
            .await;
        shell.drain_reconcile(partition_id).await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1, "the page found the row and repaired it");
        assert_eq!(changes[0].origin, Some(ChangeOrigin::Reconcile));
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert!(shell.register(partition_id, person, 1).unwrap().in_cohort);

        shell.restart();
        shell.run(partition_id, SeedWork::Tile(tile), 4).await;

        assert_eq!(
            shell.sink.changes().len(),
            1,
            "nothing left for the redelivery to repair"
        );
        assert_eq!(shell.committable(partition_id), Some(5));
    }

    /// A seeded flip that never cascades leaves cohort-of-cohort referrers permanently stale.
    #[tokio::test]
    async fn seed_flip_with_cascade_on_produces_a_first_hop_cascade() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let cascade_sink = crate::producer::CaptureCascadeSink::new();
        let mut shell = Shell::with_cascade(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            cascade_sink.clone(),
        );
        let tile = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 3)
            .await;

        assert_eq!(shell.sink.changes().len(), 1, "the cohort entered");
        let cascades = shell.cascade_sink.messages();
        assert_eq!(cascades.len(), 1, "one first-hop cascade for the flip");
        assert_eq!(cascades[0].change.cohort_id, 1);
        assert_eq!(cascades[0].depth, 1);
        assert_eq!(cascades[0].originating_cohort_id, 1);
        assert_eq!(
            cascades[0].change.origin,
            Some(ChangeOrigin::Seed),
            "the embedded change keeps its backfill provenance",
        );
        assert_eq!(
            shell.committable(partition_id),
            Some(4),
            "both acked produces release the seed offset",
        );

        // Re-delivery is Unchanged: no duplicate flip, no duplicate cascade.
        shell.run(partition_id, SeedWork::Tile(tile), 4).await;
        assert_eq!(shell.cascade_sink.messages().len(), 1);
        assert_eq!(shell.committable(partition_id), Some(5));
    }

    /// A failed cascade produce leaves the stage-2 bit unwritten, so the redelivery re-derives
    /// the composed flip and re-emits its cascade.
    #[tokio::test]
    async fn failed_composed_cascade_is_re_derived_and_emitted_on_redelivery() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        // Both leaves satisfied by one tile, so the flip is stage-2-derived.
        let mut shell = Shell::with_cascade(
            vec![(
                1,
                wrap(vec![single_leaf_json(7), multiple_leaf_json(7, "gte", 1)]),
            )],
            crate::producer::CaptureCascadeSink::failing_first(1),
        );
        let tile = tile_for(person, today(), 1);
        let stage2_key = Stage2Key {
            partition_id,
            team_id: TEAM.0 as u64,
            cohort_id: 1,
            person_id: person,
        };

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 3)
            .await;
        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        assert!(shell.cascade_sink.messages().is_empty());
        assert!(
            shell.store.get_stage2(&stage2_key).unwrap().is_none(),
            "the stage-2 bit must stay unwritten under the failed produce",
        );

        shell.run(partition_id, SeedWork::Tile(tile), 3).await;
        let cascades = shell.cascade_sink.messages();
        assert_eq!(
            cascades.len(),
            1,
            "the redelivery re-derived the flip and produced its cascade",
        );
        assert_eq!(cascades[0].change.cohort_id, 1);
        assert_eq!(
            shell.sink.changes().len(),
            2,
            "the re-derived membership change re-emits too (a LWW-safe duplicate)",
        );
        assert!(
            Stage2State::decode(&shell.store.get_stage2(&stage2_key).unwrap().unwrap())
                .unwrap()
                .in_cohort,
            "the bit commits once both produces ack",
        );
        // The tenure-sticky hold pins the committable at the held offset (redelivery replays it).
        assert_eq!(shell.committable(partition_id), Some(3));
    }

    #[tokio::test]
    async fn seed_cascade_produce_failure_holds_the_seed_offset() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::with_cascade(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            crate::producer::CaptureCascadeSink::failing_always(),
        );

        shell
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, today(), 1)),
                3,
            )
            .await;

        assert_eq!(
            shell.sink.changes().len(),
            1,
            "membership is the first leg and acked before the cascade leg",
        );
        assert!(shell.cascade_sink.messages().is_empty());
        assert_eq!(
            shell.committable(partition_id),
            None,
            "a failed cascade produce holds the seed offset for redelivery",
        );
    }

    /// Stage-1 committed but stage-2 lost: the replayed tile lands `Unchanged`, yet composition
    /// re-runs for every touched leaf and heals the stale bit.
    #[tokio::test]
    async fn unchanged_replay_recomposes_stage2_and_heals_a_stale_bit() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        // Both leaves share the tile's hash, so one tile flips the composition.
        let mut shell = Shell::new(vec![(
            1,
            wrap(vec![single_leaf_json(7), multiple_leaf_json(7, "gte", 1)]),
        )]);
        let tile = tile_for(person, today(), 1);

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 0)
            .await;
        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1, "the composed cohort entered");
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].origin, Some(ChangeOrigin::Seed));

        // Simulate the crash window: the stage-2 bit rolls back while cf_behavioral stands.
        let stage2_key = Stage2Key {
            partition_id,
            team_id: TEAM.0 as u64,
            cohort_id: 1,
            person_id: person,
        };
        shell
            .store
            .write_batch(|b| {
                b.put_stage2(
                    &stage2_key,
                    &Stage2State {
                        in_cohort: false,
                        last_evaluated_at_ms: 1,
                    }
                    .encode(),
                )
            })
            .unwrap();

        shell.run(partition_id, SeedWork::Tile(tile), 1).await;
        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            2,
            "the Unchanged replay still re-composed and re-emitted the flip",
        );
        assert_eq!(changes[1].status, MembershipStatus::Entered);
        assert_eq!(changes[1].origin, Some(ChangeOrigin::Seed));
    }
}
