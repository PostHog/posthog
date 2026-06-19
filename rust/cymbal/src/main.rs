use cymbal::config::Config;
use cymbal::modes::{self, CymbalMode};
use tracing::level_filters::LevelFilter;
use tracing::{error, info};
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

    let service_name = match config.mode {
        CymbalMode::Processing => "cymbal",
        CymbalMode::Resolution => "cymbal-resolution",
    };
    common_posthog::init(
        service_name,
        config.posthog_api_key.as_deref(),
        &config.posthog_endpoint,
    )
    .await
    .unwrap();

    match config.mode {
        CymbalMode::Processing => modes::processing::run(config).await,
        CymbalMode::Resolution => {
            if let Err(e) = modes::resolution::serve(&config).await {
                error!("cymbal-resolution server error: {e}");
                std::process::exit(1);
            }
        }
    }
}
