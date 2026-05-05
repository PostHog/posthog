use std::sync::Arc;
use std::time::Duration;

use common_kafka::kafka_consumer::SingleTopicConsumer;
use common_redis::{Client, CompressionConfig, RedisClient, RedisValueFormat};
use lifecycle::{ComponentOptions, Manager};
use opensearch_indexer::{
    api::root_router,
    bulk::BulkWriter,
    config::Config,
    readiness::wait_for_alias,
    sampling::{
        drain_decision_writes, new_decision_write_joinset, SamplingConfig,
        DECISION_WRITE_DRAIN_DEADLINE,
    },
    work_loop::{run_consumer, run_sink, SinkConfig},
};
use serve_metrics::setup_metrics_routes;
use tokio::net::TcpListener;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::level_filters::LevelFilter;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

/// Install a SIGTERM/SIGINT listener that cancels `token` on receipt. Runs
/// before the lifecycle Manager's own signal handler is up so the readiness
/// gate window is shutdown-aware. Multiple Tokio signal listeners coexist
/// fine; the lifecycle Manager will install its own copy when monitor_background
/// runs and will see the token already cancelled if shutdown happened earlier.
fn spawn_early_signal_listener(token: CancellationToken) {
    tokio::spawn(async move {
        let mut sigterm = match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(s) => s,
            Err(e) => {
                tracing::warn!(error = %e, "failed to install SIGTERM handler for readiness gate");
                return;
            }
        };
        tokio::select! {
            _ = tokio::signal::ctrl_c() => info!("readiness gate received SIGINT"),
            _ = sigterm.recv() => info!("readiness gate received SIGTERM"),
        }
        token.cancel();
    });
}

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy(),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    setup_tracing();
    info!("Starting opensearch-indexer...");

    let config = Config::init_with_defaults()?;
    let bind = format!("{}:{}", config.host, config.port);

    // Shared shutdown token: wired into both the readiness gate (so SIGTERM
    // during alias-poll exits promptly) and the lifecycle Manager (so the
    // gate's cancellation flows into the rest of the shutdown sequence).
    let shutdown_token = CancellationToken::new();
    spawn_early_signal_listener(shutdown_token.clone());

    // Readiness gate: refuse to start if the alias is missing. Auto-creating
    // an index would silently produce wrong mappings, so we'd rather fail fast
    // than ingest into a bad target. Runs before binding HTTP / spawning
    // workers so K8s sees the pod as not-ready (no listener) until the
    // dependency is verified.
    let probe_client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()?;
    wait_for_alias(
        &probe_client,
        &config.opensearch_url,
        &config.opensearch_index_alias,
        shutdown_token.clone(),
    )
    .await?;

    let mut manager = Manager::builder("opensearch-indexer")
        .with_global_shutdown_timeout(Duration::from_secs(60))
        .with_shutdown_token(shutdown_token)
        .build();

    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(Duration::from_secs(60))
            .with_stall_threshold(3),
    );

    let sink_handle = manager.register(
        "sink",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );

    let http_handle = manager.register(
        "http_server",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(10))
            .is_observability(true),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;
    info!(
        "Subscribed to topic: {}",
        config.consumer.kafka_consumer_topic
    );

    // Tight timeouts: healthy Redis ops are sub-ms. 50ms caps per-event latency
    // during an outage so fail-open in decide() degrades gracefully instead of
    // hanging the consumer. Compression off + Utf8 because counters are integers
    // and pickle/zstd would be wasted cycles per INCR.
    //
    // Capacity note: every $ai_* event triggers one Redis INCR before flowing to
    // the sink, so Redis ops/sec equals event ops/sec. Provision Redis (and the
    // multiplexed connection's parallelism) for peak event QPS, not for the
    // average; the per-event round-trip is the throughput ceiling.
    let redis: Arc<dyn Client + Send + Sync> = Arc::new(
        RedisClient::with_config(
            config.redis_url.clone(),
            CompressionConfig::disabled(),
            RedisValueFormat::Utf8,
            Some(Duration::from_millis(50)),
            Some(Duration::from_millis(50)),
        )
        .await?,
    );
    // Tracked joinset for the per-decision HINCRBY spawns in `decide()`.
    // Without it the writes are fire-and-forget and runtime-cancelled at exit;
    // with it, shutdown can drain pending observability writes within a 5s
    // deadline.
    let decision_writes = new_decision_write_joinset();
    let sampling_config = Arc::new(
        SamplingConfig::from_config(&config).with_decision_writes(decision_writes.clone()),
    );

    let writer = BulkWriter::new(&config.opensearch_url, &config.opensearch_index_alias)?
        .with_shutdown_token(sink_handle.shutdown_token());
    let sink_config = SinkConfig {
        max_batch_bytes: config.bulk_max_batch_bytes,
        max_batch_age: Duration::from_millis(config.bulk_max_age_ms),
    };

    let (tx, rx) = mpsc::channel(1000);

    let guard = manager.monitor_background();

    tokio::spawn(run_consumer(
        consumer,
        tx,
        consumer_handle,
        redis,
        sampling_config,
    ));
    tokio::spawn(run_sink(rx, sink_handle, writer, sink_config));

    let app = root_router(readiness, liveness);
    let app = setup_metrics_routes(app);

    info!(address = %bind, "HTTP server starting");
    let listener = TcpListener::bind(&bind).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(http_handle.shutdown_signal())
        .await?;
    http_handle.work_completed();

    guard.wait().await?;

    // After the lifecycle Manager has drained registered components, give any
    // still-running per-decision Redis writes a brief window to complete so
    // we don't lose observability data on shutdown. Tasks not done by the
    // deadline are aborted and counted on
    // `opensearch_indexer_team_decisions_shutdown_aborted_total`.
    drain_decision_writes(decision_writes, DECISION_WRITE_DRAIN_DEADLINE).await;

    info!("opensearch-indexer stopped");
    Ok(())
}
