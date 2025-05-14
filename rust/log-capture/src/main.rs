use std::future::ready;

use axum::{routing::get, Router};
use common_metrics::{serve, setup_metrics_routes};
use log_capture::config::Config;

use health::HealthRegistry;
use tokio::task::JoinHandle;
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
    "log hog hogs logs

.|||||||||.
|||||||||||||  gimme your logs (to /logs)
|||||||||||' .\
`||||||||||_,__o
"
}

fn start_health_liveness_server(
    config: &Config,
    health_registry: HealthRegistry,
) -> JoinHandle<()> {
    let config = config.clone();
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(health_registry.get_status())),
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
async fn main() {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_with_defaults().unwrap();

    match &config.posthog_api_key {
        Some(key) => {
            let ph_config = posthog_rs::ClientOptionsBuilder::default()
                .api_key(key.clone())
                .api_endpoint(config.posthog_endpoint.clone())
                .build()
                .unwrap();
            posthog_rs::init_global(ph_config).await.unwrap();
            info!("Posthog client initialized");
        }
        None => {
            posthog_rs::disable_global();
            warn!("Posthog client disabled");
        }
    }

    let health_registry = HealthRegistry::new("liveness");
    start_health_liveness_server(&config, health_registry);
}
