use std::sync::Arc;

use axum::{routing::get, Router};
use common_kafka::kafka_consumer::SingleTopicConsumer;

use futures::future::ready;
use property_defs_rs::{
    api::v1::query::Manager, api::v1::routing::apply_routes, app_context::AppContext,
    config::Config, update_consumer_loop, update_producer_loop,
};

use quick_cache::sync::Cache;
use serve_metrics::{serve, setup_metrics_routes};
use sqlx::postgres::PgPoolOptions;
use tokio::{
    sync::mpsc::{self},
    task::JoinHandle,
};
use tracing::{info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

fn setup_tracing() {
    let log_layer: tracing_subscriber::filter::Filtered<
        tracing_subscriber::fmt::Layer<tracing_subscriber::Registry>,
        EnvFilter,
        tracing_subscriber::Registry,
    > = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "property definitions service"
}

fn start_server(config: &Config, context: Arc<AppContext>) -> JoinHandle<()> {
    let api_ctx = context.clone();

    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(context.liveness.get_status())),
        );
    let router = apply_routes(router, api_ctx);
    let router = setup_metrics_routes(router);

    let bind = format!("{}:{}", config.host, config.port);

    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    })
}

// TODO(eli): idea for v2 batch writes: add an isolated tokio runtime to
// the AppContext just for batch writes that are *always* IO bound, leaving
// the update loop workers without interference. We could tune the v2 write
// runtime's worker_count independently then
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_with_defaults()?;

    let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;

    // owns Postgres client and biz logic that handles property defs API calls
    let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
    let api_pool = options.connect(&config.database_url).await?;
    let query_manager = Manager::new(api_pool).await?;

    let context = Arc::new(AppContext::new(&config, query_manager).await?);

    info!(
        "Subscribed to topic: {}",
        config.consumer.kafka_consumer_topic
    );

    start_server(&config, context.clone());

    let (tx, rx) = mpsc::channel(config.update_batch_size * config.channel_slots_per_worker);

    let cache = Cache::new(config.cache_capacity);

    let cache = Arc::new(cache);

    let mut handles = Vec::new();

    for _ in 0..config.worker_loop_count {
        let handle = tokio::spawn(update_producer_loop(
            config.clone(),
            consumer.clone(),
            tx.clone(),
            cache.clone(),
        ));

        handles.push(handle);
    }

    handles.push(tokio::spawn(update_consumer_loop(
        config.clone(),
        cache,
        context,
        rx,
    )));

    // if any handle returns, abort the other ones, and then return an error
    let (result, _, others) = futures::future::select_all(handles).await;
    warn!(
        "update loop process is shutting down with result: {:?}",
        result
    );

    for handle in others {
        handle.abort();
    }
    Ok(result?)
}
