use std::{
    future::ready,
    sync::{atomic::Ordering, Arc},
    time::Duration,
};

use anyhow::Error;
use axum::{routing::get, Router};
use batch_import_worker::{
    config::Config,
    context::AppContext,
    error::get_user_message,
    job::{model::JobModel, Job},
    spawn_liveness_loop,
};
use common_metrics::{serve, setup_metrics_routes};
use envconfig::Envconfig;

use tokio::task::JoinHandle;
use tracing::{error, info};
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

    context.clone().spawn_shutdown_listener();

    start_health_liveness_server(&config, context.clone());

    let liveness = context.worker_liveness.clone();

    while context.is_running() {
        liveness.report_healthy().await;
        info!("Looking for next job");
        let Some(mut model) = JobModel::claim_next_job(context.clone()).await? else {
            if !context.is_running() {
                break;
            }
            info!("No available job found, sleeping");
            tokio::time::sleep(Duration::from_secs(5)).await;
            continue;
        };

        info!("Claimed job: {:?}", model.id);

        let init_liveness_run = spawn_liveness_loop(liveness.clone());

        let mut next_step = match Job::new(model.clone(), context.clone()).await {
            Ok(job) => Some(job),
            Err(e) => {
                let error_msg = format!("Job initialization failed for job {}: {:?}", model.id, e);
                error!("{}", error_msg);
                // A developer can tag an error with a user facing message, which we'll surface to the user
                // via the display_status_message field on the job model
                let user_facing_error_message = get_user_message(&e);
                if let Err(pause_err) = model
                    .pause(
                        context.clone(),
                        error_msg,
                        Some(user_facing_error_message.to_string()),
                    )
                    .await
                {
                    error!(
                        "Failed to pause job after initialization error: {:?}",
                        pause_err
                    );
                }
                init_liveness_run.store(false, Ordering::Relaxed);
                continue;
            }
        };
        init_liveness_run.store(false, Ordering::Relaxed);

        while let Some(job) = next_step {
            liveness.report_healthy().await;
            if !context.is_running() {
                info!("Shutting down, dropping job");
                // if we're shutting down, we just drop the job - it'll remain leased for a few minutes, then another
                // worker will come along and pick it up
                break;
            }
            next_step = match job.process().await {
                Ok(next) => next,
                Err(e) => {
                    // process_next_chunk is written such that if an error occurs that should
                    // prevent the job from being picked up by a subsequent worker (which generally
                    // means an error in chunk commits to the jobs sink), the job will be in a paused
                    // state. This is why, in the event of an error, we don't try to set the job model
                    // state in PG - the job itself handles all of that.
                    error!("Error processing job: {:?}, dropping", e);
                    None
                }
            };
        }
    }

    info!("Shutting down");

    Ok(())
}
