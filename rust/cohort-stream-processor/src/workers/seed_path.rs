//! The seed-tile apply path: a pure, clock-free core ([`merge_tile_into_leaf`]) that mirrors the
//! live fold minus dedup (slide-before-evaluate, max-merge of the tile's absolute count,
//! structural-equality `Unchanged` — the whole of tile idempotency), and a batched imperative shell
//! ([`apply_tile_batch`]) ordered produce single-leaf output → stage-1 commit → stage-2 recompose →
//! produce composed output → produce cascades → stage-2 commit → mark. Every produce acks before
//! the state it reports commits, so a failed produce replays with that state either untouched
//! (single-leaf) or re-derivable (composed); store/produce failures hold the batch's first seed
//! offset.

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::num::NonZeroU32;
use std::sync::Arc;

use chrono::Utc;
use chrono_tz::Tz;
use metrics::{counter, gauge};
use tracing::{debug, warn};
use uuid::Uuid;

use cohort_core::seed::{PersonSeed, ReconcileTile, RunId, SeedTile};

use crate::filters::reverse_index::{LeafStateMeta, TeamFilters};
use crate::filters::{FilterCatalog, TeamId};
use crate::merge::tombstone_redirect::{self, Resolution, MAX_CROSS_PARTITION_REDIRECT_HOPS};
use crate::observability::metrics::{
    COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH, RECONCILE_JOBS_ENQUEUED_TOTAL,
    RECONCILE_JOBS_SUPERSEDED_TOTAL, SEED_HELD_OFFSET_GAUGE, SEED_REKEY_HOP_CAPPED_TOTAL,
    SEED_TILES_APPLIED_TOTAL, SEED_TILES_DROPPED_TOTAL, SEED_TILES_SKIPPED_TOTAL,
    SEED_TILES_UNCHANGED_TOTAL, STAGE1_STATE_DECODE_ERROR, STAGE1_TRANSITIONS,
};
use crate::partitions::offset_tracker::{MarkOutcome, OffsetTracker};
use crate::producer::{map_transition, ChangeOrigin, CohortMembershipChange, LastUpdatedClock};
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
use crate::stage2::{
    leaf_membership, single_leaf_register_writes, stage_register_writes, MembershipRegisterSource,
};
use crate::store::{Behavioral, BehavioralKey, PersonPrefix, ReadLane, StagedBatch};
use crate::sweep::EvictionQueue;
use crate::workers::merge_path::MergeWorkerDeps;
use crate::workers::reconcile::{ReconcileQueue, SupersedeOutcome};
use crate::workers::seed_batch::{
    produce_cascade_output, produce_composed_output, produce_leaf_output, recompose_batch, settle,
    Admitted, ApplyStage, BatchRecompose, SeedApplyDeps, SeedHold, SeedKind, SeedOffset,
    SeedReKeys, SeedRun, StageClock, TouchedPersons,
};
use crate::workers::stage2_path::commit_stage2_writes;
use crate::workers::worker::{first_cascades, transition_metric_label};

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
    prev: Option<StatefulRecord>,
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
    prev: Option<StatefulRecord>,
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

    let prev_state = prev.as_ref().map(|record| record.state.clone());
    let (prev_last, predicate_before, applied, redirect) = match prev {
        None => (i64::MIN, false, Default::default(), Default::default()),
        Some(record) => {
            let before = predicate(&record.state);
            match record.state {
                Stage1State::BehavioralSingle {
                    last_event_at_ms, ..
                } => (
                    last_event_at_ms,
                    before,
                    record.applied_offsets,
                    record.redirect_dedup,
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
        prev_state,
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
    prev: Option<StatefulRecord>,
    now_day: DayIdx,
) -> LeafMergeOutcome {
    let (Some(window_days), Some(op)) = (window_days, op) else {
        return LeafMergeOutcome::Dropped(SeedDropReason::MetaIncomplete);
    };
    let len = daily_bucket_len(window_days);

    let prev_state = prev.as_ref().map(|record| record.state.clone());
    let (prior, predicate_before, applied, redirect) = match prev {
        None => (None, false, Default::default(), Default::default()),
        Some(record) => match record.state {
            Stage1State::BehavioralDailyBuckets {
                buckets,
                window_start_day,
                last_event_at_ms,
                ..
            } => {
                let before = daily_predicate(&buckets, op);
                (
                    Some((buckets, window_start_day, last_event_at_ms)),
                    before,
                    record.applied_offsets,
                    record.redirect_dedup,
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
        prev_state,
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
    prev: Option<StatefulRecord>,
    now_day: DayIdx,
) -> LeafMergeOutcome {
    let (Some(window_days), Some(op)) = (window_days, op) else {
        return LeafMergeOutcome::Dropped(SeedDropReason::MetaIncomplete);
    };

    let prev_state = prev.as_ref().map(|record| record.state.clone());
    let (prior, predicate_before, applied, redirect) = match prev {
        None => (None, false, Default::default(), Default::default()),
        Some(record) => match record.state {
            Stage1State::BehavioralCompressedHistory {
                entries,
                window_start_day,
                last_event_at_ms,
                ..
            } => {
                let before = compressed_predicate(&entries, op);
                (
                    Some((entries, window_start_day, last_event_at_ms)),
                    before,
                    record.applied_offsets,
                    record.redirect_dedup,
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
        prev_state,
        record,
        predicate_before,
        predicate_after,
        earliest_eviction_at_ms,
    )
}

/// `Unchanged` detection + transition minting shared by all three variants.
fn finish(
    identity: LeafIdentity,
    prev_state: Option<Stage1State>,
    record: StatefulRecord,
    predicate_before: bool,
    predicate_after: bool,
    deadline_ms: i64,
) -> LeafMergeOutcome {
    if prev_state.as_ref() == Some(&record.state) {
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

/// Apply one run of day-tiles as a unit, then mark its whole span or hold its first offset.
///
/// The run pays one batched tombstone resolve, one batched state read, one produce of its
/// single-leaf output, one stage-1 commit, one stage-2 recompose over the deduplicated leaves, one
/// produce of its composed output, one produce of its cascades and one stage-2 commit — whatever
/// its length. A held run replays cleanly: a leaf-leg failure committed nothing, and stage 1 is
/// idempotent through max-merge while the stage-2 bits land only after every produce acks, so a
/// later failure re-derives the composed flips.
pub(crate) async fn apply_tile_batch(
    deps: &SeedApplyDeps<'_>,
    queue: &mut EvictionQueue<BehavioralKey>,
    clock: &mut LastUpdatedClock,
    run: SeedRun<SeedTile>,
) {
    let span = run.span();
    let mut stages = StageClock::start(SeedKind::Tile, run.len());
    let outcome = apply_tiles(deps, queue, clock, &mut stages, &run).await;
    settle(deps, SeedKind::Tile, span, outcome);
}

/// The ordered apply. Every `?` leaves durable state either untouched or idempotently re-appliable,
/// which is what lets the caller turn one `Err` into one hold.
async fn apply_tiles(
    deps: &SeedApplyDeps<'_>,
    queue: &mut EvictionQueue<BehavioralKey>,
    clock: &mut LastUpdatedClock,
    stages: &mut StageClock,
    run: &SeedRun<SeedTile>,
) -> Result<(), SeedHold> {
    let snapshot = deps.catalog.load();

    let RoutedTiles { locals, re_keys } = route_tiles(deps, &snapshot, run.items()).await?;
    stages.mark(ApplyStage::Resolve);

    let mut overlay = read_leaf_slots(deps, &locals).await?;
    stages.mark(ApplyStage::Read);

    // One instant for the whole run: `last_evaluated_at_ms` is a freshness stamp, and every tile in
    // the run slides against the same "now".
    let now_ms = Utc::now().timestamp_millis();
    let FoldedTiles {
        changes: leaf_changes,
        touched,
        schedules,
    } = fold_tiles(&locals, &mut overlay, clock, now_ms);
    stages.mark(ApplyStage::Fold);

    // Cascades ride the last leg, so every membership change is acked before any referrer hears
    // of it; built here from a borrow, before the changes move into their produce.
    let source_offset = run.span().last.0;
    let mut cascades = first_cascades(deps.merge, &leaf_changes, source_offset);
    produce_leaf_output(deps, leaf_changes, SeedReKeys::Tiles(re_keys)).await?;
    stages.mark(ApplyStage::ProduceLeaf);

    commit_tile_stage1(deps, &overlay, now_ms).await?;
    stages.mark(ApplyStage::Stage1Commit);
    // The rows are durable from here, so their deadlines are owed whatever the later legs do.
    for (key, deadline) in schedules {
        queue.schedule(key, deadline);
    }

    let BatchRecompose {
        changes: composed,
        writes: stage2_writes,
        counts: stage2_counts,
    } = recompose_batch(deps, &snapshot, touched, now_ms, clock).await?;
    stages.mark(ApplyStage::Recompute);

    cascades.extend(first_cascades(deps.merge, &composed, source_offset));
    produce_composed_output(deps, composed).await?;
    stages.mark(ApplyStage::ProduceComposed);

    produce_cascade_output(deps, cascades).await?;
    stages.mark(ApplyStage::ProduceCascades);

    commit_stage2_writes(deps.handle, &stage2_writes)
        .await
        .map_err(SeedHold::store(ApplyStage::Stage2Commit))?;
    stages.mark(ApplyStage::Stage2Commit);
    stage2_counts.record();
    Ok(())
}

/// One tile that applies on this partition, with everything its fold needs resolved once.
struct LocalTile<'a> {
    tile: &'a SeedTile,
    /// The tombstone chain's survivor, or the tile's own person when nothing merged.
    person: Uuid,
    filters: Arc<TeamFilters>,
    /// The leaves this tile's condition still resolves to. Never empty: a tile that references none
    /// is dropped during routing.
    lsks: Vec<LeafStateKey>,
    /// This tile's slice of the store, resolved once. The read pass and the fold both key off it,
    /// so neither can build a key the other does not have.
    prefix: PersonPrefix,
}

struct RoutedTiles<'a> {
    locals: Vec<LocalTile<'a>>,
    /// Tiles whose survivor lives on another partition, handed back to the seed topic.
    re_keys: Vec<SeedTile>,
}

/// Resolve the run's tombstones in one read and split it into local applies and hand-offs.
async fn route_tiles<'a>(
    deps: &SeedApplyDeps<'_>,
    snapshot: &FilterCatalog,
    tiles: &'a [Admitted<SeedTile>],
) -> Result<RoutedTiles<'a>, SeedHold> {
    let mut known: Vec<(&SeedTile, Arc<TeamFilters>)> = Vec::with_capacity(tiles.len());
    let mut persons: Vec<(TeamId, Uuid)> = Vec::new();
    let mut seen: HashSet<(TeamId, Uuid)> = HashSet::new();
    for Admitted { work: tile, .. } in tiles {
        let Some(filters) = snapshot.team(tile.team_id()) else {
            counter!(SEED_TILES_DROPPED_TOTAL, "reason" => "team_absent").increment(1);
            continue;
        };
        if seen.insert((tile.team_id(), tile.person_id())) {
            persons.push((tile.team_id(), tile.person_id()));
        }
        known.push((tile, filters.clone()));
    }

    // A read failure is fail-stop: a tile mis-applied to a merged-away person is durable state
    // reconcile cannot retract.
    let resolutions = tombstone_redirect::resolve_batch_offloaded(
        deps.handle,
        deps.partition_id,
        &persons,
        deps.merge.partition_count,
        ReadLane::Maintenance,
    )
    .await
    .map_err(SeedHold::store(ApplyStage::Resolve))?;

    let mut routed = RoutedTiles {
        locals: Vec::with_capacity(known.len()),
        re_keys: Vec::new(),
    };
    for (tile, filters) in known {
        let Some(&resolution) = resolutions.get(&(tile.team_id(), tile.person_id())) else {
            return Err(SeedHold::ShortRead {
                stage: ApplyStage::Resolve,
                asked: persons.len(),
                answered: resolutions.len(),
            });
        };
        let person = match route_seed(tile, resolution, MAX_CROSS_PARTITION_REDIRECT_HOPS) {
            SeedRoute::ApplyLocal { person } => person,
            SeedRoute::ReProduce { seed: rekeyed } => {
                routed.re_keys.push(rekeyed);
                continue;
            }
            SeedRoute::CapExhausted { person } => {
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
        let lsks = filters
            .by_condition_to_lsk
            .get(&tile.condition_hash().as_bytes())
            .cloned()
            .unwrap_or_default();
        if lsks.is_empty() {
            // Expected for a stale/edited cohort: the hash no longer resolves.
            counter!(SEED_TILES_DROPPED_TOTAL, "reason" => "no_referencing_leaves").increment(1);
            continue;
        }
        routed.locals.push(LocalTile {
            tile,
            person,
            filters,
            lsks,
            prefix: PersonPrefix::new(deps.partition_id, tile.team_id().0 as u64, person),
        });
    }
    Ok(routed)
}

/// One leaf's state inside a run's overlay, so a second tile for the same leaf folds onto the first
/// tile's result instead of the bytes the read pass saw.
enum LeafSlot {
    /// Read from the store, not yet folded into.
    Untouched(Option<StatefulRecord>),
    /// Folded at least once. `write` is what stages the row and its membership registers.
    Touched {
        record: StatefulRecord,
        write: LeafWrite,
        /// Whether any tile in the run actually advanced the state. A run that only ever merged to
        /// `Unchanged` still repairs the membership register, but re-writing a byte-identical
        /// `cf_behavioral` row would spend the store's write budget on nothing — the steady state
        /// of a re-run chunk.
        merged: bool,
    },
    /// Stored bytes that do not decode. Never folded into and never overwritten: rebuilding from an
    /// absent baseline would silently drop whatever the unreadable row held.
    Corrupt,
}

impl LeafSlot {
    fn decode(bytes: Option<Vec<u8>>) -> Self {
        match bytes {
            None => Self::Untouched(None),
            Some(bytes) => match StatefulRecord::decode(&bytes) {
                Ok(record) => Self::Untouched(Some(record)),
                Err(_) => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    Self::Corrupt
                }
            },
        }
    }

    /// The state the next tile merges into.
    fn prev(&self) -> Option<StatefulRecord> {
        match self {
            Self::Untouched(prev) => prev.clone(),
            Self::Touched { record, .. } => Some(record.clone()),
            Self::Corrupt => None,
        }
    }

    /// Whether an earlier tile in this run already advanced the slot's state.
    fn already_merged(&self) -> bool {
        matches!(self, Self::Touched { merged: true, .. })
    }
}

/// What one touched leaf needs to stage its row's single-leaf membership registers.
struct LeafWrite {
    filters: Arc<TeamFilters>,
    meta: LeafStateMeta,
    source: MembershipRegisterSource,
}

#[derive(Default)]
struct FoldedTiles {
    /// Single-leaf membership changes, one `last_updated` per tile that flipped something.
    changes: Vec<CohortMembershipChange>,
    touched: TouchedPersons,
    schedules: Vec<(BehavioralKey, i64)>,
}

/// Fold every tile into the overlay in offset order. Pure apart from its counters: the store is not
/// touched, so a failure later in the pipeline replays this identically.
fn fold_tiles(
    locals: &[LocalTile<'_>],
    overlay: &mut BTreeMap<BehavioralKey, LeafSlot>,
    clock: &mut LastUpdatedClock,
    now_ms: i64,
) -> FoldedTiles {
    let mut folded = FoldedTiles::default();
    for local in locals {
        let filters = local.filters.as_ref();
        let now_day = day_idx_in_tz(now_ms, filters.timezone);
        let mut transitions: Vec<LeafTransition> = Vec::new();

        for &lsk in &local.lsks {
            let Some(meta) = filters.by_lsk.get(&lsk) else {
                counter!(SEED_TILES_DROPPED_TOTAL, "reason" => SeedDropReason::MetaIncomplete.as_str())
                    .increment(1);
                continue;
            };
            let key = local.prefix.behavioral_key(lsk);
            let slot = overlay
                .get_mut(&key)
                .expect("the read pass keyed off the same prefix, so every folded leaf has a slot");
            if matches!(slot, LeafSlot::Corrupt) {
                counter!(SEED_TILES_DROPPED_TOTAL, "reason" => "corrupt_state").increment(1);
                continue;
            }

            let identity = LeafIdentity {
                team_id: local.tile.team_id(),
                lsk,
                person_id: local.person,
                condition_hash: local.tile.condition_hash().as_bytes(),
            };
            let already_merged = slot.already_merged();
            let (record, merged) = match merge_tile_into_leaf(
                meta,
                filters.timezone,
                identity,
                local.tile.day_idx(),
                local.tile.count_nonzero(),
                slot.prev(),
                now_day,
                now_ms,
            ) {
                LeafMergeOutcome::Merged {
                    record,
                    transition,
                    deadline_ms,
                } => {
                    counter!(SEED_TILES_APPLIED_TOTAL, "variant" => record.state.variant().as_str())
                        .increment(1);
                    if let Some(transition) = transition {
                        transitions.push(transition);
                    }
                    if deadline_ms != i64::MAX {
                        folded.schedules.push((key, deadline_ms));
                    }
                    (record, true)
                }
                LeafMergeOutcome::Unchanged { record } => {
                    counter!(SEED_TILES_UNCHANGED_TOTAL, "variant" => meta.variant.as_str())
                        .increment(1);
                    (record, already_merged)
                }
                LeafMergeOutcome::Dropped(reason) => {
                    counter!(SEED_TILES_DROPPED_TOTAL, "reason" => reason.as_str()).increment(1);
                    continue;
                }
            };

            *slot = LeafSlot::Touched {
                record,
                write: LeafWrite {
                    filters: local.filters.clone(),
                    meta: *meta,
                    source: MembershipRegisterSource {
                        partition_id: local.prefix.partition_id,
                        team_id: identity.team_id,
                        person_id: identity.person_id,
                        leaf_state_key: lsk,
                    },
                },
                merged,
            };
            // Merged *and* Unchanged both recompose Stage 2, so a crash between the two commits
            // self-heals on replay.
            folded
                .touched
                .touch(local.tile.team_id(), local.person, local.tile.run_id(), lsk);
        }

        if !transitions.is_empty() {
            let last_updated = clock.next();
            let start = folded.changes.len();
            for transition in &transitions {
                if let Some(kind) = transition_metric_label(filters, transition) {
                    counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
                }
                folded
                    .changes
                    .extend(map_transition(filters, transition, &last_updated));
            }
            tag_seed(&mut folded.changes[start..], local.tile.run_id());
        }
    }
    folded
}

/// Read every leaf the run will fold into, once, and decode it into the overlay.
async fn read_leaf_slots(
    deps: &SeedApplyDeps<'_>,
    locals: &[LocalTile<'_>],
) -> Result<BTreeMap<BehavioralKey, LeafSlot>, SeedHold> {
    let mut distinct: BTreeSet<BehavioralKey> = BTreeSet::new();
    for local in locals {
        distinct.extend(
            local
                .lsks
                .iter()
                .map(|&lsk| local.prefix.behavioral_key(lsk)),
        );
    }
    let keys: Vec<BehavioralKey> = distinct.into_iter().collect();
    // Maintenance lane: backfill must not contend with live event reads.
    let values = deps
        .handle
        .multi_get_behavioral(keys.clone(), ReadLane::Maintenance)
        .await
        .map_err(SeedHold::store(ApplyStage::Read))?;
    SeedHold::check_read(ApplyStage::Read, keys.len(), values.len())?;
    Ok(keys
        .into_iter()
        .zip(values)
        .map(|(key, bytes)| (key, LeafSlot::decode(bytes)))
        .collect())
}

/// Stage every touched leaf's membership-register overwrite, plus the row itself for the leaves a
/// tile actually advanced, then commit them as one batch.
///
/// Staging only the final state per key equals staging every intermediate write, because
/// `single_leaf_register_writes` is a complete overwrite and the record is the fold's fixed point.
async fn commit_tile_stage1(
    deps: &SeedApplyDeps<'_>,
    overlay: &BTreeMap<BehavioralKey, LeafSlot>,
    now_ms: i64,
) -> Result<(), SeedHold> {
    let staged = stage_tile_writes(overlay, now_ms);
    if staged.is_empty() {
        return Ok(());
    }
    deps.handle
        .commit(staged)
        .await
        .map_err(SeedHold::store(ApplyStage::Stage1Commit))
}

/// The pure half of [`commit_tile_stage1`]: what the run writes, given the settled overlay.
fn stage_tile_writes(overlay: &BTreeMap<BehavioralKey, LeafSlot>, now_ms: i64) -> StagedBatch {
    let mut staged = StagedBatch::default();
    for (key, slot) in overlay {
        let LeafSlot::Touched {
            record,
            write,
            merged,
        } = slot
        else {
            continue;
        };
        stage_seed_membership_registers(
            &mut staged,
            &write.filters,
            write.source,
            &write.meta,
            &record.state,
            now_ms,
        );
        if *merged {
            staged.put::<Behavioral>(key, &record.encode());
        }
    }
    staged
}

pub(crate) fn admit_reconcile(
    partition_id: u16,
    merge: &MergeWorkerDeps,
    queue: &mut ReconcileQueue,
    tile: &ReconcileTile,
    offset: SeedOffset,
) {
    if !merge.reconcile.enabled {
        counter!(SEED_TILES_SKIPPED_TOTAL, "reason" => "reconcile_disabled").increment(1);
        warn!(
            partition_id,
            team_id = tile.team_id().0,
            cohort_id = tile.cohort_id().0,
            run_id = %tile.run_id().0,
            "reconcile seed skipped while reconcile is disabled; re-dispatch after enabling",
        );
        mark_processed(&merge.seed_tracker, partition_id, offset);
        return;
    }

    let kind = tile.scope().kind();
    let deferred = match queue.supersede_if_newer(tile.team_id(), tile.cohort_id(), kind, offset.0)
    {
        SupersedeOutcome::NoQueuedJob => merge.seed_tracker.defer(partition_id as i32, offset.0),
        SupersedeOutcome::Replaced(superseded) => {
            let (replacement, outcome) = merge
                .seed_tracker
                .replace_deferred(superseded, offset.0)
                .expect("a queued reconcile must retain its deferred offset in the current tenure");
            match outcome {
                MarkOutcome::WithinDispatch => {}
                MarkOutcome::CappedAheadOfDispatch => {
                    counter!(COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH).increment(1);
                    warn!(
                        partition_id,
                        "superseded reconcile completion exceeded the seed dispatch ceiling",
                    );
                }
            }
            counter!(RECONCILE_JOBS_SUPERSEDED_TOTAL, "kind" => kind.as_str()).increment(1);
            replacement
        }
        SupersedeOutcome::RetainedNewerOrEqual => {
            counter!(SEED_TILES_SKIPPED_TOTAL, "reason" => "reconcile_stale_replay").increment(1);
            debug!(
                partition_id,
                team_id = tile.team_id().0,
                cohort_id = tile.cohort_id().0,
                run_id = %tile.run_id().0,
                offset = offset.0,
                "replayed reconcile seed retained the newer or equal queued job",
            );
            mark_processed(&merge.seed_tracker, partition_id, offset);
            return;
        }
    };

    queue.enqueue(tile.clone(), deferred);
    counter!(RECONCILE_JOBS_ENQUEUED_TOTAL, "kind" => kind.as_str()).increment(1);
}

fn stage_seed_membership_registers(
    staged: &mut StagedBatch,
    filters: &TeamFilters,
    source: MembershipRegisterSource,
    meta: &LeafStateMeta,
    state: &Stage1State,
    now_ms: i64,
) {
    let in_cohort = leaf_membership(Some(state), meta);
    stage_register_writes(
        staged,
        single_leaf_register_writes(filters, source, in_cohort, now_ms),
    );
}

pub(crate) fn tag_seed(changes: &mut [CohortMembershipChange], run_id: RunId) {
    for change in changes {
        change.origin = Some(ChangeOrigin::Seed);
        change.run_id = Some(run_id);
    }
}

/// Advance the seed tracker past `offset`. A mark beyond the dispatch ceiling is capped and counted.
pub(crate) fn mark_processed(tracker: &OffsetTracker, partition_id: u16, offset: SeedOffset) {
    if let MarkOutcome::CappedAheadOfDispatch =
        tracker.mark_processed(partition_id as i32, offset.0 + 1)
    {
        counter!(COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH).increment(1);
        warn!(
            partition_id,
            next_offset = offset.0 + 1,
            "seed offset mark exceeded the dispatch ceiling and was capped (F1 invariant violation)",
        );
    }
}

/// Pin the seed commit floor at the failed offset so Kafka redelivers it; emit
/// [`SEED_HELD_OFFSET_GAUGE`] so the stall is visible.
pub(crate) fn hold(tracker: &OffsetTracker, partition_id: u16, offset: SeedOffset) {
    let floor = tracker.hold(partition_id as i32, offset.0);
    gauge!(SEED_HELD_OFFSET_GAUGE, "partition" => partition_id.to_string()).set(floor as f64);
}

#[cfg(test)]
// Tests seed and assert against `CohortStore` directly, the sanctioned direct-store surface.
#[allow(clippy::disallowed_methods)]
mod tests {
    use std::collections::BTreeMap;
    use std::num::NonZeroUsize;

    use chrono_tz::America::New_York;
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
    use crate::filters::{CohortId, TeamFiltersBuilder};
    use crate::merge::transfer::Tombstone;
    use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
    use crate::producer::{
        CaptureReconcileMarkerSink, CaptureSeedTileSink, CaptureSink, MembershipSink,
        MembershipStatus,
    };
    use crate::stage1::state::AppliedOffsets;
    use crate::stage2::state::Stage2State;
    use crate::store::{
        CohortStore, OffloadConfig, OffloadMode, Stage2Key, StoreConfig, StoreHandle, TombstoneKey,
    };
    use crate::workers::event_path::{process_event_gated, EventNameGating};
    use crate::workers::seed_batch::{group_seeds, handle_seed_groups, seed_fanout};

    use super::*;

    const TEAM: TeamId = TeamId(7);
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
            prev,
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
                prev.clone(),
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
                    settled.clone(),
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
                    settled.clone(),
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

    fn single_leaf_json(window_days: i64) -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": window_days, "time_interval": "day",
            "conditionHash": "0123456789abcdef",
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
        let mut builder = TeamFiltersBuilder::default();
        for (id, filters) in cohorts {
            builder.add_cohort(CohortId(id), TEAM, &filters).unwrap();
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
        SeedTile::new(
            TEAM,
            person,
            ConditionHash::parse("0123456789abcdef").unwrap(),
            count(n),
            day,
            SChunkMs(1_700_000_000_000),
            RunId(Uuid::from_u128(0xBF)),
            ClaimEpoch(1),
        )
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
        clock: LastUpdatedClock,
    }

    impl Shell {
        fn new(cohorts: Vec<(i32, Value)>) -> Self {
            Self::with_sink(cohorts, CaptureSink::new(), CaptureSeedTileSink::new())
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
            Self::with_cascade_and_sink(cohorts, CaptureSink::new(), cascade_sink)
        }

        fn with_cascade_and_sink(
            cohorts: Vec<(i32, Value)>,
            sink: CaptureSink,
            cascade_sink: crate::producer::CaptureCascadeSink,
        ) -> Self {
            Self::build(
                cohorts,
                sink,
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
                seed_batch: crate::workers::SeedBatchLimits::default(),
            };
            let reconcile_queue =
                ReconcileQueue::new(0, deps.reconcile.backlog.clone(), handle.clone());
            Self {
                _dir,
                store,
                handle,
                catalog,
                sink,
                seed_sink,
                cascade_sink,
                marker_sink,
                deps,
                queue: EvictionQueue::new(),
                reconcile_queue,
                clock: LastUpdatedClock::default(),
            }
        }

        /// One seed through the batch pipeline, so every case below also pins that a run of one
        /// behaves exactly as the per-seed apply did.
        async fn run(&mut self, partition_id: u16, work: SeedWork, offset: i64) {
            self.run_batch(partition_id, vec![(work, offset)]).await;
        }

        /// A whole channel batch of seeds, dispatched the way the worker dispatches them.
        async fn run_batch(&mut self, partition_id: u16, seeds: Vec<(SeedWork, i64)>) {
            let highest = seeds
                .iter()
                .map(|(_, offset)| *offset)
                .max()
                .expect("a dispatched batch is non-empty");
            self.deps
                .seed_tracker
                .mark_dispatched(partition_id as i32, highest + 1);
            let sink: Arc<dyn MembershipSink> = Arc::new(self.sink.clone());
            let admitted = seeds
                .into_iter()
                .map(|(work, offset)| Admitted {
                    work,
                    offset: SeedOffset(offset),
                })
                .collect();
            let groups = {
                let snapshot = self.catalog.load();
                group_seeds(admitted, self.deps.seed_batch, |work| {
                    seed_fanout(&snapshot, work)
                })
            };
            handle_seed_groups(
                SeedApplyDeps {
                    partition_id,
                    handle: &self.handle,
                    catalog: &self.catalog,
                    sink: &sink,
                    merge: &self.deps,
                },
                &mut self.queue,
                &mut self.reconcile_queue,
                &mut self.clock,
                groups,
            )
            .await;
        }

        fn committable(&self, partition_id: u16) -> Option<i64> {
            self.deps
                .seed_tracker
                .committable_offsets()
                .get(&(partition_id as i32))
                .copied()
        }
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

        // Re-delivery: max-merge no-op, no duplicate emission, and the missing register self-heals.
        shell.run(partition_id, SeedWork::Tile(tile), 10).await;
        assert_eq!(shell.sink.changes().len(), 1);
        assert_eq!(shell.committable(partition_id), Some(11));
        assert!(
            Stage2State::decode(&shell.store.get_stage2(&register_key).unwrap().unwrap())
                .unwrap()
                .in_cohort,
            "an Unchanged seed replay restores the register from its post-merge record",
        );
    }

    #[tokio::test]
    async fn unchanged_non_member_seed_restores_an_explicit_false_register_without_emission() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::new(vec![(1, wrap(vec![multiple_leaf_json(7, "gte", 3)]))]);
        let tile = tile_for(person, today(), 1);
        let register_key = Stage2Key {
            partition_id,
            team_id: TEAM.0 as u64,
            cohort_id: 1,
            person_id: person,
        };

        shell
            .run(partition_id, SeedWork::Tile(tile.clone()), 0)
            .await;
        let registered = Stage2State::decode(
            &shell
                .store
                .get_stage2(&register_key)
                .unwrap()
                .expect("seeded non-member has a register row"),
        )
        .unwrap();
        assert!(!registered.in_cohort);
        assert!(shell.sink.changes().is_empty());

        shell
            .store
            .write_batch(|batch| batch.delete_stage2(&register_key))
            .unwrap();
        shell.run(partition_id, SeedWork::Tile(tile), 1).await;

        let restored = Stage2State::decode(
            &shell
                .store
                .get_stage2(&register_key)
                .unwrap()
                .expect("Unchanged replay restores the false register"),
        )
        .unwrap();
        assert!(!restored.in_cohort);
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

    #[tokio::test]
    async fn membership_produce_failure_holds_the_seed_offset() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::with_sink(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );

        shell
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, today(), 1)),
                4,
            )
            .await;
        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        assert!(
            leaf_states(&shell, partition_id, person)
                .iter()
                .all(Option::is_none),
            "the single-leaf output is produced before stage 1 commits, so a failure leaves no row",
        );
    }

    /// A broker acks per record, so a run can come back half acked. Committing stage 1 under that
    /// would make the replay fold to `Unchanged` and never re-emit the records that failed: a
    /// single-leaf membership lost for good. Producing before the commit means the replay re-folds
    /// every tile and re-emits every change.
    #[tokio::test]
    async fn a_partially_acked_single_leaf_produce_commits_nothing_and_the_replay_re_emits_every_change(
    ) {
        let mut shell = Shell::with_sink(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            CaptureSink::partially_failing_first(NonZeroUsize::new(2).unwrap()),
            CaptureSeedTileSink::new(),
        );
        // Every person on partition 0, so one worker owns the whole run.
        shell.deps.partition_count = 1;
        let persons: Vec<Uuid> = (0..3u128)
            .map(|i| Uuid::from_u128(0x5EED_0000 + i))
            .collect();
        // Offsets start above zero: the tracker reads a zero floor as "never processed".
        let batch = || {
            persons
                .iter()
                .zip(5i64..)
                .map(|(&person, offset)| (SeedWork::Tile(tile_for(person, today(), 1)), offset))
                .collect::<Vec<_>>()
        };
        let register_key = |person: Uuid| Stage2Key {
            partition_id: 0,
            team_id: TEAM.0 as u64,
            cohort_id: 1,
            person_id: person,
        };

        shell.run_batch(0, batch()).await;

        assert_eq!(shell.committable(0), None, "held for redelivery");
        assert_eq!(
            shell.sink.changes().len(),
            2,
            "the acked records are already downstream; the failed one is what must not be lost",
        );
        for &person in &persons {
            assert!(
                leaf_states(&shell, 0, person).iter().all(Option::is_none),
                "no leaf row for {person}: the run committed nothing",
            );
            assert!(
                shell
                    .store
                    .get_stage2(&register_key(person))
                    .unwrap()
                    .is_none(),
                "no register for {person}: the run committed nothing",
            );
        }
        assert!(
            shell.queue.is_empty(),
            "no eviction is owed for a row that was never written",
        );

        shell.run_batch(0, batch()).await;

        let changes = shell.sink.changes();
        for &person in &persons {
            assert!(
                changes.iter().any(|change| {
                    change.person_id == person.to_string()
                        && change.status == MembershipStatus::Entered
                }),
                "the replay re-folded and re-emitted {person}'s entry",
            );
        }
        // The tenure-sticky hold pins the committable at the held first offset.
        assert_eq!(shell.committable(0), Some(5));
    }

    /// A cascade tells a referrer about a flip the membership topic has not confirmed. Under a
    /// joined produce the cascade leg is submitted regardless of how the membership leg fares.
    #[tokio::test]
    async fn a_failed_membership_produce_never_submits_the_cascade_leg() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::with_cascade_and_sink(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            CaptureSink::failing_first(1),
            crate::producer::CaptureCascadeSink::new(),
        );

        shell
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, today(), 1)),
                3,
            )
            .await;

        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        assert_eq!(
            shell.cascade_sink.produce_calls(),
            0,
            "the cascade leg runs only after the membership legs ack",
        );
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

    // ---- batched apply: properties only a run of several seeds can break ----

    /// A re-run chunk is mostly `Unchanged`, so re-writing byte-identical `cf_behavioral` rows would
    /// spend the store's write budget on nothing. The register still has to be staged: it is what
    /// repairs a row a failed produce left behind.
    #[test]
    fn an_unchanged_leaf_stages_its_register_but_not_its_state_row() {
        let filters = Arc::new(build_filters(
            vec![(1, wrap(vec![single_leaf_json(7)]))],
            UTC,
        ));
        let lsk = filters.by_condition_to_lsk[&HASH][0];
        let meta = *filters.by_lsk.get(&lsk).unwrap();
        let person = Uuid::from_u128(0x5EED);
        let key = PersonPrefix::new(0, TEAM.0 as u64, person).behavioral_key(lsk);
        let (record, _, _) = merged(merge(&meta, now_day(), 1, None));
        let write = || LeafWrite {
            filters: filters.clone(),
            meta,
            source: MembershipRegisterSource {
                partition_id: 0,
                team_id: TEAM,
                person_id: person,
                leaf_state_key: lsk,
            },
        };

        let staged = |merged: bool| {
            stage_tile_writes(
                &BTreeMap::from([(
                    key,
                    LeafSlot::Touched {
                        record: record.clone(),
                        write: write(),
                        merged,
                    },
                )]),
                NOW_MS,
            )
            .len()
        };

        assert_eq!(
            staged(true),
            2,
            "a merged leaf writes its row and its register"
        );
        assert_eq!(
            staged(false),
            1,
            "an unchanged leaf writes the register only"
        );
    }

    /// Every leaf state the batch could have written for `person`, in catalog order.
    fn leaf_states(shell: &Shell, partition_id: u16, person: Uuid) -> Vec<Option<Vec<u8>>> {
        let snapshot = shell.catalog.load();
        let filters = snapshot.team(TEAM).expect("the test catalog holds TEAM");
        let prefix = PersonPrefix::new(partition_id, TEAM.0 as u64, person);
        filters
            .by_condition_to_lsk
            .get(&HASH)
            .map_or_else(Vec::new, |lsks| {
                lsks.iter()
                    .map(|&lsk| {
                        shell
                            .store
                            .get_behavioral(&prefix.behavioral_key(lsk))
                            .unwrap()
                    })
                    .collect()
            })
    }

    /// Without read-your-writes each tile would fold onto the bytes the read pass saw, so the last
    /// tile's record would overwrite the earlier days and the count would never reach the threshold.
    #[tokio::test]
    async fn two_days_in_one_batch_reach_the_same_state_as_two_batches() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let cohorts = vec![(1, wrap(vec![multiple_leaf_json(7, "gte", 2)]))];
        let (yesterday, today) = (today() - 1, today());

        let mut batched = Shell::new(cohorts.clone());
        batched
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(person, yesterday, 1)), 0),
                    (SeedWork::Tile(tile_for(person, today, 1)), 1),
                ],
            )
            .await;

        let mut separately = Shell::new(cohorts);
        separately
            .run(
                partition_id,
                SeedWork::Tile(tile_for(person, yesterday, 1)),
                0,
            )
            .await;
        separately
            .run(partition_id, SeedWork::Tile(tile_for(person, today, 1)), 1)
            .await;

        assert_eq!(
            leaf_states(&batched, partition_id, person),
            leaf_states(&separately, partition_id, person),
            "one batch must settle on the same stage-1 state as two",
        );
        let changes = batched.sink.changes();
        assert_eq!(
            changes.len(),
            1,
            "the second day crosses the gte-2 threshold"
        );
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(
            changes.len(),
            separately.sink.changes().len(),
            "batching must not add or drop a transition",
        );
        assert_eq!(
            batched.sink.produce_calls(),
            1,
            "the whole batch rides one membership produce",
        );
        assert_eq!(batched.committable(partition_id), Some(2));

        // Redelivery of the whole run: max-merge makes every tile `Unchanged`, so the run converges
        // instead of re-emitting.
        let settled = leaf_states(&batched, partition_id, person);
        batched
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(person, yesterday, 1)), 0),
                    (SeedWork::Tile(tile_for(person, today, 1)), 1),
                ],
            )
            .await;
        assert_eq!(batched.sink.changes().len(), 1, "no duplicate flip");
        assert_eq!(
            leaf_states(&batched, partition_id, person),
            settled,
            "the replayed run is a no-op on stage 1",
        );
    }

    /// The batch ceiling is the round-trip budget: a run longer than it has to split, or one slow
    /// produce would hold an unbounded number of seeds.
    #[tokio::test]
    async fn a_run_longer_than_the_cap_pays_one_produce_per_capped_group() {
        const TILES: usize = 300;
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        // Every person on partition 0, so one worker owns the whole run.
        shell.deps.partition_count = 1;
        let seeds: Vec<_> = (0..TILES)
            .map(|i| {
                (
                    SeedWork::Tile(tile_for(
                        Uuid::from_u128(0x5EED_0000 + i as u128),
                        today(),
                        1,
                    )),
                    i as i64,
                )
            })
            .collect();

        shell.run_batch(0, seeds).await;

        assert_eq!(
            shell.sink.changes().len(),
            TILES,
            "every person entered the single-leaf cohort",
        );
        assert_eq!(
            shell.sink.produce_calls(),
            TILES.div_ceil(shell.deps.seed_batch.max_seeds.get()),
            "one membership produce per capped group, not one per tile",
        );
        assert_eq!(shell.committable(0), Some(TILES as i64));
    }

    /// A batch is all-or-nothing on its offsets: the floor must sit at the *first* seed, so the
    /// redelivery replays every tile the failed produce covered.
    #[tokio::test]
    async fn a_failed_membership_produce_holds_the_batchs_first_offset() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        // Both leaves share the tile's hash, so the flip is stage-2-derived and re-derivable.
        let mut shell = Shell::with_sink(
            vec![(
                1,
                wrap(vec![single_leaf_json(7), multiple_leaf_json(7, "gte", 1)]),
            )],
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        let stage2_key = Stage2Key {
            partition_id,
            team_id: TEAM.0 as u64,
            cohort_id: 1,
            person_id: person,
        };
        let batch = |first: i64| {
            vec![
                (SeedWork::Tile(tile_for(person, today() - 1, 1)), first),
                (SeedWork::Tile(tile_for(person, today(), 1)), first + 1),
            ]
        };

        shell.run_batch(partition_id, batch(5)).await;

        assert_eq!(
            shell.committable(partition_id),
            None,
            "the failed produce holds, so nothing in the batch commits",
        );
        assert!(
            shell.store.get_stage2(&stage2_key).unwrap().is_none(),
            "the stage-2 bit must stay unwritten under the failed produce",
        );

        shell.run_batch(partition_id, batch(5)).await;

        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            1,
            "the replay re-derived the composed flip exactly once",
        );
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert!(
            Stage2State::decode(&shell.store.get_stage2(&stage2_key).unwrap().unwrap())
                .unwrap()
                .in_cohort,
        );
        // The tenure-sticky hold pins the committable at the held first offset.
        assert_eq!(shell.committable(partition_id), Some(5));
    }

    #[tokio::test]
    async fn a_batch_of_rekeys_requires_one_ack_per_tile_before_it_marks() {
        let (p_old, partition_id, p_new) = cross_partition_pair();
        let other = (p_new.as_u128() + 1..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TEAM, p, COHORT_PARTITION_COUNT) as u16 == partition_id)
            .expect("some uuid hashes onto p_old's partition");
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        write_tombstone(&shell.store, partition_id, p_old, p_new);
        write_tombstone(&shell.store, partition_id, other, p_new);

        shell
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(p_old, today(), 1)), 7),
                    (SeedWork::Tile(tile_for(other, today(), 2)), 8),
                ],
            )
            .await;

        assert_eq!(shell.seed_sink.tiles().len(), 2, "both tiles re-keyed");
        assert!(shell.sink.changes().is_empty(), "neither applied locally");
        assert_eq!(shell.committable(partition_id), Some(9));

        // A short ack vector must read as a failure, not as `all(is_ok)` over what did come back.
        let mut short = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        write_tombstone(&short.store, partition_id, p_old, p_new);
        write_tombstone(&short.store, partition_id, other, p_new);
        short.deps.seed_tile_sink = Arc::new(EmptyAckSink);
        short
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(p_old, today(), 1)), 7),
                    (SeedWork::Tile(tile_for(other, today(), 2)), 8),
                ],
            )
            .await;
        assert_eq!(short.committable(partition_id), None, "held for redelivery");
    }

    /// Two runs sharing a person in one batch must still recompose that person once: splitting their
    /// leaves by run would evaluate the cohort twice against the same uncommitted bit and emit the
    /// composed flip twice.
    #[tokio::test]
    async fn two_runs_touching_one_person_emit_the_composed_flip_once() {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::new(vec![(
            1,
            wrap(vec![single_leaf_json(7), multiple_leaf_json(7, "gte", 1)]),
        )]);
        let other_run = |day: DayIdx| {
            SeedTile::new(
                TEAM,
                person,
                ConditionHash::parse("0123456789abcdef").unwrap(),
                count(1),
                day,
                SChunkMs(1_700_000_000_000),
                RunId(Uuid::from_u128(0xC0FFEE)),
                ClaimEpoch(1),
            )
        };

        shell
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(person, today() - 1, 1)), 0),
                    (SeedWork::Tile(other_run(today())), 1),
                ],
            )
            .await;

        let composed: Vec<_> = shell
            .sink
            .changes()
            .into_iter()
            .filter(|change| change.cohort_id == 1)
            .collect();
        assert_eq!(composed.len(), 1, "one flip, not one per run");
        assert_eq!(
            composed[0].run_id,
            Some(RunId(Uuid::from_u128(0xC0FFEE))),
            "the last run to touch the person owns the provenance",
        );
    }

    /// A run spans teams whenever two backfills interleave on one partition. Folding a tile against
    /// the wrong team's catalog would read the wrong leaves and write the wrong registers.
    #[tokio::test]
    async fn a_batch_spanning_two_teams_applies_each_against_its_own_catalog() {
        const OTHER_TEAM: TeamId = TeamId(9);
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        let mut shell = Shell::new(vec![(1, wrap(vec![single_leaf_json(7)]))]);
        shell.catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([
            (
                TEAM,
                build_filters(vec![(1, wrap(vec![single_leaf_json(7)]))], UTC),
            ),
            (OTHER_TEAM, {
                let mut builder = TeamFiltersBuilder::default();
                builder
                    .add_cohort(CohortId(2), OTHER_TEAM, &wrap(vec![single_leaf_json(7)]))
                    .unwrap();
                builder.freeze(UTC)
            }),
        ])));
        let other_team_tile = SeedTile::new(
            OTHER_TEAM,
            person,
            ConditionHash::parse("0123456789abcdef").unwrap(),
            count(1),
            today(),
            SChunkMs(1_700_000_000_000),
            RunId(Uuid::from_u128(0xBF)),
            ClaimEpoch(1),
        );

        shell
            .run_batch(
                partition_id,
                vec![
                    (SeedWork::Tile(tile_for(person, today(), 1)), 0),
                    (SeedWork::Tile(other_team_tile), 1),
                ],
            )
            .await;

        let mut entered: Vec<(i32, i32)> = shell
            .sink
            .changes()
            .iter()
            .map(|change| (change.team_id, change.cohort_id))
            .collect();
        entered.sort_unstable();
        assert_eq!(
            entered,
            vec![(TEAM.0, 1), (OTHER_TEAM.0, 2)],
            "each team's tile entered its own cohort",
        );
        assert_eq!(shell.committable(partition_id), Some(2));
    }
}
