//! Operator-invoked reconcile control-tile dispatcher.

use std::num::NonZeroUsize;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use clap::Parser;
use cohort_core::partitioner::COHORT_PARTITION_COUNT;
use cohort_seeder::app::completion::{dispatch_and_record, verify_marker_topic};
use cohort_seeder::app::reconcile_dispatch::{
    execute_reconcile_dispatch, prepare_reconcile_dispatch, CompletionRequirement,
    PreparedDispatch, RegisterBackfillConfirmation,
};
use cohort_seeder::config::Config;
use cohort_seeder::domain::RunId;
use cohort_seeder::kafka::producer::SeedTileProducer;
use cohort_seeder::store::chunks::PgChunkStore;
use cohort_seeder::store::completion::{
    cas_run_reconciling, confirm_reconciling, ReconcilingClaim,
};
use cohort_seeder::store::runs::{RunKind, RunStatus};
use common_database::get_pool_with_config;
use envconfig::Envconfig;
use sqlx::PgPool;
use uuid::Uuid;

common_alloc::used!();

const PARTITION_VERIFY_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug, Parser)]
#[command(
    name = "reconcile_dispatch",
    about = "Dispatch partition-targeted reconcile snapshots for one cohort backfill run",
    long_about = "Dispatch partition-targeted reconcile snapshots for one cohort backfill run. \
                  The run's own row decides which definition fingerprint fences the snapshot, so \
                  behavioral and person-property runs are dispatched the same way.\n\nThe default \
                  invocation is a mutation: on a complete run it transitions the run to \
                  reconciling and persists the dispatch record (produce HWMs + marker-watch \
                  positions). Re-run with --dry-run first to validate the run and print the plan \
                  without touching it. --allow-incomplete produces tiles but never persists."
)]
struct Args {
    /// Cohort backfill run UUID.
    run_id: Uuid,

    /// Validate the run and print what would be dispatched, without claiming it or producing tiles.
    #[arg(long)]
    dry_run: bool,

    /// Dispatch while the run still has unconfirmed data chunks. Intended for development only.
    #[arg(long)]
    allow_incomplete: bool,

    /// Confirm that this run's data tiles were seeded or replayed after membership-register writers
    /// were deployed. Required because older runs cannot provide a complete reconcile scan domain.
    #[arg(long, required = true)]
    confirm_register_backfilled: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let config = Config::init_from_env().context("loading cohort-seeder configuration")?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("building tokio runtime")?;
    runtime.block_on(async_main(args, config))
}

async fn async_main(args: Args, config: Config) -> Result<()> {
    validate_partition_count(config.cohort_partition_count)?;
    let run_id = RunId(args.run_id);
    let pool = get_pool_with_config(&config.database_url, config.pool_config())
        .context("creating cohort-seeder PostgreSQL pool")?;
    let completion = if args.allow_incomplete {
        CompletionRequirement::AllowIncomplete
    } else {
        CompletionRequirement::Complete
    };
    let register_backfill = args
        .confirm_register_backfilled
        .then_some(RegisterBackfillConfirmation::confirmed_by_operator())
        .expect("clap requires --confirm-register-backfilled");
    let prepared = prepare_reconcile_dispatch(&pool, run_id, completion, register_backfill)
        .await
        .context("validating reconcile dispatch")?;
    if args.dry_run {
        println!(
            "dry run: run {} ({}) would dispatch {} active cohorts across {} seed partitions; \
             {}/{} chunks unconfirmed; {}",
            prepared.run_id().0,
            prepared.run_kind().as_str(),
            prepared.cohort_count(),
            COHORT_PARTITION_COUNT,
            prepared.remaining_chunks(),
            prepared.total_chunks(),
            match &prepared {
                PreparedDispatch::Certified(_) => "completion certified, would persist",
                PreparedDispatch::Uncertified(_) => "NOT certified, would not persist",
            },
        );
        return Ok(());
    }
    validate_person_dispatch(
        run_id,
        prepared.run_kind(),
        config.seeder_person_reconcile_dispatch_enabled,
    )?;
    eprintln!(
        "Dispatching {} active cohorts across {} seed partitions for run {}.",
        prepared.cohort_count(),
        COHORT_PARTITION_COUNT,
        prepared.run_id().0,
    );

    let producer = SeedTileProducer::new(
        &config.build_kafka_config(),
        config.seed_events_topic.clone(),
    )
    .await
    .context("creating seed tile producer")?;
    let max_inflight = NonZeroUsize::new(config.seeder_max_inflight_tiles)
        .context("SEEDER_MAX_INFLIGHT_TILES must be greater than zero")?;

    match prepared {
        PreparedDispatch::Certified(certified) => {
            let run_id = certified.prepared().run_id();
            let status = certified.prepared().run_status();
            // Probe before the CAS: `dispatch_and_record`'s first act is to capture this topic's
            // watermarks, and it owns the claim by then, so a topic that is missing or unreachable
            // would leave the run parked in `reconciling` with no dispatch record.
            verify_marker_topic(&producer, &config.cohort_reconcile_markers_topic).await?;
            let claim =
                acquire_claim(&pool, run_id, certified.prepared().run_kind(), status).await?;
            // `plan_chunks` gates its INSERT on a non-locking `status = 'seeding'` read, so a
            // statement whose snapshot predates the CAS can still add pending chunks the CAS's own
            // snapshot could not see. Re-read the ledger now that the run is frozen in
            // `reconciling`, and hand those chunks back rather than dispatch over a seed-data hole.
            let remaining = PgChunkStore::new(pool.clone())
                .chunk_progress(run_id)
                .await
                .context("re-reading the chunk ledger after claiming the run")?
                .remaining();
            if remaining != 0 {
                if status == RunStatus::Seeding {
                    claim
                        .revert(&pool)
                        .await
                        .context("reverting the reconciling claim after chunks reappeared")?;
                }
                bail!(
                    "run {run_id:?} gained {remaining} unconfirmed chunks after it was claimed; \
                     re-run once they confirm"
                );
            }
            let recorded = dispatch_and_record(
                &pool,
                &producer,
                &config.cohort_reconcile_markers_topic,
                max_inflight,
                PARTITION_VERIFY_TIMEOUT,
                certified,
                claim,
            )
            .await
            .context("dispatching and recording reconcile control tiles")?;
            for (partition, offset) in recorded.receipt.offsets() {
                println!("partition {}: {}", partition.as_u16(), offset);
            }
            println!(
                "dispatch record persisted (fence {})",
                recorded.epoch.as_datetime().to_rfc3339(),
            );
        }
        PreparedDispatch::Uncertified(prepared) => {
            if prepared.remaining_chunks() != 0 {
                eprintln!(
                    "Warning: dispatching run {} with {} unconfirmed chunks because \
                     --allow-incomplete was set. NOT persisted — completion tracking will not \
                     observe this dispatch.",
                    prepared.run_id().0,
                    prepared.remaining_chunks(),
                );
            } else {
                eprintln!(
                    "Warning: dispatching run {} with --allow-incomplete. NOT persisted — \
                     completion tracking will not observe this dispatch.",
                    prepared.run_id().0,
                );
            }
            let receipt = execute_reconcile_dispatch(
                prepared,
                &producer,
                max_inflight,
                PARTITION_VERIFY_TIMEOUT,
            )
            .await
            .context("dispatching reconcile control tiles")?;
            for (partition, offset) in receipt.offsets() {
                println!("partition {}: {}", partition.as_u16(), offset);
            }
        }
    }
    Ok(())
}

/// Claim the run for a persisted dispatch: CAS a seeding run into `reconciling`, or re-confirm one
/// already `reconciling`. A lost claim means the run changed state under the operator — a clear,
/// re-runnable error rather than a silent no-op.
async fn acquire_claim(
    pool: &PgPool,
    run_id: RunId,
    kind: RunKind,
    status: RunStatus,
) -> Result<ReconcilingClaim> {
    let claim = match status {
        RunStatus::Seeding => cas_run_reconciling(pool, run_id, kind).await,
        RunStatus::Reconciling => confirm_reconciling(pool, run_id, kind).await,
        other => bail!("run {run_id:?} has status {other:?}; expected seeding or reconciling"),
    }
    .context("claiming the run for reconcile dispatch")?;
    claim.context("the run changed state before it could be claimed for dispatch; re-run")
}

/// The kind is derived from the run row, so without this the CLI would put person-scoped tiles on
/// the seed topic while the fleet-wide gate is still off. Keyed on the reconcile gate rather than
/// the seed gate: producing tiles is the step an old processor cannot survive, and the two are
/// staged separately. Called after the dry-run early return, so a rehearsal stays allowed.
fn validate_person_dispatch(run_id: RunId, kind: RunKind, dispatch_enabled: bool) -> Result<()> {
    anyhow::ensure!(
        kind != RunKind::PersonProperty || dispatch_enabled,
        "run {run_id:?} is a person_property run; set SEEDER_PERSON_RECONCILE_DISPATCH_ENABLED \
         once every processor decodes reconcile_person tiles"
    );
    Ok(())
}

fn validate_partition_count(configured: u32) -> Result<()> {
    anyhow::ensure!(
        configured == COHORT_PARTITION_COUNT,
        "COHORT_PARTITION_COUNT must be {COHORT_PARTITION_COUNT} for reconcile dispatch, got {}",
        configured,
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const RUN_ID: &str = "0190f909-a2c1-7000-8000-000000000001";

    #[test]
    fn cli_requires_register_backfill_confirmation() {
        let args = Args::try_parse_from([
            "reconcile_dispatch",
            RUN_ID,
            "--allow-incomplete",
            "--confirm-register-backfilled",
        ])
        .unwrap();
        assert_eq!(args.run_id, Uuid::parse_str(RUN_ID).unwrap());
        assert!(args.allow_incomplete);
        assert!(args.confirm_register_backfilled);

        assert!(Args::try_parse_from(["reconcile_dispatch"]).is_err());
        assert!(Args::try_parse_from(["reconcile_dispatch", RUN_ID]).is_err());
        // A dry run takes the same flags as the real invocation, so the rehearsal validates exactly
        // the command that follows it.
        let dry = Args::try_parse_from([
            "reconcile_dispatch",
            RUN_ID,
            "--dry-run",
            "--confirm-register-backfilled",
        ])
        .unwrap();
        assert!(dry.dry_run);
        assert!(Args::try_parse_from(["reconcile_dispatch", RUN_ID, "--dry-run"]).is_err());
        assert!(Args::try_parse_from([
            "reconcile_dispatch",
            RUN_ID,
            RUN_ID,
            "--confirm-register-backfilled",
        ])
        .is_err());
    }

    #[test]
    fn cli_rejects_a_noncontract_partition_count() {
        assert!(validate_partition_count(COHORT_PARTITION_COUNT).is_ok());
        assert!(validate_partition_count(8).is_err());
    }

    /// The gate an operator would otherwise be the only thing standing between a person run and
    /// `reconcile_person` tiles a processor predating the split skip-commits without a marker,
    /// stranding the run a marker short of complete.
    #[test]
    fn cli_dispatches_a_person_run_only_once_the_reconcile_gate_is_open() {
        let run_id = RunId(Uuid::parse_str(RUN_ID).unwrap());
        assert!(validate_person_dispatch(run_id, RunKind::PersonProperty, false).is_err());
        assert!(validate_person_dispatch(run_id, RunKind::PersonProperty, true).is_ok());
        // The gate is person-only: a behavioral run dispatches whatever it is set to.
        assert!(validate_person_dispatch(run_id, RunKind::Behavioral, false).is_ok());
        assert!(validate_person_dispatch(run_id, RunKind::Behavioral, true).is_ok());
    }
}
