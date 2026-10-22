use std::sync::Arc;
use std::time::Duration;

use axum::{response::IntoResponse, routing::get, Router};
use common_kafka::kafka_consumer::SingleTopicConsumer;
use common_kafka::kafka_producer::EnvelopeEncoding;
use futures::future::BoxFuture;
use lifecycle::{ComponentOptions, Handle, Manager};
use property_vals_rs::{
    config::{Config, Worker},
    fan_out::{extract_tuple, fan_out, fan_out_group},
    producer::{AggregatedProducer, WireFormat},
    types::{Event, GroupIdentify, PropertyValueMessage},
    worker::{worker_loop, ReductionConfig},
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

/// Builds one worker's consumer, producer and loop. The caller spawns the loop
/// after the lifecycle monitor starts. A worker that exits before then sends its
/// exit event nowhere. The monitor then never learns that the worker stopped.
async fn build_worker(
    worker: Worker,
    config: &Arc<Config>,
    handle: Handle,
) -> Result<BoxFuture<'static, ()>, Box<dyn std::error::Error>> {
    let produce_timeout = Duration::from_secs(config.kafka_produce_timeout_secs);
    let length_caps = config.length_caps;

    let task: BoxFuture<'static, ()> = match worker {
        Worker::Events => {
            let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;
            let producer = AggregatedProducer::new(
                &config.kafka,
                handle.clone(),
                config.intermediate_topic.clone(),
                produce_timeout,
                config.intermediate_topic_encoding,
                config.intermediate_topic_format,
            )
            .await?;
            info!(
                "Subscribed to topic: {}",
                config.consumer.kafka_consumer_topic
            );
            let excluded = config.excluded_property_keys.clone();
            Box::pin(worker_loop::<Event, _, _>(
                config.clone(),
                consumer,
                producer,
                handle,
                move |e: &Event| fan_out(e, &excluded, length_caps),
                worker.name(),
                ReductionConfig {
                    max_values_per_key: 0,
                    seen_cache_capacity: config.events_seen_cache_capacity,
                },
            ))
        }
        Worker::Groups => {
            let mut consumer_config = config.consumer.clone();
            consumer_config.kafka_consumer_topic = config.groups_kafka_consumer_topic.clone();
            consumer_config.kafka_consumer_group = config.groups_kafka_consumer_group.clone();
            let consumer = SingleTopicConsumer::new(config.kafka.clone(), consumer_config)?;
            let producer = AggregatedProducer::new(
                &config.kafka,
                handle.clone(),
                config.intermediate_topic.clone(),
                produce_timeout,
                config.intermediate_topic_encoding,
                config.intermediate_topic_format,
            )
            .await?;
            info!(
                "Subscribed to topic: {}",
                config.groups_kafka_consumer_topic
            );
            let excluded = config.excluded_property_keys.clone();
            Box::pin(worker_loop::<GroupIdentify, _, _>(
                config.clone(),
                consumer,
                producer,
                handle,
                move |g: &GroupIdentify| fan_out_group(g, &excluded, length_caps),
                worker.name(),
                ReductionConfig::default(),
            ))
        }
        Worker::Merger => {
            let mut consumer_config = config.consumer.clone();
            consumer_config.kafka_consumer_topic = config.intermediate_topic.clone();
            consumer_config.kafka_consumer_group = config.merger_consumer_group.clone();
            let consumer = SingleTopicConsumer::new(config.kafka.clone(), consumer_config)?;
            // ClickHouse reads the output topic and expects raw rows. Do not encode it.
            let producer = AggregatedProducer::new(
                &config.kafka,
                handle.clone(),
                config.output_topic.clone(),
                produce_timeout,
                EnvelopeEncoding::None,
                WireFormat::Json,
            )
            .await?;
            info!("Subscribed to topic: {}", config.intermediate_topic);
            Box::pin(worker_loop::<PropertyValueMessage, _, _>(
                config.clone(),
                consumer,
                producer,
                handle,
                |m: &PropertyValueMessage| extract_tuple(m),
                worker.name(),
                ReductionConfig {
                    max_values_per_key: config.max_values_per_key,
                    seen_cache_capacity: config.merger_seen_cache_capacity,
                },
            ))
        }
    };
    Ok(task)
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

    info!(
        workers = ?config.workers(),
        events_topic = %config.consumer.kafka_consumer_topic,
        events_consumer_group = %config.consumer.kafka_consumer_group,
        groups_topic = %config.groups_kafka_consumer_topic,
        groups_consumer_group = %config.groups_kafka_consumer_group,
        intermediate_topic = %config.intermediate_topic,
        intermediate_topic_encoding = ?config.intermediate_topic_encoding,
        intermediate_topic_format = ?config.intermediate_topic_format,
        merger_consumer_group = %config.merger_consumer_group,
        output_topic = %config.output_topic,
        flush_interval_secs = config.flush_interval_secs,
        "config loaded"
    );

    let shared_config = Arc::new(config.clone());

    let mut worker_tasks = Vec::new();
    for &worker in config.workers() {
        let handle = manager.register(
            &format!("{}-worker", worker.name()),
            ComponentOptions::new()
                .with_graceful_shutdown(Duration::from_secs(30))
                .with_liveness_deadline(Duration::from_secs(60))
                .with_stall_threshold(3),
        );
        worker_tasks.push(build_worker(worker, &shared_config, handle).await?);
    }

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let guard = manager.monitor_background();

    for task in worker_tasks {
        tokio::spawn(task);
    }

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
