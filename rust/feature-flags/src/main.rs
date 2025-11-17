use std::time::Duration;

use envconfig::Envconfig;
use opentelemetry::{KeyValue, Value};
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::trace::{BatchConfig, RandomIdGenerator, Sampler, Tracer};
use opentelemetry_sdk::{runtime, Resource};
use tokio::signal;
use tracing::level_filters::LevelFilter;
use tracing_opentelemetry::OpenTelemetryLayer;
use tracing_subscriber::fmt;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use feature_flags::config::Config;
use feature_flags::server::serve;

common_alloc::used!();

async fn shutdown() {
    let mut term = signal::unix::signal(signal::unix::SignalKind::terminate())
        .expect("failed to register SIGTERM handler");

    let mut interrupt = signal::unix::signal(signal::unix::SignalKind::interrupt())
        .expect("failed to register SIGINT handler");

    tokio::select! {
        _ = term.recv() => {},
        _ = interrupt.recv() => {},
    };

    tracing::info!("Shutting down gracefully...");
}

fn init_tracer(
    sink_url: &str,
    sampling_rate: f64,
    service_name: &str,
    export_timeout_secs: u64,
) -> Tracer {
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
                .with_timeout(Duration::from_secs(export_timeout_secs)),
        )
        .install_batch(runtime::Tokio)
        .expect("Failed to initialize OpenTelemetry tracer")
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("Invalid configuration:");

    // Instantiate tracing outputs following Django's DEBUG-based approach:
    //   - stdout with a level configured by the RUST_LOG envvar
    //   - OpenTelemetry if enabled, for levels INFO and higher
    // Read DEBUG environment variable (same as Django)
    let debug: bool = *config.debug;

    let log_layer = {
        let base_layer = fmt::layer()
            .with_target(true)
            .with_thread_ids(true)
            .with_level(true);

        if debug {
            // Development: Pretty colored output (like Django's ConsoleRenderer(colors=DEBUG))
            base_layer
                .with_span_events(
                    FmtSpan::NEW
                        | FmtSpan::CLOSE
                        | FmtSpan::ENTER
                        | FmtSpan::EXIT
                        | FmtSpan::ACTIVE,
                )
                .with_ansi(true)
                .with_filter(EnvFilter::from_default_env())
                .boxed()
        } else {
            // Production: JSON format (like Django's JSONRenderer())
            base_layer
                .json()
                .with_filter(EnvFilter::from_default_env())
                .boxed()
        }
    };

    let otel_layer = if let Some(ref otel_url) = config.otel_url {
        Some(
            OpenTelemetryLayer::new(init_tracer(
                otel_url,
                config.otel_sampling_rate,
                &config.otel_service_name,
                config.otel_export_timeout_secs,
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

    // Open the TCP port and start the server
    let listener = tokio::net::TcpListener::bind(config.address)
        .await
        .expect("could not bind port");
    serve(config, listener, shutdown()).await;
    unreachable!("Server exited unexpectedly");
}
