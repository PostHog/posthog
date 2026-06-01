use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_database::get_pool_with_config;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use rdkafka::consumer::{Consumer, StreamConsumer};
use tokio::net::TcpListener;
use tracing::{info, warn};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use cohort_stream_processor::config::Config;
use cohort_stream_processor::consumers::{CohortStreamEventsConsumer, EventDispatcher};
use cohort_stream_processor::filters::{run_refresh_loop, CatalogHandle};
use cohort_stream_processor::observability;
use cohort_stream_processor::partitions::{OffsetTracker, PartitionRouter};
use cohort_stream_processor::producer::{KafkaMembershipSink, MembershipSink};
use cohort_stream_processor::store::CohortStore;

common_alloc::used!();

const SERVICE_NAME: &str = "cohort-stream-processor";

fn main() -> Result<()> {
    let config = Config::init_from_env()
        .context("Failed to load configuration from environment variables")?;

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("Failed to build tokio runtime")?;

    runtime.block_on(async_main(config))
}

async fn async_main(config: Config) -> Result<()> {
    init_tracing();
    log_startup(&config);

    // The generous shutdown timeout leaves room for the final RocksDB checkpoint flush.
    let mut manager = Manager::builder(SERVICE_NAME)
        .with_global_shutdown_timeout(Duration::from_secs(90))
        .build();

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));
    // Monitored for clean shutdown, not liveness: a refresh outage must not kill the service, which
    // keeps serving the last good snapshot.
    let catalog_handle_lifecycle = manager.register(
        "filter-catalog",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    // The consumer owns the liveness deadline: a wedged consume loop or sustained broker outage
    // trips coordinated shutdown. Its graceful window covers draining worker channels and the
    // final commit.
    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(Duration::from_secs(60))
            .with_stall_threshold(3),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let recorder_handle = if config.export_prometheus {
        Some(observability::metrics::install_recorder())
    } else {
        None
    };

    // Build all infrastructure before starting the monitor: a failure here returns before the
    // monitor thread runs, so the dropped handles are harmless no-ops and the process exits non-zero.
    let pool = get_pool_with_config(&config.database_url, config.pool_config())
        .context("creating posthog_cohort database pool")?;

    let catalog = Arc::new(CatalogHandle::new());
    match catalog.refresh(&pool).await {
        Ok(stats) => info!(
            teams = stats.teams,
            unique_conditions = stats.unique_conditions,
            "initial filter catalog loaded",
        ),
        Err(err) => warn!(
            error = %err,
            "initial filter catalog load failed; catalog is empty until the refresh task succeeds",
        ),
    }

    // The `StreamConsumer` subscribes here but does not fetch until `process()` polls it after the
    // monitor starts, so building it now keeps the fail-fast discipline above.
    let store = CohortStore::open(&config.store_config()).context("opening RocksDB state store")?;
    let router = PartitionRouter::new(config.partition_channel_buffer);
    let offset_tracker = Arc::new(OffsetTracker::new());

    // `KafkaMembershipSink::new` pings broker metadata, so a bad Kafka config fails fast here.
    let kafka_config = config.build_kafka_config();
    let sink: Arc<dyn MembershipSink> = Arc::new(
        KafkaMembershipSink::new(
            &kafka_config,
            config.cohort_membership_changed_topic.clone(),
        )
        .await
        .context("creating shadow producer")?,
    );

    let stream_consumer: StreamConsumer = config
        .consumer_client_config()
        .create()
        .context("creating cohort_stream_events consumer")?;
    stream_consumer
        .subscribe(&[config.cohort_stream_events_topic.as_str()])
        .context("subscribing to cohort_stream_events")?;

    let guard = manager.monitor_background();

    let refresh_catalog = catalog.clone();
    let refresh_pool = pool.clone();
    let refresh_interval = config.filter_catalog_refresh_interval();
    let refresh_jitter = config.filter_catalog_refresh_jitter();
    tokio::spawn(async move {
        run_refresh_loop(
            refresh_catalog,
            refresh_pool,
            refresh_interval,
            refresh_jitter,
            catalog_handle_lifecycle,
        )
        .await;
    });

    // The dispatcher shares the catalog snapshot the refresh loop swaps, and hands the sink + offset
    // tracker to each per-partition worker it spawns.
    let dispatcher = EventDispatcher::new(router, offset_tracker, store, catalog.clone(), sink);
    let events_consumer = CohortStreamEventsConsumer::new(
        stream_consumer,
        config.cohort_stream_events_topic.clone(),
        dispatcher,
        consumer_handle,
        config.recv_batch_size,
        config.recv_batch_timeout(),
        config.offset_commit_interval(),
    );
    tokio::spawn(events_consumer.process());

    let app = observability::health::router(SERVICE_NAME, readiness, liveness, recorder_handle);
    let bind = config.bind_address();
    info!(address = %bind, "observability server starting");

    let listener = TcpListener::bind(&bind)
        .await
        .with_context(|| format!("failed to bind observability server to {bind}"))?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await
        .context("observability server error")?;
    metrics_handle.work_completed();

    guard.wait().await?;

    info!(service = SERVICE_NAME, "service stopped");
    Ok(())
}

/// Log a redacted startup summary. Deliberately omits `database_url` (carries credentials).
fn log_startup(config: &Config) {
    info!(
        service = SERVICE_NAME,
        bind_address = %config.bind_address(),
        kafka_hosts = %config.kafka_hosts,
        input_topic = %config.cohort_stream_events_topic,
        output_topic = %config.cohort_membership_changed_topic,
        consumer_group = %config.kafka_consumer_group,
        offset_reset = %config.kafka_consumer_offset_reset,
        recv_batch_size = config.recv_batch_size,
        partition_channel_buffer = config.partition_channel_buffer,
        store_path = %config.store_path,
        filter_catalog_refresh_secs = config.filter_catalog_refresh_secs,
        filter_catalog_refresh_jitter_secs = config.filter_catalog_refresh_jitter_secs,
        "starting cohort-stream-processor",
    );
}

/// JSON structured logging in production; human-readable when `RUST_LOG` requests debug.
/// Mirrors `rust/ingestion-consumer/src/main.rs`.
fn init_tracing() {
    let is_debug = std::env::var("RUST_LOG")
        .map(|v| v.contains("debug"))
        .unwrap_or(false);

    let log_layer = if is_debug {
        fmt::layer()
            .with_target(true)
            .with_level(true)
            .with_ansi(true)
            .with_filter(
                EnvFilter::builder()
                    .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
                    .from_env_lossy(),
            )
            .boxed()
    } else {
        fmt::layer()
            .json()
            .flatten_event(true)
            .with_current_span(true)
            .with_filter(
                EnvFilter::builder()
                    .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
                    .from_env_lossy(),
            )
            .boxed()
    };

    tracing_subscriber::registry().with(log_layer).init();
}
