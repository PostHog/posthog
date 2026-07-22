//! Operator-invoked reconcile control-tile dispatcher.

use std::num::NonZeroUsize;
use std::time::Duration;

use anyhow::{Context, Result};
use clap::Parser;
use cohort_core::partitioner::COHORT_PARTITION_COUNT;
use cohort_seeder::app::reconcile_dispatch::{
    execute_reconcile_dispatch, prepare_reconcile_dispatch, CompletionRequirement,
    RegisterBackfillConfirmation,
};
use cohort_seeder::config::Config;
use cohort_seeder::domain::RunId;
use cohort_seeder::kafka::producer::SeedTileProducer;
use common_database::get_pool_with_config;
use envconfig::Envconfig;
use uuid::Uuid;

common_alloc::used!();

const PARTITION_VERIFY_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug, Parser)]
#[command(
    name = "reconcile_dispatch",
    about = "Dispatch partition-targeted reconcile snapshots for one behavioral cohort backfill run"
)]
struct Args {
    /// Behavioral cohort backfill run UUID.
    run_id: Uuid,

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
    if prepared.remaining_chunks() != 0 {
        eprintln!(
            "Warning: dispatching run {} with {} unconfirmed chunks because --allow-incomplete was set.",
            prepared.run_id().0,
            prepared.remaining_chunks(),
        );
    } else if args.allow_incomplete && prepared.total_chunks() == 0 {
        eprintln!(
            "Warning: dispatching run {} with an empty chunk ledger because --allow-incomplete was set.",
            prepared.run_id().0,
        );
    }
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
    let receipt =
        execute_reconcile_dispatch(prepared, &producer, max_inflight, PARTITION_VERIFY_TIMEOUT)
            .await
            .context("dispatching reconcile control tiles")?;

    for (partition, offset) in receipt.offsets() {
        println!("partition {}: {}", partition.as_u16(), offset);
    }
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
}
