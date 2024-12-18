use std::{future::ready, sync::Arc, time::Duration};

use anyhow::Error;
use axum::{routing::get, Router};
use batch_import_worker::{
    config::Config,
    context::AppContext,
    job::{model::JobModel, Job},
};
use common_metrics::{serve, setup_metrics_routes};
use envconfig::Envconfig;
use tokio::task::JoinHandle;
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
    "batch import worker"
}

fn start_health_liveness_server(config: &Config, context: Arc<AppContext>) -> JoinHandle<()> {
    let config = config.clone();
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(context.health_registry.get_status())),
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
pub async fn main() -> Result<(), Error> {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_from_env().unwrap();
    let context = Arc::new(AppContext::new(&config).await.unwrap());

    start_health_liveness_server(&config, context.clone());

    loop {
        let Some(model) = JobModel::claim_next_job(context.clone()).await? else {
            info!("No available job found, sleeping");
            tokio::time::sleep(Duration::from_secs(5)).await;
            continue;
        };

        let mut next_step = Some(Job::new(model, context.clone()).await?);
        while let Some(job) = next_step {
            next_step = job.process_next_chunk().await?;
            info!("Processed chunk, starting on next one");
        }
        info!("Job completed, waiting for next job");
    }
}
