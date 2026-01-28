use std::sync::Arc;

use cymbal::consumer::start_consumer;
use cymbal::{app_context::AppContext, config::Config, server::start_server};
use tracing::level_filters::LevelFilter;
use tracing::{error, info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

common_alloc::used!();

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer().with_filter(
        EnvFilter::builder()
            .with_default_directive(LevelFilter::INFO.into())
            .from_env_lossy()
            .add_directive("pyroscope=warn".parse().unwrap()),
    );
    tracing_subscriber::registry().with(log_layer).init();
}

#[tokio::main]
async fn main() {
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("Failed to install rustls crypto provider");

    setup_tracing();
    info!("Starting up...");

    let config = Config::init_with_defaults().unwrap();

    // Start continuous profiling if enabled (keep _agent alive for the duration of the program)
    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            error!("Failed to start continuous profiling agent: {e}");
            None
        }
    };

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

    let context = Arc::new(AppContext::from_config(&config).await.unwrap());

    tokio::join!(
        start_server(config.clone(), context.clone()),
        start_consumer(&config, context.clone())
    );
}
