use std::time::Duration;

use axum::{http::Method, routing::get, routing::post, Router};
use capture::metrics_middleware::track_metrics;
use capture_logs::config::Config;
use capture_logs::kafka::KafkaSink;
use capture_logs::service::Service;
use capture_logs::service::{export_logs_http, options_handler};
use common_metrics::setup_metrics_routes;
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
    "log hog hogs logs

.|||||||||.
|||||||||||||  gimme ur logs 🔫
|||||||||||' .\\
`||||||||||_,__o
"
}

#[tokio::main]
async fn main() {
    setup_tracing();
    info!("Starting up...");

    let config = Config::init_with_defaults().unwrap();

    // Start continuous profiling if enabled (keep _agent alive for the duration of the program)
    let _profiling_agent = match config.continuous_profiling.start_agent() {
        Ok(agent) => agent,
        Err(e) => {
            tracing::warn!("Failed to start continuous profiling agent: {e}");
            None
        }
    };

    let health_registry = HealthRegistry::new("liveness");

    let sink_liveness = health_registry
        .register("rdkafka".to_string(), Duration::from_secs(30))
        .await;

    let kafka_sink = KafkaSink::new(config.kafka.clone(), sink_liveness)
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
    let management_bind = format!("{}:{}", config.management_host, config.management_port);
    info!("Healthcheck and metrics listening on {}", management_bind);
    let management_listener = tokio::net::TcpListener::bind(management_bind)
        .await
        .expect("could not bind management port");

    let token_dropper = TokenDropper::new(&config.drop_events_by_token.unwrap_or_default());
    let logs_service = match Service::new(kafka_sink, token_dropper).await {
        Ok(service) => service,
        Err(e) => {
            error!("Failed to initialize log service: {}", e);
            panic!("Could not start log capture service: {e}");
        }
    };
    let http_bind = format!("{}:{}", config.host, config.port);
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
        .route("/v1/logs", post(export_logs_http).options(options_handler))
        .route(
            "/i/v1/logs",
            post(export_logs_http).options(options_handler),
        )
        .with_state(logs_service)
        .layer(axum::middleware::from_fn(track_metrics))
        .layer(RequestDecompressionLayer::new())
        .layer(cors);

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
