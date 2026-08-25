//! PostgreSQL contract for the seeder store, split into independent scenarios.
//!
//! Each `#[tokio::test]` connects its own schema-scoped database ([`support::with_db`]) and builds
//! only the minimal run/chunk state its invariant needs; setup duplication across scenarios is
//! deliberate and keeps them parallel-safe. Together they cover the same claim/lease/epoch-fence/CAS
//! guarantees the former single `exercise_contract` did — every assertion preserved, redistributed.

#![cfg(feature = "pg-test-support")]

use std::num::NonZeroU16;
use std::time::Duration;

use anyhow::{bail, ensure, Context, Result};
use cohort_core::filters::{CohortId, TeamId};
use cohort_seeder::app::fail_exhausted_runs_of_kind;
use cohort_seeder::app::reconcile_dispatch::{
    prepare_reconcile_dispatch, CompletionRequirement, PrepareReconcileDispatchError,
    RegisterBackfillConfirmation,
};
use cohort_seeder::domain::{
    tile_ranges, ClaimEpoch, PersonRunValidation, PinnedWarning, ProduceHwms, ScopeKind,
};
use cohort_seeder::store::chunks::{ChunkStoreError, PgChunkStore, PlanOutcome, NO_ERROR_RECORDED};
use cohort_seeder::store::lease::LeaseFailure;
use cohort_seeder::store::runs::{
    discover_runs, establish_boundary, fail_run, load_reconcile_run, record_run_warning,
    BoundaryOutcome, ReconcileRunError, RunError, RunKind, RunStatus, RunWarningNote,
};
use cohort_seeder::store::{Claimant, LeaseDuration, MaxAttempts, RenderedError};
use cohort_seeder::test_support;
use common_types::cohort::TeamAllowlist;
use serde_json::json;
use uuid::Uuid;

mod support;
use support::{
    behavioral_filter, empty_pinned, ensure_lease_lost, insert_participation, insert_person_run,
    insert_run, person_filter, person_pinned, pinned_condition, planned_count, with_db,
    ACTIVE_HASH, SUPERSEDED_HASH,
};

const ONE_BAND: NonZeroU16 = NonZeroU16::MIN;

/// Discovery honors an `Only` allowlist (self team only) and `All` admits every eligible run
/// regardless of team, trigger, or already-seeding status.
#[tokio::test]
async fn discovery_scopes_to_the_allowlist_and_all_admits_every_run() -> Result<()> {
    with_db(|pool| async move {
        let self_run = insert_run(
            &pool,
            2,
            "team_enablement",
            "awaiting_boundary",
            false,
            empty_pinned(),
        )
        .await?;
        let other_team_run = insert_run(
            &pool,
            3,
            "team_enablement",
            "awaiting_boundary",
            false,
            empty_pinned(),
        )
        .await?;
        let dr_run = insert_run(
            &pool,
            4,
            "disaster_recovery",
            "awaiting_boundary",
            false,
            empty_pinned(),
        )
        .await?;
        let cross_team_run =
            insert_run(&pool, 5, "team_enablement", "seeding", true, empty_pinned()).await?;

        let only_team_two: TeamAllowlist = "2".parse().map_err(anyhow::Error::msg)?;
        let discovered = discover_runs(&pool, &only_team_two, &[RunKind::Behavioral]).await?;
        ensure!(discovered.len() == 1);
        ensure!(discovered[0].run_id == self_run);

        let all_runs = discover_runs(&pool, &TeamAllowlist::All, &[RunKind::Behavioral]).await?;
        ensure!(all_runs.iter().any(|run| run.run_id == self_run));
        ensure!(all_runs.iter().any(|run| run.run_id == other_team_run));
        ensure!(all_runs.iter().any(|run| run.run_id == cross_team_run));
        ensure!(all_runs.iter().any(|run| run.run_id == dr_run));
        Ok(())
    })
    .await
}

/// Two racing `establish_boundary` calls on the same awaiting-boundary run: the CAS admits exactly
/// one `Established`, and the loser re-reads the now-seeding row as `AlreadyEstablished`.
#[tokio::test]
async fn concurrent_boundary_establishment_promotes_exactly_one_run() -> Result<()> {
    with_db(|pool| async move {
        insert_run(
            &pool,
            2,
            "team_enablement",
            "awaiting_boundary",
            false,
            empty_pinned(),
        )
        .await?;

        let only_team_two: TeamAllowlist = "2".parse().map_err(anyhow::Error::msg)?;
        let discovered = discover_runs(&pool, &only_team_two, &[RunKind::Behavioral]).await?;
        let left = discovered[0].clone();
        let right = discovered[0].clone();
        let (left, right) = tokio::join!(
            establish_boundary(&pool, left),
            establish_boundary(&pool, right)
        );
        let outcomes = [left?, right?];

        ensure!(
            outcomes
                .iter()
                .filter(|outcome| matches!(outcome, BoundaryOutcome::Established(_)))
                .count()
                == 1
        );
        ensure!(
            outcomes
                .iter()
                .filter(|outcome| matches!(outcome, BoundaryOutcome::AlreadyEstablished(_)))
                .count()
                == 1
        );
        Ok(())
    })
    .await
}

/// Warning notes append newest-first, dedupe on repeat, truncate the `error` column to the limit,
/// and are refused once a run leaves the `seeding` state.
#[tokio::test]
async fn run_warnings_dedupe_append_truncate_and_skip_terminal_runs() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        sqlx::query("UPDATE cohort_backfill_runs SET error = repeat('x', 5000) WHERE id = $1")
            .bind(seeding_run)
            .execute(&pool)
            .await?;

        ensure!(record_run_warning(&pool, seeding_run, RunWarningNote::ConditionsDropped).await?);
        ensure!(!record_run_warning(&pool, seeding_run, RunWarningNote::ConditionsDropped).await?);
        ensure!(record_run_warning(&pool, seeding_run, RunWarningNote::LookbackTruncated).await?);
        let run_warnings: String =
            sqlx::query_scalar("SELECT error FROM cohort_backfill_runs WHERE id = $1")
                .bind(seeding_run)
                .fetch_one(&pool)
                .await?;
        ensure!(run_warnings.len() == 4_096);
        ensure!(
            run_warnings
                .matches(RunWarningNote::ConditionsDropped.as_str())
                .count()
                == 1
        );
        ensure!(
            run_warnings
                .matches(RunWarningNote::LookbackTruncated.as_str())
                .count()
                == 1
        );

        let terminal_run =
            insert_run(&pool, 3, "team_enablement", "failed", false, empty_pinned()).await?;
        ensure!(!record_run_warning(&pool, terminal_run, RunWarningNote::ConditionsDropped).await?);
        Ok(())
    })
    .await
}

/// Loading the pinned payload drops superseded conditions (keeping only the live one plus a
/// `ConditionSuperseded` warning), rejects cohorts stored under another team, and refuses a
/// disaster-recovery run whose boundary was never pinned.
#[tokio::test]
async fn load_pinned_drops_superseded_and_rejects_cross_team_and_dr() -> Result<()> {
    with_db(|pool| async move {
        let pinned = json!({
            "schema_version": 1,
            "conditions": [
                pinned_condition(10, ACTIVE_HASH, "active-event"),
                pinned_condition(11, SUPERSEDED_HASH, "superseded-event"),
            ],
            "event_names": ["active-event", "superseded-event"],
        });
        let self_run = insert_run(
            &pool,
            2,
            "team_enablement",
            "awaiting_boundary",
            false,
            pinned,
        )
        .await?;
        insert_participation(
            &pool,
            self_run,
            2,
            10,
            false,
            behavioral_filter(ACTIVE_HASH, "active-event"),
        )
        .await?;
        insert_participation(
            &pool,
            self_run,
            2,
            11,
            true,
            behavioral_filter(SUPERSEDED_HASH, "superseded-event"),
        )
        .await?;

        let dr_run = insert_run(
            &pool,
            4,
            "disaster_recovery",
            "awaiting_boundary",
            false,
            empty_pinned(),
        )
        .await?;
        let cross_team_run =
            insert_run(&pool, 5, "team_enablement", "seeding", true, empty_pinned()).await?;
        insert_participation(
            &pool,
            cross_team_run,
            999,
            50,
            true,
            json!({"properties": {"type": "AND", "values": []}}),
        )
        .await?;

        let all_runs = discover_runs(&pool, &TeamAllowlist::All, &[RunKind::Behavioral]).await?;
        let self_discovered = all_runs
            .iter()
            .find(|run| run.run_id == self_run)
            .cloned()
            .context("self run was not discovered")?;
        let cross_team_discovered = all_runs
            .iter()
            .find(|run| run.run_id == cross_team_run)
            .cloned()
            .context("cross-team run was not discovered")?;
        let dr_discovered = all_runs
            .into_iter()
            .find(|run| run.run_id == dr_run)
            .context("DR run was not discovered")?;

        let seedable = match establish_boundary(&pool, self_discovered).await? {
            BoundaryOutcome::Established(run) | BoundaryOutcome::AlreadyEstablished(run) => run,
            BoundaryOutcome::NoLongerSeedable { .. } => bail!("self run was not seedable"),
        };
        let validated = seedable.load_pinned(&pool).await?;
        ensure!(validated.run.conditions.len() == 1);
        ensure!(validated.run.conditions[0].cohort_id == CohortId(10));
        ensure!(
            validated
                .run
                .event_names
                .iter()
                .map(String::as_str)
                .collect::<Vec<_>>()
                == ["active-event"]
        );
        ensure!(validated
            .run
            .filters
            .behavioral_by_event_name
            .contains_key("active-event"));
        ensure!(!validated
            .run
            .filters
            .behavioral_by_event_name
            .contains_key("superseded-event"));
        ensure!(validated.warnings.iter().any(|warning| matches!(
            warning,
            PinnedWarning::ConditionSuperseded { cohort_id, .. } if *cohort_id == CohortId(11)
        )));

        // Already seeding with a boundary, so it promotes to a SeedableRun without a DB write.
        let cross_team_seedable = match establish_boundary(&pool, cross_team_discovered).await? {
            BoundaryOutcome::Established(run) | BoundaryOutcome::AlreadyEstablished(run) => run,
            BoundaryOutcome::NoLongerSeedable { .. } => bail!("cross-team run was not seedable"),
        };
        ensure!(matches!(
            cross_team_seedable.load_pinned(&pool).await,
            Err(RunError::CrossTeamParticipation {
                actual_team_id: 999,
                ..
            })
        ));
        ensure!(matches!(
            establish_boundary(&pool, dr_discovered).await,
            Err(RunError::DisasterRecoveryBoundaryMissing(id)) if id == dr_run
        ));
        Ok(())
    })
    .await
}

/// Manual dispatch reads only active participations, carries the behavioral-only shape hash onto
/// the control tile, and refuses stale run states or malformed tenant/hash data before Kafka.
#[tokio::test]
async fn reconcile_run_load_is_fail_closed_and_behavioral_hash_scoped() -> Result<()> {
    with_db(|pool| async move {
        let run_id = insert_run(
            &pool,
            20,
            "team_enablement",
            "seeding",
            true,
            empty_pinned(),
        )
        .await?;
        insert_participation(
            &pool,
            run_id,
            20,
            201,
            false,
            behavioral_filter(ACTIVE_HASH, "active-event"),
        )
        .await?;
        insert_participation(
            &pool,
            run_id,
            20,
            202,
            true,
            behavioral_filter(SUPERSEDED_HASH, "superseded-event"),
        )
        .await?;

        let register_backfill = RegisterBackfillConfirmation::confirmed_by_operator();
        // A seeding run that never planned has no completion proof, so a complete dispatch fails
        // closed (the CLI must use --allow-incomplete for an unplanned run).
        ensure!(matches!(
            prepare_reconcile_dispatch(
                &pool,
                run_id,
                CompletionRequirement::Complete,
                register_backfill,
            )
            .await,
            Err(PrepareReconcileDispatchError::PlanningUnproven(id)) if id == run_id
        ));
        let overridden = prepare_reconcile_dispatch(
            &pool,
            run_id,
            CompletionRequirement::AllowIncomplete,
            register_backfill,
        )
        .await?;
        ensure!(overridden.total_chunks() == 0);
        ensure!(overridden.remaining_chunks() == 0);

        let reconcile = load_reconcile_run(&pool, run_id).await?;
        ensure!(reconcile.run_id() == run_id);
        ensure!(reconcile.status() == RunStatus::Seeding);
        ensure!(reconcile.cohort_count() == 1);
        let tile = reconcile
            .tiles()
            .next()
            .context("missing active cohort tile")?;
        ensure!(tile.team_id() == TeamId(20));
        ensure!(tile.cohort_id() == CohortId(201));
        ensure!(tile.scope().hash_str() == "behavioral-shape");
        ensure!(tile.scope().kind() == ScopeKind::Behavioral);
        ensure!(tile.run_id() == run_id);

        sqlx::query("UPDATE cohort_backfill_runs SET status = 'reconciling' WHERE id = $1")
            .bind(run_id)
            .execute(&pool)
            .await?;
        ensure!(load_reconcile_run(&pool, run_id).await?.status() == RunStatus::Reconciling);
        // Reaching `reconciling` is not itself a planning proof — only the stamp is.
        ensure!(matches!(
            prepare_reconcile_dispatch(
                &pool,
                run_id,
                CompletionRequirement::Complete,
                register_backfill,
            )
            .await,
            Err(PrepareReconcileDispatchError::PlanningUnproven(id)) if id == run_id
        ));

        sqlx::query("UPDATE cohort_backfill_runs SET chunks_planned_at = now() WHERE id = $1")
            .bind(run_id)
            .execute(&pool)
            .await?;
        ensure!(prepare_reconcile_dispatch(
            &pool,
            run_id,
            CompletionRequirement::Complete,
            register_backfill,
        )
        .await
        .is_ok());

        sqlx::query(
            "UPDATE cohort_backfill_run_cohorts SET behavioral_filters_shape_hash = '' \
             WHERE run_id = $1 AND cohort_id = 201",
        )
        .bind(run_id)
        .execute(&pool)
        .await?;
        ensure!(matches!(
            load_reconcile_run(&pool, run_id).await,
            Err(ReconcileRunError::InvalidShapeHash { cohort_id, kind, .. })
                if cohort_id == CohortId(201) && kind == ScopeKind::Behavioral
        ));

        sqlx::query(
            "UPDATE cohort_backfill_run_cohorts \
             SET behavioral_filters_shape_hash = 'behavioral-shape', team_id = 999 \
             WHERE run_id = $1 AND cohort_id = 201",
        )
        .bind(run_id)
        .execute(&pool)
        .await?;
        ensure!(matches!(
            load_reconcile_run(&pool, run_id).await,
            Err(ReconcileRunError::CrossTeamParticipation {
                expected_team_id: 20,
                actual_team_id: 999,
                ..
            })
        ));

        sqlx::query(
            "UPDATE cohort_backfill_run_cohorts SET superseded_at = now() WHERE run_id = $1",
        )
        .bind(run_id)
        .execute(&pool)
        .await?;
        ensure!(matches!(
            load_reconcile_run(&pool, run_id).await,
            Err(ReconcileRunError::NoActiveParticipations(id)) if id == run_id
        ));

        let completed_run = insert_run(
            &pool,
            21,
            "team_enablement",
            "completed",
            true,
            empty_pinned(),
        )
        .await?;
        insert_participation(
            &pool,
            completed_run,
            21,
            211,
            false,
            behavioral_filter(ACTIVE_HASH, "active-event"),
        )
        .await?;
        ensure!(matches!(
            load_reconcile_run(&pool, completed_run).await,
            Err(ReconcileRunError::Status {
                status: RunStatus::Completed,
                ..
            })
        ));
        Ok(())
    })
    .await
}

/// Planning a seeding run's days is idempotent (re-planning inserts nothing), stamps the run's team
/// onto every chunk, and reports `RunNotSeeding` for a run that is not seeding.
#[tokio::test]
async fn planning_is_idempotent_scopes_team_and_gates_on_seeding() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());

        ensure!(planned_count(store.plan_chunks(seeding_run, [100, 101], ONE_BAND).await?)? == 2);
        ensure!(planned_count(store.plan_chunks(seeding_run, [100, 101], ONE_BAND).await?)? == 0);
        let progress = store.chunk_progress(seeding_run).await?;
        ensure!(progress.total() == 2);
        ensure!(progress.remaining() == 2);
        let chunk_teams_match: bool = sqlx::query_scalar(
            "SELECT bool_and(team_id = 2) FROM cohort_backfill_chunks WHERE run_id = $1",
        )
        .bind(seeding_run)
        .fetch_one(&pool)
        .await?;
        ensure!(chunk_teams_match);

        let idle_run = insert_run(
            &pool,
            3,
            "team_enablement",
            "awaiting_boundary",
            false,
            empty_pinned(),
        )
        .await?;
        ensure!(matches!(
            store.plan_chunks(idle_run, [200], ONE_BAND).await?,
            PlanOutcome::RunNotSeeding
        ));
        Ok(())
    })
    .await
}

/// A multi-band plan fans a day into one chunk per band (idempotently), and a claim decodes the
/// band with the day's full band count so the scan predicate partitions persons correctly.
#[tokio::test]
async fn planning_fans_out_bands_and_claims_carry_the_band_count() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        let four_bands = NonZeroU16::new(4).context("four is non-zero")?;
        ensure!(planned_count(store.plan_chunks(seeding_run, [100], four_bands).await?)? == 4);
        ensure!(planned_count(store.plan_chunks(seeding_run, [100], four_bands).await?)? == 0);

        let lease60 = LeaseDuration::new(Duration::from_secs(60))?;
        let attempts5 = MaxAttempts::new(5)?;
        let claimed = store
            .claim_next(
                &[seeding_run],
                &Claimant::new("worker-a")?,
                lease60,
                attempts5,
            )
            .await?
            .context("claimant found no chunk")?;
        let band = claimed.chunk.spec().band;
        ensure!(band.num_bands().get() == 4);
        ensure!(band.band() < 4);
        drop(claimed);
        Ok(())
    })
    .await
}

/// Two racing claimants take disjoint chunks — `SKIP LOCKED` never hands the same chunk to both.
#[tokio::test]
async fn concurrent_claims_take_disjoint_chunks() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(planned_count(store.plan_chunks(seeding_run, [100, 101], ONE_BAND).await?)? == 2);

        let lease60 = LeaseDuration::new(Duration::from_secs(60))?;
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [seeding_run];
        let first_store = store.clone();
        let second_store = store.clone();
        let claimant_a = Claimant::new("worker-a")?;
        let claimant_b = Claimant::new("worker-b")?;
        let (first, second) = tokio::join!(
            first_store.claim_next(&run_ids, &claimant_a, lease60, attempts5),
            second_store.claim_next(&run_ids, &claimant_b, lease60, attempts5),
        );
        let first = first?.context("first claimant found no chunk")?;
        let second = second?.context("second claimant found no chunk")?;
        ensure!(first.chunk.spec().lease.chunk_id() != second.chunk.spec().lease.chunk_id());
        Ok(())
    })
    .await
}

/// An expired lease is reclaimed as the SAME chunk with a bumped epoch; the reclaim fences the stale
/// lease so every one of its fenced operations reports `LeaseLost`, while the fresh lease works.
#[tokio::test]
async fn expired_lease_reclaim_bumps_epoch_and_fences_the_stale_lease() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(planned_count(store.plan_chunks(seeding_run, [100], ONE_BAND).await?)? == 1);

        let lease60 = LeaseDuration::new(Duration::from_secs(60))?;
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [seeding_run];

        let first = store
            .claim_next(&run_ids, &Claimant::new("worker-a")?, lease60, attempts5)
            .await?
            .context("first claimant found no chunk")?;
        let stale = first.chunk.spec().lease;
        drop(first);
        sqlx::query(
            "UPDATE cohort_backfill_chunks SET lease_expires_at = now() - interval '1 second' WHERE id = $1",
        )
        .bind(stale.chunk_id())
        .execute(&pool)
        .await?;

        let reclaimed = store
            .claim_next(&run_ids, &Claimant::new("worker-c")?, lease60, attempts5)
            .await?
            .context("expired chunk was not reclaimed")?;
        let reclaimed_lease = reclaimed.chunk.spec().lease;
        ensure!(reclaimed_lease.chunk_id() == stale.chunk_id());
        ensure!(reclaimed_lease.epoch() == ClaimEpoch(stale.epoch().0 + 1));

        ensure_lease_lost(
            test_support::heartbeat(&store, stale, &Claimant::new("worker-a")?, lease60).await,
        )?;
        ensure_lease_lost(test_support::mark_produced_raw(&store, stale, 1).await)?;
        ensure_lease_lost(test_support::confirm_raw(&store, stale, &ProduceHwms::default()).await)?;
        ensure_lease_lost(test_support::fail(&store, stale, "stale failure").await)?;
        ensure_lease_lost(test_support::unclaim(&store, stale).await)?;

        // The fresh lease, in contrast, drives the chunk through mark-produced and confirm.
        let mut hwms = ProduceHwms::default();
        hwms.observe(3, 41);
        test_support::mark_produced_raw(&store, reclaimed_lease, 0).await?;
        test_support::confirm_raw(&store, reclaimed_lease, &hwms).await?;
        drop(reclaimed);
        Ok(())
    })
    .await
}

/// Unclaiming a scanning chunk returns it to `pending` and refunds the attempt the claim charged.
#[tokio::test]
async fn unclaim_returns_chunk_to_pending_and_refunds_one_attempt() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(planned_count(store.plan_chunks(seeding_run, [100], ONE_BAND).await?)? == 1);

        let lease60 = LeaseDuration::new(Duration::from_secs(60))?;
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [seeding_run];

        let claimed = store
            .claim_next(&run_ids, &Claimant::new("worker-a")?, lease60, attempts5)
            .await?
            .context("claimant found no chunk")?;
        let lease = claimed.chunk.spec().lease;
        let chunk_id = lease.chunk_id();
        sqlx::query("UPDATE cohort_backfill_chunks SET attempts = 5 WHERE id = $1")
            .bind(chunk_id)
            .execute(&pool)
            .await?;
        store.unclaim(lease).await?;
        drop(claimed);

        let (pending_status, refunded_attempts): (String, i32) =
            sqlx::query_as("SELECT status, attempts FROM cohort_backfill_chunks WHERE id = $1")
                .bind(chunk_id)
                .fetch_one(&pool)
                .await?;
        ensure!(pending_status == "pending");
        ensure!(refunded_attempts == 4);
        Ok(())
    })
    .await
}

/// The attempt cap is terminal for a `failed` chunk (no further claim), but an expired `produced`
/// chunk sitting AT the cap is still reclaimed with a bumped epoch — its tiles are already in
/// Kafka, so it must keep retrying until it reaches `confirmed`. Only `scanning` reclaims are
/// capped (see `expired_scanning_chunk_at_the_cap_is_reaped_not_reclaimed`).
#[tokio::test]
async fn attempt_cap_is_terminal_for_failed_but_reclaims_expired_produced() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        let lease60 = LeaseDuration::new(Duration::from_secs(60))?;
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [seeding_run];

        // A chunk driven to the attempt cap by claiming, then failed, is not claimable again.
        ensure!(planned_count(store.plan_chunks(seeding_run, [100], ONE_BAND).await?)? == 1);
        sqlx::query("UPDATE cohort_backfill_chunks SET attempts = 4 WHERE run_id = $1")
            .bind(seeding_run)
            .execute(&pool)
            .await?;
        let retry = store
            .claim_next(&run_ids, &Claimant::new("worker-d")?, lease60, attempts5)
            .await?
            .context("chunk under the cap was not claimable")?;
        let retry_lease = retry.chunk.spec().lease;
        let reclaimed_attempts: i32 =
            sqlx::query_scalar("SELECT attempts FROM cohort_backfill_chunks WHERE id = $1")
                .bind(retry_lease.chunk_id())
                .fetch_one(&pool)
                .await?;
        ensure!(reclaimed_attempts == 5);
        store
            .fail(retry_lease, &RenderedError::from_message("terminal"))
            .await?;
        drop(retry);
        ensure!(store
            .claim_next(&run_ids, &Claimant::new("worker-terminal")?, lease60, attempts5)
            .await?
            .is_none());

        // A second chunk, marked produced then expired at the cap, IS reclaimed.
        ensure!(planned_count(store.plan_chunks(seeding_run, [101], ONE_BAND).await?)? == 1);
        let final_attempt = store
            .claim_next(&run_ids, &Claimant::new("worker-e")?, lease60, attempts5)
            .await?
            .context("second chunk was not claimable")?;
        let final_attempt_lease = final_attempt.chunk.spec().lease;
        test_support::mark_produced_raw(&store, final_attempt_lease, 1).await?;
        drop(final_attempt);
        sqlx::query(
            "UPDATE cohort_backfill_chunks SET attempts = 5, lease_expires_at = now() - interval '1 second' WHERE id = $1",
        )
        .bind(final_attempt_lease.chunk_id())
        .execute(&pool)
        .await?;

        let observed = store
            .claim_next(&run_ids, &Claimant::new("worker-f")?, lease60, attempts5)
            .await?
            .context("expired produced chunk at the attempt cap was not reclaimed")?;
        let observed_lease = observed.chunk.spec().lease;
        ensure!(observed_lease.chunk_id() == final_attempt_lease.chunk_id());
        ensure!(observed_lease.epoch() == ClaimEpoch(final_attempt_lease.epoch().0 + 1));
        let active_reclaim_attempts: i32 =
            sqlx::query_scalar("SELECT attempts FROM cohort_backfill_chunks WHERE id = $1")
                .bind(observed_lease.chunk_id())
                .fetch_one(&pool)
                .await?;
        ensure!(active_reclaim_attempts == 5);
        Ok(())
    })
    .await
}

/// A `scanning` chunk whose lease expires below the attempt cap is left for reclaim, but once its
/// attempts saturate it is neither reclaimed (no hard-crash loop) nor left invisible: the reaper
/// dead-letters it to `failed` — the same terminal state a clean cap-out reaches — exactly once.
#[tokio::test]
async fn expired_scanning_chunk_at_the_cap_is_reaped_not_reclaimed() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(planned_count(store.plan_chunks(seeding_run, [100], ONE_BAND).await?)? == 1);

        let lease60 = LeaseDuration::new(Duration::from_secs(60))?;
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [seeding_run];
        let claimed = store
            .claim_next(&run_ids, &Claimant::new("worker-a")?, lease60, attempts5)
            .await?
            .context("claimant found no chunk")?;
        let chunk_id = claimed.chunk.spec().lease.chunk_id();
        drop(claimed);

        // Expired below the cap: not reaped — the ordinary reclaim path still owns it.
        sqlx::query(
            "UPDATE cohort_backfill_chunks SET lease_expires_at = now() - interval '1 second' WHERE id = $1",
        )
        .bind(chunk_id)
        .execute(&pool)
        .await?;
        ensure!(store.reap_poisoned_chunks(&run_ids, attempts5).await? == 0);

        // A hard-crashed worker's residue: still `scanning`, attempts saturated, lease expired.
        sqlx::query("UPDATE cohort_backfill_chunks SET attempts = 5 WHERE id = $1")
            .bind(chunk_id)
            .execute(&pool)
            .await?;
        ensure!(store
            .claim_next(&run_ids, &Claimant::new("worker-b")?, lease60, attempts5)
            .await?
            .is_none());

        ensure!(store.reap_poisoned_chunks(&run_ids, attempts5).await? == 1);
        let (status, last_error): (String, String) =
            sqlx::query_as("SELECT status, last_error FROM cohort_backfill_chunks WHERE id = $1")
                .bind(chunk_id)
                .fetch_one(&pool)
                .await?;
        ensure!(status == "failed");
        ensure!(last_error.contains("attempt cap"));
        // Terminal: not claimable, and a second sweep is a no-op.
        ensure!(store
            .claim_next(&run_ids, &Claimant::new("worker-c")?, lease60, attempts5)
            .await?
            .is_none());
        ensure!(store.reap_poisoned_chunks(&run_ids, attempts5).await? == 0);
        Ok(())
    })
    .await
}

/// Only chunks that saturated the attempt cap count as exhausted. A `failed` chunk still under the
/// cap is reclaimable and will retry, so reporting it would fail runs that were about to recover.
#[tokio::test]
async fn runs_with_exhausted_chunks_selects_only_capped_failures() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(planned_count(store.plan_chunks(seeding_run, [100, 101], ONE_BAND).await?)? == 2);
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [seeding_run];

        let chunk_ids: Vec<Uuid> = sqlx::query_scalar(
            "SELECT id FROM cohort_backfill_chunks WHERE run_id = $1 ORDER BY day",
        )
        .bind(seeding_run)
        .fetch_all(&pool)
        .await?;
        sqlx::query(
            "UPDATE cohort_backfill_chunks SET status = 'failed', attempts = 4, last_error = 'still retrying' WHERE id = $1",
        )
        .bind(chunk_ids[0])
        .execute(&pool)
        .await?;
        ensure!(store
            .runs_with_exhausted_chunks(&run_ids, attempts5)
            .await?
            .is_empty());

        sqlx::query(
            "UPDATE cohort_backfill_chunks SET status = 'failed', attempts = 5, last_error = 'scan blew up' WHERE id = $1",
        )
        .bind(chunk_ids[1])
        .execute(&pool)
        .await?;
        let exhausted = store.runs_with_exhausted_chunks(&run_ids, attempts5).await?;
        ensure!(exhausted.len() == 1);
        ensure!(exhausted[0].run_id == seeding_run);
        ensure!(exhausted[0].exhausted == 1, "only the capped chunk counts");
        ensure!(exhausted[0].chunk_id == chunk_ids[1].to_string());
        ensure!(exhausted[0].last_error == "scan blew up");

        ensure!(store
            .runs_with_exhausted_chunks(&[], attempts5)
            .await?
            .is_empty());
        Ok(())
    })
    .await
}

/// The reported chunk and error come from one row. Aggregating them independently pairs the lowest
/// chunk id with some other chunk's error, sending the operator to read a row that never failed
/// that way.
#[tokio::test]
async fn exhausted_chunk_and_error_are_read_off_the_same_row() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(planned_count(store.plan_chunks(seeding_run, [100, 101], ONE_BAND).await?)? == 2);
        let attempts5 = MaxAttempts::new(5)?;

        // Ordered so the lowest-id chunk carries the *higher* error text: an independent
        // `min(last_error)` would then hand back the other chunk's error.
        let mut chunk_ids: Vec<Uuid> =
            sqlx::query_scalar("SELECT id FROM cohort_backfill_chunks WHERE run_id = $1")
                .bind(seeding_run)
                .fetch_all(&pool)
                .await?;
        chunk_ids.sort();
        for (chunk_id, error) in chunk_ids.iter().zip(["zzz lowest id", "aaa highest id"]) {
            sqlx::query(
                "UPDATE cohort_backfill_chunks SET status = 'failed', attempts = 5, last_error = $2 WHERE id = $1",
            )
            .bind(chunk_id)
            .bind(error)
            .execute(&pool)
            .await?;
        }

        let exhausted = store
            .runs_with_exhausted_chunks(&[seeding_run], attempts5)
            .await?;
        ensure!(exhausted.len() == 1);
        ensure!(exhausted[0].exhausted == 2, "both capped chunks counted");
        ensure!(exhausted[0].chunk_id == chunk_ids[0].to_string());
        ensure!(exhausted[0].last_error == "zzz lowest id");

        // A capped chunk with no persisted error still has to render as something: the run error
        // interpolates this text, and an empty one leaves the operator a trailing colon.
        sqlx::query("UPDATE cohort_backfill_chunks SET last_error = '' WHERE id = $1")
            .bind(chunk_ids[0])
            .execute(&pool)
            .await?;
        let exhausted = store
            .runs_with_exhausted_chunks(&[seeding_run], attempts5)
            .await?;
        ensure!(exhausted[0].last_error == NO_ERROR_RECORDED);
        Ok(())
    })
    .await
}

/// Failing a run whose chunk exhausted its retries stops the run dead: a still-pending sibling is no
/// longer claimable, a live sibling's heartbeat is refused, and a second failure is a no-op rather
/// than a double-count. Without it the run sits in `seeding` forever holding its cohort's slot.
#[tokio::test]
async fn exhausted_chunk_fails_the_run_and_stops_further_claims() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(
            planned_count(store.plan_chunks(seeding_run, [100, 101, 102], ONE_BAND).await?)? == 3
        );

        let lease60 = LeaseDuration::new(Duration::from_secs(60))?;
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [seeding_run];
        let claimant = Claimant::new("worker-a")?;

        // One chunk mid-scan with a live lease, one capped out, one left pending.
        let claimed = store
            .claim_next(&run_ids, &claimant, lease60, attempts5)
            .await?
            .context("claimant found no chunk")?;
        let live_lease = claimed.chunk.spec().lease;
        let capped_id: Uuid = sqlx::query_scalar(
            "SELECT id FROM cohort_backfill_chunks WHERE run_id = $1 AND status = 'pending' ORDER BY day LIMIT 1",
        )
        .bind(seeding_run)
        .fetch_one(&pool)
        .await?;
        sqlx::query(
            "UPDATE cohort_backfill_chunks SET status = 'failed', attempts = 5, last_error = 'scan blew up' WHERE id = $1",
        )
        .bind(capped_id)
        .execute(&pool)
        .await?;

        // Through the seeder's own pass, not a hand-rolled equivalent: the scan, the error text and
        // the attempt-cap interpolation are what an operator ends up reading.
        ensure!(
            fail_exhausted_runs_of_kind(
                &pool,
                &store,
                &run_ids,
                RunKind::Behavioral,
                attempts5
            )
            .await
                == 1
        );

        let (status, error, finished): (String, String, bool) = sqlx::query_as(
            "SELECT status, error, finished_at IS NOT NULL FROM cohort_backfill_runs WHERE id = $1",
        )
        .bind(seeding_run)
        .fetch_one(&pool)
        .await?;
        ensure!(status == "failed");
        ensure!(error.contains("1 chunk(s) exhausted the 5 attempt retry budget"));
        ensure!(error.contains(&capped_id.to_string()));
        ensure!(error.contains("scan blew up"));
        ensure!(finished);

        // The claim and heartbeat predicates both join `runs.status = 'seeding'`, so the pending
        // sibling stops being claimable and the in-flight one halts on its next beat.
        ensure!(store
            .claim_next(&run_ids, &Claimant::new("worker-b")?, lease60, attempts5)
            .await?
            .is_none());
        let still_pending: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM cohort_backfill_chunks WHERE run_id = $1 AND status = 'pending'",
        )
        .bind(seeding_run)
        .fetch_one(&pool)
        .await?;
        ensure!(
            still_pending == 1,
            "a claimable chunk remained, so the run status is what blocked the claim"
        );
        ensure_lease_lost(test_support::heartbeat(&store, live_lease, &claimant, lease60).await)?;
        drop(claimed);

        // Idempotent: a later pass re-reads the same exhausted chunks, and the already-terminal run
        // must not be counted again.
        ensure!(
            fail_exhausted_runs_of_kind(
                &pool,
                &store,
                &run_ids,
                RunKind::Behavioral,
                attempts5
            )
            .await
                == 0
        );
        ensure!(matches!(
            fail_run(&pool, seeding_run, &RenderedError::from_message("again")).await,
            Err(RunError::NotActive(_))
        ));
        Ok(())
    })
    .await
}

/// Both persisted error columns are truncated to the limit: `chunk.fail` clamps `last_error` and
/// `fail_run` clamps `run.error`, each flipping the row to `failed`.
#[tokio::test]
async fn fail_truncates_chunk_and_run_error_columns() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(planned_count(store.plan_chunks(seeding_run, [100], ONE_BAND).await?)? == 1);

        let lease60 = LeaseDuration::new(Duration::from_secs(60))?;
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [seeding_run];
        let claimed = store
            .claim_next(&run_ids, &Claimant::new("worker-a")?, lease60, attempts5)
            .await?
            .context("claimant found no chunk")?;
        let lease = claimed.chunk.spec().lease;
        let chunk_id = lease.chunk_id();
        store
            .fail(lease, &RenderedError::from_message("x".repeat(5_000)))
            .await?;
        drop(claimed);
        let (failed_status, error_length): (String, i32) = sqlx::query_as(
            "SELECT status, length(last_error)::integer FROM cohort_backfill_chunks WHERE id = $1",
        )
        .bind(chunk_id)
        .fetch_one(&pool)
        .await?;
        ensure!(failed_status == "failed");
        ensure!(error_length == 4_096);

        let active_run = insert_run(
            &pool,
            3,
            "team_enablement",
            "awaiting_boundary",
            false,
            empty_pinned(),
        )
        .await?;
        fail_run(
            &pool,
            active_run,
            &RenderedError::from_message("y".repeat(5_000)),
        )
        .await?;
        let (run_status, run_error_length): (String, i32) = sqlx::query_as(
            "SELECT status, length(error)::integer FROM cohort_backfill_runs WHERE id = $1",
        )
        .bind(active_run)
        .fetch_one(&pool)
        .await?;
        ensure!(run_status == RunStatus::Failed.as_str());
        ensure!(run_error_length == 4_096);
        Ok(())
    })
    .await
}

/// The dark-by-default proof: discovery with `kinds = [Behavioral]` (the gate-off binding) never
/// yields a person run, while widening the kind set surfaces it with its kind and pinned
/// `person_scan_since` decoded, and the pinned load validates the person payload.
#[tokio::test]
async fn discovery_is_kind_gated_and_person_pinned_load_validates() -> Result<()> {
    with_db(|pool| async move {
        let behavioral_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let person_run = insert_person_run(
            &pool,
            2,
            "seeding",
            true,
            person_pinned(&[(10, ACTIVE_HASH), (11, SUPERSEDED_HASH)]),
        )
        .await?;
        insert_participation(
            &pool,
            person_run,
            2,
            10,
            false,
            person_filter(ACTIVE_HASH, "email"),
        )
        .await?;
        insert_participation(
            &pool,
            person_run,
            2,
            11,
            true,
            person_filter(SUPERSEDED_HASH, "plan"),
        )
        .await?;

        let behavioral_only =
            discover_runs(&pool, &TeamAllowlist::All, &[RunKind::Behavioral]).await?;
        ensure!(behavioral_only.iter().all(|run| run.run_id != person_run));
        ensure!(behavioral_only
            .iter()
            .any(|run| run.run_id == behavioral_run));

        let both_kinds = discover_runs(
            &pool,
            &TeamAllowlist::All,
            &[RunKind::Behavioral, RunKind::PersonProperty],
        )
        .await?;
        let discovered = both_kinds
            .iter()
            .find(|run| run.run_id == person_run)
            .cloned()
            .context("person run was not discovered with the widened kind set")?;
        ensure!(discovered.kind == RunKind::PersonProperty);
        ensure!(discovered.person_scan_since.is_some());
        let behavioral = both_kinds
            .iter()
            .find(|run| run.run_id == behavioral_run)
            .context("behavioral run missing from the widened discovery")?;
        ensure!(behavioral.kind == RunKind::Behavioral);

        let seedable = match establish_boundary(&pool, discovered).await? {
            BoundaryOutcome::Established(run) | BoundaryOutcome::AlreadyEstablished(run) => run,
            BoundaryOutcome::NoLongerSeedable { .. } => bail!("person run was not seedable"),
        };
        let PersonRunValidation::Seedable(validated) = seedable.load_person_pinned(&pool).await?
        else {
            bail!("person run with an active participation unexpectedly retired");
        };
        ensure!(validated.run.conditions.len() == 1);
        ensure!(validated.run.horizon_days == 30);
        ensure!(validated.uncovered_cohorts.is_empty());
        ensure!(validated.warnings.iter().any(|warning| matches!(
            warning,
            PinnedWarning::ConditionSuperseded { cohort_id, .. } if *cohort_id == CohortId(11)
        )));
        Ok(())
    })
    .await
}

/// The cluster-wide planning claim is exclusive per run and frees on release, so at most one
/// replica ever runs a run's boundary scan.
#[tokio::test]
async fn person_planning_claim_is_exclusive_per_run_until_released() -> Result<()> {
    with_db(|pool| async move {
        let run = insert_person_run(&pool, 2, "seeding", true, person_pinned(&[])).await?;
        let other_run = insert_person_run(&pool, 3, "seeding", true, person_pinned(&[])).await?;
        let store = PgChunkStore::new(pool.clone());

        let held = store
            .try_claim_person_planning(run)
            .await?
            .context("first claim should win")?;
        ensure!(store.try_claim_person_planning(run).await?.is_none());
        // Claims are per run: a different run's planner is unaffected.
        let other = store
            .try_claim_person_planning(other_run)
            .await?
            .context("a different run's claim should win")?;

        held.release().await;
        other.release().await;
        let reclaimed = store
            .try_claim_person_planning(run)
            .await?
            .context("a released claim should be reclaimable")?;
        reclaimed.release().await;
        Ok(())
    })
    .await
}

/// Person planning is all-or-nothing: one racing planner wins and inserts every range under the
/// sentinel day with ordinal bands, the loser and any re-plan report `AlreadyPlanned`, and a
/// non-seeding run refuses.
#[tokio::test]
async fn person_planning_is_all_or_nothing_and_idempotent() -> Result<()> {
    with_db(|pool| async move {
        let run = insert_person_run(&pool, 2, "seeding", true, person_pinned(&[])).await?;
        let store = PgChunkStore::new(pool.clone());
        let boundaries = [Uuid::from_u128(0x10), Uuid::from_u128(0x20)];
        let ranges = tile_ranges(&boundaries)?;
        ensure!(ranges.len() == 3);

        let (left, right) = tokio::join!(
            store.plan_person_chunks(run, &ranges),
            store.plan_person_chunks(run, &ranges),
        );
        let outcomes = [left?, right?];
        ensure!(
            outcomes
                .iter()
                .filter(|outcome| matches!(outcome, PlanOutcome::Planned { inserted: 3 }))
                .count()
                == 1,
            "expected exactly one winning planner, got {outcomes:?}"
        );
        ensure!(
            outcomes
                .iter()
                .filter(|outcome| matches!(outcome, PlanOutcome::AlreadyPlanned))
                .count()
                == 1,
            "expected the losing planner to observe AlreadyPlanned, got {outcomes:?}"
        );
        ensure!(matches!(
            store.plan_person_chunks(run, &ranges).await?,
            PlanOutcome::AlreadyPlanned
        ));

        let rows: Vec<(String, i16, Option<Uuid>, Option<Uuid>)> = sqlx::query_as(
            "SELECT day::text, band, person_range_lo, person_range_hi \
             FROM cohort_backfill_chunks WHERE run_id = $1 ORDER BY band",
        )
        .bind(run)
        .fetch_all(&pool)
        .await?;
        ensure!(rows.len() == 3);
        ensure!(rows.iter().all(|(day, ..)| day == "9999-01-01"));
        ensure!(rows.iter().map(|(_, band, ..)| *band).eq(0..3));
        ensure!(rows[0].2 == Some(Uuid::nil()));
        ensure!(rows[0].3 == Some(boundaries[0]));
        ensure!(rows[1].2 == Some(boundaries[0]));
        ensure!(rows[1].3 == Some(boundaries[1]));
        ensure!(rows[2].2 == Some(boundaries[1]));
        ensure!(rows[2].3.is_none());

        let idle =
            insert_person_run(&pool, 3, "awaiting_boundary", false, person_pinned(&[])).await?;
        ensure!(matches!(
            store.plan_person_chunks(idle, &ranges).await?,
            PlanOutcome::RunNotSeeding
        ));
        Ok(())
    })
    .await
}

/// The sentinel day makes person chunks claim strictly after behavioral days on the shared claim
/// loop, and a person claim decodes its range with `num_bands` = the run's chunk count.
#[tokio::test]
async fn person_chunks_claim_after_behavioral_days_and_carry_ranges() -> Result<()> {
    with_db(|pool| async move {
        let behavioral_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let person_run = insert_person_run(&pool, 2, "seeding", true, person_pinned(&[])).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(planned_count(store.plan_chunks(behavioral_run, [100], ONE_BAND).await?)? == 1);
        let boundary = Uuid::from_u128(0x42);
        let ranges = tile_ranges(&[boundary])?;
        ensure!(planned_count(store.plan_person_chunks(person_run, &ranges).await?)? == 2);

        let lease60 = LeaseDuration::new(Duration::from_secs(60))?;
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [behavioral_run, person_run];
        let claimant = Claimant::new("worker-a")?;

        let first = store
            .claim_next(&run_ids, &claimant, lease60, attempts5)
            .await?
            .context("behavioral chunk was not claimed first")?;
        ensure!(first.chunk.spec().lease.run_id() == behavioral_run);
        ensure!(first.chunk.spec().person_range.is_none());

        let second = store
            .claim_next(&run_ids, &claimant, lease60, attempts5)
            .await?
            .context("first person chunk was not claimed")?;
        let second_spec = second.chunk.spec();
        ensure!(second_spec.lease.run_id() == person_run);
        ensure!(second_spec.band.band() == 0);
        ensure!(second_spec.band.num_bands().get() == 2);
        let second_range = second_spec
            .person_range
            .context("person claim lost its range")?;
        ensure!(second_range.lo() == Uuid::nil());
        ensure!(second_range.hi() == Some(boundary));

        let third = store
            .claim_next(&run_ids, &claimant, lease60, attempts5)
            .await?
            .context("second person chunk was not claimed")?;
        let third_range = third
            .chunk
            .spec()
            .person_range
            .context("person claim lost its range")?;
        ensure!(third_range.lo() == boundary);
        ensure!(third_range.hi().is_none());
        drop((first, second, third));
        Ok(())
    })
    .await
}

/// Cancelling a run breaks its live leases: the claimed chunk's next heartbeat fences out, so the
/// lease surfaces `Heartbeat(LeaseLost)` and its cancellation token trips.
#[tokio::test]
async fn cancelling_a_run_kills_its_live_lease_via_the_heartbeat() -> Result<()> {
    with_db(|pool| async move {
        let seeding_run =
            insert_run(&pool, 2, "team_enablement", "seeding", true, empty_pinned()).await?;
        let store = PgChunkStore::new(pool.clone());
        ensure!(planned_count(store.plan_chunks(seeding_run, [100], ONE_BAND).await?)? == 1);

        let lease3 = LeaseDuration::new(Duration::from_secs(3))?;
        let attempts5 = MaxAttempts::new(5)?;
        let run_ids = [seeding_run];
        let observed = store
            .claim_next(&run_ids, &Claimant::new("worker-f")?, lease3, attempts5)
            .await?
            .context("claimant found no chunk")?;
        let cancelled = observed.lease.cancellation_token();
        sqlx::query(
            "UPDATE cohort_backfill_runs SET status = 'cancelled', updated_at = now() WHERE id = $1",
        )
        .bind(seeding_run)
        .execute(&pool)
        .await?;
        let failure =
            tokio::time::timeout(Duration::from_secs(3), observed.lease.failure()).await?;
        ensure!(matches!(
            failure,
            LeaseFailure::Heartbeat(ChunkStoreError::LeaseLost { .. })
        ));
        ensure!(cancelled.is_cancelled());
        Ok(())
    })
    .await
}
