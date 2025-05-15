use std::sync::Arc;
use std::time::Duration;

use common_database::get_pool;
use common_kafka::kafka_producer::create_kafka_producer;
use common_redis::RedisClient;
use envconfig::Envconfig;
use health::{HealthHandle, HealthRegistry};
use links::server::serve;
use tokio::signal;
use tracing_subscriber::fmt;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use links::config::Config;
use links::state::State;

common_alloc::used!();

async fn shutdown() {
    let mut term = signal::unix::signal(signal::unix::SignalKind::terminate())
        .expect("failed to register SIGTERM handler");

    let mut interrupt = signal::unix::signal(signal::unix::SignalKind::interrupt())
        .expect("failed to register SIGINT handler");

    tokio::select! {
        _ = term.recv() => {},
        _ = interrupt.recv() => {},
    };

    tracing::info!("Shutting down gracefully...");
}

async fn liveness_loop(handle: HealthHandle) {
    loop {
        handle.report_healthy().await;
        tokio::time::sleep(std::time::Duration::from_secs(10)).await;
    }
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("Invalid configuration:");

    let external_redis_client = match RedisClient::new(config.external_link_redis_url.clone()) {
        Ok(client) => Arc::new(client),
        Err(e) => {
            tracing::error!("Failed to create Redis client: {}", e);
            return;
        }
    };

    let internal_redis_client = match RedisClient::new(config.internal_link_redis_url.clone()) {
        Ok(client) => Arc::new(client),
        Err(e) => {
            tracing::error!("Failed to create Redis client: {}", e);
            return;
        }
    };

    let reader = match get_pool(&config.read_database_url, config.max_pg_connections).await {
        Ok(client) => {
            tracing::info!("Successfully created read Postgres client");
            Arc::new(client)
        }
        Err(e) => {
            tracing::error!(
                error = %e,
                url = %config.read_database_url,
                max_connections = config.max_pg_connections,
                "Failed to create read Postgres client"
            );
            return;
        }
    };

    let health = Arc::new(HealthRegistry::new("liveness"));

    let simple_loop = health
        .register("simple_loop".to_string(), Duration::from_secs(30))
        .await;
    tokio::spawn(liveness_loop(simple_loop));

    let kafka_immediate_liveness = health
        .register(
            "internal_events_producer".to_string(),
            Duration::from_secs(30),
        )
        .await;
    let internal_events_producer = create_kafka_producer(&config.kafka, kafka_immediate_liveness)
        .await
        .unwrap();

    let state = State {
        db_reader_client: reader,
        external_redis_client,
        internal_redis_client,
        internal_events_producer,
        liveness: health,
        default_domain_for_public_store: config.default_domain_for_public_store,
        enable_metrics: config.enable_metrics,
    };

    // Configure logging format:
    //   with_span_events: Log when spans are created/closed
    //   with_target: Include module path (e.g. "feature_flags::api")
    //   with_thread_ids: Include thread ID for concurrent debugging
    //   with_level: Show log level (ERROR, INFO, etc)
    //   with_filter: Use RUST_LOG env var to control verbosity
    let fmt_layer = fmt::layer()
        .with_span_events(
            FmtSpan::NEW | FmtSpan::CLOSE | FmtSpan::ENTER | FmtSpan::EXIT | FmtSpan::ACTIVE,
        )
        .with_target(true)
        .with_thread_ids(true)
        .with_level(true)
        .with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry().with(fmt_layer).init();

    // Open the TCP port and start the server
    let listener = tokio::net::TcpListener::bind(config.address)
        .await
        .expect("could not bind port");
    serve(state, listener, shutdown()).await;
    unreachable!("Server exited unexpectedly");
}
