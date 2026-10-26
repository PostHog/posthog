use std::sync::Arc;
use std::time::Duration;

use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_kafka_producer;
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
use replay_recorder_v4::consumer::{run, RecorderConsumer, Settings, Sources};
use replay_recorder_v4::flush::{Writer, PRODUCER_FLUSH_ON_SHUTDOWN};
use replay_recorder_v4::limits::{Restrictions, SessionLimiter};
use replay_recorder_v4::store::S3Store;
use replay_recorder_v4::teams::TeamCache;

common_alloc::used!();

/// The index producer's local queue. A block row is a few KB, so this holds several large flushes.
const INDEX_QUEUE_MIB: u32 = 512;
const INDEX_QUEUE_MESSAGES: u32 = 500_000;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env().expect("invalid configuration");
    config.validate()?;
    tracing_subscriber::registry()
        .with(fmt::layer().with_target(true).with_level(true))
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();
    tracing::info!(topic = %config.kafka_topic, overflow_topic = %config.kafka_overflow_topic, group = %config.kafka_consumer_group, sample = config.sample_percentage, "starting replay-recorder-v4");

    // The consumer flushes the buffer, then the producer, on shutdown.
    let consumer_shutdown =
        Duration::from_secs(config.shutdown_flush_secs + 5) + PRODUCER_FLUSH_ON_SHUTDOWN;
    let mut manager = Manager::builder("replay-recorder-v4")
        .with_global_shutdown_timeout(consumer_shutdown + Duration::from_secs(10))
        .build();
    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(consumer_shutdown)
            .with_liveness_deadline(Duration::from_secs(60)),
    );
    let restrictions_handle = manager.register(
        "event-restrictions",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    // A producer reports itself live from librdkafka's statistics callback.
    let producer_handles = config.write_enabled.then(|| {
        let mut register = |name: &str| {
            manager.register(
                name,
                ComponentOptions::new()
                    .with_graceful_shutdown(Duration::from_secs(5))
                    .with_liveness_deadline(Duration::from_secs(60)),
            )
        };
        (register("image-fetch-producer"), register("index-producer"))
    });
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

    // The first team list must load before any message is read: an empty list would skip every message as unknown.
    let pool = get_pool_with_config(
        &config.database_url,
        PoolConfig {
            max_connections: 2,
            pool_name: Some("replay-recorder-v4".to_owned()),
            ..Default::default()
        },
    )?;
    let teams = Arc::new(TeamCache::new(TeamCache::max_age_for(Duration::from_secs(
        config.team_refresh_secs,
    ))));
    let loaded = tokio::time::timeout(
        replay_recorder_v4::teams::REFRESH_TIMEOUT,
        teams.refresh(&pool),
    )
    .await
    .map_err(|_| "the first team list did not load in time")??;
    tracing::info!(teams = loaded, "loaded the team list");
    tokio::spawn(teams.clone().refresh_every(
        pool,
        Duration::from_secs(config.team_refresh_secs),
        teams_handle,
    ));

    let restrictions = Restrictions::default();
    tokio::spawn(restrictions.clone().refresh_forever(
        config.event_restrictions_redis_url.clone(),
        Duration::from_secs(config.event_restrictions_refresh_secs),
        restrictions_handle,
    ));
    // Before the first load no restriction applies, so nothing is read until it is in.
    if !restrictions.wait_loaded(Duration::from_secs(60)).await {
        return Err("the event ingestion restrictions did not load".into());
    }
    let (capacity, replenish_rate) = config.new_session_bucket();
    let limiter = SessionLimiter::connect(
        config.redis_url.clone(),
        capacity,
        replenish_rate,
        config.new_session_blocking_enabled,
    )
    .await?;

    let consumer = RecorderConsumer::new(
        &config.kafka,
        &config.kafka_consumer_group,
        &config.kafka_consumer_offset_reset,
        &[
            config.kafka_topic.clone(),
            config.kafka_overflow_topic.clone(),
        ],
    )?;
    let settings = Settings {
        sample_percentage: config.sample_percentage,
        flush_interval: Duration::from_millis(config.flush_interval_ms),
        flush_max_bytes: config.flush_max_bytes,
        flush_concurrency: if config.flush_concurrency == 0 {
            std::thread::available_parallelism().map_or(4, |n| n.get())
        } else {
            config.flush_concurrency
        },
        flush_timeout: Duration::from_secs(config.flush_timeout_secs),
        flush_retries: config.flush_retries,
        shutdown_flush: Duration::from_secs(config.shutdown_flush_secs),
        session_idle: Duration::from_secs(config.session_idle_secs),
        session_state_max_bytes: config.session_state_max_bytes,
        redirecting_topic: (config.ingestion_overflow_mode == "redirect")
            .then(|| config.kafka_topic.clone()),
    };
    let writer = if let Some((producer_handle, index_producer_handle)) = producer_handles {
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
            images_bucket: config.images_bucket.clone(),
            producer: create_kafka_producer(
                &KafkaConfig {
                    kafka_compression_codec: "lz4".to_owned(),
                    kafka_message_timeout_ms: config.image_fetch_delivery_timeout_ms,
                    ..config.kafka.clone()
                },
                producer_handle,
            )
            .await?,
            image_fetch_topic: config.image_fetch_topic.clone(),
            index_producer: create_kafka_producer(
                &KafkaConfig {
                    kafka_compression_codec: "lz4".to_owned(),
                    kafka_message_timeout_ms: config.index_delivery_timeout_ms,
                    // Rows of a few flushes, so a slow broker holds them here instead of losing them at once.
                    kafka_producer_queue_mib: INDEX_QUEUE_MIB,
                    kafka_producer_queue_messages: INDEX_QUEUE_MESSAGES,
                    ..config.kafka.clone()
                },
                index_producer_handle,
            )
            .await?,
            index_topic: config.index_topic.clone(),
            sent_urls: replay_recorder_v4::urls::sent_urls(500_000),
            seal_permits: Arc::new(tokio::sync::Semaphore::new(settings.flush_concurrency)),
        })
    } else {
        tracing::info!("writes are off: the recorder stores nothing");
        None
    };
    let sources = Sources {
        teams,
        restrictions,
        limiter,
    };
    tokio::spawn(run(consumer, settings, sources, writer, consumer_handle));

    monitor.wait().await?;
    Ok(())
}
