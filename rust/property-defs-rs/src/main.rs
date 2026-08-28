use std::{sync::Arc, time::Duration};

use axum::{response::IntoResponse, routing::get, Router};
use common_kafka::kafka_consumer::SingleTopicConsumer;
use lifecycle::{ComponentOptions, Manager};
use property_defs_rs::{
    api::v1::{query::Manager as QueryManager, routing::apply_routes},
    app_context::AppContext,
    config::Config,
    measuring_channel::measuring_channel,
    metrics_buckets::bucket_overrides,
    metrics_consts::{CHANNEL_CAPACITY, CHANNEL_CAPACITY_TOTAL},
    types::MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS,
    update_cache::Cache,
    update_consumer_loop, update_producer_loop,
};

use common_metrics::setup_metrics_routes_with_overrides;
use sqlx::postgres::PgPoolOptions;
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
    "property definitions service"
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    setup_tracing();
    info!("Starting up property definitions service...");

    let config = Config::init_with_defaults()?;

    // Refuse the "0 disables it" convention: with flooring off, every event's last_seen_at is
    // unique, dedup filters nothing, and the full event stream lands on posthog_eventdefinition
    // as row updates. Failing the deploy is cheaper than that. The upper bound guards the same
    // outcome from the other direction, where the jitter offset outruns the timestamp range.
    if config.eventdef_last_seen_floor_secs <= 0
        || config.eventdef_last_seen_floor_secs > MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS
    {
        return Err(format!(
            "EVENTDEF_LAST_SEEN_FLOOR_SECS must be in 1..={MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS}, got {}: flooring bounds how often event-definition writes are re-issued and must not be disabled",
            config.eventdef_last_seen_floor_secs
        )
        .into());
    }

    // Start continuous profiling if enabled (keep _agent alive for the duration of the program)
    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            warn!("Failed to start continuous profiling agent: {e}");
            None
        }
    };

    // -- Lifecycle manager: signals, health monitoring, coordinated shutdown --
    let mut manager = Manager::builder("property-defs-rs")
        .with_global_shutdown_timeout(Duration::from_secs(60))
        .build();

    let producer_handle = manager.register(
        "producer",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );

    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(Duration::from_secs(60))
            .with_stall_threshold(3),
    );

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;

    // Dedicated PG conn pool for serving propdefs API queries only. The API is mounted but
    // receives no production traffic today, so connect lazily: `connect` would open a connection
    // at startup and hold it idle for a surface nothing calls, and would also make boot depend on
    // Postgres being reachable. The first request pays the connect cost instead.
    let api_pool = PgPoolOptions::new()
        .max_connections(config.max_pg_connections)
        .connect_lazy(&config.database_url)?;
    let query_manager = QueryManager::new(api_pool).await?;

    let context = Arc::new(AppContext::new(&config, query_manager).await?);

    info!(
        "Subscribed to topic: {}",
        config.consumer.kafka_consumer_topic
    );

    let (tx, rx) = measuring_channel(config.update_batch_size * config.channel_slots_per_worker);

    let cache = Cache::new(
        config.eventdefs_cache_capacity,
        config.eventprops_cache_capacity,
        config.propdefs_cache_capacity,
    );

    let cache = Arc::new(cache);

    // Start the lifecycle monitor before spawning components
    let guard = manager.monitor_background();

    // Spawn N producer loops (Kafka consumers -> channel)
    for _ in 0..config.worker_loop_count {
        let h = producer_handle.clone();
        tokio::spawn(update_producer_loop(
            config.clone(),
            consumer.clone(),
            cache.clone(),
            tx.clone(),
            h,
        ));
    }
    drop(producer_handle);

    // Publish the tx capacity metrics every 10 seconds. Both are needed to read occupancy:
    // `capacity()` is remaining slots, `max_capacity()` is the channel size.
    tokio::spawn({
        let tx = tx.clone();
        async move {
            loop {
                tokio::time::sleep(Duration::from_secs(10)).await;
                metrics::gauge!(CHANNEL_CAPACITY).set(tx.capacity() as f64);
                metrics::gauge!(CHANNEL_CAPACITY_TOTAL).set(tx.max_capacity() as f64);
            }
        }
    });
    drop(tx);

    // Spawn the consumer loop (channel -> DB)
    tokio::spawn(update_consumer_loop(
        config.clone(),
        cache,
        context.clone(),
        rx,
        consumer_handle,
    ));

    // Build HTTP server with lifecycle readiness/liveness
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
    let app = apply_routes(app, context);
    let app = setup_metrics_routes_with_overrides(app, &bucket_overrides());

    let bind = format!("{}:{}", config.host, config.port);
    info!(address = %bind, "HTTP server starting");
    let listener = TcpListener::bind(&bind).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await?;
    metrics_handle.work_completed();

    guard.wait().await?;

    info!("property-defs-rs stopped");
    Ok(())
}
