//! OTLP and Prometheus remote-write metrics capture. This binary serves only
//! the metrics routes of `capture-logs`, so metrics traffic can scale and
//! deploy on its own. All handlers, config, and the Kafka sink come from the
//! `capture-logs` library.

use std::sync::Arc;
use std::time::Duration;

use axum::{extract::DefaultBodyLimit, http::Method, routing::get, routing::post, Router};
use capture::metrics_middleware::track_metrics;
use capture_apm_metrics::config::Config;
use capture_apm_metrics::prometheus;
use capture_apm_metrics::series_label_gate::{spawn_redis_writer, SeriesLabelGate};
use capture_apm_metrics::service::{export_metrics_http, MetricsService};
use capture_logs::authorizer::Authorizer;
use capture_logs::kafka::KafkaSink;
use capture_logs::middleware::translate_compression_query_param;
use capture_logs::service::options_handler;
use common_metrics::setup_metrics_routes;
use common_redis::{Client, CompressionConfig, RedisClient, RedisValueFormat};
use std::future::ready;
use std::net::SocketAddr;

use health::HealthRegistry;
use tokio::signal;
use tower_http::cors::{AllowHeaders, AllowOrigin, CorsLayer};
use tower_http::decompression::RequestDecompressionLayer;
use tracing::level_filters::LevelFilter;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter, Layer};

use limiters::token_dropper::TokenDropper;

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

fn setup_tracing() {
    let log_layer = tracing_subscriber::fmt::layer()
        .json()
        .with_span_list(false)
        .with_filter(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy()
                .add_directive("pyroscope=warn".parse().unwrap()),
        );
    tracing_subscriber::registry().with(log_layer).init();
}

pub async fn index() -> &'static str {
    "metric hog hogs metrics

.|||||||||.
|||||||||||||  gimme ur metrics 📈
|||||||||||' .\\
`||||||||||_,__o
"
}

/// Build the series label gate and, when Redis is configured, its background
/// tasks. The Redis client is optional on purpose: without it the gate still
/// dedupes labels within this pod.
async fn start_series_label_gate(config: &Config) -> Arc<SeriesLabelGate> {
    let window = Duration::from_secs(config.metrics_series_label_interval_secs);
    let enabled = config.metrics_series_label_gate_enabled;
    info!(
        "Series label gate {} (window {}s)",
        if enabled {
            "enabled"
        } else {
            "in dry-run mode"
        },
        window.as_secs()
    );

    let Some(redis_url) = config.redis_url.clone() else {
        info!("REDIS_URL unset, series label gate runs with the local cache only");
        let gate = SeriesLabelGate::local_only(window, enabled);
        gate.spawn_pruner();
        return gate;
    };

    let redis_timeout = Duration::from_millis(config.metrics_series_redis_timeout_ms);
    let seed_timeout = Duration::from_millis(config.metrics_series_redis_seed_timeout_ms);
    let pull_interval = Duration::from_secs(config.metrics_series_redis_pull_interval_secs);
    let client: Arc<dyn Client> = match RedisClient::with_config(
        redis_url,
        CompressionConfig::disabled(),
        RedisValueFormat::Utf8,
        Some(seed_timeout),
        Some(seed_timeout),
    )
    .await
    {
        Ok(client) => Arc::new(client),
        Err(e) => {
            error!(
                "Could not connect to Redis, series label gate runs with the local cache only: {e}"
            );
            let gate = SeriesLabelGate::local_only(window, enabled);
            gate.spawn_pruner();
            return gate;
        }
    };

    let (gate, rx) = SeriesLabelGate::new(window, enabled);
    gate.seed_from_redis(client.as_ref(), seed_timeout).await;
    gate.spawn_redis_puller(Arc::clone(&client), pull_interval, seed_timeout);
    gate.spawn_pruner();
    spawn_redis_writer(client, rx, redis_timeout, window);
    gate
}

#[tokio::main]
async fn main() {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_with_defaults().unwrap();

    // Start continuous profiling if enabled (keep _agent alive for the duration of the program)
    let _profiling_agent = match config.base.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            tracing::warn!("Failed to start continuous profiling agent: {e}");
            None
        }
    };

    let health_registry = HealthRegistry::new("liveness");

    // The shared sink owns one producer per signal. This binary only sends
    // metrics, but the sink constructor is unchanged, so the other producers
    // still connect and report liveness.
    let logs_sink_liveness = health_registry
        .register("rdkafka".to_string(), Duration::from_secs(30))
        .await;
    let traces_sink_liveness = health_registry
        .register("rdkafka_traces".to_string(), Duration::from_secs(30))
        .await;
    let metrics_sink_liveness = health_registry
        .register("rdkafka_metrics".to_string(), Duration::from_secs(30))
        .await;

    let kafka_sink = KafkaSink::new(
        config.base.kafka.clone(),
        logs_sink_liveness,
        traces_sink_liveness,
        metrics_sink_liveness,
    )
    .await
    .expect("failed to start Kafka sink");

    let management_router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route(
            "/_liveness",
            get(move || ready(health_registry.get_status())),
        );
    let management_router = setup_metrics_routes(management_router);
    let management_bind = format!(
        "{}:{}",
        config.base.management_host, config.base.management_port
    );
    info!("Healthcheck and metrics listening on {}", management_bind);
    let management_listener = tokio::net::TcpListener::bind(management_bind)
        .await
        .expect("could not bind management port");

    let series_label_gate = start_series_label_gate(&config).await;
    let token_dropper =
        TokenDropper::new(&config.base.drop_events_by_token.clone().unwrap_or_default());
    let authorizer = Authorizer::new(Arc::new(token_dropper));
    let metrics_service = MetricsService::new(
        kafka_sink,
        authorizer,
        config.base.max_request_body_size_bytes,
        series_label_gate,
    );
    let http_bind = format!("{}:{}", config.base.host, config.base.port);
    info!("Listening on {}", http_bind);
    let http_listener = tokio::net::TcpListener::bind(http_bind)
        .await
        .expect("could not bind http port");

    // Very permissive CORS policy
    let cors = CorsLayer::new()
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(AllowHeaders::mirror_request())
        .allow_credentials(true)
        .allow_origin(AllowOrigin::mirror_request());

    let http_router = Router::new()
        .route(
            "/v1/metrics",
            post(export_metrics_http).options(options_handler),
        )
        .route(
            "/i/v1/metrics",
            post(export_metrics_http).options(options_handler),
        )
        .with_state(metrics_service.clone())
        .layer(DefaultBodyLimit::max(
            config.base.max_request_body_size_bytes,
        ))
        .layer(axum::middleware::from_fn(track_metrics))
        .layer(RequestDecompressionLayer::new())
        .layer(axum::middleware::from_fn(translate_compression_query_param));

    // Prometheus remote-write sends `Content-Encoding: snappy`, which
    // RequestDecompressionLayer rejects with 415 before the handler runs. This
    // route is deliberately kept off that layer (and the gzip query-param
    // shim); the handler snappy-decodes the body itself.
    let prometheus_router = Router::new()
        .route(
            "/i/v1/prometheus/write",
            post(prometheus::export_prometheus_remote_write_http).options(options_handler),
        )
        .route(
            "/i/v1/prometheus/write/:token",
            post(prometheus::export_prometheus_remote_write_http).options(options_handler),
        )
        .with_state(metrics_service)
        .layer(DefaultBodyLimit::max(
            config.base.max_request_body_size_bytes,
        ))
        .layer(axum::middleware::from_fn(track_metrics));

    let http_router = http_router.merge(prometheus_router).layer(cors);

    let http_server = tokio::spawn(async move {
        if let Err(e) = axum::serve(
            http_listener,
            http_router.into_make_service_with_connect_info::<SocketAddr>(),
        )
        .with_graceful_shutdown(shutdown())
        .await
        {
            error!("HTTP server failed: {}", e);
        }
    });

    let mgmt_server = tokio::spawn(async move {
        if let Err(e) = axum::serve(
            management_listener,
            management_router.into_make_service_with_connect_info::<SocketAddr>(),
        )
        .await
        {
            error!("Management server failed: {}", e);
        }
    });

    // Wait for any server to finish
    tokio::select! {
        _ = http_server => {
            error!("HTTP server stopped");
        }
        _ = mgmt_server => {
            error!("Management server stopped");
        }
    }
}
