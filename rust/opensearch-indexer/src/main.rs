use std::time::Duration;

use common_kafka::kafka_consumer::SingleTopicConsumer;
use lifecycle::{ComponentOptions, Manager};
use opensearch_indexer::{
    api::root_router,
    config::Config,
    work_loop::{run_consumer, run_sink},
};
use serve_metrics::setup_metrics_routes;
use tokio::net::TcpListener;
use tokio::sync::mpsc;
use tracing::level_filters::LevelFilter;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

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

    let mut manager = Manager::builder("opensearch-indexer")
        .with_global_shutdown_timeout(Duration::from_secs(60))
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

    let (tx, rx) = mpsc::channel(1000);

    let guard = manager.monitor_background();

    tokio::spawn(run_consumer(consumer, tx, consumer_handle));
    tokio::spawn(run_sink(rx, sink_handle));

    let app = root_router(readiness, liveness);
    let app = setup_metrics_routes(app);

    info!(address = %bind, "HTTP server starting");
    let listener = TcpListener::bind(&bind).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(http_handle.shutdown_signal())
        .await?;
    http_handle.work_completed();

    guard.wait().await?;

    info!("opensearch-indexer stopped");
    Ok(())
}
