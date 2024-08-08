use axum::{routing::get, Router};
use common_metrics::setup_metrics_routes;
use cyclotron_janitor::{config::Config, janitor::Janitor};
use envconfig::Envconfig;
use eyre::Result;
use health::{HealthHandle, HealthRegistry};
use std::{future::ready, time::Duration};
use tracing::{error, info};

/// Most of this stuff is stolen pretty shamelessly from the rustyhook janitor. It'll diverge more
/// once we introduce the management command stuff, but for now it's a good starting point.

async fn cleanup_loop(janitor: Janitor, livenes: HealthHandle, interval_secs: u64) -> Result<()> {
    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));

    loop {
        interval.tick().await;

        if let Err(e) = janitor.run_once().await {
            error!("janitor failed cleanup with: {}", e);
            livenes.report_healthy().await;
        } else {
            livenes.report_healthy().await;
        }
    }
}

async fn listen(app: Router, bind: String) -> Result<()> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, app).await?;

    Ok(())
}

pub fn app(liveness: HealthRegistry) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())))
}

pub async fn index() -> &'static str {
    "rusty-hook janitor"
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("failed to load configuration from env");

    let liveness = HealthRegistry::new("liveness");

    let janitor_config = config.get_janitor_config();

    info!("Starting janitor with ID {:?}", janitor_config.settings.id);

    let janitor = Janitor::new(janitor_config)
        .await
        .expect("failed to create janitor");

    let janitor_liveness = liveness
        .register(
            "janitor".to_string(),
            Duration::from_secs(config.cleanup_interval_secs * 4),
        )
        .await;

    let janitor_loop = tokio::spawn(cleanup_loop(
        janitor,
        janitor_liveness,
        config.cleanup_interval_secs,
    ));

    let app = setup_metrics_routes(app(liveness));
    let bind = format!("{}:{}", config.host, config.port);
    let http_server = tokio::spawn(listen(app, bind));

    tokio::select! {
        res = janitor_loop => {
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
