//! One production-shaped bulk delete against a running stack: create the
//! persons through the identity service, delete them as one chunked job,
//! and print what the job cost.

use std::time::Instant;

use anyhow::{bail, Result};
use futures::stream::{StreamExt, TryStreamExt};
use uuid::Uuid;

use crate::bulk_delete::BulkDeleter;
use crate::cli::BulkDeleteArgs;
use crate::client::{IdentityClient, LifecycleClient};
use crate::seed;

/// The identity service caps a get-or-create batch at 250 entries.
const SEED_BATCH: usize = 200;
const SEED_CONCURRENCY: usize = 8;

pub async fn run(args: BulkDeleteArgs) -> Result<()> {
    let identity =
        IdentityClient::connect_with_channels(&args.identity_url, args.router_channels).await?;
    let lifecycle =
        LifecycleClient::connect_with_channels(&args.identity_url, args.router_channels).await?;
    let deleter = BulkDeleter::new(lifecycle, args.chunk_size, args.concurrency)?;

    // The job id names the persons too, so a rerun creates fresh rows
    // instead of reviving the previous run's tombstones.
    let job_id = Uuid::new_v4();
    let distinct_ids: Vec<String> = (0..args.count)
        .map(|i| format!("bulk-{job_id}-{i}"))
        .collect();

    println!(
        "Seeding {} persons on team {} through {}...",
        args.count, args.team_id, args.identity_url
    );
    let seed_started = Instant::now();
    let batches: Vec<Vec<i64>> = futures::stream::iter(distinct_ids.chunks(SEED_BATCH))
        .map(|batch| seed::seed_persons_via_identity(&identity, args.team_id, batch))
        .buffered(SEED_CONCURRENCY)
        .try_collect()
        .await?;
    let person_ids: Vec<i64> = batches.into_iter().flatten().collect();
    println!(
        "  seeded {} persons in {:.2}s",
        person_ids.len(),
        seed_started.elapsed().as_secs_f64()
    );

    println!(
        "Deleting them as job {job_id}: chunks of {} ids, {} calls in flight...",
        args.chunk_size, args.concurrency
    );
    let report = deleter.delete(args.team_id, &person_ids, job_id).await?;
    let seconds = report.elapsed.as_secs_f64();
    println!("=== personhog-test-harness bulk-delete results ===");
    println!(
        "  Persons: {} | Chunks: {} | Concurrency: {} | Duration: {seconds:.2}s | Persons/s: {:.0}",
        person_ids.len(),
        report.chunks,
        args.concurrency,
        person_ids.len() as f64 / seconds.max(f64::EPSILON)
    );
    println!(
        "  Outcomes: deleted={} not_found={} skipped_conflict={} unspecified={}",
        report.deleted,
        report.not_found,
        report.skipped_conflict.len(),
        report.unspecified.len()
    );

    if let Some(person_id) = report.first_unsettled() {
        bail!(
            "person {person_id} on team {} was not deleted",
            args.team_id
        );
    }
    if report.not_found > 0 {
        // The persons were created moments ago by this run, so a
        // not_found answer means the row vanished between seed and delete.
        bail!("{} freshly seeded persons were not found", report.not_found);
    }
    Ok(())
}
