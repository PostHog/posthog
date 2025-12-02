use std::time::Duration;

use envconfig::Envconfig;
use opentelemetry::{KeyValue, Value};
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::trace::{BatchConfig, RandomIdGenerator, Sampler, Tracer};
use opentelemetry_sdk::{runtime, Resource};
use tokio::signal;
use tracing::level_filters::LevelFilter;
use tracing_opentelemetry::OpenTelemetryLayer;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use capture::config::Config;
use capture::server::serve;

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
        .unwrap()
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("Invalid configuration:");

    // Instantiate tracing outputs:
    //   - stdout with a level configured by the RUST_LOG envvar (default=ERROR)
    //   - OpenTelemetry if enabled, for levels INFO and higher
    let log_layer = tracing_subscriber::fmt::layer().with_filter(EnvFilter::from_default_env());
    let otel_layer = config
        .otel_url
        .clone()
        .map(|url| {
            OpenTelemetryLayer::new(init_tracer(
                &url,
                config.otel_sampling_rate,
                &config.otel_service_name,
            ))
        })
        .with_filter(LevelFilter::from_level(config.log_level));
    tracing_subscriber::registry()
        .with(log_layer)
        .with(otel_layer)
        .init();

    // Open the TCP port and start the server
    let listener = tokio::net::TcpListener::bind(config.address)
        .await
        .expect("could not bind port");
    serve(config, listener, shutdown()).await
}
