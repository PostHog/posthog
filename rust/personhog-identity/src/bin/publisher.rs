//! `personhog-publisher`: drains the publish outbox that personhog-identity
//! writes and produces the ClickHouse distinct id feed and the person merge
//! events. A separate deployment because publish load follows the create
//! rate and merge sizes while identity load follows RPC traffic, and because
//! a Kafka outage must hold this process's connections, not identity's.

use std::time::Duration;

use axum::{routing::get, Router};
use common_database::get_pool_with_config;
use common_kafka::kafka_producer::{create_kafka_producer, spawn_bounded_flush_on_shutdown};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use personhog_identity::publish::config::{MergeEventsAllowlist, PublisherConfig};
use personhog_identity::publish::sink::KafkaSink;
use personhog_identity::publish::Publisher;

common_alloc::used!();

/// Headroom past the longest pass, so shutdown waits for an in-flight
/// claim to commit or roll back before the producer flushes. The two
/// phases add up to under the 30 s Kubernetes default termination grace
/// period at the default timeouts.
const SHUTDOWN_MARGIN: Duration = Duration::from_secs(2);
const PRODUCER_FLUSH_BOUND: Duration = Duration::from_secs(10);

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = PublisherConfig::init_from_env().expect("Invalid configuration");

    tracing_subscriber::registry()
        .with(
            fmt::layer()
                .with_target(true)
                .with_thread_ids(true)
                .with_level(true),
        )
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();

    let tables = config.tables();
    tables.validate().expect("Invalid identity table set");
    let kafka = config.kafka().expect("Invalid Kafka producer settings");
    let merge_events = config
        .merge_events()
        .expect("Invalid PERSON_MERGE_EVENTS settings");
    let drain_config = config.drain_config(merge_events.as_ref());

    tracing::info!("Starting personhog-publisher");
    tracing::info!("Metrics port: {}", config.metrics_port);
    tracing::info!("Tables: {:?}", tables);
    tracing::info!(
        distinct_id_topic = %config.person_distinct_id_topic,
        batch_size = drain_config.batch_size,
        max_rows_per_pass = drain_config.max_rows_per_pass,
        interval_ms = drain_config.interval.as_millis() as u64,
        produce_timeout_ms = config.produce_timeout().as_millis() as u64,
        partitioner = ?kafka.kafka_producer_partitioner,
        "Publish settings"
    );
    match &merge_events {
        Some(settings) => {
            tracing::info!(
                topic = %settings.topic,
                team_allowlist = ?settings.team_allowlist,
                "Person merge events enabled"
            );
            // The cohort seeder reads an empty allowlist as every team, so
            // a value copied from there silences this one without an error.
            if matches!(&settings.team_allowlist, MergeEventsAllowlist::Teams(teams) if teams.is_empty())
            {
                tracing::warn!(
                    "PERSON_MERGE_EVENTS_TEAM_ALLOWLIST is empty, which allows no team; no merge event will be produced"
                );
            }
        }
        None => tracing::info!("Person merge events disabled"),
    }
    if tables.is_validation() {
        tracing::warn!(
            outbox = %tables.person_publish_outbox,
            distinct_id_topic = %config.person_distinct_id_topic,
            merge_events_topic = ?merge_events.as_ref().map(|s| s.topic.as_str()),
            "Publisher runs on the validation table set; its topics must be capture topics, never the production names"
        );
    }

    let mut manager = Manager::builder("personhog-publisher").build();
    let publisher_handle = manager.register(
        "publisher",
        ComponentOptions::new().with_graceful_shutdown(config.pass_deadline() + SHUTDOWN_MARGIN),
    );
    // Phase 1: the producer flushes only after the drain loop has stopped,
    // so the last pass's records are in the queue it flushes.
    let kafka_handle = manager.register(
        "kafka-producer",
        ComponentOptions::new()
            .with_graceful_shutdown(PRODUCER_FLUSH_BOUND + SHUTDOWN_MARGIN)
            .with_shutdown_phase(1),
    );
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let monitor = manager.monitor_background();

    // Built before anything records a metric: this call installs the
    // process-wide recorder.
    let metrics_router = setup_metrics_routes(
        Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let r = readiness.clone();
                    async move { r.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() })),
    );
    let metrics_port = config.metrics_port;
    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();
        let bind = format!("0.0.0.0:{metrics_port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, metrics_router)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    let pool = get_pool_with_config(&config.primary_database_url, config.pool_config())
        .expect("Failed to create database pool");

    let producer = match create_kafka_producer(&kafka, kafka_handle.clone()).await {
        Ok(producer) => producer,
        Err(e) => {
            tracing::error!(error = %e, "failed to create Kafka producer");
            return Err(e.into());
        }
    };
    spawn_bounded_flush_on_shutdown(producer.clone(), kafka_handle, PRODUCER_FLUSH_BOUND);

    let sink = KafkaSink::new(
        producer,
        config.person_distinct_id_topic.clone(),
        merge_events.as_ref().map(|s| s.topic.clone()),
        config.produce_timeout(),
    );
    let publisher = Publisher::new(pool, tables, sink, drain_config);
    tokio::spawn(async move {
        let _guard = publisher_handle.process_scope();
        publisher.run(&publisher_handle).await;
    });

    monitor.wait().await?;
    Ok(())
}
