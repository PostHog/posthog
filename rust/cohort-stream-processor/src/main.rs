use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_database::get_pool_with_config;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use rdkafka::consumer::{Consumer, StreamConsumer};
use tokio::net::TcpListener;
use tokio::sync::mpsc;
use tracing::{info, warn};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use cohort_stream_processor::config::Config;
use cohort_stream_processor::consumers::{CohortStreamEventsConsumer, EventDispatcher};
use cohort_stream_processor::filters::{run_refresh_loop, CatalogHandle};
use cohort_stream_processor::observability;
use cohort_stream_processor::partitions::{
    run_rebalance_worker, CohortConsumerContext, OffsetTracker, PartitionRouter,
};
use cohort_stream_processor::producer::{KafkaMembershipSink, MembershipSink};
use cohort_stream_processor::store::CohortStore;
use cohort_stream_processor::sweep::{run_sweep_loop, DispatchSweeper};

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

    let catalog = Arc::new(CatalogHandle::with_allowlist(config.team_allowlist.clone()));
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
    // monitor starts, so building it now keeps the fail-fast discipline above. `wipe_store_on_start`
    // makes `open` destroy any on-disk state first, so a restart never serves a previous owner's
    // per-partition state.
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

    // The dispatcher owns the shared router/workers/ownership state; the consume loop dispatches
    // through it while the rebalance context (and its async worker) drive the partition lifecycle
    // over the *same* state. It shares the catalog snapshot the refresh loop swaps, and hands the
    // sink + offset tracker to each per-partition worker.
    let dispatcher = Arc::new(EventDispatcher::new(
        router,
        offset_tracker,
        store,
        catalog.clone(),
        sink,
    ));

    // The consumer carries the rebalance context, so `create_with_context` (which pings broker
    // metadata) still fails fast here on a bad Kafka config.
    let (context, rebalance_rx) = CohortConsumerContext::new(dispatcher.clone());
    let stream_consumer: StreamConsumer<CohortConsumerContext> = config
        .consumer_client_config()
        .create_with_context(context)
        .context("creating cohort_stream_events consumer")?;
    stream_consumer
        .subscribe(&[config.cohort_stream_events_topic.as_str()])
        .context("subscribing to cohort_stream_events")?;

    // Currently unused; wired through to the rebalance worker and the consume loop.
    let (consumer_command_tx, consumer_command_rx) = mpsc::unbounded_channel();

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

    // The async half of rebalancing: reclaim revoked partitions off the poll thread, exiting on the
    // consumer's shutdown token. Held so teardown can await it after the consume loop stops.
    let rebalance_worker = tokio::spawn(run_rebalance_worker(
        rebalance_rx,
        dispatcher.clone(),
        consumer_command_tx,
        consumer_handle.shutdown_token(),
    ));

    // The time-driven eviction sweep: each tick routes a `Sweep` to every owned partition's worker,
    // which drains its own queue and emits any `left`. Shares the consumer's shutdown token so it
    // stops on coordinated shutdown. Grab the token + dispatcher clone before the consumer takes
    // ownership of both (mirrors the rebalance-worker spawn above).
    tokio::spawn(run_sweep_loop(
        DispatchSweeper::new(dispatcher.clone(), config.sweep_safety_margin_ms as i64),
        config.sweep_interval(),
        consumer_handle.shutdown_token(),
    ));

    let events_consumer = CohortStreamEventsConsumer::new(
        stream_consumer,
        config.cohort_stream_events_topic.clone(),
        dispatcher,
        consumer_handle,
        config.recv_batch_size,
        config.recv_batch_timeout(),
        config.offset_commit_interval(),
        consumer_command_rx,
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

    // The consume loop has stopped and drained its workers; wait for the rebalance worker to finish
    // any in-flight revoke cleanup before exiting.
    if let Err(err) = rebalance_worker.await {
        warn!(error = %err, "rebalance worker task did not exit cleanly");
    }

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
        session_timeout_ms = config.kafka_session_timeout_ms,
        pod_identity = config.pod_identity().unwrap_or("<dynamic>"),
        recv_batch_size = config.recv_batch_size,
        partition_channel_buffer = config.partition_channel_buffer,
        store_path = %config.store_path,
        wipe_store_on_start = config.wipe_store_on_start,
        filter_catalog_refresh_secs = config.filter_catalog_refresh_secs,
        filter_catalog_refresh_jitter_secs = config.filter_catalog_refresh_jitter_secs,
        team_allowlist = ?config.team_allowlist,
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
