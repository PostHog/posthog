mod config;
mod data_gen;
mod metrics;
mod population;
mod report;
mod schema;
mod workloads;

use std::time::Instant;

use clap::Parser;
use common_database::{get_pool_with_config, PoolConfig};
use flags_consumer::storage::postgres::PostgresStorage;
use rand::SeedableRng;

use crate::config::BenchmarkConfig;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();

    let config = BenchmarkConfig::parse();

    tracing::info!(
        scale = config.scale,
        teams = config.teams,
        concurrency = config.concurrency,
        burst_factor = config.burst_factor,
        duration_secs = config.duration_secs,
        "starting GIN index benchmark"
    );

    // Size the pool for the burst phase: burst tasks + readers + headroom.
    let max_conns = (config.concurrency * config.burst_factor + config.concurrency + 4) as u32;
    let max_conns = max_conns.max(64);

    let pool = get_pool_with_config(
        &config.database_url,
        PoolConfig {
            max_connections: max_conns,
            min_connections: 2,
            acquire_timeout: std::time::Duration::from_secs(30),
            ..Default::default()
        },
    )?;

    let storage = PostgresStorage::new(pool.clone());

    // Verify connectivity.
    storage.ping().await?;
    tracing::info!("database connected");

    // Schema + population.
    let registry = if config.skip_populate {
        if !schema::table_exists(&pool).await? {
            anyhow::bail!("--skip-populate but flags_person_lookup table does not exist");
        }
        tracing::info!("skipping population, generating in-memory registry only");
        let mut rng = rand::rngs::StdRng::seed_from_u64(42);
        data_gen::generate_person_registry(&config, &mut rng)
    } else {
        schema::create_schema(&pool).await?;

        let mut rng = rand::rngs::StdRng::seed_from_u64(42);
        let registry = data_gen::generate_person_registry(&config, &mut rng);

        let pop_start = Instant::now();
        population::populate(&pool, &storage, &registry, config.batch_size).await?;
        tracing::info!(
            elapsed_secs = pop_start.elapsed().as_secs(),
            "population complete"
        );

        registry
    };

    // Reset pg_stat counters for clean per-phase deltas.
    metrics::reset_stats(&pool).await;

    // Run workload phases.
    let mut results = Vec::new();

    tracing::info!("=== Phase 1: Sustained property updates ===");
    let r = workloads::phase_property_updates(&pool, &registry, &config).await?;
    tracing::info!(ops = r.latency.count, errors = r.errors, "phase 1 complete");
    results.push(r);

    // Reset stats between phases for clean deltas.
    metrics::reset_stats(&pool).await;

    tracing::info!("=== Phase 2: Identification appends ===");
    let r = workloads::phase_identification_appends(&pool, &registry, &config).await?;
    tracing::info!(ops = r.latency.count, errors = r.errors, "phase 2 complete");
    results.push(r);

    metrics::reset_stats(&pool).await;

    tracing::info!("=== Phase 3: Merge workload ===");
    let r = workloads::phase_merges(&pool, &registry, &config, "Merges", None, None).await?;
    tracing::info!(ops = r.latency.count, errors = r.errors, "phase 3 complete");
    results.push(r);

    metrics::reset_stats(&pool).await;

    tracing::info!(
        burst_concurrency = config.concurrency * config.burst_factor,
        "=== Phase 4: Burst merge storm ==="
    );
    let burst_concurrency = config.concurrency * config.burst_factor;
    let burst_duration = config.duration_secs / 4;
    let burst_name = format!("Burst merges ({}x)", config.burst_factor);
    let r = workloads::phase_merges(
        &pool,
        &registry,
        &config,
        &burst_name,
        Some(burst_concurrency),
        Some(burst_duration),
    )
    .await?;
    tracing::info!(ops = r.latency.count, errors = r.errors, "phase 4 complete");
    results.push(r);

    metrics::reset_stats(&pool).await;

    tracing::info!("=== Phase 5: Concurrent reads + writes ===");
    let (write_r, read_r) =
        workloads::phase_concurrent_reads_writes(&pool, &registry, &config).await?;
    tracing::info!(
        write_ops = write_r.latency.count,
        read_ops = read_r.latency.count,
        "phase 5 complete"
    );
    results.push(write_r);
    results.push(read_r);

    // Print final report.
    report::print_report(&config, &results);

    Ok(())
}
