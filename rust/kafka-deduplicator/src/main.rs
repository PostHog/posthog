use std::time::Duration;

use anyhow::{Context, Result};
use axum::{routing::get, Router};
use futures::future::ready;
use health::HealthRegistry;
use opentelemetry::{KeyValue, Value};
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::trace::{BatchConfig, RandomIdGenerator, Sampler, Tracer};
use opentelemetry_sdk::{runtime, Resource};
use serve_metrics::{serve, setup_metrics_recorder};
use tokio::task::JoinHandle;
use tracing::info;
use tracing::level_filters::LevelFilter;
use tracing_opentelemetry::OpenTelemetryLayer;
use tracing_subscriber::fmt;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use kafka_deduplicator::{config::Config, service::KafkaDeduplicatorService};

common_alloc::used!();

fn init_tracer(sink_url: &str, sampling_rate: f64, service_name: &str) -> Tracer {
    opentelemetry_otlp::new_pipeline()
        .tracing()
        .with_trace_config(
            opentelemetry_sdk::trace::Config::default()
                .with_sampler(Sampler::ParentBased(Box::new(Sampler::TraceIdRatioBased(
                    sampling_rate,
                ))))
                .with_id_generator(RandomIdGenerator::default())
                .with_resource(Resource::new(vec![KeyValue::new(
                    "service.name",
                    Value::from(service_name.to_string()),
                )])),
        )
        .with_batch_config(BatchConfig::default())
        .with_exporter(
            opentelemetry_otlp::new_exporter()
                .tonic()
                .with_endpoint(sink_url)
                .with_timeout(Duration::from_secs(3)),
        )
        .install_batch(runtime::Tokio)
        .expect("Failed to initialize OpenTelemetry tracer")
}

pub async fn index() -> &'static str {
    "kafka deduplicator service"
}

fn start_server(config: &Config, liveness: HealthRegistry) -> JoinHandle<()> {
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())));

    // Don't install metrics unless asked to
    // Installing a global recorder when capture is used as a library (during tests etc)
    // does not work well.
    let router = if config.export_prometheus {
        let recorder_handle = setup_metrics_recorder();
        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    };

    let bind = config.bind_address();

    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    })
}

#[tokio::main]
async fn main() -> Result<()> {
    // Load configuration first to get OTEL settings
    let config = Config::init_with_defaults()
        .context("Failed to load configuration from environment variables. Please check your environment setup.")?;

    // Initialize tracing with structured output similar to feature-flags
    let log_layer = fmt::layer()
        .with_span_events(
            FmtSpan::NEW | FmtSpan::CLOSE | FmtSpan::ENTER | FmtSpan::EXIT | FmtSpan::ACTIVE,
        )
        .with_target(true)
        .with_thread_ids(true)
        .with_level(true)
        .with_ansi(false)
        .with_filter(EnvFilter::from_default_env());

    // OpenTelemetry layer if configured
    let otel_layer = if let Some(ref otel_url) = config.otel_url {
        Some(
            OpenTelemetryLayer::new(init_tracer(
                otel_url,
                config.otel_sampling_rate,
                &config.otel_service_name,
            ))
            .with_filter(LevelFilter::from_level(config.otel_log_level)),
        )
    } else {
        None
    };

    tracing_subscriber::registry()
        .with(log_layer)
        .with(otel_layer)
        .init();

    info!("Starting Kafka Deduplicator service");

    info!("Configuration loaded: {:?}", config);

    // Create health registry for liveness checks
    let liveness = HealthRegistry::new("liveness");

    // Start HTTP server with metrics endpoint
    let server_handle = start_server(&config, liveness.clone());
    info!("Started metrics server on {}", config.bind_address());

    // Create and run the service
    let service = KafkaDeduplicatorService::new(config, liveness)
        .with_context(|| "Failed to create Kafka Deduplicator service. Check your Kafka connection and RocksDB configuration.".to_string())?;

    // Run the service (this blocks until shutdown)
    service.run().await?;

    // Clean up metrics server
    server_handle.abort();

    Ok(())
}
