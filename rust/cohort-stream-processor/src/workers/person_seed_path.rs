//! Applies person-property seeds to `cf_person_records`, giving dormant persons leaf state that
//! otherwise only arrives on a live event carrying `person_properties`.
//!
//! [`PersonHead`] is this path's half of a seed run: route, read, fold. The free functions below
//! are pure. [`seed_apply`](crate::workers::seed_apply) owns everything after the fold, so the
//! `Ok ⇒ mark, Err ⇒ hold` decision lives at one site for both seed kinds.
//!
//! Ordering against live traffic is [`person_seed_verdict`]'s job, not the apply fence's: a person
//! seed carries no arrival bound over the event stream, so it admits fence-open. The partition-wide
//! live-lag, disk, and channel-full holds still apply.

use std::collections::{BTreeMap, BTreeSet};

use cohort_core::seed::{PersonSeed, RunId};
use metrics::counter;
use tracing::{debug, warn};
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::TeamId;
use crate::merge::tombstone_redirect::MAX_CROSS_PARTITION_REDIRECT_HOPS;
use crate::observability::metrics::{
    PERSON_SEED_HASHES_DROPPED_TOTAL, PERSON_SEED_PRIOR_CORRUPT_TOTAL,
    PERSON_SEED_REKEY_HOP_CAPPED_TOTAL,
};
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::{
    apply_person_seed, person_seed_verdict, MatchedSet, PersonRecord, PersonSeedOutcome,
    PersonSeedVerdict, PriorRecord,
};
use crate::stage1::state::StateVariant;
use crate::stage1::transition::{LeafTransition, TransitionKind};
use crate::store::{PersonPrefix, PersonRecordKey, PersonRecords, ReadLane, StagedBatch};
use crate::workers::seed_apply::{
    record_stage1_transition, resolve_run_persons, ApplyDeps, ApplyStage, Decoded, Folded, Outcome,
    Overlay, ReKeys, RunStamp, SeedHead, SeedHold, StageClock, Tally, TouchedPersons,
};
use crate::workers::seed_path::{route_seed, SeedRoute};
use crate::workers::seed_run::{Admitted, OffsetSpan, SeedKind, SeedRun};
use crate::workers::stage2_path::FoldedLeaf;

/// Person-property seed admission for the partition workers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PersonSeedDeps {
    /// While off, person seeds skip and commit, so a run produced against a gate-off fleet has to
    /// be re-produced.
    pub enabled: bool,
    /// How far a scan instant must beat the stored record's stamp before the seed may overwrite it.
    /// Covers ClickHouse replication lag plus client-clock skew; see
    /// [`crate::stage1::person_record::person_seed_verdict`].
    pub live_margin_ms: i64,
}

impl Default for PersonSeedDeps {
    fn default() -> Self {
        Self {
            enabled: false,
            live_margin_ms: 900_000,
        }
    }
}

/// The person head: route each seed, read every record the run can touch in one batch, and fold
/// them into an overlay. Everything after this is [`seed_apply`](crate::workers::seed_apply)'s.
pub(crate) struct PersonHead;

impl SeedHead for PersonHead {
    type Seed = PersonSeed;
    const KIND: SeedKind = SeedKind::Person;

    async fn fold(
        deps: ApplyDeps<'_>,
        run: SeedRun<PersonSeed>,
        _stamp: &RunStamp,
        clock: &mut StageClock,
    ) -> Result<Folded, SeedHold> {
        let span = run.span();
        let mut tally = Tally::default();

        if !deps.merge.person_seed.enabled {
            // A gate-off run is one message per scanned person, so this stays off `warn!` and
            // leans on `cohort_person_seeds_skipped_total{reason="apply_disabled"}` for the signal.
            for _ in 0..run.len() {
                tally.add(Outcome::PersonSkipped("apply_disabled"));
            }
            debug!(
                partition_id = deps.partition_id,
                seeds = run.len(),
                "person seed run skipped while person apply is disabled; re-produce the run after enabling",
            );
            clock.mark(ApplyStage::Fold);
            return Ok(Folded::nothing(span, ReKeys::Persons(Vec::new()), tally));
        }

        let Routed { local, re_keys } = route_person_seeds(deps, run, &mut tally).await?;
        clock.mark(ApplyStage::Resolve);

        let overlay = read_person_records(deps, &local).await?;
        clock.mark(ApplyStage::Read);

        let folded = fold_person_seeds(deps, span, local, re_keys, overlay, tally);
        clock.mark(ApplyStage::Fold);
        Ok(folded)
    }
}

/// One person seed that applies on this partition, with everything its fold needs resolved.
struct LocalPersonSeed<'a> {
    seed: PersonSeed,
    person: Uuid,
    filters: &'a TeamFilters,
    effective: EffectiveHashes,
    record_key: PersonRecordKey,
}

struct Routed<'a> {
    local: Vec<LocalPersonSeed<'a>>,
    re_keys: Vec<PersonSeed>,
}

/// Resolve every distinct person's tombstone chain in one batched read, then split the run into
/// what applies here and what hands off.
///
/// The catalog checks run first: the catalog is team-wide, so a seed nothing backs is dropped
/// identically on the survivor's partition, and resolving first would spend a store read and
/// possibly a cross-partition re-produce on a message already doomed.
///
/// A read failure is fail-stop: a seed applied to a merged-away person is durable state that
/// nothing downstream can retract, so a missing verdict holds the run rather than reading as
/// not-merged.
async fn route_person_seeds<'a>(
    deps: ApplyDeps<'a>,
    run: SeedRun<PersonSeed>,
    tally: &mut Tally,
) -> Result<Routed<'a>, SeedHold> {
    let mut placed: Vec<(PersonSeed, &TeamFilters, EffectiveHashes)> =
        Vec::with_capacity(run.len());
    for Admitted { work: seed, .. } in run.into_items() {
        let Some(filters) = deps.team(seed.team_id()) else {
            tally.add(Outcome::PersonDropped("team_absent"));
            continue;
        };
        let Some(effective) = effective_hashes(filters, &seed) else {
            tally.add(Outcome::PersonDropped("no_effective_hashes"));
            continue;
        };
        placed.push((seed, filters, effective));
    }

    let persons: Vec<(TeamId, Uuid)> = placed
        .iter()
        .map(|(seed, _, _)| (seed.team_id(), seed.person_id()))
        .collect();
    let resolved = resolve_run_persons(deps, persons).await?;

    let mut local = Vec::with_capacity(placed.len());
    let mut re_keys = Vec::new();
    for (seed, filters, effective) in placed {
        let resolution = resolved[&(seed.team_id(), seed.person_id())];
        let person = match route_seed(&seed, resolution, MAX_CROSS_PARTITION_REDIRECT_HOPS) {
            SeedRoute::ApplyLocal { person } => person,
            SeedRoute::ReProduce { seed: rekeyed } => {
                tally.add(Outcome::ReKeyed(SeedKind::Person));
                re_keys.push(rekeyed);
                continue;
            }
            // Apply at the best-known target once the hop budget is spent, matching the tile and
            // event paths: an orphaned row beats a silent seed loss, and holding the run instead
            // would stall every later seed on the partition behind a tombstone cycle that will
            // never resolve. The row lands under this worker's partition prefix, which the
            // survivor's own worker never reads. No sweep owns it — only the `cf_person_records`
            // TTL reclaims it, and `apply_person_seed` floors `last_seen_ms` at the scan instant
            // so it does age out wherever `COHORT_PERSON_RECORD_TTL_DAYS` is set.
            SeedRoute::CapExhausted { person } => {
                // On the attempt, with the warning: a run that a later hold keeps from settling
                // must not hide the anomaly.
                counter!(PERSON_SEED_REKEY_HOP_CAPPED_TOTAL).increment(1);
                warn!(
                    partition_id = deps.partition_id,
                    team_id = seed.team_id().0,
                    %person,
                    hops = seed.redirect_hops(),
                    "person seed redirect hop cap hit (corrupt tombstone cycle?); applying inline at the best-known target",
                );
                person
            }
        };
        let record_key =
            PersonPrefix::new(deps.partition_id, seed.team_id().0 as u64, person).record_key();
        local.push(LocalPersonSeed {
            seed,
            person,
            filters,
            effective,
            record_key,
        });
    }
    Ok(Routed { local, re_keys })
}

/// One `multi_get` over every record the run can touch, on the maintenance lane so backfill never
/// contends with live event reads.
///
/// A row that exists but does not decode is counted here, at the read, the way the event path
/// counts it: the fold rebuilds from an absent baseline, so without the counter a real codec
/// failure is indistinguishable from a dormant person that never had a record — and a run that a
/// later hold keeps from settling must not hide it.
async fn read_person_records(
    deps: ApplyDeps<'_>,
    local: &[LocalPersonSeed<'_>],
) -> Result<Overlay<PersonRecordKey, PersonRecord>, SeedHold> {
    let mut keys: Vec<PersonRecordKey> = local.iter().map(|seed| seed.record_key).collect();
    keys.sort_unstable();
    keys.dedup();

    let values = deps
        .handle
        .multi_get_person_records(keys.clone(), ReadLane::Maintenance)
        .await
        .map_err(SeedHold::store(ApplyStage::Read))?;
    let overlay =
        Overlay::from_read(
            ApplyStage::Read,
            keys,
            values,
            |bytes| match PersonRecord::decode(bytes) {
                Ok(record) => Decoded::Value(record),
                Err(_) => Decoded::Corrupt,
            },
        )?;
    let corrupt = overlay.prior_corrupt_rows();
    if corrupt > 0 {
        counter!(PERSON_SEED_PRIOR_CORRUPT_TOTAL).increment(corrupt as u64);
    }
    Ok(overlay)
}

/// What the run left on one person, carried from the fold to the emit.
struct SeededPerson<'a> {
    team_id: TeamId,
    filters: &'a TeamFilters,
    person: Uuid,
    /// Every effective evaluated hash of every seed that touched this person, `SkipLiveFresh` ones
    /// included: a register left `true` by a produce that never acked is only found by diffing the
    /// hashes the record does not match. Each maps to the run of the last seed that evaluated *it*,
    /// which is the leaf-level provenance a [`FoldedLeaf`] carries — two seeds of different runs
    /// can evaluate different hashes of one person.
    hashes: BTreeMap<[u8; 16], RunId>,
    /// The run of the last seed that touched this person, which their recomposed changes carry.
    run_id: RunId,
    /// The leaves some seed asked to recompose. Registered after the fold, so they carry the
    /// person's final run rather than the run of whichever seed happened to ask.
    recompose: BTreeSet<LeafStateKey>,
}

/// Fold every local seed into the overlay in offset order, then read the run's durable intent off
/// the touched slots.
fn fold_person_seeds(
    deps: ApplyDeps<'_>,
    span: OffsetSpan,
    local: Vec<LocalPersonSeed<'_>>,
    re_keys: Vec<PersonSeed>,
    mut overlay: Overlay<PersonRecordKey, PersonRecord>,
    mut tally: Tally,
) -> Folded {
    let margin_ms = deps.merge.person_seed.live_margin_ms;
    let mut touches: BTreeMap<PersonRecordKey, SeededPerson<'_>> = BTreeMap::new();
    let mut recompose = TouchedPersons::default();

    for seeded in &local {
        let team_id = seeded.seed.team_id();
        let run_id = seeded.seed.run_id();
        let slot = overlay
            .slot_mut(&seeded.record_key)
            .expect("the read pass keyed a slot for every person this run can touch");
        // Read-your-writes covers the verdict, not just the record: a second seed for the same
        // person in a run sees the first seed's stamp and zeroed fingerprints and gets
        // `SkipLiveFresh`, exactly as it would in a later run.
        let prior = match slot.current() {
            Some(record) => PriorRecord::Present(record.clone()),
            None if slot.prior_corrupt() => PriorRecord::Corrupt,
            None => PriorRecord::Absent,
        };
        let verdict = person_seed_verdict(
            &prior,
            seeded.seed.scanned_at_ms(),
            margin_ms,
            seeded.filters.catalog_fingerprint,
        );
        // A live-fresh skip is not merged at all: the stored state already subsumes the seed.
        let update = match verdict {
            PersonSeedVerdict::SkipLiveFresh => RecordUpdate::Unchanged,
            _ => record_update(&prior, &seeded.seed, &seeded.effective, margin_ms),
        };
        tally.add(update.outcome(verdict));
        let recomposes_this = recomposes(&update, verdict, &prior);
        match update {
            RecordUpdate::Changed(record) => slot.advance(record),
            RecordUpdate::Unchanged => {}
        }

        let touch = touches
            .entry(seeded.record_key)
            .or_insert_with(|| SeededPerson {
                team_id,
                filters: seeded.filters,
                person: seeded.person,
                hashes: BTreeMap::new(),
                run_id,
                recompose: BTreeSet::new(),
            });
        // Offset order, so last write wins on both: the person carries the last seed that touched
        // them, each hash the last seed that evaluated that hash.
        touch.run_id = run_id;
        for &hash in &seeded.effective.evaluated {
            touch.hashes.insert(hash, run_id);
        }
        if recomposes_this {
            touch.recompose.extend(seeded.effective.leaf_keys());
        }
    }

    let mut records = StagedBatch::default();
    let mut leaves: BTreeMap<TeamId, Vec<FoldedLeaf>> = BTreeMap::new();
    for (key, touch) in &touches {
        let slot = overlay
            .slot(key)
            .expect("every touch came from a slot the read pass keyed");
        if let Some(record) = slot.advanced() {
            records.put::<PersonRecords>(key, &record.encode());
        }
        // A person with no stored record and no write has no leaves: nothing was durably
        // evaluated, so there is no register to diff. That is the dominant scan shape, a
        // non-matching dormant person, which stays at one batched read slot and no write.
        let evaluated = slot.advanced().is_some() || slot.before().is_some();
        if !evaluated && !slot.prior_corrupt() {
            continue;
        }
        // Every recomposing seed's leaves under the person's final run, so the composed change
        // names the last seed that touched them. A person with leaves here always has state to
        // evaluate, so the guard above never drops one.
        for &leaf in &touch.recompose {
            recompose.touch(touch.team_id, touch.person, touch.run_id, leaf);
        }
        for (hash, &run_id) in &touch.hashes {
            // An unreadable row survives only under seeds that matched nothing, so the seeds are
            // the one readable evaluation and they say no matches, which is also how the
            // composition reads the row.
            let in_cohort = evaluated
                && slot
                    .current()
                    .is_some_and(|record| record.matched.contains(hash));
            let before = slot
                .before()
                .is_some_and(|record| record.matched.contains(hash));
            let minted_transition = before != in_cohort;
            leaves.entry(touch.team_id).or_default().push(FoldedLeaf {
                leaf_state_key: LeafStateKey::for_person_property(hash),
                person_id: touch.person,
                in_cohort,
                minted_transition,
                run_id,
            });
            if minted_transition {
                let kind = if in_cohort {
                    TransitionKind::Entered
                } else {
                    TransitionKind::Left
                };
                let transition = LeafTransition {
                    team_id: touch.team_id,
                    leaf_state_key: LeafStateKey::for_person_property(hash),
                    person_id: touch.person,
                    condition_hash: *hash,
                    kind,
                };
                // Stage-1 flips, not emissions: the register diff owns what downstream is told.
                record_stage1_transition(&mut tally, touch.filters, &transition);
            }
        }
    }

    Folded {
        span,
        records,
        leaves,
        recompose,
        // Nothing to schedule: person-property membership has no window, so the sweep never owns
        // these leaves.
        schedules: Vec::new(),
        re_keys: ReKeys::Persons(re_keys),
        tally,
    }
}

#[derive(Debug, PartialEq, Eq)]
enum RecordUpdate {
    Changed(PersonRecord),
    /// Nothing to write, so an absent record with no matches is never created and store growth
    /// stays proportional to matchers.
    Unchanged,
}

impl RecordUpdate {
    /// `verdict` labels the writing arm only: an unchanged merge says nothing about which verdict
    /// admitted it. Counted only once the run settles, so a hold cannot count one seed twice under
    /// two different arms.
    fn outcome(&self, verdict: PersonSeedVerdict) -> Outcome {
        match (self, verdict) {
            (_, PersonSeedVerdict::SkipLiveFresh) => Outcome::PersonSkipped("stale_vs_live"),
            (Self::Changed(_), _) => Outcome::PersonApplied(verdict.as_str()),
            (Self::Unchanged, _) => Outcome::PersonUnchanged,
        }
    }
}

/// Whether stage 2 has to be recomposed for this seed.
///
/// A merge that changed nothing leaves stage 2 already consistent with stage 1, and skipping the
/// recompose keeps a non-matching dormant person to a single point read instead of a composition
/// over every cohort its hashes touch — the dominant message shape of a scan that emits
/// non-matchers. Two outcomes still have to recompose:
///
/// - `SkipLiveFresh` may be the redelivery of an attempt that committed stage 1 and then failed its
///   produce. The replay merges to `Unchanged` and mints no transition, and a live event that
///   re-derives the same matched set mints none either, so nothing else would ever write those
///   stage-2 bits and the person would sit outside every composed cohort.
/// - A corrupt prior's stage-1 truth is unreadable, so the stored bits cannot be assumed to match
///   it.
///
/// Residue: once a live event has overwritten a held attempt's zeroed fingerprints *and* the catalog
/// has since rotated, the replay reads as an ordinary catalog-uncovered no-op and the composed bit
/// is the reconcile snapshot's to repair. The single-leaf half of the same replay is safe either
/// way, because a lagging register admits the emit on its own.
fn recomposes(update: &RecordUpdate, verdict: PersonSeedVerdict, prior: &PriorRecord) -> bool {
    matches!(update, RecordUpdate::Changed(_))
        || verdict == PersonSeedVerdict::SkipLiveFresh
        || matches!(prior, PriorRecord::Corrupt)
}

/// An absent or corrupt prior folds from the absent baseline rather than skipping: freezing
/// membership on an unreadable row would be a silent correctness hole. What the unreadable row held
/// outside `evaluated` is lost with it, and mints no `Left` — hence the corrupt counter at the read.
fn record_update(
    prior: &PriorRecord,
    seed: &PersonSeed,
    effective: &EffectiveHashes,
    live_margin_ms: i64,
) -> RecordUpdate {
    let baseline = PersonRecord::absent();
    let from = match prior {
        PriorRecord::Present(record) => record,
        PriorRecord::Absent | PriorRecord::Corrupt => &baseline,
    };
    match apply_person_seed(
        from,
        &effective.evaluated,
        &effective.matched,
        seed.scanned_at_ms(),
        live_margin_ms,
    ) {
        PersonSeedOutcome::Unchanged => RecordUpdate::Unchanged,
        // The per-seed transitions are dropped: a run counts the *net* flip per hash, which the
        // fold derives from the overlay once every seed has folded.
        PersonSeedOutcome::Changed { record, .. } => RecordUpdate::Changed(record),
    }
}

/// The seed's hashes projected onto the team's live person-property catalog.
struct EffectiveHashes {
    /// Sorted and distinct, so [`effective_hashes`] can binary-search it.
    evaluated: Vec<[u8; 16]>,
    matched: MatchedSet,
}

impl EffectiveHashes {
    fn leaf_keys(&self) -> impl Iterator<Item = LeafStateKey> + '_ {
        self.evaluated.iter().map(LeafStateKey::for_person_property)
    }
}

/// Restrict the seed to hashes this team's catalog still resolves to a person-property leaf, or
/// `None` when nothing survives.
///
/// Both lists must be filtered together: keeping a hash in `evaluated` that was dropped from
/// `matched` would retract a TRUE the catalog no longer knows how to re-derive.
fn effective_hashes(filters: &TeamFilters, seed: &PersonSeed) -> Option<EffectiveHashes> {
    let mut evaluated: Vec<[u8; 16]> = Vec::with_capacity(seed.evaluated().len());
    for hash in seed.evaluated() {
        let condition_hash = hash.as_bytes();
        if !filters.person_property_conditions.contains(&condition_hash) {
            counter!(PERSON_SEED_HASHES_DROPPED_TOTAL, "reason" => "unknown_hash").increment(1);
            continue;
        }
        let lsk = LeafStateKey::for_person_property(&condition_hash);
        match filters.by_lsk.get(&lsk).map(|meta| meta.variant) {
            Some(StateVariant::PersonProperty) => evaluated.push(condition_hash),
            Some(_) => {
                counter!(PERSON_SEED_HASHES_DROPPED_TOTAL, "reason" => "variant_mismatch")
                    .increment(1);
            }
            None => {
                counter!(PERSON_SEED_HASHES_DROPPED_TOTAL, "reason" => "unknown_hash").increment(1);
            }
        }
    }
    if evaluated.is_empty() {
        return None;
    }

    // `evaluated` was built in the seed's sorted order, so it stays sorted for the binary search.
    let matched: MatchedSet = seed
        .matched()
        .iter()
        .map(|hash| hash.as_bytes())
        .filter(|hash| evaluated.binary_search(hash).is_ok())
        .collect();
    Some(EffectiveHashes { evaluated, matched })
}

#[cfg(test)]
// Tests seed and assert against `CohortStore` directly, the sanctioned direct-store surface.
#[allow(clippy::disallowed_methods)]
mod tests {
    use std::sync::Arc;

    use chrono_tz::UTC;
    use cohort_core::seed::{ClaimEpoch, ConditionHash, ScannedAtMs};
    use serde_json::{json, Value};
    use tempfile::TempDir;

    use crate::consumers::events::CohortStreamEvent;
    use crate::filters::manager::CatalogHandle;
    use crate::filters::{CohortId, FilterCatalog, TeamFiltersBuilder, TeamId};
    use crate::merge::transfer::Tombstone;
    use crate::partitions::offset_tracker::OffsetTracker;
    use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
    use crate::partitions::watermarks::LiveWatermarks;
    use crate::producer::MembershipSink;
    use crate::producer::{
        CaptureCascadeSink, CaptureSeedTileSink, CaptureSink, CaptureStreamEventSink,
        CaptureTransferSink, ChangeOrigin, MembershipStatus,
    };
    use crate::stage1::person_record::{PropsFingerprint, Stamp};
    use crate::stage1::state::AppliedOffsets;
    use crate::stage2::state::Stage2State;
    use crate::store::{BehavioralKey, StoreHandle};
    use crate::store::{
        CohortStore, OffloadConfig, OffloadMode, Stage2Key, StoreConfig, TombstoneKey,
    };
    use crate::sweep::EvictionQueue;
    use crate::workers::event_path::{process_event_gated, EventNameGating};
    use crate::workers::merge_path::MergeWorkerDeps;
    use crate::workers::seed_apply::{apply, BatchMarks};
    use crate::workers::seed_run::{SeedOffset, SeedRun};
    use crate::workers::stage2_path::compose_stage2;
    use crate::workers::{CascadeConfig, ReconcileDeps, TransferRetryPolicy};

    use super::*;

    const TEAM: TeamId = TeamId(7);
    const PERSON_HASH: &str = "fedcba9876543210";
    const OTHER_HASH: &str = "abcdef0123456789";
    const UNKNOWN_HASH: &str = "0000000000000000";
    const LAST_UPDATED: &str = "2026-06-15 12:00:00.000000";
    const MARGIN_MS: i64 = 900_000;

    fn person_leaf(hash: &str) -> Value {
        json!({
            "type": "person",
            "key": "email",
            "value": "a@b.com",
            "operator": "exact",
            "conditionHash": hash,
            "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn behavioral_leaf() -> Value {
        json!({
            "type": "behavioral", "value": "performed_event", "key": "$pageview",
            "time_value": 7, "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn wrap(values: Vec<Value>) -> Value {
        json!({ "properties": { "type": "AND", "values": values } })
    }

    /// Cohort 1 is the person leaf alone (single-leaf register + direct emission); cohort 2 ANDs it
    /// with a behavioral leaf (Stage 2 composition).
    fn mixed_cohorts() -> Vec<(i32, Value)> {
        vec![
            (1, wrap(vec![person_leaf(PERSON_HASH)])),
            (2, wrap(vec![person_leaf(PERSON_HASH), behavioral_leaf()])),
        ]
    }

    /// One single-leaf cohort per hash, so each hash's own change carries its own provenance.
    fn one_cohort_per_hash() -> Vec<(i32, Value)> {
        vec![
            (1, wrap(vec![person_leaf(PERSON_HASH)])),
            (3, wrap(vec![person_leaf(OTHER_HASH)])),
        ]
    }

    fn build_filters(cohorts: &[(i32, Value)]) -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        for (id, filters) in cohorts {
            builder.add_cohort(CohortId(*id), TEAM, filters).unwrap();
        }
        builder.freeze(UTC)
    }

    fn hash(value: &str) -> ConditionHash {
        ConditionHash::parse(value).unwrap()
    }

    fn seed_for(
        person: Uuid,
        evaluated: &[&str],
        matched: &[&str],
        scanned_at_ms: i64,
    ) -> PersonSeed {
        seed_of_run(
            person,
            RunId(Uuid::from_u128(0xBF)),
            evaluated,
            matched,
            scanned_at_ms,
        )
    }

    fn seed_of_run(
        person: Uuid,
        run: RunId,
        evaluated: &[&str],
        matched: &[&str],
        scanned_at_ms: i64,
    ) -> PersonSeed {
        PersonSeed::new(
            TEAM,
            person,
            evaluated.iter().copied().map(hash).collect(),
            matched.iter().copied().map(hash).collect(),
            ScannedAtMs(scanned_at_ms),
            run,
            ClaimEpoch(1),
        )
        .unwrap()
    }

    struct Shell {
        _dir: TempDir,
        store: CohortStore,
        handle: StoreHandle,
        filters: TeamFilters,
        catalog: Arc<CatalogHandle>,
        sink: CaptureSink,
        seed_sink: CaptureSeedTileSink,
        deps: MergeWorkerDeps,
        /// Mints a strictly increasing stamp per run, the way a partition worker does, so a
        /// re-emission wins LWW against the change it replaces.
        clock: crate::producer::LastUpdatedClock,
    }

    impl Shell {
        fn new(cohorts: Vec<(i32, Value)>) -> Self {
            Self::with_sinks(cohorts, CaptureSink::new(), CaptureSeedTileSink::new())
        }

        fn with_sinks(
            cohorts: Vec<(i32, Value)>,
            sink: CaptureSink,
            seed_sink: CaptureSeedTileSink,
        ) -> Self {
            let dir = TempDir::new().unwrap();
            let store = CohortStore::open(&StoreConfig {
                path: dir.path().join("db"),
                ..StoreConfig::default()
            })
            .unwrap();
            let handle = StoreHandle::new(
                store.clone(),
                OffloadConfig {
                    mode: OffloadMode::All,
                    event_read_permits: 16,
                    maintenance_permits: 6,
                },
            );
            let catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
                TEAM,
                build_filters(&cohorts),
            )])));
            let deps = MergeWorkerDeps {
                transfer_sink: Arc::new(CaptureTransferSink::new()),
                stream_event_sink: Arc::new(CaptureStreamEventSink::new()),
                merge_tracker: Arc::new(OffsetTracker::new()),
                transfer_tracker: Arc::new(OffsetTracker::new()),
                retry: TransferRetryPolicy::default(),
                gc_scan_limit: crate::workers::DEFAULT_MERGE_GC_SCAN_LIMIT,
                stage2_orphan_gc_enabled: true,
                cascade_sink: Arc::new(CaptureCascadeSink::new()),
                cascade_tracker: Arc::new(OffsetTracker::new()),
                cascade: CascadeConfig::default(),
                partition_count: COHORT_PARTITION_COUNT,
                seed_tile_sink: Arc::new(seed_sink.clone()),
                seed_tracker: Arc::new(OffsetTracker::new()),
                live_watermarks: Arc::new(LiveWatermarks::new()),
                register_transfer_enabled: false,
                reconcile: ReconcileDeps::default(),
                person_seed: PersonSeedDeps {
                    enabled: true,
                    live_margin_ms: MARGIN_MS,
                },
                seed_budget: crate::workers::seed_run::RunBudget::default(),
            };
            Self {
                _dir: dir,
                store,
                handle,
                filters: build_filters(&cohorts),
                catalog,
                sink,
                seed_sink,
                deps,
                clock: crate::producer::LastUpdatedClock::default(),
            }
        }

        /// Apply one seed as a run of one, which is what a batch of one seed becomes.
        async fn run(&mut self, partition_id: u16, seed: &PersonSeed, offset: i64) {
            self.run_batch(partition_id, vec![(seed.clone(), offset)])
                .await;
        }

        /// Apply several seeds as one run, the way a channel batch of them applies.
        async fn run_batch(&mut self, partition_id: u16, seeds: Vec<(PersonSeed, i64)>) {
            let max = seeds.iter().map(|(_, offset)| *offset).max().unwrap();
            self.deps
                .seed_tracker
                .mark_dispatched(partition_id as i32, max + 1);
            let sink: Arc<dyn MembershipSink> = Arc::new(self.sink.clone());
            let snapshot = self.catalog.load();
            let deps = ApplyDeps {
                partition_id,
                handle: &self.handle,
                catalog: &snapshot,
                sink: &sink,
                merge: &self.deps,
            };
            let run = SeedRun::new(
                seeds
                    .into_iter()
                    .map(|(work, offset)| Admitted {
                        work,
                        offset: SeedOffset(offset),
                    })
                    .collect(),
            )
            .expect("a run of at least one seed");
            let mut queue = EvictionQueue::<BehavioralKey>::new();
            let mut marks = BatchMarks::default();
            apply::<PersonHead>(deps, &mut queue, &mut self.clock, &mut marks, run).await;
            marks.publish(&self.deps.seed_tracker, partition_id);
        }

        /// Without `person_properties`, this leaves behavioral state written and no person record.
        fn live_pageview(&self, partition_id: u16, person: Uuid, person_properties: Option<&str>) {
            process_event_gated(
                partition_id,
                &self.store,
                &self.filters,
                &CohortStreamEvent {
                    team_id: TEAM.0,
                    person_id: person.to_string(),
                    distinct_id: "d".to_string(),
                    uuid: "u".to_string(),
                    event: "$pageview".to_string(),
                    timestamp: chrono::Utc::now()
                        .format("%Y-%m-%d %H:%M:%S%.6f")
                        .to_string(),
                    properties: Some("{}".to_string()),
                    person_properties: person_properties.map(str::to_string),
                    elements_chain: None,
                    source_offset: 1,
                    source_partition: 0,
                    redirected_from: None,
                    redirect_hops: 0,
                },
                EventNameGating::Disabled,
            )
            .unwrap();
        }

        fn record(&self, partition_id: u16, person: Uuid) -> Option<PersonRecord> {
            let key = PersonPrefix::new(partition_id, TEAM.0 as u64, person).record_key();
            self.store
                .get_person_record(&key)
                .unwrap()
                .map(|bytes| PersonRecord::decode(&bytes).unwrap())
        }

        fn put_record(&self, partition_id: u16, person: Uuid, record: &PersonRecord) {
            let key = PersonPrefix::new(partition_id, TEAM.0 as u64, person).record_key();
            self.store
                .write_batch(|batch| batch.put::<PersonRecords>(&key, &record.encode()))
                .unwrap();
        }

        fn put_corrupt_record(&self, partition_id: u16, person: Uuid) {
            let key = PersonPrefix::new(partition_id, TEAM.0 as u64, person).record_key();
            self.store
                .write_batch(|batch| batch.put::<PersonRecords>(&key, b"not a person record"))
                .unwrap();
        }

        /// A new tenure over the same store, catalog, and sinks: fresh offset trackers, the way a
        /// restart or rebalance re-assigns the partition at `Offset::Stored` and replays whatever a
        /// hold pinned.
        fn restart(&mut self) {
            self.deps.seed_tracker = Arc::new(OffsetTracker::new());
            self.deps.merge_tracker = Arc::new(OffsetTracker::new());
            self.deps.transfer_tracker = Arc::new(OffsetTracker::new());
            self.deps.cascade_tracker = Arc::new(OffsetTracker::new());
        }

        /// The register row a live evaluation would have left beside `put_record`'s record.
        fn put_register(&self, partition_id: u16, person: Uuid, cohort_id: u64, in_cohort: bool) {
            let key = Stage2Key {
                partition_id,
                team_id: TEAM.0 as u64,
                cohort_id,
                person_id: person,
            };
            let state = Stage2State {
                in_cohort,
                last_evaluated_at_ms: now_ms(),
            };
            self.store
                .write_batch(|b| b.put_stage2(&key, &state.encode()))
                .unwrap();
        }

        fn stage2(&self, partition_id: u16, person: Uuid, cohort_id: u64) -> Option<Stage2State> {
            self.store
                .get_stage2(&Stage2Key {
                    partition_id,
                    team_id: TEAM.0 as u64,
                    cohort_id,
                    person_id: person,
                })
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

    fn dormant_person() -> (Uuid, u16) {
        let person = Uuid::from_u128(0x5EED);
        let partition_id = partition_of(TEAM, &person, COHORT_PARTITION_COUNT) as u16;
        (person, partition_id)
    }

    fn now_ms() -> i64 {
        chrono::Utc::now().timestamp_millis()
    }

    #[tokio::test]
    async fn a_dormant_person_seed_creates_the_record_and_lands_both_cohorts() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        shell.live_pageview(partition_id, person, None);
        assert!(
            shell.record(partition_id, person).is_none(),
            "an event without person_properties leaves the person record absent",
        );

        let seed = seed_for(person, &[PERSON_HASH], &[PERSON_HASH], now_ms());
        shell.run(partition_id, &seed, 9).await;

        let stored = shell
            .record(partition_id, person)
            .expect("the seed creates the record");
        assert!(stored.matched.contains(&hash(PERSON_HASH).as_bytes()));
        assert_eq!(
            stored.catalog_fingerprint,
            crate::stage1::person_record::CatalogFingerprint(0),
            "a subset evaluation must not claim full-catalog coverage",
        );

        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            2,
            "single-leaf cohort 1 and composed cohort 2"
        );
        assert!(changes.iter().all(|change| {
            change.status == MembershipStatus::Entered
                && change.origin == Some(ChangeOrigin::Seed)
                && change.run_id == Some(seed.run_id())
                && change.person_id == person.to_string()
        }));
        assert!(shell.stage2(partition_id, person, 1).unwrap().in_cohort);
        assert!(shell.stage2(partition_id, person, 2).unwrap().in_cohort);
        assert_eq!(shell.committable(partition_id), Some(10));

        // Replay: the merge is Unchanged, so nothing is re-emitted.
        shell.run(partition_id, &seed, 10).await;
        assert_eq!(shell.sink.changes().len(), 2);
        assert_eq!(shell.committable(partition_id), Some(11));
    }

    #[tokio::test]
    async fn a_live_fresh_covered_record_skips_the_seed_without_writing() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        let live = PersonRecord {
            last_seen_ms: now_ms(),
            stamp: Stamp::new(now_ms(), 0),
            props_fingerprint: PropsFingerprint::of(r#"{"email":"a@b.com"}"#),
            catalog_fingerprint: shell.filters.catalog_fingerprint,
            matched: MatchedSet::from_iter([hash(PERSON_HASH).as_bytes()]),
            applied_offsets: AppliedOffsets::default(),
            redirect_dedup: Default::default(),
        };
        shell.put_record(partition_id, person, &live);
        shell.put_register(partition_id, person, 1, true);

        // An older scan that would retract the hash.
        let seed = seed_for(person, &[PERSON_HASH], &[], now_ms() - 1_000);
        shell.run(partition_id, &seed, 0).await;

        assert_eq!(
            shell.record(partition_id, person).unwrap(),
            live,
            "the record is byte-identical: no write at all",
        );
        assert!(shell.stage2(partition_id, person, 1).unwrap().in_cohort);
        assert!(shell.sink.changes().is_empty());
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    /// The record carries the hash but no register row, the state left behind when the row is GC'd
    /// or when the cohort post-dates the live evaluation that matched. A retraction must still be
    /// emitted: an absent row cannot prove downstream was never told, and the minted `Left` is the
    /// only thing that can retire a stale entry.
    #[tokio::test]
    async fn a_newer_seed_retracts_a_stale_true_hash_with_no_register_row() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        let stale = PersonRecord {
            last_seen_ms: 1_000,
            stamp: Stamp::new(1_000, 0),
            props_fingerprint: PropsFingerprint::of("{}"),
            catalog_fingerprint: shell.filters.catalog_fingerprint,
            matched: MatchedSet::from_iter([hash(PERSON_HASH).as_bytes()]),
            applied_offsets: AppliedOffsets::default(),
            redirect_dedup: Default::default(),
        };
        shell.put_record(partition_id, person, &stale);
        assert!(shell.stage2(partition_id, person, 1).is_none());

        let seed = seed_for(person, &[PERSON_HASH], &[], 1_000 + MARGIN_MS + 1);
        shell.run(partition_id, &seed, 0).await;

        assert!(shell
            .record(partition_id, person)
            .unwrap()
            .matched
            .is_empty());
        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1, "cohort 1 only: cohort 2 was never in");
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].status, MembershipStatus::Left);
        assert!(!shell.stage2(partition_id, person, 1).unwrap().in_cohort);
    }

    #[tokio::test]
    async fn a_nonmatching_seed_retracts_a_true_register_over_a_corrupt_record() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        shell.put_corrupt_record(partition_id, person);
        shell.put_register(partition_id, person, 1, true);

        let seed = seed_for(person, &[PERSON_HASH], &[], now_ms());
        shell.run(partition_id, &seed, 0).await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].status, MembershipStatus::Left);
        assert!(!shell.stage2(partition_id, person, 1).unwrap().in_cohort);
    }

    /// The same retraction with its produce failing: the stage-1 pre-write has to record that
    /// downstream still holds the entry, or the redelivery merges to `Unchanged`, mints nothing,
    /// and the `Left` is lost for good.
    #[tokio::test]
    async fn a_failed_retraction_over_an_absent_register_is_re_emitted_on_redelivery() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        let stale = PersonRecord {
            last_seen_ms: 1_000,
            stamp: Stamp::new(1_000, 0),
            props_fingerprint: PropsFingerprint::of("{}"),
            catalog_fingerprint: shell.filters.catalog_fingerprint,
            matched: MatchedSet::from_iter([hash(PERSON_HASH).as_bytes()]),
            applied_offsets: AppliedOffsets::default(),
            redirect_dedup: Default::default(),
        };
        shell.put_record(partition_id, person, &stale);
        let seed = seed_for(person, &[PERSON_HASH], &[], 1_000 + MARGIN_MS + 1);

        shell.run(partition_id, &seed, 0).await;
        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        assert!(shell.sink.changes().is_empty());
        assert!(
            shell.stage2(partition_id, person, 1).unwrap().in_cohort,
            "the pre-write records the entry downstream still holds",
        );

        shell.restart();
        shell.run(partition_id, &seed, 0).await;

        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1, "the redelivery re-derived the retraction");
        assert_eq!(changes[0].cohort_id, 1);
        assert_eq!(changes[0].status, MembershipStatus::Left);
        assert!(!shell.stage2(partition_id, person, 1).unwrap().in_cohort);
    }

    /// A retraction over an absent register pre-writes `true` and then fails its produce, so
    /// downstream was told nothing while the register claims it holds the entry. A newer seed that
    /// re-matches before the redelivery mints `Entered` over a register already reading `true`;
    /// the minted transition wins, or downstream would never hear of a membership the store holds.
    #[tokio::test]
    async fn a_re_entry_over_a_stranded_true_pre_write_is_emitted() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        let stale = PersonRecord {
            last_seen_ms: 1_000,
            stamp: Stamp::new(1_000, 0),
            props_fingerprint: PropsFingerprint::of("{}"),
            catalog_fingerprint: shell.filters.catalog_fingerprint,
            matched: MatchedSet::from_iter([hash(PERSON_HASH).as_bytes()]),
            applied_offsets: AppliedOffsets::default(),
            redirect_dedup: Default::default(),
        };
        shell.put_record(partition_id, person, &stale);
        assert!(shell.stage2(partition_id, person, 1).is_none());

        let retract = seed_for(person, &[PERSON_HASH], &[], 1_000 + MARGIN_MS + 1);
        shell.run(partition_id, &retract, 0).await;
        assert!(
            shell.sink.changes().is_empty(),
            "nothing reached downstream"
        );
        assert!(
            shell.stage2(partition_id, person, 1).unwrap().in_cohort,
            "the pre-write claims downstream still holds the entry",
        );

        let rematch = seed_for(
            person,
            &[PERSON_HASH],
            &[PERSON_HASH],
            1_000 + 2 * MARGIN_MS + 2,
        );
        shell.run(partition_id, &rematch, 1).await;

        let changes = shell.sink.changes();
        assert_eq!(
            changes
                .iter()
                .map(|change| (change.cohort_id, change.status))
                .collect::<Vec<_>>(),
            vec![(1, MembershipStatus::Entered)],
            "downstream is told about the membership the store holds",
        );
        assert!(shell.stage2(partition_id, person, 1).unwrap().in_cohort);
        assert_eq!(
            shell.committable(partition_id),
            None,
            "the held retraction still pins the floor"
        );
    }

    #[tokio::test]
    async fn a_record_evaluated_under_another_catalog_still_applies() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        let stamped_at = now_ms();
        let uncovered = PersonRecord {
            last_seen_ms: stamped_at,
            stamp: Stamp::new(stamped_at, 0),
            props_fingerprint: PropsFingerprint::of("{}"),
            // Evaluated against a catalog that did not hold this team's person conditions.
            catalog_fingerprint: crate::stage1::person_record::CatalogFingerprint(0xDEAD),
            matched: MatchedSet::empty(),
            applied_offsets: AppliedOffsets::default(),
            redirect_dedup: Default::default(),
        };
        shell.put_record(partition_id, person, &uncovered);

        // Inside the margin, so the record is not provably older; only the catalog rotation admits.
        let seed = seed_for(person, &[PERSON_HASH], &[PERSON_HASH], stamped_at + 1_000);
        shell.run(partition_id, &seed, 0).await;

        assert!(shell
            .record(partition_id, person)
            .unwrap()
            .matched
            .contains(&hash(PERSON_HASH).as_bytes()));
        assert_eq!(shell.sink.changes().len(), 1);
    }

    /// A rotated catalog is a team-wide event, so without a recency test any backlogged scan would
    /// overwrite live state on the strength of an unrelated cohort edit.
    #[tokio::test]
    async fn a_scan_older_than_the_record_never_applies_on_a_catalog_rotation_alone() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        let live = PersonRecord {
            last_seen_ms: now_ms(),
            stamp: Stamp::new(now_ms(), 0),
            props_fingerprint: PropsFingerprint::of(r#"{"email":"b@c.com"}"#),
            catalog_fingerprint: crate::stage1::person_record::CatalogFingerprint(0xDEAD),
            matched: MatchedSet::empty(),
            applied_offsets: AppliedOffsets::default(),
            redirect_dedup: Default::default(),
        };
        shell.put_record(partition_id, person, &live);

        shell
            .run(
                partition_id,
                &seed_for(
                    person,
                    &[PERSON_HASH],
                    &[PERSON_HASH],
                    now_ms() - 86_400_000,
                ),
                0,
            )
            .await;

        assert_eq!(
            shell.record(partition_id, person).unwrap(),
            live,
            "a day-old scan must not re-enter a person live already evaluated out",
        );
        assert!(shell.sink.changes().is_empty());
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    #[tokio::test]
    async fn hashes_the_catalog_no_longer_backs_drop_out_of_the_effective_set() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());

        let partial = seed_for(
            person,
            &[UNKNOWN_HASH, PERSON_HASH],
            &[UNKNOWN_HASH, PERSON_HASH],
            now_ms(),
        );
        shell.run(partition_id, &partial, 0).await;

        let stored = shell.record(partition_id, person).unwrap();
        assert_eq!(stored.matched.len(), 1, "only the known hash is stored");
        assert!(stored.matched.contains(&hash(PERSON_HASH).as_bytes()));

        // Nothing survives the projection: a whole-seed drop that still commits its offset.
        let orphaned = seed_for(person, &[UNKNOWN_HASH], &[UNKNOWN_HASH], now_ms());
        shell.run(partition_id, &orphaned, 1).await;
        assert_eq!(shell.record(partition_id, person).unwrap(), stored);
        assert_eq!(shell.committable(partition_id), Some(2));
    }

    #[tokio::test]
    async fn a_non_matching_dormant_person_creates_no_record() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());

        shell
            .run(
                partition_id,
                &seed_for(person, &[PERSON_HASH], &[], now_ms()),
                0,
            )
            .await;

        assert!(shell.record(partition_id, person).is_none());
        assert!(shell.sink.changes().is_empty());
        assert!(
            shell.stage2(partition_id, person, 1).is_none(),
            "no record means nothing was durably evaluated, so no register row is invented \
             either, and store growth stays proportional to matchers",
        );
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    // ---- runs of more than one seed ----

    /// Read-your-writes has to cover the verdict, not just the record: the second seed for one
    /// person must see the first seed's stamp and zeroed fingerprints and skip, exactly as it
    /// would in a later run. Folding it against the run-start bytes would let the older scan
    /// retract what the newer one matched.
    #[tokio::test]
    async fn a_second_seed_for_one_person_in_a_run_sees_the_first_seeds_write() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        let scanned_at = now_ms();

        shell
            .run_batch(
                partition_id,
                vec![
                    (
                        seed_for(person, &[PERSON_HASH], &[PERSON_HASH], scanned_at),
                        0,
                    ),
                    // A second scan of the same person, within the live margin of the first, so its
                    // retraction must lose to the stamp the first seed installed.
                    (seed_for(person, &[PERSON_HASH], &[], scanned_at), 1),
                ],
            )
            .await;

        let stored = shell
            .record(partition_id, person)
            .expect("the first seed created the record");
        assert!(
            stored.matched.contains(&hash(PERSON_HASH).as_bytes()),
            "the second seed was live-fresh against the first seed's stamp, so it changed nothing",
        );
        assert!(shell.stage2(partition_id, person, 1).unwrap().in_cohort);
        assert_eq!(shell.committable(partition_id), Some(2));
    }

    /// Splitting a person's leaves across two recompute calls would evaluate the composed cohort
    /// twice against the same uncommitted bit and emit its flip twice.
    #[tokio::test]
    async fn a_person_touched_by_two_seeds_in_a_run_recomposes_once() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        // The behavioral half of cohort 2, so the person composes in once the person half lands.
        shell.live_pageview(partition_id, person, None);
        let scanned_at = now_ms();

        shell
            .run_batch(
                partition_id,
                vec![
                    (
                        seed_for(person, &[PERSON_HASH], &[PERSON_HASH], scanned_at),
                        0,
                    ),
                    (
                        seed_for(person, &[PERSON_HASH], &[PERSON_HASH], scanned_at),
                        1,
                    ),
                ],
            )
            .await;

        let composed: Vec<_> = shell
            .sink
            .changes()
            .into_iter()
            .filter(|change| change.cohort_id == 2)
            .collect();
        assert_eq!(
            composed.len(),
            1,
            "the composed cohort flipped once for the run, not once per seed",
        );
        assert_eq!(composed[0].status, MembershipStatus::Entered);
    }

    /// Provenance is per leaf, not per person: two backfill runs can seed one person on different
    /// hashes in one batch, and a change for a hash the later run never evaluated must not claim
    /// that run.
    #[tokio::test]
    async fn each_leafs_change_carries_the_run_that_last_evaluated_that_leaf() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(one_cohort_per_hash());
        let first = RunId(Uuid::from_u128(0xA));
        let second = RunId(Uuid::from_u128(0xB));

        shell
            .run_batch(
                partition_id,
                vec![
                    (
                        seed_of_run(
                            person,
                            first,
                            &[PERSON_HASH],
                            &[PERSON_HASH],
                            now_ms() - 2 * MARGIN_MS,
                        ),
                        0,
                    ),
                    // A later scan of the same person on a different hash, past the first seed's
                    // stamp floor so it applies rather than skipping live-fresh.
                    (
                        seed_of_run(person, second, &[OTHER_HASH], &[OTHER_HASH], now_ms()),
                        1,
                    ),
                ],
            )
            .await;

        let runs: BTreeMap<u64, Option<RunId>> = shell
            .sink
            .changes()
            .into_iter()
            .map(|change| (change.cohort_id as u64, change.run_id))
            .collect();
        assert_eq!(
            runs,
            BTreeMap::from([(1, Some(first)), (3, Some(second))]),
            "each cohort names the run of the seed that evaluated its hash",
        );
    }

    /// A person's composed change carries the last seed that touched them, whether or not that
    /// seed was the one that asked for the recompose.
    #[tokio::test]
    async fn a_composed_change_carries_the_last_seed_that_touched_the_person() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        // The behavioral half of cohort 2, so the person composes in once the person half lands.
        shell.live_pageview(partition_id, person, None);
        let first = RunId(Uuid::from_u128(0xA));
        let second = RunId(Uuid::from_u128(0xB));

        shell
            .run_batch(
                partition_id,
                vec![
                    (
                        seed_of_run(
                            person,
                            first,
                            &[PERSON_HASH],
                            &[PERSON_HASH],
                            now_ms() - 2 * MARGIN_MS,
                        ),
                        0,
                    ),
                    // Asserts what the first seed already wrote, so it recomposes nothing itself.
                    (
                        seed_of_run(person, second, &[PERSON_HASH], &[PERSON_HASH], now_ms()),
                        1,
                    ),
                ],
            )
            .await;

        let composed: Vec<_> = shell
            .sink
            .changes()
            .into_iter()
            .filter(|change| change.cohort_id == 2)
            .collect();
        assert_eq!(composed.len(), 1, "one composed flip for the run");
        assert_eq!(
            composed[0].run_id,
            Some(second),
            "the last seed to touch the person, not the one that asked to recompose",
        );
    }

    /// A run mixes local and redirected seeds, so a hand-off that fails must not strand the local
    /// registers. The membership leg already acked, and the cascade for that flip is consumed
    /// against the *stored* bit right after this run: an unwritten bit reads every referring
    /// cohort as unchanged until the next tenure replays the run.
    #[tokio::test]
    async fn a_failed_rekey_commits_the_local_registers_before_it_holds() {
        let (redirected, partition_id, survivor) = cross_partition_pair();
        let local = (100u128..)
            .map(Uuid::from_u128)
            .find(|person| {
                partition_of(TEAM, person, COHORT_PARTITION_COUNT) as u16 == partition_id
            })
            .expect("some uuid hashes onto the delivering partition");
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::new(),
            CaptureSeedTileSink::failing_always(),
        );
        write_tombstone(&shell.store, partition_id, redirected, survivor);
        let scanned_at = now_ms();

        shell
            .run_batch(
                partition_id,
                vec![
                    (
                        seed_for(local, &[PERSON_HASH], &[PERSON_HASH], scanned_at),
                        4,
                    ),
                    (
                        seed_for(redirected, &[PERSON_HASH], &[PERSON_HASH], scanned_at),
                        5,
                    ),
                ],
            )
            .await;

        assert_eq!(
            shell.sink.changes().len(),
            1,
            "the local seed's membership acked",
        );
        assert!(
            shell
                .stage2(partition_id, local, 1)
                .expect("the register row exists")
                .in_cohort,
            "and the register says what downstream was told",
        );
        assert_eq!(
            shell.committable(partition_id),
            None,
            "the run still holds its first offset for the hand-off",
        );
    }

    /// A seed that asserts what the record already holds recomposes nothing on its own, so a
    /// register the last run failed to emit would strand the person outside every composed cohort.
    /// The lagging row has to be its own reason to recompose.
    #[tokio::test]
    async fn a_person_whose_only_signal_is_a_lagging_register_still_recomposes() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        // The behavioral half of cohort 2, so the person composes in once stage 2 runs.
        shell.live_pageview(partition_id, person, None);
        let live = PersonRecord {
            last_seen_ms: now_ms(),
            stamp: Stamp::new(now_ms() - 2 * MARGIN_MS, 0),
            props_fingerprint: PropsFingerprint::of(r#"{"email":"a@b.com"}"#),
            catalog_fingerprint: shell.filters.catalog_fingerprint,
            matched: MatchedSet::from_iter([hash(PERSON_HASH).as_bytes()]),
            applied_offsets: AppliedOffsets::default(),
            redirect_dedup: Default::default(),
        };
        shell.put_record(partition_id, person, &live);
        // What a run that acked nothing leaves behind: the single-leaf register says the person is
        // out while the record says they are in.
        shell.put_register(partition_id, person, 1, false);

        // Asserts exactly what the record already holds, so the merge is Unchanged and mints no
        // transition — nothing in the fold would admit a recompose.
        let seed = seed_for(person, &[PERSON_HASH], &[PERSON_HASH], now_ms());
        shell.run(partition_id, &seed, 0).await;

        assert_eq!(
            shell.record(partition_id, person).unwrap().matched,
            live.matched,
            "the seed changed nothing about the record",
        );
        let changes = shell.sink.changes();
        assert_eq!(
            changes
                .iter()
                .map(|change| change.cohort_id)
                .collect::<BTreeSet<_>>(),
            BTreeSet::from([1, 2]),
            "the lagging register admits both the repair and the composition behind it",
        );
        assert!(shell.stage2(partition_id, person, 1).unwrap().in_cohort);
        assert!(shell.stage2(partition_id, person, 2).unwrap().in_cohort);
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    /// A gate-off run is dark: it marks every offset it carries and touches nothing. Marking only
    /// the last seed would be right; marking none would wedge the partition.
    #[tokio::test]
    async fn a_gate_off_run_marks_its_whole_span_without_touching_the_store() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        shell.deps.person_seed.enabled = false;
        let scanned_at = now_ms();

        shell
            .run_batch(
                partition_id,
                vec![
                    (
                        seed_for(person, &[PERSON_HASH], &[PERSON_HASH], scanned_at),
                        4,
                    ),
                    (
                        seed_for(person, &[PERSON_HASH], &[PERSON_HASH], scanned_at),
                        5,
                    ),
                ],
            )
            .await;

        assert!(shell.record(partition_id, person).is_none());
        assert!(shell.sink.changes().is_empty());
        assert_eq!(shell.committable(partition_id), Some(6));
    }

    #[tokio::test]
    async fn person_apply_disabled_skips_and_commits_without_touching_the_store() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        shell.deps.person_seed.enabled = false;

        shell
            .run(
                partition_id,
                &seed_for(person, &[PERSON_HASH], &[PERSON_HASH], now_ms()),
                4,
            )
            .await;

        assert!(shell.record(partition_id, person).is_none());
        assert!(shell.sink.changes().is_empty());
        assert_eq!(shell.committable(partition_id), Some(5));
    }

    /// A merged-away person and a survivor on the same partition, so the tombstone resolves inline.
    fn same_partition_pair() -> (Uuid, u16, Uuid) {
        let p_old = Uuid::from_u128(0xA11CE);
        let partition_id = partition_of(TEAM, &p_old, COHORT_PARTITION_COUNT) as u16;
        let p_new = (10u128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TEAM, p, COHORT_PARTITION_COUNT) as u16 == partition_id)
            .expect("some uuid hashes onto p_old's partition");
        (p_old, partition_id, p_new)
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

    fn write_tombstone(store: &CohortStore, partition_id: u16, old: Uuid, new: Uuid) {
        store
            .write_batch(|batch| {
                batch.put_tombstone(
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

    /// The resolved survivor feeds the record key, the transition's person, and the recomposed
    /// leaves. Should any of the three regress to the seed's own merged-away person, the record would
    /// land on one person and its membership on another.
    #[tokio::test]
    async fn an_inline_redirect_applies_the_seed_at_the_survivor() {
        let (p_old, partition_id, p_new) = same_partition_pair();
        let mut shell = Shell::new(mixed_cohorts());
        write_tombstone(&shell.store, partition_id, p_old, p_new);
        shell.live_pageview(partition_id, p_new, None);

        let seed = seed_for(p_old, &[PERSON_HASH], &[PERSON_HASH], now_ms());
        shell.run(partition_id, &seed, 0).await;

        assert!(
            shell.record(partition_id, p_old).is_none(),
            "nothing is written for the merged-away person",
        );
        assert!(shell
            .record(partition_id, p_new)
            .expect("the survivor gets the record")
            .matched
            .contains(&hash(PERSON_HASH).as_bytes()));
        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            2,
            "single-leaf cohort 1 and composed cohort 2"
        );
        assert!(changes
            .iter()
            .all(|change| change.person_id == p_new.to_string()));
        assert!(
            shell.stage2(partition_id, p_new, 2).unwrap().in_cohort,
            "the composed bit follows the survivor too",
        );
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    /// A capped redirect applies inline rather than dropping the seed or holding forever: the chain
    /// is corrupt, so a hold would stall every later seed on the partition behind it. The write lands
    /// under this worker's prefix, which is the accepted orphan — see `Apply::degrade_to`.
    #[tokio::test]
    async fn a_hop_capped_seed_applies_inline_and_orphans_the_row_on_this_partition() {
        let (p_old, partition_id, p_new) = cross_partition_pair();
        let mut shell = Shell::new(mixed_cohorts());
        write_tombstone(&shell.store, partition_id, p_old, p_new);

        // Exhaust the hop budget on the wire, then deliver: rekeyed_to returns None at the cap.
        let mut seed = seed_for(p_old, &[PERSON_HASH], &[PERSON_HASH], now_ms());
        for _ in 0..MAX_CROSS_PARTITION_REDIRECT_HOPS {
            seed = seed
                .rekeyed_to(p_old, MAX_CROSS_PARTITION_REDIRECT_HOPS)
                .unwrap();
        }
        shell.run(partition_id, &seed, 0).await;

        assert!(
            shell.seed_sink.person_seeds().is_empty(),
            "the hop budget is spent: no further re-produce",
        );
        let changes = shell.sink.changes();
        assert_eq!(changes.len(), 1, "cohort 1 applied inline instead");
        assert_eq!(changes[0].person_id, p_new.to_string());
        assert!(
            shell.record(partition_id, p_new).is_some(),
            "the record lands under the delivering partition's prefix",
        );
        let survivor_partition = partition_of(TEAM, &p_new, COHORT_PARTITION_COUNT) as u16;
        assert!(
            shell.record(survivor_partition, p_new).is_none(),
            "and not under the survivor's own, which is what makes it an orphan",
        );
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    #[tokio::test]
    async fn a_cross_partition_redirect_re_produces_the_rekeyed_seed_before_marking() {
        let (p_old, partition_id, p_new) = cross_partition_pair();
        let mut shell = Shell::new(mixed_cohorts());
        write_tombstone(&shell.store, partition_id, p_old, p_new);
        let seed = seed_for(p_old, &[PERSON_HASH], &[PERSON_HASH], now_ms());

        shell.run(partition_id, &seed, 7).await;

        let produced = shell.seed_sink.person_seeds();
        assert_eq!(produced.len(), 1);
        assert_eq!(produced[0].person_id(), p_new);
        assert_eq!(produced[0].redirect_hops(), 1);
        assert_eq!(
            produced[0].scanned_at_ms(),
            seed.scanned_at_ms(),
            "the LWW input rides verbatim to the survivor's worker",
        );
        assert!(
            shell.record(partition_id, p_old).is_none(),
            "no local apply"
        );
        assert_eq!(shell.committable(partition_id), Some(8));
    }

    #[tokio::test]
    async fn a_failed_rekey_produce_holds_the_seed_offset() {
        let (p_old, partition_id, p_new) = cross_partition_pair();
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::new(),
            CaptureSeedTileSink::failing_first(1),
        );
        write_tombstone(&shell.store, partition_id, p_old, p_new);
        let seed = seed_for(p_old, &[PERSON_HASH], &[PERSON_HASH], now_ms());

        shell.run(partition_id, &seed, 7).await;
        assert_eq!(shell.committable(partition_id), None);

        shell.run(partition_id, &seed, 7).await;
        assert_eq!(shell.seed_sink.person_seeds().len(), 1);
        assert_eq!(shell.committable(partition_id), Some(7));
    }

    #[tokio::test]
    async fn a_failed_membership_produce_holds_and_the_replay_re_derives_both_halves() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        shell.live_pageview(partition_id, person, None);
        let seed = seed_for(person, &[PERSON_HASH], &[PERSON_HASH], now_ms());

        shell.run(partition_id, &seed, 3).await;
        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        assert!(
            shell.record(partition_id, person).is_some(),
            "stage 1 committed before the produce",
        );
        assert!(
            shell.stage2(partition_id, person, 2).is_none(),
            "the composed bit must stay unwritten under a failed produce",
        );
        assert_eq!(
            shell
                .stage2(partition_id, person, 1)
                .map(|state| state.in_cohort),
            Some(false),
            "the single-leaf register holds its pre-write: downstream was never told",
        );

        shell.restart();
        shell.run(partition_id, &seed, 3).await;
        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            2,
            "the Unchanged replay re-derives the single-leaf change and the composed flip",
        );
        assert_eq!(
            changes
                .iter()
                .map(|change| change.cohort_id)
                .collect::<Vec<_>>(),
            vec![1, 2],
        );
        assert!(changes
            .iter()
            .all(|change| change.origin == Some(ChangeOrigin::Seed)
                && change.status == MembershipStatus::Entered));
        assert!(shell.stage2(partition_id, person, 1).unwrap().in_cohort);
        assert!(shell.stage2(partition_id, person, 2).unwrap().in_cohort);
        assert_eq!(
            shell.committable(partition_id),
            Some(4),
            "a fresh tenure commits past the redelivered offset"
        );
    }

    /// The held replay can arrive after a live event has already re-derived the same matched set.
    /// That event mints no transition, so it composes nothing, and the seed then reads as live
    /// fresh. If the skip committed without recomposing, the person would sit outside every
    /// composed cohort forever: no later event flips a leaf, and reconcile scans `cf_stage2` rows,
    /// which is precisely what is missing.
    #[tokio::test]
    async fn a_live_fresh_skip_still_recomposes_a_stage_2_bit_a_held_attempt_never_wrote() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        shell.live_pageview(partition_id, person, None);
        let seed = seed_for(person, &[PERSON_HASH], &[PERSON_HASH], now_ms());

        shell.run(partition_id, &seed, 3).await;
        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        assert!(shell.stage2(partition_id, person, 2).is_none());

        // A live event carrying the same properties re-evaluates to the set the seed already
        // stored, so it mints no transition and composes nothing.
        shell.live_pageview(partition_id, person, Some(r#"{"email":"a@b.com"}"#));
        assert!(
            shell.stage2(partition_id, person, 2).is_none(),
            "the no-op re-eval leaves the composed bit unwritten",
        );

        shell.run(partition_id, &seed, 3).await;

        assert!(
            shell.stage2(partition_id, person, 2).unwrap().in_cohort,
            "the live-fresh skip must still recompose the bit nothing else would ever write",
        );
        let changes = shell.sink.changes();
        assert_eq!(
            changes
                .iter()
                .map(|change| change.cohort_id)
                .collect::<Vec<_>>(),
            vec![1, 2],
            "the single-leaf change the failed produce lost is re-derived alongside it",
        );
        assert!(shell.stage2(partition_id, person, 1).unwrap().in_cohort);
        assert_eq!(shell.committable(partition_id), Some(3));
    }

    /// A cohort added over a record that predates it has no register row, so the next seed tells
    /// downstream even though the merge is a no-op and mints no transition.
    #[tokio::test]
    async fn a_cohort_added_over_an_existing_record_enters_on_the_next_unchanged_seed() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::new(mixed_cohorts());
        let seed = seed_for(person, &[PERSON_HASH], &[PERSON_HASH], now_ms());

        shell.run(partition_id, &seed, 0).await;
        assert_eq!(
            shell.sink.changes().len(),
            1,
            "cohort 1 only: no behavioral state"
        );

        // Cohort 3 arrives on the same person leaf, over a record it never saw evaluated.
        let mut cohorts = mixed_cohorts();
        cohorts.push((3, wrap(vec![person_leaf(PERSON_HASH)])));
        shell.catalog = Arc::new(CatalogHandle::from_catalog(FilterCatalog::from_teams([(
            TEAM,
            build_filters(&cohorts),
        )])));

        shell.run(partition_id, &seed, 1).await;

        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            2,
            "the replay is Unchanged but cohort 3 is new"
        );
        assert_eq!(changes[1].cohort_id, 3);
        assert_eq!(changes[1].status, MembershipStatus::Entered);
        assert!(shell.stage2(partition_id, person, 3).unwrap().in_cohort);
        assert_eq!(shell.committable(partition_id), Some(2));
    }

    #[tokio::test]
    async fn a_seeded_dormant_person_reaches_the_same_membership_as_a_live_evaluated_one() {
        let live_person = Uuid::from_u128(0xA11CE);
        let seeded_person = Uuid::from_u128(0x5EED);
        // One partition for both, so the two folds are directly comparable.
        let partition_id = 0;
        let mut shell = Shell::new(mixed_cohorts());

        shell.live_pageview(partition_id, live_person, Some(r#"{"email":"a@b.com"}"#));
        // Same behavioral history, but no event carried person properties.
        shell.live_pageview(partition_id, seeded_person, None);
        shell
            .run(
                partition_id,
                &seed_for(seeded_person, &[PERSON_HASH], &[PERSON_HASH], now_ms()),
                0,
            )
            .await;

        let live = shell.record(partition_id, live_person).unwrap();
        let seeded = shell.record(partition_id, seeded_person).unwrap();
        assert_eq!(
            seeded.matched, live.matched,
            "the matched set is the whole of person-property membership",
        );

        // Compose the live person's stage 2 the way its next flip would; the seed already did so.
        let leaves = [(
            LeafStateKey::for_person_property(&hash(PERSON_HASH).as_bytes()),
            live_person,
        )];
        compose_stage2(
            partition_id,
            &shell.handle,
            &shell.filters,
            &leaves,
            now_ms(),
            LAST_UPDATED,
            ReadLane::Event,
        )
        .await
        .unwrap();

        for (person, who) in [(live_person, "live"), (seeded_person, "seeded")] {
            assert!(
                shell.stage2(partition_id, person, 1).unwrap().in_cohort,
                "{who}: single-leaf cohort",
            );
            assert!(
                shell.stage2(partition_id, person, 2).unwrap().in_cohort,
                "{who}: composed cohort",
            );
        }

        assert_ne!(
            seeded.catalog_fingerprint, live.catalog_fingerprint,
            "the seed's zeroed fingerprints must force a full re-eval on the next event",
        );
        assert_ne!(seeded.props_fingerprint, live.props_fingerprint);
        assert!(
            seeded.stamp < live.stamp,
            "the seed installs a floor a margin below its scan, never the live event's own stamp",
        );
    }
}
