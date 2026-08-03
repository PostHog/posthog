//! PostgreSQL contract for the backfill-completion protocol, split into independent scenarios.
//!
//! Each `#[tokio::test]` connects its own schema-scoped database ([`support::with_db`]) and builds
//! only the minimal run/participation state its invariant needs. Together they pin the planning-proof
//! stamp, the `seeding → reconciling` CAS, the atomic dispatch record and reset, the epoch fence on
//! every observation write, the bitmap OR-merge, phase discovery, and the current-hash read.

#![cfg(feature = "pg-test-support")]

use std::collections::BTreeMap;
use std::num::NonZeroU16;
use std::time::Duration;

use anyhow::{ensure, Context, Result};
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use cohort_core::filters::{CohortId, TeamId};
use cohort_core::partitioner::COHORT_PARTITION_COUNT;
use cohort_seeder::domain::{
    CompletionPhase, DispatchEpoch, MarkerPartition, MarkerWatch, MembershipPartition, NextOffset,
    ObservationEnds, PartitionBitmap, ProducedOffset, ReconcileHwms, RunId, SeedPartition,
    UndispatchedReason, WatchPositions,
};
use cohort_seeder::store::chunks::PgChunkStore;
use cohort_seeder::store::completion::{
    cas_run_reconciling, confirm_reconciling, discover_completions, load_current_behavioral_hashes,
    load_observation_participations, mark_chunks_planned, mark_participation_completed,
    mark_run_observed, mark_run_observed_unreconcilable, persist_marker_observations,
    persist_observation_ends, read_planning_stamp, record_participation_partial,
    record_participation_shortfall, runs_with_all_chunks_confirmed, CompletionStoreError,
    CurrentBehavioralHash, PlanningStampOutcome,
};
use cohort_seeder::store::runs::RunKind;
use cohort_seeder::store::RenderedError;
use cohort_seeder::test_support;
use common_types::cohort::TeamAllowlist;
use sqlx::types::Json;
use sqlx::PgPool;

mod support;
use support::{
    empty_pinned, ensure_fence_lost, insert_cohort, insert_participation, insert_person_run,
    insert_reconciling_run, insert_run, person_pinned, set_marker_bits, with_db,
};

const ONE_BAND: NonZeroU16 = NonZeroU16::MIN;

fn full_hwms() -> ReconcileHwms {
    let offsets: BTreeMap<SeedPartition, ProducedOffset> =
        SeedPartition::all(COHORT_PARTITION_COUNT)
            .unwrap()
            .map(|partition| {
                (
                    partition,
                    ProducedOffset::new(1_000 + i64::from(partition.as_u16())),
                )
            })
            .collect();
    ReconcileHwms::new(offsets).unwrap()
}

fn captured_ends() -> ObservationEnds {
    let mut ends = ObservationEnds::new();
    ends.insert(
        MembershipPartition::new(0),
        NextOffset::from_high_watermark(10),
    );
    ends
}

fn empty_watch() -> MarkerWatch {
    MarkerWatch {
        positions: WatchPositions::new(),
        ends: None,
    }
}

/// Stamping the planning proof applies once, is idempotent, and refuses a run that is not seeding.
#[tokio::test]
async fn planning_stamp_is_idempotent_and_refuses_non_seeding() -> Result<()> {
    with_db(|pool| async move {
        let seeding =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        ensure!(matches!(
            mark_chunks_planned(&pool, seeding, RunKind::Behavioral).await?,
            PlanningStampOutcome::Stamped
        ));
        ensure!(matches!(
            mark_chunks_planned(&pool, seeding, RunKind::Behavioral).await?,
            PlanningStampOutcome::Skipped
        ));

        let reconciling = insert_reconciling_run(&pool, 3).await?;
        ensure!(matches!(
            mark_chunks_planned(&pool, reconciling, RunKind::Behavioral).await?,
            PlanningStampOutcome::Skipped
        ));
        Ok(())
    })
    .await
}

/// The person-kind inertness contract: `discover_completions` never surfaces a person run — the
/// reconcile protocol stays behavioral-only by design — while the kind-parameterized stamp pair
/// lets a person run earn its planning proof and refuses the wrong kind.
#[tokio::test]
async fn completion_discovery_excludes_person_runs_but_the_stamp_is_kind_aware() -> Result<()> {
    with_db(|pool| async move {
        let person_run = insert_person_run(&pool, 2, "seeding", true, person_pinned(&[])).await?;

        ensure!(discover_completions(&pool, &TeamAllowlist::All)
            .await?
            .iter()
            .all(|completion| completion.run_id != person_run));

        ensure!(matches!(
            mark_chunks_planned(&pool, person_run, RunKind::Behavioral).await?,
            PlanningStampOutcome::Skipped
        ));
        ensure!(
            read_planning_stamp(&pool, person_run, RunKind::PersonProperty)
                .await?
                .is_none()
        );
        ensure!(matches!(
            mark_chunks_planned(&pool, person_run, RunKind::PersonProperty).await?,
            PlanningStampOutcome::Stamped
        ));
        ensure!(
            read_planning_stamp(&pool, person_run, RunKind::PersonProperty)
                .await?
                .is_some()
        );
        // The behavioral-filtered read still refuses to see it.
        ensure!(read_planning_stamp(&pool, person_run, RunKind::Behavioral)
            .await?
            .is_none());
        Ok(())
    })
    .await
}

/// The CAS admits exactly one winner, and refuses a run that has not planned or still has an
/// unconfirmed chunk.
#[tokio::test]
async fn cas_reconciling_is_single_winner_and_gated_on_planned_and_confirmed() -> Result<()> {
    with_db(|pool| async move {
        // Planned, no chunks: two racing CAS attempts, exactly one wins.
        let ready =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        mark_chunks_planned(&pool, ready, RunKind::Behavioral).await?;
        let (left, right) = tokio::join!(
            cas_run_reconciling(&pool, ready),
            cas_run_reconciling(&pool, ready)
        );
        let winners = [left?, right?].into_iter().filter(Option::is_some).count();
        ensure!(
            winners == 1,
            "expected exactly one CAS winner, got {winners}"
        );

        // Unplanned seeding run: CAS refused.
        let unplanned =
            insert_run(&pool, 3, "team_enablement", "seeding", true, empty_pinned()).await?;
        ensure!(cas_run_reconciling(&pool, unplanned).await?.is_none());

        // Planned but with an unconfirmed chunk: CAS refused.
        let pending =
            insert_run(&pool, 4, "team_enablement", "seeding", true, empty_pinned()).await?;
        mark_chunks_planned(&pool, pending, RunKind::Behavioral).await?;
        PgChunkStore::new(pool.clone())
            .plan_chunks(pending, [100], ONE_BAND)
            .await?;
        ensure!(cas_run_reconciling(&pool, pending).await?.is_none());
        Ok(())
    })
    .await
}

/// Recording a dispatch writes the HWMs and watch, resets every non-superseded participation's
/// bits/completion/error, nulls the observed stamp, and mints the fence epoch; a re-dispatch stamps a
/// fresh epoch and resets again.
#[tokio::test]
async fn record_dispatch_resets_participations_and_mints_fresh_epoch() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, run_id, 2, 301, false, empty_pinned()).await?;
        set_marker_bits(&pool, run_id, 301, 7).await?;
        sqlx::query(
            "UPDATE cohort_backfill_run_cohorts SET reconcile_completed_at = now(), error = 'stale' \
             WHERE run_id = $1 AND cohort_id = 301",
        )
        .bind(run_id)
        .execute(&pool)
        .await?;

        let claim = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable for dispatch")?;
        let epoch = claim.record(&pool, &full_hwms(), &empty_watch()).await?;

        let (bits, completed, error): (i64, Option<chrono::DateTime<chrono::Utc>>, String) =
            sqlx::query_as(
                "SELECT reconcile_marker_bits, reconcile_completed_at, error \
                 FROM cohort_backfill_run_cohorts WHERE run_id = $1 AND cohort_id = 301",
            )
            .bind(run_id)
            .fetch_one(&pool)
            .await?;
        ensure!(bits == 0 && completed.is_none() && error.is_empty());

        let (hwms_set, observed): (bool, Option<chrono::DateTime<chrono::Utc>>) = sqlx::query_as(
            "SELECT reconcile_hwms IS NOT NULL, reconcile_observed_at \
             FROM cohort_backfill_runs WHERE id = $1",
        )
        .bind(run_id)
        .fetch_one(&pool)
        .await?;
        ensure!(hwms_set && observed.is_none());
        ensure!(test_support::dispatch_epoch(&pool, run_id).await? == epoch);

        // Re-dispatch: a fresh claim records a new fence at or after the first.
        set_marker_bits(&pool, run_id, 301, 5).await?;
        let claim = confirm_reconciling(&pool, run_id)
            .await?
            .context("re-dispatch should be claimable")?;
        let next_epoch = claim.record(&pool, &full_hwms(), &empty_watch()).await?;
        ensure!(next_epoch.as_datetime() >= epoch.as_datetime());
        ensure!(test_support::dispatch_epoch(&pool, run_id).await? == next_epoch);
        let bits: i64 = sqlx::query_scalar(
            "SELECT reconcile_marker_bits FROM cohort_backfill_run_cohorts \
             WHERE run_id = $1 AND cohort_id = 301",
        )
        .bind(run_id)
        .fetch_one(&pool)
        .await?;
        ensure!(bits == 0);
        Ok(())
    })
    .await
}

/// Reverting a claim returns the run to seeding and clears any dispatch record, so it re-enters
/// discovery as a plain planned seeding run instead of the seeding-with-reconcile-columns anomaly.
#[tokio::test]
async fn revert_clears_the_dispatch_record_and_returns_to_seeding() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, run_id, 2, 301, false, empty_pinned()).await?;
        let claim = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable")?;
        let _ = claim.record(&pool, &full_hwms(), &empty_watch()).await?;

        let claim = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be re-claimable")?;
        claim.revert(&pool).await?;

        let (status, cleared): (String, bool) = sqlx::query_as(
            "SELECT status, reconcile_dispatched_at IS NULL AND reconcile_observed_at IS NULL \
             AND reconcile_hwms IS NULL AND marker_watch IS NULL \
             FROM cohort_backfill_runs WHERE id = $1",
        )
        .bind(run_id)
        .fetch_one(&pool)
        .await?;
        ensure!(status == "seeding" && cleared);

        let discovered = discover_completions(&pool, &TeamAllowlist::All).await?;
        let phase = discovered
            .iter()
            .find(|completion| completion.run_id == run_id)
            .map(|completion| completion.phase.clone());
        ensure!(phase == Some(CompletionPhase::SeedingPlanned));
        Ok(())
    })
    .await
}

/// A claim minted before another dispatcher recorded its dispatch cannot revert it — two replicas
/// can hold a claim for one run, and an unfenced revert would bounce a live dispatch to `seeding`.
#[tokio::test]
async fn revert_is_fenced_against_a_dispatch_recorded_after_the_claim() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, run_id, 2, 301, false, empty_pinned()).await?;
        let stale = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable")?;
        let winner = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable twice")?;
        let epoch = winner.record(&pool, &full_hwms(), &empty_watch()).await?;

        stale.revert(&pool).await?;

        let (status, dispatched_at): (String, Option<DateTime<Utc>>) = sqlx::query_as(
            "SELECT status, reconcile_dispatched_at FROM cohort_backfill_runs WHERE id = $1",
        )
        .bind(run_id)
        .fetch_one(&pool)
        .await?;
        ensure!(status == "reconciling", "revert bounced a live dispatch");
        ensure!(dispatched_at == Some(epoch.as_datetime()));
        mark_run_observed(&pool, run_id, epoch).await?;
        Ok(())
    })
    .await
}

/// A claim that lost the race cannot record over the winner's dispatch. Recording resets marker bits
/// and completions, so an unfenced second write would discard observations already merged under the
/// ruling epoch.
#[tokio::test]
async fn record_is_fenced_against_a_dispatch_recorded_after_the_claim() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, run_id, 2, 301, false, empty_pinned()).await?;
        let stale = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable")?;
        let winner = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable twice")?;
        let epoch = winner.record(&pool, &full_hwms(), &empty_watch()).await?;
        persist_marker_observations(
            &pool,
            run_id,
            epoch,
            &[(CohortId(301), PartitionBitmap::from_bits(3)?)],
            &WatchPositions::new(),
        )
        .await?;

        ensure_fence_lost(
            stale
                .record(&pool, &full_hwms(), &empty_watch())
                .await
                .map(|_| ()),
        )?;

        let bits: i64 = sqlx::query_scalar(
            "SELECT reconcile_marker_bits FROM cohort_backfill_run_cohorts \
             WHERE run_id = $1 AND cohort_id = 301",
        )
        .bind(run_id)
        .fetch_one(&pool)
        .await?;
        ensure!(
            bits == 3,
            "a lost claim reset the ruling epoch's marker bits"
        );
        ensure!(test_support::dispatch_epoch(&pool, run_id).await? == epoch);
        Ok(())
    })
    .await
}

/// The batched ledger check returns exactly the runs whose chunks have all confirmed.
#[tokio::test]
async fn runs_with_all_chunks_confirmed_selects_only_fully_confirmed_ledgers() -> Result<()> {
    with_db(|pool| async move {
        let store = PgChunkStore::new(pool.clone());
        let no_chunks =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let confirmed =
            insert_run(&pool, 3, "team_enablement", "seeding", true, empty_pinned()).await?;
        store.plan_chunks(confirmed, [100], ONE_BAND).await?;
        sqlx::query("UPDATE cohort_backfill_chunks SET status = 'confirmed' WHERE run_id = $1")
            .bind(confirmed)
            .execute(&pool)
            .await?;
        let pending =
            insert_run(&pool, 4, "team_enablement", "seeding", true, empty_pinned()).await?;
        store.plan_chunks(pending, [100, 101], ONE_BAND).await?;
        sqlx::query(
            "UPDATE cohort_backfill_chunks SET status = 'confirmed' \
             WHERE id = (SELECT id FROM cohort_backfill_chunks WHERE run_id = $1 LIMIT 1)",
        )
        .bind(pending)
        .execute(&pool)
        .await?;

        let ready = runs_with_all_chunks_confirmed(&pool, &[no_chunks, confirmed, pending]).await?;
        ensure!(
            ready == [no_chunks, confirmed].into_iter().collect(),
            "unexpected ready set: {ready:?}"
        );
        ensure!(runs_with_all_chunks_confirmed(&pool, &[]).await?.is_empty());
        Ok(())
    })
    .await
}

/// A participation Django already superseded keeps the reason Django recorded for it.
#[tokio::test]
async fn recording_a_partial_preserves_an_existing_supersession_reason() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, run_id, 2, 301, true, empty_pinned()).await?;
        sqlx::query(
            "UPDATE cohort_backfill_run_cohorts SET error = 'Cohort definition changed during backfill' \
             WHERE run_id = $1",
        )
        .bind(run_id)
        .execute(&pool)
        .await?;
        let claim = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable")?;
        let epoch = claim.record(&pool, &full_hwms(), &empty_watch()).await?;

        record_participation_partial(
            &pool,
            run_id,
            epoch,
            CohortId(301),
            &RenderedError::from_message("markers short; cohort diverged"),
        )
        .await?;

        let error: String = sqlx::query_scalar(
            "SELECT error FROM cohort_backfill_run_cohorts WHERE run_id = $1 AND cohort_id = 301",
        )
        .bind(run_id)
        .fetch_one(&pool)
        .await?;
        ensure!(
            error == "Cohort definition changed during backfill",
            "reconcile outcome overwrote the original supersession reason: {error}"
        );
        Ok(())
    })
    .await
}

/// Every fenced observation write is rejected under a stale epoch and under a run whose status has
/// left `reconciling`, while a matching epoch on a reconciling run is accepted.
#[tokio::test]
async fn fenced_writes_reject_stale_epoch_and_wrong_status() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, run_id, 2, 301, false, empty_pinned()).await?;
        let claim = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable")?;
        let epoch = claim.record(&pool, &full_hwms(), &empty_watch()).await?;

        // A matching epoch on a reconciling run is accepted.
        mark_participation_completed(&pool, run_id, epoch, CohortId(301)).await?;

        let stale = test_support::epoch_at(epoch.as_datetime() - ChronoDuration::hours(1));
        let bit_updates = [(CohortId(301), PartitionBitmap::default())];
        let error = RenderedError::from_message("shortfall");
        for at in [stale, epoch] {
            if at == epoch {
                // Same valid epoch, but flip the run out of reconciling: the status guard fences.
                sqlx::query("UPDATE cohort_backfill_runs SET status = 'completed' WHERE id = $1")
                    .bind(run_id)
                    .execute(&pool)
                    .await?;
            }
            ensure_fence_lost(persist_observation_ends(&pool, run_id, at, &captured_ends()).await)?;
            ensure_fence_lost(
                persist_marker_observations(
                    &pool,
                    run_id,
                    at,
                    &bit_updates,
                    &WatchPositions::new(),
                )
                .await,
            )?;
            ensure_fence_lost(
                mark_participation_completed(&pool, run_id, at, CohortId(301)).await,
            )?;
            ensure_fence_lost(
                record_participation_partial(&pool, run_id, at, CohortId(301), &error).await,
            )?;
            ensure_fence_lost(
                record_participation_shortfall(&pool, run_id, at, CohortId(301), &error).await,
            )?;
            ensure_fence_lost(mark_run_observed(&pool, run_id, at).await)?;
        }
        Ok(())
    })
    .await
}

/// A participation write whose epoch is superseded *while the statement runs* must still lose the
/// fence. The three participation writes fence through a CTE rather than a run-row UPDATE, so
/// without `FOR UPDATE` the CTE would be evaluated against the pre-block snapshot (epoch still
/// current), the participation UPDATE would unblock after the re-dispatch committed, and
/// EvalPlanQual — which re-checks only the participation row's quals — would land the stale write
/// inside the new epoch's regime while reporting success.
#[tokio::test]
async fn fenced_participation_writes_lose_an_epoch_superseded_mid_statement() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, run_id, 2, 301, false, empty_pinned()).await?;
        let claim = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable")?;
        let _initial = claim.record(&pool, &full_hwms(), &empty_watch()).await?;

        for write in [
            FencedWrite::Completed,
            FencedWrite::Partial,
            FencedWrite::Shortfall,
        ] {
            let current: DateTime<Utc> = sqlx::query_scalar(
                "SELECT reconcile_dispatched_at FROM cohort_backfill_runs WHERE id = $1",
            )
            .bind(run_id)
            .fetch_one(&pool)
            .await?;
            let epoch = test_support::epoch_at(current);

            // A re-dispatch that has stamped the new epoch but not yet committed. Only the run row
            // is touched, so nothing but the fence itself can block the write under test.
            let mut redispatch = pool.begin().await?;
            sqlx::query(
                "UPDATE cohort_backfill_runs \
                 SET reconcile_dispatched_at = reconcile_dispatched_at + interval '1 second' \
                 WHERE id = $1",
            )
            .bind(run_id)
            .execute(&mut *redispatch)
            .await?;

            let mut pending = tokio::spawn(fenced_write(pool.clone(), run_id, epoch, write));
            // The fence must hold the run row's lock, so the write cannot resolve while the
            // re-dispatch transaction is open. An unfenced read would return `Ok` immediately here.
            let early = tokio::time::timeout(Duration::from_millis(500), &mut pending).await;
            ensure!(
                early.is_err(),
                "{write:?} resolved past an in-flight re-dispatch instead of blocking on the fence"
            );

            redispatch.commit().await?;
            ensure_fence_lost(pending.await?)?;
        }

        let completed: Option<DateTime<Utc>> = sqlx::query_scalar(
            "SELECT reconcile_completed_at FROM cohort_backfill_run_cohorts \
             WHERE run_id = $1 AND cohort_id = 301",
        )
        .bind(run_id)
        .fetch_one(&pool)
        .await?;
        ensure!(
            completed.is_none(),
            "a stale-epoch write landed inside the ruling epoch"
        );
        Ok(())
    })
    .await
}

#[derive(Debug, Clone, Copy)]
enum FencedWrite {
    Completed,
    Partial,
    Shortfall,
}

async fn fenced_write(
    pool: PgPool,
    run_id: RunId,
    epoch: DispatchEpoch,
    write: FencedWrite,
) -> std::result::Result<(), CompletionStoreError> {
    let error = RenderedError::from_message("stale-epoch write");
    let cohort_id = CohortId(301);
    match write {
        FencedWrite::Completed => {
            mark_participation_completed(&pool, run_id, epoch, cohort_id).await
        }
        FencedWrite::Partial => {
            record_participation_partial(&pool, run_id, epoch, cohort_id, &error).await
        }
        FencedWrite::Shortfall => {
            record_participation_shortfall(&pool, run_id, epoch, cohort_id, &error).await
        }
    }
}

/// Capturing the observation ends patches only the `ends` key. The observer holds discovery-time
/// positions, so writing the whole document would regress the watcher's flushed coverage — and on a
/// topic that then goes idle nothing would repair it, leaving the run unable to ever mint a proof.
#[tokio::test]
async fn capturing_ends_leaves_the_watcher_positions_alone() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, run_id, 2, 301, false, empty_pinned()).await?;
        let claim = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable")?;
        let epoch = claim.record(&pool, &full_hwms(), &empty_watch()).await?;

        let mut advanced = WatchPositions::new();
        advanced.insert(
            MembershipPartition::new(0),
            NextOffset::from_high_watermark(42),
        );
        persist_marker_observations(&pool, run_id, epoch, &[], &advanced).await?;
        persist_observation_ends(&pool, run_id, epoch, &captured_ends()).await?;

        let watch: Json<MarkerWatch> =
            sqlx::query_scalar("SELECT marker_watch FROM cohort_backfill_runs WHERE id = $1")
                .bind(run_id)
                .fetch_one(&pool)
                .await?;
        ensure!(
            watch.0.positions.get(MembershipPartition::new(0))
                == Some(NextOffset::from_high_watermark(42)),
            "capturing the ends regressed the watcher positions"
        );
        ensure!(watch.0.ends == Some(captured_ends()));
        Ok(())
    })
    .await
}

/// A reconciling run whose every participation was superseded has nothing to dispatch and no outcome
/// to write, so the seeder stamps the observation itself and hands the run to Django's finalizer.
/// The guard refuses to shortcut a run that still has an active participation.
#[tokio::test]
async fn unreconcilable_runs_are_marked_observed_for_django() -> Result<()> {
    with_db(|pool| async move {
        let stranded = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, stranded, 2, 301, true, empty_pinned()).await?;
        mark_run_observed_unreconcilable(&pool, stranded).await?;

        let discovered = discover_completions(&pool, &TeamAllowlist::All).await?;
        let phase = discovered
            .iter()
            .find(|completion| completion.run_id == stranded)
            .map(|completion| completion.phase.clone());
        ensure!(phase == Some(CompletionPhase::Observed));

        let live = insert_reconciling_run(&pool, 3).await?;
        insert_participation(&pool, live, 3, 401, false, empty_pinned()).await?;
        ensure_fence_lost(mark_run_observed_unreconcilable(&pool, live).await)?;
        let observed: Option<DateTime<Utc>> = sqlx::query_scalar(
            "SELECT reconcile_observed_at FROM cohort_backfill_runs WHERE id = $1",
        )
        .bind(live)
        .fetch_one(&pool)
        .await?;
        ensure!(observed.is_none());
        Ok(())
    })
    .await
}

/// The observed-marker OR-merge accumulates across calls and round-trips through PostgreSQL,
/// including the bit-63 case that stores as a negative BIGINT.
#[tokio::test]
async fn marker_observations_or_merge_round_trip_including_bit_63() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_reconciling_run(&pool, 2).await?;
        insert_participation(&pool, run_id, 2, 401, false, empty_pinned()).await?;
        let claim = confirm_reconciling(&pool, run_id)
            .await?
            .context("run should be claimable")?;
        let epoch = claim.record(&pool, &full_hwms(), &empty_watch()).await?;

        let mut low = PartitionBitmap::default();
        low.set(MarkerPartition::new(0)?);
        persist_marker_observations(
            &pool,
            run_id,
            epoch,
            &[(CohortId(401), low)],
            &WatchPositions::new(),
        )
        .await?;

        let mut high = PartitionBitmap::default();
        high.set(MarkerPartition::new(63)?);
        persist_marker_observations(
            &pool,
            run_id,
            epoch,
            &[(CohortId(401), high)],
            &WatchPositions::new(),
        )
        .await?;

        let stored: i64 = sqlx::query_scalar(
            "SELECT reconcile_marker_bits FROM cohort_backfill_run_cohorts \
             WHERE run_id = $1 AND cohort_id = 401",
        )
        .bind(run_id)
        .fetch_one(&pool)
        .await?;
        ensure!(stored < 0, "bit 63 must store as a negative BIGINT");

        let participations = load_observation_participations(&pool, run_id).await?;
        let bits = participations
            .iter()
            .find(|participation| participation.cohort_id == CohortId(401))
            .map(|participation| participation.bits)
            .context("cohort 401 not loaded")?;
        let missing = bits.missing();
        ensure!(!missing.contains(&MarkerPartition::new(0)?));
        ensure!(!missing.contains(&MarkerPartition::new(63)?));
        ensure!(missing.contains(&MarkerPartition::new(1)?));
        Ok(())
    })
    .await
}

/// Discovery classifies each completion phase, including a reconciling run whose completion
/// columns are all NULL.
#[tokio::test]
async fn discovery_classifies_each_phase_including_undispatched_rows() -> Result<()> {
    with_db(|pool| async move {
        let unplanned =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;

        let planned =
            insert_run(&pool, 3, "team_enablement", "seeding", true, empty_pinned()).await?;
        mark_chunks_planned(&pool, planned, RunKind::Behavioral).await?;

        let dispatched = insert_reconciling_run(&pool, 4).await?;
        insert_participation(&pool, dispatched, 4, 401, false, empty_pinned()).await?;
        let claim = confirm_reconciling(&pool, dispatched)
            .await?
            .context("dispatched run should be claimable")?;
        let _ = claim.record(&pool, &full_hwms(), &empty_watch()).await?;

        // A run that predates the completion columns: reconciling with every one of them NULL.
        let undispatched = insert_run(
            &pool,
            5,
            "team_enablement",
            "reconciling",
            true,
            empty_pinned(),
        )
        .await?;

        let observed = insert_reconciling_run(&pool, 6).await?;
        insert_participation(&pool, observed, 6, 601, false, empty_pinned()).await?;
        let claim = confirm_reconciling(&pool, observed)
            .await?
            .context("observed run should be claimable")?;
        let epoch = claim.record(&pool, &full_hwms(), &empty_watch()).await?;
        mark_run_observed(&pool, observed, epoch).await?;

        let discovered = discover_completions(&pool, &TeamAllowlist::All).await?;
        let phase = |run| {
            discovered
                .iter()
                .find(|completion| completion.run_id == run)
                .map(|completion| completion.phase.clone())
        };
        ensure!(phase(unplanned) == Some(CompletionPhase::SeedingUnplanned));
        ensure!(phase(planned) == Some(CompletionPhase::SeedingPlanned));
        ensure!(matches!(
            phase(dispatched),
            Some(CompletionPhase::Reconciling(_))
        ));
        ensure!(
            phase(undispatched)
                == Some(CompletionPhase::ReconcilingUndispatched(
                    UndispatchedReason::NeverDispatched
                ))
        );
        ensure!(phase(observed) == Some(CompletionPhase::Observed));
        Ok(())
    })
    .await
}

/// The current-hash read distinguishes present, deleted, absent, and NULL/unparseable cohorts.
#[tokio::test]
async fn current_behavioral_hashes_read_present_deleted_absent_and_null() -> Result<()> {
    with_db(|pool| async move {
        insert_cohort(&pool, 501, 2, Some("shape-a"), false).await?;
        insert_cohort(&pool, 502, 2, Some("shape-b"), true).await?;
        insert_cohort(&pool, 503, 2, None, false).await?;
        // 504 intentionally absent.

        let hashes = load_current_behavioral_hashes(
            &pool,
            TeamId(2),
            &[CohortId(501), CohortId(502), CohortId(503), CohortId(504)],
        )
        .await?;

        ensure!(matches!(
            hashes.get(&CohortId(501)),
            Some(CurrentBehavioralHash::Present(hash)) if hash.as_str() == "shape-a"
        ));
        ensure!(hashes.get(&CohortId(502)) == Some(&CurrentBehavioralHash::Deleted));
        ensure!(hashes.get(&CohortId(503)) == Some(&CurrentBehavioralHash::Indeterminate));
        ensure!(!hashes.contains_key(&CohortId(504)));
        Ok(())
    })
    .await
}
