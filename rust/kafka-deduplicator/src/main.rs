use std::time::Duration;

use anyhow::{Context, Result};
use axum::{routing::get, Router};
use futures::future::ready;
use health::HealthRegistry;
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder, PrometheusHandle};
use opentelemetry::{KeyValue, Value};
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::trace::{BatchConfig, RandomIdGenerator, Sampler, Tracer};
use opentelemetry_sdk::{runtime, Resource};
use serve_metrics::serve;
use tokio::task::JoinHandle;
use tracing::level_filters::LevelFilter;
use tracing::{error, info};
use tracing_opentelemetry::OpenTelemetryLayer;
use tracing_subscriber::fmt;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use kafka_deduplicator::{
    config::Config,
    service::KafkaDeduplicatorService,
    utils::pprof::{handle_flamegraph, handle_profile},
};

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

/// Setup metrics recorder with optimized histogram buckets for kafka-deduplicator
/// Using fewer buckets to reduce cardinality
fn setup_kafka_deduplicator_metrics() -> PrometheusHandle {
    const BUCKETS: &[f64] = &[0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 100.0, 500.0, 5000.0];
    // similarity scores are all in the range [0.0, 1.0] so we want
    // granular bucket ranges for higher fidelity metrics
    const SIMILARITY_BUCKETS: &[f64] = &[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0];

    const CHECKPOINT_FILE_COUNT_BUCKETS: &[f64] = &[
        1.0, 10.0, 50.0, 100.0, 200.0, 400.0, 600.0, 800.0, 1000.0, 1500.0,
    ];
    const CHECKPOINT_SIZE_BYTES_BUCKETS: &[f64] = &[
        1.0,
        10.0,
        100.0,
        1024.0,
        10.0 * 1024.0,
        100.0 * 1024.0,
        1024.0 * 1024.0,
        10.0 * 1024.0 * 1024.0,
        100.0 * 1024.0 * 1024.0,
        1024.0 * 1024.0 * 1024.0,
        10.0 * 1024.0 * 1024.0 * 1024.0,
        100.0 * 1024.0 * 1024.0 * 1024.0,
    ];

    PrometheusBuilder::new()
        .set_buckets(BUCKETS)
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Suffix("similarity_score".to_string()),
            SIMILARITY_BUCKETS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Suffix("checkpoint_file_count".to_string()),
            CHECKPOINT_FILE_COUNT_BUCKETS,
        )
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Suffix("checkpoint_size_bytes".to_string()),
            CHECKPOINT_SIZE_BYTES_BUCKETS,
        )
        .unwrap()
        .install_recorder()
        .unwrap()
}

fn start_server(config: &Config, liveness: HealthRegistry) -> JoinHandle<()> {
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || async move {
                let status = liveness.get_status();
                if !status.healthy {
                    let unhealthy_components: Vec<String> = status
                        .components
                        .iter()
                        .filter(|(_, component_status)| !component_status.is_healthy())
                        .map(|(name, component_status)| format!("{name}: {component_status:?}"))
                        .collect();
                    error!(
                        "Health check FAILED - unhealthy components: [{}]",
                        unhealthy_components.join(", ")
                    );
                }
                status
            }),
        );

    let router = if config.enable_pprof {
        router
            .route("/pprof/profile", get(handle_profile))
            .route("/pprof/flamegraph", get(handle_flamegraph))
    } else {
        router
    };

    // Don't install metrics unless asked to
    // Installing a global recorder when capture is used as a library (during tests etc)
    // does not work well.
    let router = if config.export_prometheus {
        let recorder_handle = setup_kafka_deduplicator_metrics();
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
        .await
        .with_context(|| "Failed to create Kafka Deduplicator service. Check your Kafka connection and RocksDB configuration.".to_string())?;

    // Run the service (this blocks until shutdown)
    service.run().await?;

    // Clean up metrics server
    server_handle.abort();

    Ok(())
}
