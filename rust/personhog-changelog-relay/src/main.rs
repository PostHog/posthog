use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use axum::{routing::get, Router};
use common_kafka::kafka_producer::{create_kafka_producer, spawn_bounded_flush_on_shutdown};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use metrics::counter;
use personhog_coordination::changelog::{load_changelog_config, CHANGELOG_BOOT_POLL_INTERVAL};
use personhog_coordination::follow::{follow_changelog, ChangelogSubscription, Follower, Reporter};
use personhog_coordination::store::PersonhogStore;
use tokio_util::sync::CancellationToken;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter};

use personhog_changelog_relay::config::Config;
use personhog_changelog_relay::consumer::{
    base_client_config, consumer_client_config, ChangelogConsumer,
};
use personhog_changelog_relay::relay::Relay;

common_alloc::used!();

const PRODUCER_FLUSH_BOUND: Duration = Duration::from_secs(10);

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env().expect("Invalid configuration");
    tracing_subscriber::registry()
        .with(fmt::layer().with_target(true).with_level(true))
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();
    tracing::info!(
        group = %config.kafka_consumer_group,
        output_topic = %config.output_topic,
        dlq_topic = %config.dlq_topic,
        "starting personhog-changelog-relay"
    );

    let mut manager = Manager::builder("personhog-changelog-relay")
        .with_global_shutdown_timeout(Duration::from_secs(30))
        .build();
    let relay_handle = manager.register(
        "relay",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(15))
            .with_liveness_deadline(Duration::from_secs(30)),
    );
    // Phase 1: the producer flushes only after the relay loop has stopped.
    let producer_handle = manager.register(
        "kafka-producer",
        ComponentOptions::new()
            .with_graceful_shutdown(PRODUCER_FLUSH_BOUND + Duration::from_secs(2))
            .with_shutdown_phase(1),
    );
    let changelog_handle = manager.register("changelog-config", ComponentOptions::new());
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let monitor = manager.monitor_background();

    // Installs the process-wide recorder, so it precedes every metric.
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
        let listener = tokio::net::TcpListener::bind(format!("0.0.0.0:{metrics_port}"))
            .await
            .expect("Failed to bind metrics port");
        axum::serve(listener, metrics_router)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    let store = EtcdStore::connect(StoreConfig {
        endpoints: config.etcd_endpoint_list(),
        prefix: config.etcd_prefix.clone(),
    })
    .await?;
    let store = Arc::new(PersonhogStore::new(store));
    let loaded = load_changelog_config(&store, CHANGELOG_BOOT_POLL_INTERVAL).await?;
    // Retire waits only on the groups the config lists, so relaying under any
    // other group could see a generation deleted before it is read.
    if !loaded.retire_groups.contains(&config.kafka_consumer_group) {
        return Err(format!(
            "config/changelog's retire_groups {:?} do not include KAFKA_CONSUMER_GROUP {}; add it from the control plane first",
            loaded.retire_groups, config.kafka_consumer_group
        )
        .into());
    }
    // Oldest undrained generation first, so a restart mid-drain resumes it.
    let mut follower = Follower::default();
    let topic = follower
        .select_topic(&loaded, |topic| drained(&config, topic))
        .await?;
    let consumer = Arc::new(ChangelogConsumer::new(
        &consumer_client_config(&config.kafka, &config.kafka_consumer_group),
        topic.clone(),
    )?);
    consumer.set_draining(topic != loaded.topic);
    tracing::info!(topic = %topic, draining = consumer.is_draining(), "subscribed to the changelog");

    let producer = create_kafka_producer(&config.output_kafka(), producer_handle.clone()).await?;
    spawn_bounded_flush_on_shutdown(producer.clone(), producer_handle, PRODUCER_FLUSH_BOUND);

    {
        let consumer = Arc::clone(&consumer);
        let config = config.clone();
        tokio::spawn(async move {
            let _guard = changelog_handle.process_scope();
            let cancel = CancellationToken::new();
            let follow = follow_changelog(
                store,
                loaded,
                follower,
                consumer,
                |topic: String| drained(&config, topic),
                Reporter::for_group(&config.kafka_consumer_group),
                |_, _| counter!("personhog_changelog_relay_resubscriptions_total").increment(1),
                cancel.clone(),
            );
            tokio::select! {
                _ = changelog_handle.shutdown_signal() => cancel.cancel(),
                _ = follow => {}
            }
        });
    }

    let relay = Relay::new(
        consumer,
        producer,
        config.output_topic.clone(),
        config.dlq_topic.clone(),
        config.batch_size,
        config.batch_timeout(),
    );
    tokio::spawn(async move {
        let _guard = relay_handle.process_scope();
        relay.run(&relay_handle).await;
    });

    monitor.wait().await?;
    Ok(())
}

/// Whether the relay's group has read every partition of `topic` to its end.
async fn drained(config: &Config, topic: String) -> Result<bool, String> {
    let base = base_client_config(&config.kafka);
    let group = config.kafka_consumer_group.clone();
    tokio::task::spawn_blocking(move || {
        common_kafka::probe::group_drained(&base, &group, &topic, Duration::from_secs(10))
    })
    .await
    .map_err(|e| format!("drain probe join: {e}"))?
    .map_err(|e| format!("drain probe: {e}"))
}
