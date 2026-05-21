use std::sync::Arc;
use std::time::Duration;

use axum::{response::IntoResponse, routing::get, Router};
use common_kafka::kafka_consumer::SingleTopicConsumer;
use lifecycle::{ComponentOptions, Manager};
use property_vals_rs::{
    app_context::AppContext,
    config::Config,
    fan_out::{fan_out, fan_out_group},
    producer::AggregatedProducer,
    types::{Event, GroupIdentify},
    worker::worker_loop,
};
use serve_metrics::setup_metrics_routes;
use tokio::net::TcpListener;
use tracing::level_filters::LevelFilter;
use tracing::{info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy()
            .add_directive("pyroscope=warn".parse().unwrap()),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "property-vals-rs"
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    setup_tracing();
    info!("Starting up property-vals-rs...");

    let config = Config::init_with_defaults()?;

    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            warn!("Failed to start continuous profiling agent: {e}");
            None
        }
    };

    let mut manager = Manager::builder("property-vals-rs")
        .with_global_shutdown_timeout(Duration::from_secs(60))
        .build();

    let events_handle = manager.register(
        "events-worker",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(Duration::from_secs(60))
            .with_stall_threshold(3),
    );
    let groups_handle = manager.register(
        "groups-worker",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(Duration::from_secs(60))
            .with_stall_threshold(3),
    );

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    info!(
        events_topic = %config.consumer.kafka_consumer_topic,
        events_consumer_group = %config.consumer.kafka_consumer_group,
        events_transactional_id = %config.kafka_transactional_id,
        groups_topic = %config.groups_kafka_consumer_topic,
        groups_consumer_group = %config.groups_kafka_consumer_group,
        groups_transactional_id = %config.groups_kafka_transactional_id,
        output_topic = %config.output_topic,
        flush_interval_secs = config.flush_interval_secs,
        "config loaded"
    );

    let events_consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;
    let events_producer = AggregatedProducer::new(
        &config.kafka,
        &config.kafka_transactional_id,
        config.output_topic.clone(),
        Duration::from_secs(config.kafka_transaction_timeout_secs),
        events_consumer.clone(),
    )?;

    // Groups consumer inherits the events ConsumerConfig and overrides topic +
    // group only. Other tuning (TLS, fetch sizes, auto_commit=false) carries
    // over so the two workers have consistent Kafka client behavior.
    let mut groups_consumer_config = config.consumer.clone();
    groups_consumer_config.kafka_consumer_topic = config.groups_kafka_consumer_topic.clone();
    groups_consumer_config.kafka_consumer_group = config.groups_kafka_consumer_group.clone();
    let groups_consumer = SingleTopicConsumer::new(config.kafka.clone(), groups_consumer_config)?;
    let groups_producer = AggregatedProducer::new(
        &config.kafka,
        &config.groups_kafka_transactional_id,
        config.output_topic.clone(),
        Duration::from_secs(config.kafka_transaction_timeout_secs),
        groups_consumer.clone(),
    )?;

    info!(
        "Subscribed to topic: {}",
        config.consumer.kafka_consumer_topic
    );
    info!(
        "Subscribed to topic: {}",
        config.groups_kafka_consumer_topic
    );

    let ctx = Arc::new(AppContext::new(&config));

    let guard = manager.monitor_background();

    // One worker per topic. Each has its own transactional producer because
    // rdkafka allows one outstanding transaction per transactional.id.
    tokio::spawn(worker_loop::<Event, _, _>(
        ctx.clone(),
        events_consumer,
        events_producer,
        events_handle.clone(),
        fan_out,
    ));
    tokio::spawn(worker_loop::<GroupIdentify, _, _>(
        ctx.clone(),
        groups_consumer,
        groups_producer,
        groups_handle.clone(),
        fan_out_group,
    ));
    drop(events_handle);
    drop(groups_handle);

    let app = Router::new()
        .route("/", get(index))
        .route(
            "/_readiness",
            get({
                let r = readiness.clone();
                move || {
                    let r = r.clone();
                    async move { r.check().await }
                }
            }),
        )
        .route(
            "/_liveness",
            get({
                let l = liveness.clone();
                move || {
                    let l = l.clone();
                    async move { l.check().into_response() }
                }
            }),
        );
    let app = setup_metrics_routes(app);

    let bind = format!("{}:{}", config.host, config.port);
    info!(address = %bind, "HTTP server starting");
    let listener = TcpListener::bind(&bind).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await?;
    metrics_handle.work_completed();

    guard.wait().await?;

    info!("property-vals-rs stopped");
    Ok(())
}
