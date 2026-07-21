//! The seed-tile apply path: a pure, clock-free core ([`merge_tile_into_leaf`]) that mirrors the
//! live fold minus dedup (slide-before-evaluate, max-merge of the tile's absolute count,
//! structural-equality `Unchanged` — the whole of tile idempotency), and an imperative shell
//! ([`handle_seed`]) ordered stage-1 commit → stage-2 recompute → produce → stage-2 commit → mark.
//! Committing the stage-2 bits after the produces ack makes a failed produce re-derivable on
//! replay; store/produce failures hold the seed offset.

use std::num::NonZeroU32;
use std::sync::Arc;

use chrono::Utc;
use chrono_tz::Tz;
use metrics::{counter, gauge};
use tracing::warn;
use uuid::Uuid;

use cohort_core::seed::{RunId, SeedTile};

use crate::consumers::seeds::SeedWork;
use crate::filters::manager::CatalogHandle;
use crate::filters::reverse_index::{LeafStateMeta, TeamFilters};
use crate::filters::TeamId;
use crate::merge::tombstone_redirect::{self, Resolution, MAX_CROSS_PARTITION_REDIRECT_HOPS};
use crate::observability::metrics::{
    COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH, SEED_HELD_OFFSET_GAUGE, SEED_REKEYED_TOTAL,
    SEED_REKEY_HOP_CAPPED_TOTAL, SEED_REKEY_PRODUCE_FAILURE_TOTAL, SEED_TILES_APPLIED_TOTAL,
    SEED_TILES_DROPPED_TOTAL, SEED_TILES_SKIPPED_TOTAL, SEED_TILES_UNCHANGED_TOTAL,
    STAGE1_STATE_DECODE_ERROR, STAGE1_TRANSITIONS,
};
use crate::partitions::offset_tracker::{MarkOutcome, OffsetTracker};
use crate::producer::{map_transition, ChangeOrigin, CohortMembershipChange, MembershipSink};
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
use crate::store::{Behavioral, BehavioralKey, PersonPrefix, ReadLane, StagedBatch, StoreHandle};
use crate::sweep::EvictionQueue;
use crate::workers::merge_path::MergeWorkerDeps;
use crate::workers::stage2_path::{commit_stage2_writes, recompute_stage2};
use crate::workers::worker::{
    first_cascades, produce_cascades, produce_membership, transition_metric_label,
};

/// Where a tile applies after tombstone resolution; an exhausted hop budget is unrepresentable
/// as a re-produce, forcing the degraded inline arm.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum TileRoute {
    ApplyLocal { person: Uuid },
    ReProduce { tile: SeedTile },
    CapExhausted { person: Uuid },
}

/// Total routing of a tile through its tombstone [`Resolution`].
pub(crate) fn route_tile(tile: &SeedTile, resolution: Resolution, cap: u8) -> TileRoute {
    match resolution {
        Resolution::NotMerged => TileRoute::ApplyLocal {
            person: tile.person_id(),
        },
        Resolution::Inline { final_person, .. } => TileRoute::ApplyLocal {
            person: final_person,
        },
        Resolution::CrossPartition { target_person, .. } => {
            match tile.rekeyed_to(target_person, cap) {
                Some(rekeyed) => TileRoute::ReProduce { tile: rekeyed },
                None => TileRoute::CapExhausted {
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

/// One leaf's merge outcome; `Unchanged` (byte-identical post-merge record) is the tile
/// idempotency.
#[must_use]
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum LeafMergeOutcome {
    Merged {
        record: StatefulRecord,
        transition: Option<LeafTransition>,
        /// The recomputed eviction deadline ([`i64::MAX`] = permanent, never scheduled).
        deadline_ms: i64,
    },
    Unchanged,
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
        return LeafMergeOutcome::Unchanged;
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

/// Handle one seed message on its owning partition worker; marks or holds the seed tracker only.
#[allow(clippy::too_many_arguments)]
pub(crate) async fn handle_seed(
    partition_id: u16,
    handle: &StoreHandle,
    catalog: &CatalogHandle,
    sink: &Arc<dyn MembershipSink>,
    merge: &MergeWorkerDeps,
    queue: &mut EvictionQueue<BehavioralKey>,
    last_updated: &str,
    work: &SeedWork,
    offset: i64,
) {
    let tile = match work {
        SeedWork::Skip(reason) => {
            counter!(SEED_TILES_SKIPPED_TOTAL, "reason" => reason.as_str()).increment(1);
            mark_processed(&merge.seed_tracker, partition_id, offset);
            return;
        }
        SeedWork::Tile(tile) => tile,
    };

    let snapshot = catalog.load();
    let Some(team_filters) = snapshot.team(tile.team_id()) else {
        counter!(SEED_TILES_DROPPED_TOTAL, "reason" => "team_absent").increment(1);
        mark_processed(&merge.seed_tracker, partition_id, offset);
        return;
    };
    let filters: &TeamFilters = team_filters;

    // A read failure is fail-stop: a tile mis-applied to a merged-away person is durable state
    // reconcile cannot retract.
    let resolution = match tombstone_redirect::resolve_offloaded(
        handle,
        partition_id,
        tile.team_id(),
        tile.person_id(),
        merge.partition_count,
        ReadLane::Maintenance,
    )
    .await
    {
        Ok(resolution) => resolution,
        Err(error) => {
            warn!(
                partition_id,
                team_id = tile.team_id().0,
                error = %error,
                "seed tombstone preflight read failed; holding the seed offset for redelivery",
            );
            hold(&merge.seed_tracker, partition_id, offset);
            return;
        }
    };
    let person = match route_tile(tile, resolution, MAX_CROSS_PARTITION_REDIRECT_HOPS) {
        TileRoute::ApplyLocal { person } => person,
        TileRoute::ReProduce { tile: rekeyed } => {
            // Ack before mark; the tile has no other copy. Exactly one Ok ack — an empty vector
            // would make an `all(is_ok)` guard vacuously true and commit past a lost tile.
            let acks = merge.seed_tile_sink.produce(vec![rekeyed]).await;
            if matches!(acks.as_slice(), [Ok(())]) {
                counter!(SEED_REKEYED_TOTAL).increment(1);
                mark_processed(&merge.seed_tracker, partition_id, offset);
            } else {
                counter!(SEED_REKEY_PRODUCE_FAILURE_TOTAL).increment(1);
                warn!(
                    partition_id,
                    team_id = tile.team_id().0,
                    "seed tile re-key produce failed; holding the seed offset for redelivery",
                );
                hold(&merge.seed_tracker, partition_id, offset);
            }
            return;
        }
        TileRoute::CapExhausted { person } => {
            counter!(SEED_REKEY_HOP_CAPPED_TOTAL).increment(1);
            // Same degrade as the event path: orphaned-but-bounded state (the survivor's live
            // path never reads this slice) that ages out via eviction, preferred over a silent
            // tile loss.
            warn!(
                partition_id,
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
        counter!(SEED_TILES_DROPPED_TOTAL, "reason" => "no_referencing_leaves").increment(1);
        mark_processed(&merge.seed_tracker, partition_id, offset);
        return;
    }

    let prefix = PersonPrefix::new(partition_id, tile.team_id().0 as u64, person);
    let keys: Vec<BehavioralKey> = lsks.iter().map(|&lsk| prefix.behavioral_key(lsk)).collect();
    // Maintenance lane: backfill must not contend with live event reads.
    let values = match handle
        .multi_get_behavioral(keys, ReadLane::Maintenance)
        .await
    {
        Ok(values) => values,
        Err(error) => {
            warn!(
                partition_id,
                team_id = tile.team_id().0,
                error = %error,
                "seed state read failed; holding the seed offset for redelivery",
            );
            hold(&merge.seed_tracker, partition_id, offset);
            return;
        }
    };

    let now_ms = Utc::now().timestamp_millis();
    let now_day = day_idx_in_tz(now_ms, filters.timezone);
    let TileApplication {
        staged,
        transitions,
        stage2_leaves,
        schedules,
    } = apply_tile_to_leaves(
        filters, &prefix, lsks, values, tile, person, now_day, now_ms,
    );

    // Order: stage-1 commit → stage-2 recompute → produce → stage-2 commit → schedule → mark.
    if !staged.is_empty() {
        if let Err(error) = handle.commit(staged).await {
            warn!(
                partition_id,
                team_id = tile.team_id().0,
                error = %error,
                "seed state commit failed; holding the seed offset for redelivery",
            );
            hold(&merge.seed_tracker, partition_id, offset);
            return;
        }
    }

    let mut changes: Vec<CohortMembershipChange> = Vec::new();
    for transition in &transitions {
        if let Some(kind) = transition_metric_label(filters, transition) {
            counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
        }
        changes.extend(map_transition(filters, transition, last_updated));
    }
    // `event_ms := now_ms`: `last_evaluated_at_ms` is a freshness stamp, and the worker-batch
    // `last_updated` makes backfill flips win LWW downstream.
    let recompute = match recompute_stage2(
        partition_id,
        handle,
        filters,
        &stage2_leaves,
        now_ms,
        last_updated,
        ReadLane::Maintenance,
    )
    .await
    {
        Ok(recompute) => recompute,
        Err(error) => {
            warn!(
                partition_id,
                team_id = tile.team_id().0,
                error = %error,
                "seed stage 2 recompute failed; holding the seed offset for redelivery",
            );
            hold(&merge.seed_tracker, partition_id, offset);
            return;
        }
    };
    changes.extend(recompute.changes.iter().cloned());

    tag_seed(&mut changes, tile.run_id());
    // Only the cascade topic can re-evaluate cohort-of-cohort referrers; gate-off builds nothing.
    let cascades = first_cascades(merge, &changes, offset);
    if !changes.is_empty() {
        let errors = produce_membership(sink, changes).await;
        if errors > 0 {
            // Replay re-derives the stage-2 flips (bits unwritten); a lost single-leaf change is
            // not re-emitted — the reconcile snapshot heals that class.
            warn!(
                partition_id,
                team_id = tile.team_id().0,
                errors,
                "seed membership produce failed; holding the seed offset for redelivery",
            );
            hold(&merge.seed_tracker, partition_id, offset);
            return;
        }
    }
    let cascade_errors = produce_cascades(merge, cascades).await;
    if cascade_errors > 0 {
        warn!(
            partition_id,
            team_id = tile.team_id().0,
            errors = cascade_errors,
            "seed cascade produce failed; holding the seed offset for redelivery",
        );
        hold(&merge.seed_tracker, partition_id, offset);
        return;
    }

    // The bits commit only after both produces ack, so a failed produce is re-derived on replay
    // instead of lost against a flipped bit; replay duplicates are LWW-safe downstream.
    if let Err(error) = commit_stage2_writes(handle, &recompute.writes).await {
        warn!(
            partition_id,
            team_id = tile.team_id().0,
            error = %error,
            "seed stage 2 commit failed; holding the seed offset for redelivery",
        );
        hold(&merge.seed_tracker, partition_id, offset);
        return;
    }
    recompute.record_metrics();

    for (key, deadline) in schedules {
        queue.schedule(key, deadline);
    }
    mark_processed(&merge.seed_tracker, partition_id, offset);
}

/// What one tile staged across its referencing leaves.
#[derive(Default)]
struct TileApplication {
    staged: StagedBatch,
    transitions: Vec<LeafTransition>,
    /// Merged *and* Unchanged leaves both recompose Stage 2, so a crash between the two commits
    /// self-heals on replay.
    stage2_leaves: Vec<(LeafStateKey, Uuid)>,
    schedules: Vec<(BehavioralKey, i64)>,
}

/// Fold the tile into every referencing leaf.
#[allow(clippy::too_many_arguments)]
fn apply_tile_to_leaves(
    filters: &TeamFilters,
    prefix: &PersonPrefix,
    lsks: &[LeafStateKey],
    values: Vec<Option<Vec<u8>>>,
    tile: &SeedTile,
    person: Uuid,
    now_day: DayIdx,
    now_ms: i64,
) -> TileApplication {
    let count = tile.count_nonzero();
    let mut application = TileApplication::default();
    for (&lsk, bytes) in lsks.iter().zip(values) {
        let Some(meta) = filters.by_lsk.get(&lsk) else {
            counter!(SEED_TILES_DROPPED_TOTAL, "reason" => SeedDropReason::MetaIncomplete.as_str())
                .increment(1);
            continue;
        };
        let prev = match bytes {
            None => None,
            Some(bytes) => match StatefulRecord::decode(&bytes) {
                Ok(record) => Some(record),
                Err(_) => {
                    counter!(STAGE1_STATE_DECODE_ERROR).increment(1);
                    counter!(SEED_TILES_DROPPED_TOTAL, "reason" => "corrupt_state").increment(1);
                    continue;
                }
            },
        };
        let identity = LeafIdentity {
            team_id: tile.team_id(),
            lsk,
            person_id: person,
            condition_hash: tile.condition_hash().as_bytes(),
        };
        match merge_tile_into_leaf(
            meta,
            filters.timezone,
            identity,
            tile.day_idx(),
            count,
            prev,
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
                let key = prefix.behavioral_key(lsk);
                application.staged.put::<Behavioral>(&key, &record.encode());
                application.stage2_leaves.push((lsk, person));
                if let Some(transition) = transition {
                    application.transitions.push(transition);
                }
                if deadline_ms != i64::MAX {
                    application.schedules.push((key, deadline_ms));
                }
            }
            LeafMergeOutcome::Unchanged => {
                counter!(SEED_TILES_UNCHANGED_TOTAL, "variant" => meta.variant.as_str())
                    .increment(1);
                application.stage2_leaves.push((lsk, person));
            }
            LeafMergeOutcome::Dropped(reason) => {
                counter!(SEED_TILES_DROPPED_TOTAL, "reason" => reason.as_str()).increment(1);
            }
        }
    }
    application
}

fn tag_seed(changes: &mut [CohortMembershipChange], run_id: RunId) {
    for change in changes {
        change.origin = Some(ChangeOrigin::Seed);
        change.run_id = Some(run_id);
    }
}

/// Advance the seed tracker past `offset`. A mark beyond the dispatch ceiling is capped and counted.
fn mark_processed(tracker: &OffsetTracker, partition_id: u16, offset: i64) {
    if let MarkOutcome::CappedAheadOfDispatch =
        tracker.mark_processed(partition_id as i32, offset + 1)
    {
        counter!(COHORT_STREAM_OFFSET_AHEAD_OF_DISPATCH).increment(1);
        warn!(
            partition_id,
            next_offset = offset + 1,
            "seed offset mark exceeded the dispatch ceiling and was capped (F1 invariant violation)",
        );
    }
}

/// Pin the seed commit floor at the failed offset so Kafka redelivers it; emit
/// [`SEED_HELD_OFFSET_GAUGE`] so the stall is visible.
fn hold(tracker: &OffsetTracker, partition_id: u16, offset: i64) {
    let floor = tracker.hold(partition_id as i32, offset);
    gauge!(SEED_HELD_OFFSET_GAUGE, "partition" => partition_id.to_string()).set(floor as f64);
}

#[cfg(test)]
// Tests seed and assert against `CohortStore` directly, the sanctioned direct-store surface.
#[allow(clippy::disallowed_methods)]
mod tests {
    use std::collections::BTreeMap;

    use chrono_tz::America::New_York;
    use chrono_tz::UTC;
    use proptest::prelude::*;
    use serde_json::{json, Value};
    use tempfile::TempDir;

    use cohort_core::seed::{ClaimEpoch, ConditionHash, SChunkMs, SeedTile};

    use crate::consumers::seeds::SeedSkipReason;
    use crate::filters::{CohortId, FilterCatalog, TeamFiltersBuilder};
    use crate::merge::transfer::Tombstone;
    use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
    use crate::producer::{CaptureSeedTileSink, CaptureSink, MembershipStatus};
    use crate::stage1::state::AppliedOffsets;
    use crate::stage2::state::Stage2State;
    use crate::store::{
        CohortStore, OffloadConfig, OffloadMode, Stage2Key, StoreConfig, TombstoneKey,
    };
    use crate::workers::event_path::{process_event_gated, EventNameGating};

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

        assert_eq!(
            merge(&meta, now_day(), 1, Some(record)),
            LeafMergeOutcome::Unchanged,
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
        assert_eq!(
            merge(&meta, now_day(), 2, Some(live.clone())),
            LeafMergeOutcome::Unchanged,
        );
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

        assert_eq!(
            merge(&meta, now_day() - 30, 2, Some(record)),
            LeafMergeOutcome::Unchanged,
        );
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
    fn route_tile_maps_each_resolution_and_caps_the_hop_budget() {
        let tile = tile_for(Uuid::from_u128(0xA11CE), now_day(), 1);
        let survivor = Uuid::from_u128(0xB0B);

        assert_eq!(
            route_tile(&tile, Resolution::NotMerged, 8),
            TileRoute::ApplyLocal {
                person: tile.person_id()
            },
        );
        assert_eq!(
            route_tile(
                &tile,
                Resolution::Inline {
                    final_person: survivor,
                    origin: tile.person_id()
                },
                8,
            ),
            TileRoute::ApplyLocal { person: survivor },
        );
        match route_tile(
            &tile,
            Resolution::CrossPartition {
                target_person: survivor,
                origin: tile.person_id(),
            },
            8,
        ) {
            TileRoute::ReProduce { tile: rekeyed } => {
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
            route_tile(
                &tile,
                Resolution::CrossPartition {
                    target_person: survivor,
                    origin: tile.person_id(),
                },
                0,
            ),
            TileRoute::CapExhausted { person: survivor },
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

    struct Shell {
        _dir: TempDir,
        store: CohortStore,
        handle: StoreHandle,
        catalog: Arc<CatalogHandle>,
        sink: CaptureSink,
        seed_sink: CaptureSeedTileSink,
        cascade_sink: crate::producer::CaptureCascadeSink,
        deps: MergeWorkerDeps,
        queue: EvictionQueue<BehavioralKey>,
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
            };
            Self {
                _dir,
                store,
                handle,
                catalog,
                sink,
                seed_sink,
                cascade_sink,
                deps,
                queue: EvictionQueue::new(),
            }
        }

        async fn run(&mut self, partition_id: u16, work: SeedWork, offset: i64) {
            self.deps
                .seed_tracker
                .mark_dispatched(partition_id as i32, offset + 1);
            let sink: Arc<dyn MembershipSink> = Arc::new(self.sink.clone());
            handle_seed(
                partition_id,
                &self.handle,
                &self.catalog,
                &sink,
                &self.deps,
                &mut self.queue,
                "2026-06-15 12:00:00.000000",
                &work,
                offset,
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

        // Re-delivery: max-merge no-op, no duplicate emission, offset still advances.
        shell.run(partition_id, SeedWork::Tile(tile), 10).await;
        assert_eq!(shell.sink.changes().len(), 1);
        assert_eq!(shell.committable(partition_id), Some(11));
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
