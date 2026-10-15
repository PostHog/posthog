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

use replay_core_v4::keys::batch::KeyStore;
use replay_core_v4::keys::kms::{AwsKms, CachedKms, KmsLimits};
use replay_core_v4::keys::table::{AwsKeyTable, CachedKeyTable};
use replay_recorder_v4::config::Config;
use replay_recorder_v4::consumer::{run, RecorderConsumer, Settings, Writer};
use replay_recorder_v4::store::S3Store;
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
    let teams_handle = manager.register(
        "team-refresh",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
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

    if config.team_refresh_secs == 0 {
        return Err("TEAM_REFRESH_SECS must be over 0".into());
    }
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
    tokio::spawn(teams.clone().refresh_every(
        pool,
        Duration::from_secs(config.team_refresh_secs),
        teams_handle,
    ));

    let consumer = RecorderConsumer::new(
        &config.kafka,
        &config.kafka_consumer_group,
        &config.kafka_consumer_offset_reset,
        &config.kafka_topic,
    )?;
    let settings = Settings {
        sample_percentage: config.sample_percentage,
        flush_interval: Duration::from_millis(config.flush_interval_ms),
        flush_max_bytes: config.flush_max_bytes,
        session_idle: Duration::from_secs(config.session_idle_secs),
    };
    let writer = if config.write_enabled {
        let aws = aws_config::defaults(aws_config::BehaviorVersion::latest())
            .load()
            .await;
        // The cache lifetimes are v3's: a session row's lifetime bounds how late a deletion is seen.
        let table = CachedKeyTable::new(
            AwsKeyTable::new(
                aws_sdk_dynamodb::Client::new(&aws),
                config.key_table.clone(),
            ),
            100_000,
            Duration::from_secs(300),
            Duration::from_secs(3600),
        );
        let kms = CachedKms::new(
            AwsKms::new(
                aws_sdk_kms::Client::new(&aws),
                config.kms_key_arn.clone(),
                KmsLimits::default(),
            ),
            100_000,
            Duration::from_secs(1800),
        );
        Some(Writer {
            keys: KeyStore::new(table, kms),
            store: Arc::new(S3Store::new(aws_sdk_s3::Client::new(&aws))),
            rrweb_bucket: config.rrweb_bucket.clone(),
        })
    } else {
        tracing::info!("writes are off: the recorder stores nothing");
        None
    };
    tokio::spawn(run(consumer, settings, teams, writer, consumer_handle));

    monitor.wait().await?;
    Ok(())
}
