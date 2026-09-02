//! Applies person-property seeds to `cf_person_records`, giving dormant persons leaf state that
//! otherwise only arrives on a live event carrying `person_properties`.
//!
//! [`apply_person_seeds`] is the algorithm; the functions around it are its I/O steps and the free
//! functions below are pure. Every step that must not commit returns [`SeedHold`], so the
//! `Ok ⇒ mark, Err ⇒ hold` decision lives in one place per run.
//!
//! Ordering against live traffic is [`person_seed_verdict`]'s job, not the apply fence's: a person
//! seed carries no arrival bound over the event stream, so it admits fence-open. The partition-wide
//! live-lag, disk, and channel-full holds still apply.

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::sync::Arc;

use chrono::Utc;
use cohort_core::seed::PersonSeed;
use metrics::counter;
use tracing::{debug, warn};
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::{FilterCatalog, TeamId};
use crate::merge::tombstone_redirect::{self, MAX_CROSS_PARTITION_REDIRECT_HOPS};
use crate::observability::metrics::{
    PERSON_SEEDS_APPLIED_TOTAL, PERSON_SEEDS_DROPPED_TOTAL, PERSON_SEEDS_SKIPPED_TOTAL,
    PERSON_SEEDS_UNCHANGED_TOTAL, PERSON_SEED_HASHES_DROPPED_TOTAL,
    PERSON_SEED_PRIOR_CORRUPT_TOTAL, PERSON_SEED_REKEY_HOP_CAPPED_TOTAL, STAGE1_TRANSITIONS,
};
use crate::producer::{map_transition, CohortMembershipChange, LastUpdatedClock};
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::{
    apply_person_seed, person_seed_verdict, MatchedSet, PersonRecord, PersonSeedOutcome,
    PersonSeedVerdict, PriorRecord,
};
use crate::stage1::state::StateVariant;
use crate::stage1::transition::LeafTransition;
use crate::stage2::{single_leaf_transition_register_writes, stage_register_writes};
use crate::store::{PersonPrefix, PersonRecordKey, PersonRecords, ReadLane, StagedBatch};
use crate::workers::seed_batch::{
    produce_cascade_output, produce_composed_output, produce_leaf_output, recompose_batch, settle,
    Admitted, ApplyStage, SeedApplyDeps, SeedHold, SeedKind, SeedReKeys, SeedRun, StageClock,
    TouchedPersons,
};
use crate::workers::seed_path::{route_seed, tag_seed, SeedRoute};
use crate::workers::stage2_path::commit_stage2_writes;
use crate::workers::worker::{first_cascades, transition_metric_label};

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

/// Apply one run of person seeds as a unit, then mark its whole span or hold its first offset.
///
/// Shares the tile path's shape: one batched tombstone resolve, one batched record read, one
/// produce of the single-leaf output, one stage-1 commit, one stage-2 recompose, one produce of the
/// composed output, one produce of the cascades, one stage-2 commit. The overlay gives
/// read-your-writes within the run, so a second seed for the same person merges onto the first
/// seed's record rather than the bytes the read pass saw.
pub(crate) async fn apply_person_batch(
    deps: &SeedApplyDeps<'_>,
    clock: &mut LastUpdatedClock,
    run: SeedRun<PersonSeed>,
) {
    let span = run.span();
    let mut stages = StageClock::start(SeedKind::Person, run.len());
    let outcome = apply_person_seeds(deps, clock, &mut stages, &run).await;
    settle(deps, SeedKind::Person, span, outcome);
}

/// The ordered apply. Each `?` holds the whole run; every early `return Ok(())` is a terminal skip
/// whose offsets commit.
async fn apply_person_seeds(
    deps: &SeedApplyDeps<'_>,
    clock: &mut LastUpdatedClock,
    stages: &mut StageClock,
    run: &SeedRun<PersonSeed>,
) -> Result<(), SeedHold> {
    if !deps.merge.person_seed.enabled {
        skip_gate_off(deps.partition_id, run);
        return Ok(());
    }

    let snapshot = deps.catalog.load();
    let RoutedPersonSeeds { locals, re_keys } =
        route_person_seeds(deps, &snapshot, run.items()).await?;
    stages.mark(ApplyStage::Resolve);

    let mut overlay = read_person_records(deps, &locals).await?;
    stages.mark(ApplyStage::Read);

    let now_ms = Utc::now().timestamp_millis();
    let FoldedPersonSeeds {
        staged,
        changes: leaf_changes,
        touched,
        outcomes,
    } = fold_person_seeds(
        deps.merge.person_seed.live_margin_ms,
        &locals,
        &mut overlay,
        clock,
        now_ms,
    );
    stages.mark(ApplyStage::Fold);

    // Cascades ride the last leg, so every membership change is acked before any referrer hears
    // of it; built here from a borrow, before the changes move into their produce.
    let source_offset = run.span().last.0;
    let mut cascades = first_cascades(deps.merge, &leaf_changes, source_offset);
    produce_leaf_output(deps, leaf_changes, SeedReKeys::Persons(re_keys)).await?;
    stages.mark(ApplyStage::ProduceLeaf);

    // One batch, so a register is never stranded without the matched set that justifies it.
    if !staged.is_empty() {
        deps.handle
            .commit(staged)
            .await
            .map_err(SeedHold::store(ApplyStage::Stage1Commit))?;
    }
    stages.mark(ApplyStage::Stage1Commit);

    let mut recomposed = recompose_batch(deps, &snapshot, touched, now_ms, clock).await?;
    stages.mark(ApplyStage::Recompute);

    let composed = std::mem::take(&mut recomposed.changes);
    cascades.extend(first_cascades(deps.merge, &composed, source_offset));
    produce_composed_output(deps, composed).await?;
    stages.mark(ApplyStage::ProduceComposed);

    produce_cascade_output(deps, cascades).await?;
    stages.mark(ApplyStage::ProduceCascades);

    commit_stage2_writes(deps.handle, &recomposed.writes)
        .await
        .map_err(SeedHold::store(ApplyStage::Stage2Commit))?;
    stages.mark(ApplyStage::Stage2Commit);
    recomposed.record_metrics();

    // Counted last: a failure holds the run, and the redelivery re-derives every verdict against the
    // records this attempt already wrote, so counting any earlier counts one seed twice under two
    // different arms.
    for outcome in outcomes {
        outcome.record();
    }
    Ok(())
}

/// A gate-off run is one message per scanned person, so this stays off `warn!` and leans on
/// `cohort_person_seeds_skipped_total{reason="apply_disabled"}` for the signal.
fn skip_gate_off(partition_id: u16, run: &SeedRun<PersonSeed>) {
    counter!(PERSON_SEEDS_SKIPPED_TOTAL, "reason" => "apply_disabled").increment(run.len() as u64);
    debug!(
        partition_id,
        seeds = run.len(),
        "person seeds skipped while person apply is disabled; re-produce the run after enabling",
    );
}

/// One seed that applies on this partition, with everything its fold needs resolved once.
struct LocalPersonSeed<'a> {
    seed: &'a PersonSeed,
    /// The tombstone chain's survivor, or the seed's own person when nothing merged.
    person: Uuid,
    filters: Arc<TeamFilters>,
    effective: EffectiveHashes,
    /// This seed's record row, resolved once. The read pass and the fold both key off it, so
    /// neither can build a key the other does not have.
    record_key: PersonRecordKey,
}

struct RoutedPersonSeeds<'a> {
    locals: Vec<LocalPersonSeed<'a>>,
    /// Seeds whose survivor lives on another partition, handed back to the seed topic.
    re_keys: Vec<PersonSeed>,
}

/// Resolve the run's tombstones in one read and split it into local applies and hand-offs.
async fn route_person_seeds<'a>(
    deps: &SeedApplyDeps<'_>,
    snapshot: &FilterCatalog,
    seeds: &'a [Admitted<PersonSeed>],
) -> Result<RoutedPersonSeeds<'a>, SeedHold> {
    let mut known: Vec<(&PersonSeed, Arc<TeamFilters>, EffectiveHashes)> =
        Vec::with_capacity(seeds.len());
    let mut persons: Vec<(TeamId, Uuid)> = Vec::new();
    let mut seen: HashSet<(TeamId, Uuid)> = HashSet::new();
    for Admitted { work: seed, .. } in seeds {
        let Some(filters) = snapshot.team(seed.team_id()) else {
            counter!(PERSON_SEEDS_DROPPED_TOTAL, "reason" => "team_absent").increment(1);
            continue;
        };
        // Ahead of the tombstone resolution: the catalog is team-wide, so a seed nothing backs is
        // dropped identically on the survivor's partition, and resolving first would spend a store
        // read and possibly a cross-partition re-produce on a message already doomed.
        let Some(effective) = effective_hashes(filters, seed) else {
            counter!(PERSON_SEEDS_DROPPED_TOTAL, "reason" => "no_effective_hashes").increment(1);
            continue;
        };
        if seen.insert((seed.team_id(), seed.person_id())) {
            persons.push((seed.team_id(), seed.person_id()));
        }
        known.push((seed, filters.clone(), effective));
    }

    // A read failure is fail-stop: a seed applied to a merged-away person is durable state that
    // nothing downstream can retract.
    let resolutions = tombstone_redirect::resolve_batch_offloaded(
        deps.handle,
        deps.partition_id,
        &persons,
        deps.merge.partition_count,
        ReadLane::Maintenance,
    )
    .await
    .map_err(SeedHold::store(ApplyStage::Resolve))?;

    let mut routed = RoutedPersonSeeds {
        locals: Vec::with_capacity(known.len()),
        re_keys: Vec::new(),
    };
    for (seed, filters, effective) in known {
        let Some(&resolution) = resolutions.get(&(seed.team_id(), seed.person_id())) else {
            return Err(SeedHold::ShortRead {
                stage: ApplyStage::Resolve,
                asked: persons.len(),
                answered: resolutions.len(),
            });
        };
        let person = match route_seed(seed, resolution, MAX_CROSS_PARTITION_REDIRECT_HOPS) {
            SeedRoute::ApplyLocal { person } => person,
            SeedRoute::ReProduce { seed: rekeyed } => {
                routed.re_keys.push(rekeyed);
                continue;
            }
            SeedRoute::CapExhausted { person } => degrade_to(deps.partition_id, seed, person),
        };
        routed.locals.push(LocalPersonSeed {
            seed,
            person,
            filters,
            effective,
            record_key: PersonPrefix::new(deps.partition_id, seed.team_id().0 as u64, person)
                .record_key(),
        });
    }
    Ok(routed)
}

/// Apply at the best-known target once the hop budget is spent, matching the tile and event paths:
/// an orphaned row beats a silent seed loss, and holding the offset instead would stall every later
/// seed on the partition behind a tombstone cycle that will never resolve.
///
/// The row lands under this worker's partition prefix, which the survivor's own worker never reads.
/// Unlike the tile path's orphan, no sweep owns it — only the `cf_person_records` TTL reclaims it,
/// and `apply_person_seed` floors `last_seen_ms` at the scan instant so it does age out wherever
/// `COHORT_PERSON_RECORD_TTL_DAYS` is set.
fn degrade_to(partition_id: u16, seed: &PersonSeed, person: Uuid) -> Uuid {
    counter!(PERSON_SEED_REKEY_HOP_CAPPED_TOTAL).increment(1);
    warn!(
        partition_id,
        team_id = seed.team_id().0,
        %person,
        hops = seed.redirect_hops(),
        "person seed redirect hop cap hit (corrupt tombstone cycle?); applying inline at the best-known target",
    );
    person
}

/// Read every record the run will fold into, once.
///
/// Maintenance lane: backfill must not contend with live event reads. A row that exists but does not
/// decode is counted here, the way the event path counts it: the apply rebuilds from an absent
/// baseline, so without the counter a real codec failure is indistinguishable from a dormant person
/// that never had a record.
async fn read_person_records(
    deps: &SeedApplyDeps<'_>,
    locals: &[LocalPersonSeed<'_>],
) -> Result<BTreeMap<PersonRecordKey, PriorRecord>, SeedHold> {
    let distinct: BTreeSet<PersonRecordKey> = locals.iter().map(|local| local.record_key).collect();
    let keys: Vec<PersonRecordKey> = distinct.into_iter().collect();
    let values = deps
        .handle
        .multi_get_person_records(keys.clone(), ReadLane::Maintenance)
        .await
        .map_err(SeedHold::store(ApplyStage::Read))?;
    SeedHold::check_read(ApplyStage::Read, keys.len(), values.len())?;

    Ok(keys
        .into_iter()
        .zip(values)
        .map(|(key, bytes)| {
            let prior = PriorRecord::decode(bytes.as_deref());
            if matches!(prior, PriorRecord::Corrupt) {
                counter!(PERSON_SEED_PRIOR_CORRUPT_TOTAL).increment(1);
            }
            (key, prior)
        })
        .collect())
}

#[derive(Default)]
struct FoldedPersonSeeds {
    staged: StagedBatch,
    /// Single-leaf membership changes, one `last_updated` per seed that flipped something.
    changes: Vec<CohortMembershipChange>,
    touched: TouchedPersons,
    outcomes: Vec<PersonSeedMetric>,
}

/// Fold every seed into the overlay in offset order, staging its record and registers. Pure apart
/// from its counters: the store is not touched, so a failure later in the pipeline replays this
/// identically.
fn fold_person_seeds(
    live_margin_ms: i64,
    locals: &[LocalPersonSeed<'_>],
    overlay: &mut BTreeMap<PersonRecordKey, PriorRecord>,
    clock: &mut LastUpdatedClock,
    now_ms: i64,
) -> FoldedPersonSeeds {
    let mut folded = FoldedPersonSeeds::default();

    for local in locals {
        let key = local.record_key;
        let partition_id = key.0.partition_id;
        let (verdict, update, recompose) = {
            let prior = overlay
                .get(&key)
                .expect("the read pass keyed off the same record key, so every seed has a prior");
            let verdict = person_seed_verdict(
                prior,
                local.seed.scanned_at_ms(),
                live_margin_ms,
                local.filters.catalog_fingerprint,
            );
            // A live-fresh skip is not merged at all: the stored state already subsumes the seed.
            let update = match verdict {
                PersonSeedVerdict::SkipLiveFresh => RecordUpdate::Unchanged,
                _ => record_update(
                    prior,
                    local.seed,
                    local.person,
                    &local.effective,
                    live_margin_ms,
                ),
            };
            let recompose = recomposes(&update, verdict, prior);
            (verdict, update, recompose)
        };

        if let RecordUpdate::Changed {
            record,
            transitions,
        } = &update
        {
            folded.staged.put::<PersonRecords>(&key, &record.encode());
            for transition in transitions {
                stage_register_writes(
                    &mut folded.staged,
                    single_leaf_transition_register_writes(
                        &local.filters,
                        partition_id,
                        transition,
                        now_ms,
                    ),
                );
            }
        }

        // Recomposes every evaluated leaf, not just the ones this seed flipped, so a crash between
        // the two commits heals on replay.
        if recompose {
            for (leaf, person) in local.effective.leaves(local.person) {
                folded
                    .touched
                    .touch(local.seed.team_id(), person, local.seed.run_id(), leaf);
            }
        }

        let transitions = update.transitions();
        if !transitions.is_empty() {
            let last_updated = clock.next();
            let start = folded.changes.len();
            folded.changes.extend(single_leaf_changes(
                &local.filters,
                transitions,
                &last_updated,
            ));
            tag_seed(&mut folded.changes[start..], local.seed.run_id());
        }

        folded.outcomes.push(update.metric(verdict));
        // Read-your-writes: a later seed for the same person merges onto this record.
        if let RecordUpdate::Changed { record, .. } = update {
            overlay.insert(key, PriorRecord::Present(record));
        }
    }
    folded
}

#[derive(Debug, PartialEq, Eq)]
enum RecordUpdate {
    Changed {
        record: PersonRecord,
        transitions: Vec<LeafTransition>,
    },
    /// Nothing to write, so an absent record with no matches is never created and store growth
    /// stays proportional to matchers.
    Unchanged,
}

impl RecordUpdate {
    fn transitions(&self) -> &[LeafTransition] {
        match self {
            Self::Changed { transitions, .. } => transitions,
            Self::Unchanged => &[],
        }
    }

    /// The counter this seed lands on. `verdict` labels the writing arm only: an unchanged merge
    /// says nothing about which verdict admitted it.
    fn metric(&self, verdict: PersonSeedVerdict) -> PersonSeedMetric {
        match (self, verdict) {
            (_, PersonSeedVerdict::SkipLiveFresh) => PersonSeedMetric::SkippedStaleVsLive,
            (Self::Changed { .. }, _) => PersonSeedMetric::Applied(verdict),
            (Self::Unchanged, _) => PersonSeedMetric::Unchanged,
        }
    }
}

/// One seed's counted outcome, decided during the fold and recorded only once the batch's durable
/// effects land — a batch counted mid-flight would count every seed twice when it replays.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum PersonSeedMetric {
    SkippedStaleVsLive,
    Applied(PersonSeedVerdict),
    Unchanged,
}

impl PersonSeedMetric {
    fn record(self) {
        match self {
            Self::SkippedStaleVsLive => {
                counter!(PERSON_SEEDS_SKIPPED_TOTAL, "reason" => "stale_vs_live").increment(1);
            }
            Self::Applied(verdict) => {
                counter!(PERSON_SEEDS_APPLIED_TOTAL, "verdict" => verdict.as_str()).increment(1);
            }
            Self::Unchanged => counter!(PERSON_SEEDS_UNCHANGED_TOTAL).increment(1),
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
/// is the reconcile snapshot's to repair — the same surface that already owns single-leaf changes
/// lost to a failed produce.
fn recomposes(update: &RecordUpdate, verdict: PersonSeedVerdict, prior: &PriorRecord) -> bool {
    matches!(update, RecordUpdate::Changed { .. })
        || verdict == PersonSeedVerdict::SkipLiveFresh
        || matches!(prior, PriorRecord::Corrupt)
}

/// An absent or corrupt prior folds from the absent baseline rather than skipping: freezing
/// membership on an unreadable row would be a silent correctness hole. What the unreadable row held
/// outside `evaluated` is lost with it, and mints no `Left` — hence the corrupt counter at the read.
fn record_update(
    prior: &PriorRecord,
    seed: &PersonSeed,
    person: Uuid,
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
        PersonSeedOutcome::Changed {
            record,
            transitions,
        } => RecordUpdate::Changed {
            record,
            transitions: transitions
                .into_iter()
                .map(|(condition_hash, kind)| LeafTransition {
                    team_id: seed.team_id(),
                    leaf_state_key: LeafStateKey::for_person_property(&condition_hash),
                    person_id: person,
                    condition_hash,
                    kind,
                })
                .collect(),
        },
    }
}

fn single_leaf_changes(
    filters: &TeamFilters,
    transitions: &[LeafTransition],
    last_updated: &str,
) -> Vec<CohortMembershipChange> {
    let mut changes = Vec::new();
    for transition in transitions {
        if let Some(kind) = transition_metric_label(filters, transition) {
            counter!(STAGE1_TRANSITIONS, "kind" => kind).increment(1);
        }
        changes.extend(map_transition(filters, transition, last_updated));
    }
    changes
}

/// The seed's hashes projected onto the team's live person-property catalog.
struct EffectiveHashes {
    /// Sorted and distinct, so [`effective_hashes`] can binary-search it.
    evaluated: Vec<[u8; 16]>,
    matched: MatchedSet,
}

impl EffectiveHashes {
    fn leaves(&self, person: Uuid) -> Vec<(LeafStateKey, Uuid)> {
        self.evaluated
            .iter()
            .map(|hash| (LeafStateKey::for_person_property(hash), person))
            .collect()
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
    use std::num::NonZeroUsize;

    use chrono_tz::UTC;
    use cohort_core::seed::{ClaimEpoch, ConditionHash, RunId, ScannedAtMs};
    use serde_json::{json, Value};
    use tempfile::TempDir;

    use crate::consumers::events::CohortStreamEvent;
    use crate::filters::manager::CatalogHandle;
    use crate::filters::{CohortId, TeamFiltersBuilder};
    use crate::merge::transfer::Tombstone;
    use crate::partitions::offset_tracker::OffsetTracker;
    use crate::partitions::partitioner::{partition_of, COHORT_PARTITION_COUNT};
    use crate::partitions::watermarks::LiveWatermarks;
    use crate::producer::{
        CaptureCascadeSink, CaptureSeedTileSink, CaptureSink, CaptureStreamEventSink,
        CaptureTransferSink, ChangeOrigin, MembershipSink, MembershipStatus,
    };
    use crate::stage1::person_record::{PropsFingerprint, Stamp};
    use crate::stage1::state::AppliedOffsets;
    use crate::stage2::state::Stage2State;
    use crate::store::StoreHandle;
    use crate::store::{
        CohortStore, OffloadConfig, OffloadMode, Stage2Key, StoreConfig, TombstoneKey,
    };
    use crate::workers::event_path::{process_event_gated, EventNameGating};
    use crate::workers::seed_batch::{Admitted, SeedApplyDeps, SeedOffset, SeedRun};
    use crate::workers::stage2_path::compose_stage2;
    use crate::workers::MergeWorkerDeps;
    use crate::workers::{CascadeConfig, ReconcileDeps, TransferRetryPolicy};

    use super::*;

    const TEAM: TeamId = TeamId(7);
    const PERSON_HASH: &str = "fedcba9876543210";
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
        PersonSeed::new(
            TEAM,
            person,
            evaluated.iter().copied().map(hash).collect(),
            matched.iter().copied().map(hash).collect(),
            ScannedAtMs(scanned_at_ms),
            RunId(Uuid::from_u128(0xBF)),
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
        clock: LastUpdatedClock,
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
                seed_batch: crate::workers::SeedBatchLimits::default(),
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
                clock: LastUpdatedClock::default(),
            }
        }

        /// One seed through the batch pipeline, so every case below also pins that a run of one
        /// behaves exactly as the per-seed apply did.
        async fn run(&mut self, partition_id: u16, seed: &PersonSeed, offset: i64) {
            self.run_batch(partition_id, vec![(seed.clone(), offset)])
                .await;
        }

        async fn run_batch(&mut self, partition_id: u16, seeds: Vec<(PersonSeed, i64)>) {
            let highest = seeds
                .iter()
                .map(|(_, offset)| *offset)
                .max()
                .expect("a dispatched batch is non-empty");
            self.deps
                .seed_tracker
                .mark_dispatched(partition_id as i32, highest + 1);
            let sink: Arc<dyn MembershipSink> = Arc::new(self.sink.clone());
            let run = SeedRun::new(
                seeds
                    .into_iter()
                    .map(|(work, offset)| Admitted {
                        work,
                        offset: SeedOffset(offset),
                    })
                    .collect(),
            )
            .expect("a dispatched batch is non-empty");
            apply_person_batch(
                &SeedApplyDeps {
                    partition_id,
                    handle: &self.handle,
                    catalog: &self.catalog,
                    sink: &sink,
                    merge: &self.deps,
                },
                &mut self.clock,
                run,
            )
            .await;
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

        // An older scan that would retract the hash.
        let seed = seed_for(person, &[PERSON_HASH], &[], now_ms() - 1_000);
        shell.run(partition_id, &seed, 0).await;

        assert_eq!(
            shell.record(partition_id, person).unwrap(),
            live,
            "the record is byte-identical: no write at all",
        );
        assert!(shell.sink.changes().is_empty());
        assert_eq!(shell.committable(partition_id), Some(1));
    }

    #[tokio::test]
    async fn a_newer_seed_retracts_a_stale_true_hash() {
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
        assert_eq!(shell.committable(partition_id), Some(1));
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

    /// The composed leg fails after the single-leaf leg acked and stage 1 committed, so the replay
    /// merges to `Unchanged` and has only the composed flip left to re-derive.
    #[tokio::test]
    async fn a_failed_membership_produce_holds_and_the_replay_re_derives_the_composed_flip() {
        let (person, partition_id) = dormant_person();
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::failing_calls(1, 1),
            CaptureSeedTileSink::new(),
        );
        shell.live_pageview(partition_id, person, None);
        let seed = seed_for(person, &[PERSON_HASH], &[PERSON_HASH], now_ms());

        shell.run(partition_id, &seed, 3).await;
        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        assert!(
            shell.record(partition_id, person).is_some(),
            "stage 1 committed once the single-leaf leg acked",
        );
        assert!(
            shell.stage2(partition_id, person, 2).is_none(),
            "the composed bit must stay unwritten under a failed produce",
        );

        shell.run(partition_id, &seed, 3).await;
        let changes = shell.sink.changes();
        assert_eq!(
            changes.len(),
            2,
            "the Unchanged replay re-derives the composed flip only",
        );
        assert_eq!(
            changes[0].cohort_id, 1,
            "the single-leaf leg acked first time"
        );
        assert_eq!(changes[1].cohort_id, 2);
        assert_eq!(changes[1].origin, Some(ChangeOrigin::Seed));
        assert!(shell.stage2(partition_id, person, 2).unwrap().in_cohort);
        assert_eq!(shell.committable(partition_id), Some(3));
    }

    /// A broker acks per record, so a run can come back half acked. Committing stage 1 under that
    /// would make the replay skip as live-fresh and never re-emit the records that failed. Producing
    /// before the commit means the replay re-folds every seed and re-emits every change.
    #[tokio::test]
    async fn a_partially_acked_person_produce_commits_no_record_and_the_replay_re_emits_every_change(
    ) {
        let (person, partition_id) = dormant_person();
        let other = (0x5EEE_u128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TEAM, p, COHORT_PARTITION_COUNT) as u16 == partition_id)
            .expect("some uuid hashes onto the same partition");
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::partially_failing_first(NonZeroUsize::new(2).unwrap()),
            CaptureSeedTileSink::new(),
        );
        for p in [person, other] {
            shell.live_pageview(partition_id, p, None);
        }
        let scanned = now_ms();
        let seeds = || {
            vec![
                (seed_for(person, &[PERSON_HASH], &[PERSON_HASH], scanned), 5),
                (seed_for(other, &[PERSON_HASH], &[PERSON_HASH], scanned), 6),
            ]
        };

        shell.run_batch(partition_id, seeds()).await;

        assert_eq!(shell.committable(partition_id), None, "held for redelivery");
        assert_eq!(
            shell.sink.changes().len(),
            1,
            "the acked record is already downstream; the failed one is what must not be lost",
        );
        for p in [person, other] {
            assert!(
                shell.record(partition_id, p).is_none(),
                "no record for {p}: the run committed nothing",
            );
            assert!(
                shell.stage2(partition_id, p, 1).is_none(),
                "no register for {p}: the run committed nothing",
            );
        }

        shell.run_batch(partition_id, seeds()).await;

        let changes = shell.sink.changes();
        for p in [person, other] {
            for cohort_id in [1, 2] {
                assert!(
                    changes.iter().any(|change| {
                        change.person_id == p.to_string()
                            && change.cohort_id == cohort_id
                            && change.status == MembershipStatus::Entered
                    }),
                    "the replay re-folded and re-emitted {p}'s entry into cohort {cohort_id}",
                );
            }
        }
        // The tenure-sticky hold pins the committable at the held first offset.
        assert_eq!(shell.committable(partition_id), Some(5));
    }

    /// The held replay can arrive after a live event has already re-derived the same matched set.
    /// That event mints no transition, so it composes nothing, and the seed then reads as live
    /// fresh. If the skip committed without recomposing, the person would sit outside every
    /// composed cohort forever: no later event flips a leaf, and reconcile scans `cf_stage2` rows,
    /// which is precisely what is missing.
    #[tokio::test]
    async fn a_live_fresh_skip_still_recomposes_a_stage_2_bit_a_held_attempt_never_wrote() {
        let (person, partition_id) = dormant_person();
        // The composed leg is the one that fails, so stage 1 is committed under the hold.
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::failing_calls(1, 1),
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
        assert_eq!(shell.committable(partition_id), Some(3));
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

    // ---- batched apply: properties only a run of several seeds can break ----

    /// The change fields a batch must reproduce exactly. `last_updated` is excluded on purpose: it
    /// is minted per apply, so two shells never agree on it.
    fn change_shape(changes: &[CohortMembershipChange]) -> Vec<(i32, String, MembershipStatus)> {
        changes
            .iter()
            .map(|change| (change.cohort_id, change.person_id.clone(), change.status))
            .collect()
    }

    /// Without read-your-writes the second seed would score its verdict against the bytes the read
    /// pass saw, so a retraction that follows its own scan in the same run would mint no `Left`.
    #[tokio::test]
    async fn two_seeds_for_one_person_in_one_batch_settle_as_two_batches_do() {
        let (person, partition_id) = dormant_person();
        let scanned = now_ms();
        let seeds = || {
            vec![
                (seed_for(person, &[PERSON_HASH], &[PERSON_HASH], scanned), 0),
                (
                    seed_for(person, &[PERSON_HASH], &[], scanned + MARGIN_MS + 1),
                    1,
                ),
            ]
        };

        let mut batched = Shell::new(mixed_cohorts());
        batched.run_batch(partition_id, seeds()).await;

        let mut separately = Shell::new(mixed_cohorts());
        for (seed, offset) in seeds() {
            separately.run(partition_id, &seed, offset).await;
        }

        assert_eq!(
            batched.record(partition_id, person),
            separately.record(partition_id, person),
            "one batch must settle on the same record as two",
        );
        assert_eq!(
            change_shape(&batched.sink.changes()),
            change_shape(&separately.sink.changes()),
            "batching must not add or drop a transition",
        );
        assert_eq!(
            batched.sink.changes().last().map(|change| change.status),
            Some(MembershipStatus::Left),
            "the retraction still lands after the entry it undoes",
        );
        assert_eq!(batched.committable(partition_id), Some(2));
    }

    #[tokio::test]
    async fn a_run_of_person_seeds_rides_one_membership_produce() {
        const SEEDS: usize = 5;
        let mut shell = Shell::new(mixed_cohorts());
        // Every person on partition 0, so one worker owns the whole run.
        shell.deps.partition_count = 1;
        let scanned = now_ms();
        let seeds: Vec<_> = (0..SEEDS)
            .map(|i| {
                (
                    seed_for(
                        Uuid::from_u128(0x5EED_0000 + i as u128),
                        &[PERSON_HASH],
                        &[PERSON_HASH],
                        scanned,
                    ),
                    i as i64,
                )
            })
            .collect();

        shell.run_batch(0, seeds).await;

        assert_eq!(
            shell.sink.changes().len(),
            SEEDS,
            "each person entered the single-leaf cohort",
        );
        assert_eq!(
            shell.sink.produce_calls(),
            1,
            "one membership produce for the whole run, not one per seed",
        );
        assert_eq!(shell.committable(0), Some(SEEDS as i64));
    }

    /// A batch is all-or-nothing on its offsets: the floor must sit at the *first* seed, so the
    /// redelivery replays every seed the failed produce covered.
    #[tokio::test]
    async fn a_failed_membership_produce_holds_the_person_batchs_first_offset() {
        let (person, partition_id) = dormant_person();
        let other = (0x5EEE_u128..)
            .map(Uuid::from_u128)
            .find(|p| partition_of(TEAM, p, COHORT_PARTITION_COUNT) as u16 == partition_id)
            .expect("some uuid hashes onto the same partition");
        let mut shell = Shell::with_sinks(
            mixed_cohorts(),
            CaptureSink::failing_first(1),
            CaptureSeedTileSink::new(),
        );
        shell.live_pageview(partition_id, person, None);
        let scanned = now_ms();
        let seeds = |first: i64| {
            vec![
                (
                    seed_for(person, &[PERSON_HASH], &[PERSON_HASH], scanned),
                    first,
                ),
                (
                    seed_for(other, &[PERSON_HASH], &[PERSON_HASH], scanned),
                    first + 1,
                ),
            ]
        };

        shell.run_batch(partition_id, seeds(5)).await;

        assert_eq!(
            shell.committable(partition_id),
            None,
            "the failed produce holds, so nothing in the batch commits",
        );
        for p in [person, other] {
            assert!(
                shell.record(partition_id, p).is_none(),
                "no record for {p}: the single-leaf leg failed before stage 1 committed",
            );
        }
        assert!(
            shell.stage2(partition_id, person, 2).is_none(),
            "the composed bit must stay unwritten under the failed produce",
        );

        shell.run_batch(partition_id, seeds(5)).await;

        assert!(
            shell.stage2(partition_id, person, 2).unwrap().in_cohort,
            "the replay re-derived the composed flip and committed its bit",
        );
        // The tenure-sticky hold pins the committable at the held first offset.
        assert_eq!(shell.committable(partition_id), Some(5));
    }
}
