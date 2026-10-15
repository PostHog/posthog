use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tracing::level_filters::LevelFilter;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter};

use replay_recorder_v4::config::Config;
use replay_recorder_v4::consumer::{create_consumer, run};
use replay_recorder_v4::teams::TeamCache;

common_alloc::used!();

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env().expect("invalid configuration");
    tracing_subscriber::registry()
        .with(fmt::layer().with_target(true).with_level(true))
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();
    tracing::info!(topic = %config.kafka_topic, group = %config.kafka_consumer_group, sample = config.sample_percentage, "starting replay-recorder-v4");

    let mut manager = Manager::builder("replay-recorder-v4")
        .with_global_shutdown_timeout(Duration::from_secs(30))
        .build();
    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(15))
            .with_liveness_deadline(Duration::from_secs(60)),
    );
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let monitor = manager.monitor_background();

    let port = config.metrics_port;
    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();
        let router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let readiness = readiness.clone();
                    async move { readiness.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() }));
        let listener = tokio::net::TcpListener::bind(format!("0.0.0.0:{port}"))
            .await
            .expect("bind metrics port");
        axum::serve(listener, setup_metrics_routes(router))
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("metrics server");
    });

    // The first team list must load before any message is read: an empty list would skip every message as unknown.
    let pool = get_pool_with_config(
        &config.database_url,
        PoolConfig {
            max_connections: 2,
            pool_name: Some("replay-recorder-v4".to_owned()),
            ..Default::default()
        },
    )?;
    let teams = Arc::new(TeamCache::default());
    let loaded = teams.refresh(&pool).await?;
    tracing::info!(teams = loaded, "loaded the team list");
    tokio::spawn(
        teams
            .clone()
            .refresh_every(pool, Duration::from_secs(config.team_refresh_secs)),
    );

    let consumer = create_consumer(
        &config.kafka,
        &config.kafka_consumer_group,
        &config.kafka_consumer_offset_reset,
        &config.kafka_topic,
    )?;
    tokio::spawn(run(
        consumer,
        config.sample_percentage,
        teams,
        consumer_handle,
    ));

    monitor.wait().await?;
    Ok(())
}
