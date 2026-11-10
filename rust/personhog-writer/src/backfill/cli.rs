//! The one-time load of existing person properties into SlateDB: `start` sets where the backfill
//! writers begin, `plan` splits the person table into key ranges, `scan`
//! workers publish their ranges onto the backfill topic, and `verify` compares the two stores.

use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use axum::Router;
use common_database::{get_pool_with_config, PoolConfig};
use common_metrics::setup_metrics_routes;
use personhog_coordination::changelog::{load_changelog_config, CHANGELOG_BOOT_POLL_INTERVAL};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::ChangelogConfig;
use personhog_property_store::object_store::ObjectStore;
use rdkafka::producer::Producer;
use tokio_util::sync::CancellationToken;

use crate::backfill::scanner::{self, Run, SizeLimits, TopicSink};
use crate::backfill::start;
use crate::backfill::verify::{self, Verification};
use crate::config::Config;
use crate::kafka::{base_client_config, changelog_kafka};

const METADATA_TIMEOUT: Duration = Duration::from_secs(10);
/// Room for the message key and the record's other fields inside the producer's message limit.
const MESSAGE_OVERHEAD: usize = 4096;
const DEFAULT_MESSAGE_MAX_BYTES: usize = 1_000_000;

#[derive(clap::Args)]
pub struct Backfill {
    #[command(subcommand)]
    command: Command,
}

#[derive(clap::Subcommand)]
enum Command {
    /// Starts the backfill group at the writer group's committed offsets, before any backfill writer runs.
    Start,
    /// Splits the source table into the key ranges a run scans.
    Plan(PlanArgs),
    /// Scans this worker's share of a planned run onto the backfill topic.
    Scan(ScanArgs),
    /// Compares this worker's share of a planned run between Postgres and SlateDB.
    Verify(VerifyArgs),
}

#[derive(clap::Args)]
struct PlanArgs {
    #[arg(long)]
    run_id: String,
    #[arg(long, default_value_t = 5_000_000)]
    rows_per_range: i64,
}

#[derive(clap::Args)]
struct ScanArgs {
    /// The run `plan` planned; rerunning a finished range does nothing.
    #[arg(long)]
    run_id: String,
    /// This worker's number, such as an Indexed Job's completion index.
    #[arg(long)]
    index: usize,
    #[arg(long)]
    workers: usize,
    #[arg(long, default_value_t = 1000)]
    page_size: i64,
}

#[derive(clap::Args)]
struct VerifyArgs {
    /// The run whose plan supplies the key ranges; the progress goes under the same id.
    #[arg(long)]
    run_id: String,
    #[arg(long)]
    index: usize,
    #[arg(long)]
    workers: usize,
    #[arg(long, default_value_t = 1000)]
    page_size: i64,
    /// Checks one row in every N of each page; 1 checks every row.
    #[arg(long, default_value_t = 1)]
    sample_every: usize,
    /// The live database, which lists a team deleted after the snapshot in DATABASE_URL.
    #[arg(long)]
    live_database_url: Option<String>,
}

pub async fn run(backfill: Backfill, config: &Config) -> Result<(), Box<dyn std::error::Error>> {
    match backfill.command {
        Command::Start => start(config).await,
        Command::Plan(args) => plan(config, args).await,
        Command::Scan(args) => scan(config, args).await,
        Command::Verify(args) => verify(config, args).await,
    }
}

/// The scanner's size limits: the producer's message limit less the record's overhead, and the
/// leader's trim target.
pub(crate) fn limits(config: &Config) -> SizeLimits {
    SizeLimits {
        message_bytes: config
            .kafka
            .kafka_producer_message_max_bytes
            .map_or(DEFAULT_MESSAGE_MAX_BYTES, |bytes| bytes as usize)
            .saturating_sub(MESSAGE_OVERHEAD),
        trim_target: config.properties_trim_target,
    }
}

/// The object store a run's plan and progress live in, never the property store itself.
fn state_store(config: &Config) -> Result<Arc<dyn ObjectStore>, Box<dyn std::error::Error>> {
    let url = config.property_backfill_state_url.trim_end_matches('/');
    if url.is_empty() {
        return Err("backfill runs need PROPERTY_BACKFILL_STATE_URL".into());
    }
    if config
        .property_store
        .url()
        .is_ok_and(|store| store.trim_end_matches('/') == url)
    {
        return Err("PROPERTY_BACKFILL_STATE_URL must not be the property store".into());
    }
    let mut state = config.property_store.clone();
    state.url = Some(url.to_string());
    Ok(personhog_property_store::object_store(&state)?)
}

async fn changelog(config: &Config) -> Result<Option<ChangelogConfig>, Box<dyn std::error::Error>> {
    let store = EtcdStore::connect_with_member_failover(StoreConfig {
        endpoints: config.etcd_endpoint_list(),
        prefix: config.etcd_prefix.clone(),
    })
    .await?;
    let store = PersonhogStore::new(store);
    Ok(load_changelog_config(
        &store,
        CHANGELOG_BOOT_POLL_INTERVAL,
        &CancellationToken::new(),
    )
    .await?)
}

async fn start(config: &Config) -> Result<(), Box<dyn std::error::Error>> {
    if config.property_backfill_group.is_empty() {
        return Err("the start needs PROPERTY_BACKFILL_GROUP".into());
    }
    let Some(loaded) = changelog(config).await? else {
        return Err("no changelog config is registered".into());
    };
    let base = base_client_config(&changelog_kafka(&config.kafka, loaded.cluster.as_ref()));
    let (writer_group, backfill_group) = (
        loaded.writer_group.clone(),
        config.property_backfill_group.clone(),
    );
    let (topic, partitions) = (loaded.topic.clone(), loaded.partitions);
    let offsets = tokio::task::spawn_blocking(move || {
        start::copy_writer_offsets(&base, &writer_group, &backfill_group, &topic, partitions)
    })
    .await??;
    println!(
        "started {} at {}'s committed offsets on all {} partitions of {}",
        config.property_backfill_group,
        loaded.writer_group,
        offsets.len(),
        loaded.topic
    );
    Ok(())
}

async fn verify(config: &Config, args: VerifyArgs) -> Result<(), Box<dyn std::error::Error>> {
    serve_metrics(config.metrics_port);
    let pool = pool(config)?;
    let limits = limits(config);
    let live_pool = match &args.live_database_url {
        Some(url) => Some(get_pool_with_config(
            url,
            PoolConfig {
                max_connections: 2,
                pool_name: Some("personhog-writer-verify-live".to_string()),
                statement_timeout_ms: Some(10_000),
                ..Default::default()
            },
        )?),
        None => None,
    };
    let state = state_store(config)?;
    let run = Run::new(Arc::clone(&state), &args.run_id)?;
    let verification = Verification::new(state, &args.run_id)?;
    let reader = personhog_property_store::PropertyReader::new(
        &config.property_store,
        personhog_property_store::reader_object_store(&config.property_store)?,
    );
    tracing::info!(
        run_id = %args.run_id,
        index = args.index,
        workers = args.workers,
        sample_every = args.sample_every,
        "starting verification worker"
    );
    let counts = verify::Verifier {
        pool: &pool,
        reader: &reader,
        live_pool: live_pool.as_ref(),
        verification: &verification,
        limits,
    }
    .run_worker(
        &run,
        args.index,
        args.workers,
        args.page_size,
        args.sample_every,
    )
    .await;
    reader.close().await;
    let counts = counts?;
    tracing::info!(
        ?counts,
        divergent = counts.divergent(),
        "verification worker finished"
    );
    Ok(())
}

async fn plan(config: &Config, args: PlanArgs) -> Result<(), Box<dyn std::error::Error>> {
    let pool = pool(config)?;
    let run = Run::new(state_store(config)?, &args.run_id)?;
    let plan = scanner::plan(&pool, &config.pg_target_table, args.rows_per_range).await?;
    run.save_plan(&plan).await?;
    tracing::info!(
        run_id = %args.run_id,
        table = %config.pg_target_table,
        ranges = plan.ranges.len(),
        "backfill planned"
    );
    Ok(())
}

async fn scan(config: &Config, args: ScanArgs) -> Result<(), Box<dyn std::error::Error>> {
    if config.property_backfill_topic.is_empty() {
        return Err("the backfill needs PROPERTY_BACKFILL_TOPIC".into());
    }
    serve_metrics(config.metrics_port);
    let Some(loaded) = changelog(config).await? else {
        return Ok(());
    };
    if !loaded.draining.is_empty() {
        return Err("a changelog migration is draining; backfill after it finishes".into());
    }
    if config.property_backfill_topic == loaded.topic {
        return Err("PROPERTY_BACKFILL_TOPIC is the changelog itself".into());
    }

    let producer = common_kafka::kafka_producer::create_kafka_producer(
        &changelog_kafka(&config.kafka, loaded.cluster.as_ref()),
        Unmonitored,
    )
    .await?;
    let partitions = {
        let producer = producer.clone();
        let topic = config.property_backfill_topic.clone();
        tokio::task::spawn_blocking(move || {
            producer
                .client()
                .fetch_metadata(Some(&topic), METADATA_TIMEOUT)
                .map(|metadata| {
                    metadata
                        .topics()
                        .iter()
                        .find(|t| t.name() == topic)
                        .map_or(0, |t| t.partitions().len() as u32)
                })
        })
        .await??
    };
    // The backfill writers' range assignor co-locates the two topics' partitions only when their counts match.
    if partitions != loaded.partitions {
        return Err(format!(
            "backfill topic {} has {partitions} partitions; the changelog has {}",
            config.property_backfill_topic, loaded.partitions
        )
        .into());
    }

    let pool = pool(config)?;
    let run = Run::new(state_store(config)?, &args.run_id)?;
    let sink = TopicSink::new(
        producer,
        config.property_backfill_topic.clone(),
        loaded.partitions,
    );
    tracing::info!(
        run_id = %args.run_id,
        index = args.index,
        workers = args.workers,
        topic = %config.property_backfill_topic,
        "starting backfill worker"
    );
    let counts = scanner::run_worker(
        &pool,
        &sink,
        &run,
        args.index,
        args.workers,
        args.page_size,
        limits(config),
    )
    .await?;
    tracing::info!(?counts, "backfill worker finished");
    Ok(())
}

fn pool(config: &Config) -> Result<sqlx::PgPool, Box<dyn std::error::Error>> {
    Ok(get_pool_with_config(
        &config.database_url,
        PoolConfig {
            max_connections: 2,
            pool_name: Some("personhog-writer-backfill".to_string()),
            statement_timeout_ms: Some(300_000),
            ..Default::default()
        },
    )?)
}

fn serve_metrics(port: u16) {
    tokio::spawn(async move {
        let router = setup_metrics_routes(Router::new());
        let bind = format!("0.0.0.0:{port}");
        match tokio::net::TcpListener::bind(&bind).await {
            Ok(listener) => {
                tracing::info!("Metrics server listening on {bind}");
                if let Err(e) = axum::serve(listener, router).await {
                    tracing::warn!(error = %e, "metrics server stopped");
                }
            }
            Err(e) => tracing::warn!(error = %e, bind, "metrics server could not bind"),
        }
    });
}

#[derive(Clone)]
struct Unmonitored;

impl common_liveness::SyncLivenessReporter for Unmonitored {
    fn report_healthy(&self) {}
    fn report_unhealthy(&self) {}
}
