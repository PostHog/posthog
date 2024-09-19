use axum::{extract::State, routing::get, Router};
use common_metrics::setup_metrics_routes;
use cyclotron_fetch::{
    config::Config,
    context::AppContext,
    fetch::{tick, FetchError},
};
use envconfig::Envconfig;
use health::HealthRegistry;
use std::{future::ready, sync::Arc};
use tracing::{error, info};

common_alloc::used!();

async fn listen(app: Router, bind: String) -> Result<(), std::io::Error> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, app).await?;

    Ok(())
}

// For axums state stuff
#[derive(Clone)]
struct WorkerId(pub String);

pub fn app(liveness: HealthRegistry, worker_id: String) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())))
        .with_state(WorkerId(worker_id))
}

async fn index(State(worker_id): State<WorkerId>) -> String {
    format!("cyclotron janitor {}", worker_id.0)
}

async fn worker_loop(context: AppContext) -> Result<(), FetchError> {
    let context = Arc::new(context);
    loop {
        context.liveness.report_healthy().await;
        let started = tick(context.clone()).await?;
        info!("started {} jobs", started);
        // This will happen if 1) there are no jobs or 2) we have no capacity to start new jobs. Either way, we should sleep for a bit
        if started == 0 {
            tokio::time::sleep(context.config.job_poll_interval.to_std().unwrap()).await;
        }
    }
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("failed to load configuration from env");
    tracing_subscriber::fmt::init();

    let liveness = HealthRegistry::new("liveness");

    let (app_config, pool_config, kafka_config, worker_config) = config.to_components();
    let bind = format!("{}:{}", app_config.host, app_config.port);

    info!(
        "Fetch worker starting with ID {:?}, listening at {}",
        app_config.worker_id, bind
    );

    let worker_liveness = liveness
        .register(
            "worker".to_string(),
            (app_config.job_poll_interval * 4).to_std().unwrap(),
        )
        .await
        .expect("failed to register job poller");

    let kafka_liveness = liveness
        .register("rdkafka".to_string(), time::Duration::seconds(30))
        .await
        .expect("failed to register kafka liveness");

    let app = setup_metrics_routes(app(liveness, app_config.worker_id.clone()));

    let context = AppContext::create(
        app_config,
        pool_config,
        kafka_config,
        worker_config,
        worker_liveness,
        kafka_liveness,
    )
    .await
    .expect("failed to create app context");

    context.worker.run_migrations().await;

    let http_server = tokio::spawn(listen(app, bind));

    let worker_loop = tokio::spawn(worker_loop(context));

    tokio::select! {
        res = worker_loop => {
            error!("janitor loop exited");
            if let Err(e) = res {
                error!("janitor failed with: {}", e)
            }
        }
        res = http_server => {
            error!("http server exited");
            if let Err(e) = res {
                error!("server failed with: {}", e)
            }
        }
    }

    info!("exiting");
}
