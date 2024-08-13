use axum::{extract::State, routing::get, Router};
use common_metrics::setup_metrics_routes;
use cyclotron_fetch::{config::Config, fetch::FetchError};
use envconfig::Envconfig;
use health::{HealthHandle, HealthRegistry};
use std::{future::ready, time::Duration};
use tracing::{error, info};

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

async fn worker_loop(worker_liveness: HealthHandle) -> Result<(), FetchError> {
    todo!()
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("failed to load configuration from env");
    tracing_subscriber::fmt::init();

    let liveness = HealthRegistry::new("liveness");

    let worker_id = config.get_id();
    let bind = format!("{}:{}", config.host, config.port);

    info!(
        "Fetch worker starting with ID {:?}, listening at {}",
        worker_id, bind
    );

    let worker_liveness = liveness
        .register(
            "worker".to_string(),
            Duration::from_secs(config.cleanup_interval_secs * 4),
        )
        .await;

    let app = setup_metrics_routes(app(liveness, worker_id));

    let http_server = tokio::spawn(listen(app, bind));
    let worker_loop = tokio::spawn(worker_loop(worker_liveness));

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
