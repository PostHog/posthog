use std::time::Duration;

use envconfig::Envconfig;
use lifecycle::Manager;
use opentelemetry::{KeyValue, Value};
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::trace::{BatchConfig, RandomIdGenerator, Sampler, Tracer};
use opentelemetry_sdk::{runtime, Resource};
use tracing::level_filters::LevelFilter;
use tracing_opentelemetry::OpenTelemetryLayer;
use tracing_subscriber::fmt::format::FmtSpan;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Layer};

use capture::config::Config;
use capture::server::serve;

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
        .unwrap()
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("Invalid configuration:");

    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            eprintln!("Failed to start continuous profiling agent: {e:#}");
            None
        }
    };

    let log_layer = {
        let base = tracing_subscriber::fmt::layer()
            .with_target(true)
            .with_thread_ids(true)
            .with_level(true);

        if config.log_level == tracing::Level::DEBUG {
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
            // Production: JSON format so Loki/Grafana can extract useful filter tags
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

    // Root span with pod hostname for Loki/Grafana filtering
    let pod = std::env::var("HOSTNAME").unwrap_or_else(|_| "unknown".to_string());
    let _root_span = tracing::info_span!("service", pod = %pod).entered();

    let manager = Manager::builder("capture")
        .with_trap_signals(true)
        .with_prestop_check(true)
        .build();

    let listener = tokio::net::TcpListener::bind(config.address)
        .await
        .expect("could not bind port");

    serve(config, listener, manager).await;
}
