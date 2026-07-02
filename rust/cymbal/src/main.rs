use cymbal::modes::notifications::NotificationsConfig;
use cymbal::modes::processing::ProcessingConfig;
use cymbal::modes::resolution::ResolutionConfig;
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

/// Read `CYMBAL_MODE` without parsing any mode-specific config, so each mode can
/// own and parse its own config below.
fn read_mode() -> CymbalMode {
    std::env::var("CYMBAL_MODE")
        .ok()
        .map(|s| s.parse().expect("invalid CYMBAL_MODE"))
        .unwrap_or_default()
}

#[tokio::main]
async fn main() {
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("Failed to install rustls crypto provider");

    setup_tracing();
    info!("Starting up...");

    match read_mode() {
        CymbalMode::Processing => {
            let config = ProcessingConfig::init_with_defaults().unwrap();
            let _profiling_agent = start_profiling(&config.continuous_profiling);
            init_posthog("cymbal", &config.posthog_api_key, &config.posthog_endpoint).await;
            modes::processing::run(config).await;
        }
        CymbalMode::Resolution => {
            let config = ResolutionConfig::init_with_defaults().unwrap();
            let _profiling_agent = start_profiling(&config.continuous_profiling);
            init_posthog(
                "cymbal-resolution",
                &config.posthog_api_key,
                &config.posthog_endpoint,
            )
            .await;
            if let Err(e) = modes::resolution::serve(&config.resolver, &config.service).await {
                error!("cymbal-resolution server error: {e}");
                std::process::exit(1);
            }
        }
        CymbalMode::Notifications => {
            let config = NotificationsConfig::init_with_defaults().unwrap();
            let _profiling_agent = start_profiling(&config.continuous_profiling);
            init_posthog(
                "cymbal-notifications",
                &config.posthog_api_key,
                &config.posthog_endpoint,
            )
            .await;
            modes::notifications::run(config).await;
        }
    }
}

// Keep the returned agent alive for the duration of the program.
fn start_profiling(
    config: &common_continuous_profiling::ContinuousProfilingConfig,
) -> Option<impl Sized> {
    match config.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            error!("Failed to start continuous profiling agent: {e}");
            None
        }
    }
}

async fn init_posthog(service_name: &'static str, api_key: &Option<String>, endpoint: &str) {
    common_posthog::init(service_name, api_key.as_deref(), endpoint)
        .await
        .unwrap();
}
