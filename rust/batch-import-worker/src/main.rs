use std::{sync::Arc, time::Duration};

use anyhow::Error;
use axum::{routing::get, Router};
use batch_import_worker::{
    config::Config,
    context::AppContext,
    error::get_user_message,
    job::{model::JobModel, Job},
};
use common_metrics::setup_metrics_routes;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};

use tracing::level_filters::LevelFilter;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

const MAX_CONSECUTIVE_CLAIM_FAILURES: u32 = 10;

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy()
            .add_directive("pyroscope=warn".parse().unwrap())
            .add_directive("rdkafka=warn".parse().unwrap()),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "batch import worker"
}

#[tokio::main]
pub async fn main() -> Result<(), Error> {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_from_env().unwrap();

    // Start continuous profiling if enabled (keep _agent alive for the duration of the program)
    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            error!("Failed to start continuous profiling agent: {e}");
            None
        }
    };

    let context = Arc::new(AppContext::new(&config).await.unwrap());

    let mut manager = Manager::builder("batch-import-worker").build();

    let job_handle = manager.register(
        "job-loop",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let monitor = manager.monitor_background();

    // Metrics/health HTTP server (observability handle -- stays alive during standard drain)
    let bind = format!("{}:{}", config.host, config.port);
    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();

        let health_router = Router::new()
            .route("/", get(index))
            .route(
                "/_readiness",
                get(move || {
                    let r = readiness.clone();
                    async move { r.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() }));
        let router = setup_metrics_routes(health_router);

        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        info!("Metrics server listening on {}", bind);
        axum::serve(listener, router)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    // Job processing loop runs inline (not spawned) because Job::process() holds
    // tracing format args across .await points, making its future !Send.
    // The lifecycle monitor runs on a background OS thread and handles signals.
    {
        let _guard = job_handle.process_scope();
        let mut consecutive_claim_failures: u32 = 0;

        while !job_handle.is_shutting_down() {
            let claim_result = JobModel::claim_next_job(context.clone()).await;

            let claimed = match claim_result {
                Ok(model) => {
                    consecutive_claim_failures = 0;
                    model
                }
                Err(e) => {
                    consecutive_claim_failures += 1;
                    if consecutive_claim_failures >= MAX_CONSECUTIVE_CLAIM_FAILURES {
                        error!(
                            "Failed to claim next job ({consecutive_claim_failures} consecutive failures), triggering shutdown: {e:?}"
                        );
                        job_handle.signal_failure(format!("Failed to claim next job: {e}"));
                    } else {
                        error!(
                            "Failed to claim next job (attempt {consecutive_claim_failures}/{MAX_CONSECUTIVE_CLAIM_FAILURES}): {e:?}"
                        );
                    }
                    None
                }
            };

            let Some(mut model) = claimed else {
                if job_handle.is_shutting_down() {
                    break;
                }
                tokio::select! {
                    _ = tokio::time::sleep(Duration::from_secs(5)) => {},
                    _ = job_handle.shutdown_recv() => break,
                }
                continue;
            };

            info!("Claimed job: {:?}", model.id);

            let mut next_step =
                match Job::new(model.clone(), context.clone(), job_handle.clone()).await {
                    Ok(job) => Some(job),
                    Err(e) => {
                        let error_msg =
                            format!("Job initialization failed for job {}: {:?}", model.id, e);
                        error!("{}", error_msg);
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
                        continue;
                    }
                };

            while let Some(job) = next_step {
                if job_handle.is_shutting_down() {
                    info!("Shutting down, dropping job");
                    // The job remains leased for a few minutes, then another worker picks it up
                    break;
                }
                next_step = match job.process().await {
                    Ok(next) => next,
                    Err(e) => {
                        // If an error occurs that should prevent the job from being picked up by
                        // a subsequent worker, the job will already be in a paused state. We don't
                        // try to set the job model state in PG here -- the job handles that itself.
                        error!("Error processing job: {:?}, dropping", e);
                        None
                    }
                };
            }
        }

        info!("Shutting down");
    }
    // _guard dropped here during shutdown → signals completion to monitor

    monitor.wait().await?;

    Ok(())
}
