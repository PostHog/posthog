use axum::Router;
use envconfig::Envconfig;
use sqlx::postgres::PgPoolOptions;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

use common_metrics::setup_metrics_routes;

use agent_sync::app::{create_router, AppState};
use agent_sync::auth::CachedAuthService;
use agent_sync::config::Config;
use agent_sync::kafka::{run_consumer, KafkaEventPublisher};
use agent_sync::store::ClickHouseLogStore;
use agent_sync::streaming::FanoutRouter;

common_alloc::used!();

async fn listen(app: Router, bind: String) -> std::io::Result<()> {
    let listener = tokio::net::TcpListener::bind(&bind).await?;
    tracing::info!("Listening on {}", bind);
    axum::serve(listener, app).await?;
    Ok(())
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let config = Config::init_from_env().expect("failed to load configuration from env");

    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            tracing::error!("Failed to start continuous profiling agent: {e}");
            None
        }
    };

    let postgres_pool = PgPoolOptions::new()
        .max_connections(config.max_pg_connections)
        .acquire_timeout(Duration::from_secs(10))
        .connect(&config.database_url)
        .await
        .expect("failed to connect to postgres");

    let auth = CachedAuthService::new(
        postgres_pool.clone(),
        Duration::from_secs(config.auth_cache_ttl_secs),
        config.auth_cache_max_size,
    );

    let log_store = ClickHouseLogStore::new(
        &config.clickhouse_host,
        config.clickhouse_http_port,
        &config.clickhouse_database,
        &config.clickhouse_user,
        &config.clickhouse_password,
    );

    let publisher = KafkaEventPublisher::new(&config.kafka.kafka_hosts, &config.kafka_topic)
        .expect("failed to create Kafka producer");

    let router = FanoutRouter::new();

    let state = AppState {
        auth,
        log_store,
        publisher,
        router: router.clone(),
        pg_pool: postgres_pool,
        max_logs_limit: config.max_logs_limit,
        sse_keepalive_secs: config.sse_keepalive_secs,
    };

    let app = create_router(state);
    let app = setup_metrics_routes(app);

    let shutdown = CancellationToken::new();

    let consumer = agent_sync::kafka::consumer::create_consumer(
        &config.kafka.kafka_hosts,
        &config.kafka_consumer_group,
        &config.kafka_topic,
    )
    .expect("failed to create Kafka consumer");

    let consumer_shutdown = shutdown.clone();
    let consumer_router = router;
    tokio::spawn(async move {
        run_consumer(consumer, consumer_router, consumer_shutdown).await;
    });

    if let Err(e) = listen(app, config.bind()).await {
        tracing::error!("Server error: {}", e);
    }

    shutdown.cancel();
}
