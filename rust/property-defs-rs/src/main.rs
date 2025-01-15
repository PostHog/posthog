use std::sync::Arc;

use axum::{routing::get, Router};
use common_kafka::kafka_consumer::SingleTopicConsumer;

use futures::future::ready;
use property_defs_rs::{
    app_context::AppContext, config::Config, update_consumer_loop, update_producer_loop,
};

use quick_cache::sync::Cache;
use serve_metrics::{serve, setup_metrics_routes};
use tokio::{
    sync::mpsc::{self},
    task::JoinHandle,
};
use tracing::info;
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

fn start_health_liveness_server(config: &Config, context: Arc<AppContext>) -> JoinHandle<()> {
    let config = config.clone();
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(context.liveness.get_status())),
        );
    let router = setup_metrics_routes(router);
    let bind = format!("{}:{}", config.host, config.port);
    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    })
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_with_defaults()?;

    let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())?;

    let context = Arc::new(AppContext::new(&config).await?);

    info!(
        "Subscribed to topic: {}",
        config.consumer.kafka_consumer_topic
    );

    start_health_liveness_server(&config, context.clone());

    let (tx, rx) = mpsc::channel(config.update_batch_size * config.channel_slots_per_worker);

    let cache = Cache::new(config.cache_capacity);

    let cache = Arc::new(cache);

    let mut handles = Vec::new();

    for _ in 0..config.worker_loop_count {
        let handle = tokio::spawn(update_producer_loop(
            consumer.clone(),
            tx.clone(),
            cache.clone(),
            config.update_count_skip_threshold,
            config.compaction_batch_size,
            config.filter_mode.clone(),
            config.filtered_teams.clone(),
        ));

        handles.push(handle);
    }

    handles.push(tokio::spawn(update_consumer_loop(
        config, cache, context, rx,
    )));

    // if any handle returns, abort the other ones, and then return an error
    let (result, _, others) = futures::future::select_all(handles).await;

    for handle in others {
        handle.abort();
    }
    Ok(result?)
}
