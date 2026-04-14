pub mod data_gen;
pub mod metrics;
pub mod population;
pub mod report;
pub mod schema;
pub mod workloads;

use std::time::Instant;

use common_database::{get_pool_with_config, PoolConfig};
use rand::SeedableRng;

use crate::storage::postgres::PostgresStorage;
use data_gen::build_benchmark_data;

/// CLI arguments for the GIN index benchmark subcommand.
#[derive(clap::Args)]
pub struct BenchmarkArgs {
    /// Total number of person rows to populate.
    #[arg(long, default_value = "100000")]
    pub scale: u64,

    /// Number of teams to spread data across.
    #[arg(long, default_value = "100")]
    pub teams: i32,

    /// Duration in seconds for each workload phase.
    #[arg(long, default_value = "60")]
    pub duration_secs: u64,

    /// Number of concurrent writer tasks per phase.
    #[arg(long, default_value = "4")]
    pub concurrency: usize,

    /// Concurrency multiplier for the burst merge storm phase.
    #[arg(long, default_value = "10")]
    pub burst_factor: usize,

    /// Batch size for batch_upsert_persons calls.
    #[arg(long, default_value = "500")]
    pub batch_size: usize,

    /// Skip data population (reuse existing table data).
    #[arg(long)]
    pub skip_populate: bool,
}

/// Run the GIN index benchmark against the database at `FLAGS_READ_STORE_DATABASE_URL`.
pub async fn run(args: BenchmarkArgs) -> anyhow::Result<()> {
    let database_url = std::env::var("FLAGS_READ_STORE_DATABASE_URL")
        .or_else(|_| std::env::var("DATABASE_URL"))
        .map_err(|_| {
            anyhow::anyhow!(
                "FLAGS_READ_STORE_DATABASE_URL or DATABASE_URL must be set for benchmark mode"
            )
        })?;

    tracing::info!(
        scale = args.scale,
        teams = args.teams,
        concurrency = args.concurrency,
        burst_factor = args.burst_factor,
        duration_secs = args.duration_secs,
        "starting GIN index benchmark"
    );

    // Size the pool for the burst phase: burst tasks + readers + headroom.
    let max_conns = (args.concurrency * args.burst_factor + args.concurrency + 4) as u32;
    let max_conns = max_conns.max(64);

    let pool = get_pool_with_config(
        &database_url,
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

    // Generate lightweight registry (no properties stored — ~20 bytes/person).
    let mut rng = rand::rngs::StdRng::seed_from_u64(42);
    let registry = data_gen::generate_person_registry(&args, &mut rng);

    // Schema + population (if not skipped).
    if args.skip_populate {
        if !schema::table_exists(&pool).await? {
            anyhow::bail!("--skip-populate but flags_person_lookup table does not exist");
        }
        tracing::info!("skipping population");
    } else {
        schema::create_schema(&pool).await?;

        let pop_start = Instant::now();
        population::populate(&pool, &storage, &registry, args.batch_size).await?;
        tracing::info!(
            elapsed_secs = pop_start.elapsed().as_secs(),
            "population complete"
        );
    }

    // Build shared benchmark data: Arc-wrapped, pre-computed team indices and CDF.
    let data = build_benchmark_data(registry);
    tracing::info!(
        teams_with_merges = data.team_cdf.len(),
        "benchmark data ready"
    );

    // Reset pg_stat counters for clean per-phase deltas.
    metrics::reset_stats(&pool).await;

    // Run workload phases.
    let mut results = Vec::new();

    tracing::info!("=== Phase 1: Sustained property updates ===");
    let r = workloads::phase_property_updates(&pool, &data, &args).await?;
    tracing::info!(ops = r.latency.count, errors = r.errors, "phase 1 complete");
    results.push(r);

    // Reset stats between phases for clean deltas.
    metrics::reset_stats(&pool).await;

    tracing::info!("=== Phase 2: Identification appends ===");
    let r = workloads::phase_identification_appends(&pool, &data, &args).await?;
    tracing::info!(ops = r.latency.count, errors = r.errors, "phase 2 complete");
    results.push(r);

    metrics::reset_stats(&pool).await;

    tracing::info!("=== Phase 3: Merge workload ===");
    let r = workloads::phase_merges(&pool, &data, &args, "Merges", None, None).await?;
    tracing::info!(ops = r.latency.count, errors = r.errors, "phase 3 complete");
    results.push(r);

    metrics::reset_stats(&pool).await;

    tracing::info!(
        burst_concurrency = args.concurrency * args.burst_factor,
        "=== Phase 4: Burst merge storm ==="
    );
    let burst_concurrency = args.concurrency * args.burst_factor;
    let burst_duration = args.duration_secs / 4;
    let burst_name = format!("Burst merges ({}x)", args.burst_factor);
    let r = workloads::phase_merges(
        &pool,
        &data,
        &args,
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
        workloads::phase_concurrent_reads_writes(&pool, &data, &args).await?;
    tracing::info!(
        write_ops = write_r.latency.count,
        read_ops = read_r.latency.count,
        "phase 5 complete"
    );
    results.push(write_r);
    results.push(read_r);

    metrics::reset_stats(&pool).await;

    tracing::info!("=== Phase 6: Post-burst steady-state recovery ===");
    let r =
        workloads::phase_merges(&pool, &data, &args, "Post-burst merges", None, None).await?;
    tracing::info!(ops = r.latency.count, errors = r.errors, "phase 6 complete");
    results.push(r);

    // Print final report.
    report::print_report(&args, &results);

    Ok(())
}
