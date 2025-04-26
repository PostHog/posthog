use property_filter::{
    app::{Context, FilterRow},
    config::Config,
    worker::filter_builder,
};

use health::{HealthHandle, HealthRegistry};
use serve_metrics::{serve, setup_metrics_routes};

use axum::{routing::get, Router};
use chrono::Utc;
use envconfig::Envconfig;
use futures::future::ready;
use sqlx::postgres::PgPoolOptions;
use time::Duration;
use tokio::task::JoinHandle;
use tracing::{info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

use std::sync::Arc;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // bootstrap logging infra
    setup_tracing();
    info!("starting filter builder service");

    // build app context
    let config = Config::init_from_env().unwrap();
    let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
    let pool = options
        .connect(&config.database_url)
        .await
        .expect("failed to connect to database");
    let liveness: HealthRegistry = HealthRegistry::new("liveness");
    let worker_liveness: HealthHandle = liveness
        .register("worker".to_string(), Duration::seconds(60))
        .await;
    let ctx = Arc::new(Context {
        config,
        pool,
        liveness,
        worker_liveness,
    });

    // start health, metrics server
    start_server(ctx.clone());

    // start filter builder worker (TODO: parallelize this via chunked table scan)
    let mut handles = Vec::new();

    // TODO(eli): just for demo, construct a synthetic team entry to scan.
    // next up, we'll fetch batches of team IDs to fan out into worker threads
    let team_id = 2;
    let filter_row = FilterRow {
        team_id,
        fwd_bloom: None,
        rev_bloom: None,
        property_count: 0,
        blocked: false,
        last_updated_at: Utc::now(),
    };

    let filter_builder_handle = tokio::spawn(filter_builder(ctx, filter_row));
    handles.push(filter_builder_handle);

    // if any handle returns, abort the other ones, and then return an error
    let (result, _, others) = futures::future::select_all(handles).await;
    warn!("workers shutting down with result: {:?}", result);

    for handle in others {
        handle.abort();
    }
    Ok(result?)
}

async fn index() -> &'static str {
    "property definitions filter builder service"
}

fn start_server(ctx: Arc<Context>) -> JoinHandle<()> {
    let bind = format!("{}:{}", ctx.config.host, ctx.config.port);

    let context = ctx.clone();
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(context.liveness.get_status())),
        );
    let router = setup_metrics_routes(router);

    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    })
}

fn setup_tracing() {
    let log_layer: tracing_subscriber::filter::Filtered<
        tracing_subscriber::fmt::Layer<tracing_subscriber::Registry>,
        EnvFilter,
        tracing_subscriber::Registry,
    > = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    tracing_subscriber::registry().with(log_layer).init();
}
