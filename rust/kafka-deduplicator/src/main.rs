use std::time::Duration;

use anyhow::{Context, Result};
use axum::{routing::get, Router};
use futures::future::ready;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::{Matcher, PrometheusBuilder, PrometheusHandle};
use opentelemetry::{KeyValue, Value};
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::trace::{BatchConfig, RandomIdGenerator, Sampler, Tracer};
use opentelemetry_sdk::{runtime, Resource};
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

/// Setup metrics recorder with optimized histogram buckets for kafka-deduplicator
fn setup_kafka_deduplicator_metrics() -> PrometheusHandle {
    const BUCKETS: &[f64] = &[
        0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0,
    ];
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

    const COUNT_BUCKETS: &[f64] = &[
        1.0, 2.0, 5.0, 10.0, 50.0, 100.0, 500.0, 1000.0, 5000.0, 10000.0,
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
        .set_buckets_for_metric(Matcher::Suffix("unique_uuids".to_string()), COUNT_BUCKETS)
        .unwrap()
        .set_buckets_for_metric(
            Matcher::Suffix("unique_timestamps".to_string()),
            COUNT_BUCKETS,
        )
        .unwrap()
        .install_recorder()
        .unwrap()
}

#[tokio::main]
async fn main() -> Result<()> {
    // Load configuration first to get OTEL settings
    let config = Config::init_with_defaults()
        .context("Failed to load configuration from environment variables. Please check your environment setup.")?;

    // Initialize tracing
    let log_layer = {
        let base = fmt::layer()
            .with_target(true)
            .with_thread_ids(true)
            .with_level(true);

        if config.otel_log_level == tracing::Level::DEBUG {
            base.with_span_events(
                FmtSpan::NEW | FmtSpan::CLOSE | FmtSpan::ENTER | FmtSpan::EXIT | FmtSpan::ACTIVE,
            )
            .with_ansi(true)
            .with_filter(
                EnvFilter::builder()
                    .with_default_directive(LevelFilter::INFO.into())
                    .from_env_lossy()
                    .add_directive("pyroscope=warn".parse().unwrap()),
            )
            .boxed()
        } else {
            base.json()
                .flatten_event(true)
                .with_span_list(true)
                .with_current_span(true)
                .with_filter(
                    EnvFilter::builder()
                        .with_default_directive(LevelFilter::INFO.into())
                        .from_env_lossy()
                        .add_directive("pyroscope=warn".parse().unwrap()),
                )
                .boxed()
        }
    };

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

    let pod = config
        .pod_hostname
        .clone()
        .unwrap_or_else(|| "unknown".to_string());
    let _root_span = tracing::info_span!("service", pod = %pod).entered();

    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            tracing::warn!("Failed to start continuous profiling agent: {e:#}");
            None
        }
    };

    info!("Starting Kafka Deduplicator service");
    info!("Configuration loaded: {:?}", config);

    let mut manager = Manager::builder("kafka-deduplicator")
        .with_global_shutdown_timeout(config.shutdown_timeout())
        .build();

    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(15)),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let shutdown_signal = manager.shutdown_signal();

    let mut service = KafkaDeduplicatorService::new(config.clone(), &mut manager)
        .await
        .with_context(|| "Failed to create Kafka Deduplicator service. Check your Kafka connection and RocksDB configuration.".to_string())?;

    service.initialize(&mut manager).await?;

    let bind = config.bind_address();
    let mut router = Router::new()
        .route("/", get(index))
        .route(
            "/_readiness",
            get({
                let r = readiness.clone();
                move || {
                    let r = r.clone();
                    async move { r.check().await }
                }
            }),
        )
        .route("/_liveness", get(move || async move { liveness.check() }));

    if config.export_prometheus {
        let recorder_handle = setup_kafka_deduplicator_metrics();
        router = router.route("/metrics", get(move || ready(recorder_handle.render())));
    }

    let monitor_guard = manager.monitor_background();

    info!("Started metrics server on {}", bind);

    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("failed to bind metrics port");
        axum::serve(listener, router)
            .with_graceful_shutdown(shutdown_signal)
            .await
            .expect("failed to start serving metrics");
    });

    service.spawn_consumer_task()?;

    monitor_guard.wait().await?;

    Ok(())
}
