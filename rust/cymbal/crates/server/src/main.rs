use axum::{routing::get, Router};
use common_metrics::setup_metrics_routes;
use cymbal_api::cymbal::v1::cymbal_ingestion_server::CymbalIngestionServer;
use cymbal_api::cymbal::v1::cymbal_stage_runtime_server::CymbalStageRuntimeServer;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use cymbal_runtime::{init_process, CymbalRuntime};
use cymbal_server::config::{
    parse_remote_targets, parse_stage_ids, parse_stage_item_limits, remote_connection_options,
    remote_routing_config, resolve_remote_stage_routes, Config, ServerMode,
};
use cymbal_server::observability::{wait_for_in_flight_drain, InFlightBatchTracker};
use cymbal_server::pipeline::{CymbalPipelineService, PipelineLimits};
use cymbal_server::registry::StageRegistry;
use cymbal_server::remote::RemoteStageConnectionManager;
use cymbal_server::stage::{CymbalStageService, StageServiceLimits};
use envconfig::Envconfig;
use tokio::net::TcpListener;
use tonic::transport::Server;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

/// `CYMBAL_LOG_FORMAT` toggles between JSON (production) and a compact text
/// format (local dev). Default is JSON so Loki / Grafana can index fields like
/// `stage_id`, `batch_id`, and `team_id` from the per-stage observability log
/// emitted by `cymbal_server::observability::metered_stage`.
const LOG_FORMAT_ENV: &str = "CYMBAL_LOG_FORMAT";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum LogFormat {
    Json,
    Text,
}

fn log_format_from_env() -> LogFormat {
    match std::env::var(LOG_FORMAT_ENV)
        .ok()
        .as_deref()
        .map(str::trim)
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("text") | Some("compact") => LogFormat::Text,
        Some("json") | None | Some("") => LogFormat::Json,
        Some(other) => {
            eprintln!("unknown {LOG_FORMAT_ENV}={other:?}; expected text|json; defaulting to json");
            LogFormat::Json
        }
    }
}

fn setup_tracing() {
    let env_filter = EnvFilter::builder()
        .with_default_directive(LevelFilter::INFO.into())
        .from_env_lossy();

    let format = log_format_from_env();
    match format {
        LogFormat::Json => {
            let layer = fmt::layer()
                .with_target(true)
                .with_thread_ids(false)
                .with_level(true)
                .json()
                .flatten_event(true)
                .with_current_span(true)
                .with_span_list(false)
                .with_filter(env_filter)
                .boxed();
            tracing_subscriber::registry().with(layer).init();
        }
        LogFormat::Text => {
            let layer = fmt::layer()
                .compact()
                .with_target(true)
                .with_thread_ids(false)
                .with_level(true)
                .with_filter(env_filter)
                .boxed();
            tracing_subscriber::registry().with(layer).init();
        }
    }
}

async fn readiness(accepting_traffic: Arc<AtomicBool>) -> axum::http::StatusCode {
    if accepting_traffic.load(Ordering::Relaxed) {
        axum::http::StatusCode::OK
    } else {
        axum::http::StatusCode::SERVICE_UNAVAILABLE
    }
}

async fn liveness() -> axum::http::StatusCode {
    axum::http::StatusCode::OK
}

async fn spawn_management_server(
    metrics_port: u16,
    accepting_traffic: Arc<AtomicBool>,
) -> Result<(), Box<dyn std::error::Error>> {
    let router = Router::new()
        .route(
            "/_readiness",
            get(move || {
                let accepting_traffic = accepting_traffic.clone();
                async move { readiness(accepting_traffic).await }
            }),
        )
        .route("/_liveness", get(liveness));
    let router = setup_metrics_routes(router);

    let bind = format!("0.0.0.0:{metrics_port}");
    let listener = TcpListener::bind(&bind).await?;
    tracing::info!(metrics_port, bind = %bind, "Cymbal management server listening");

    tokio::spawn(async move {
        if let Err(error) = axum::serve(listener, router).await {
            tracing::error!(?error, "Cymbal management server stopped unexpectedly");
        }
    });

    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    setup_tracing();

    let config = Config::init_from_env().expect("Invalid configuration");
    warn_if_postgres_pool_undersized(&config);
    let runtime_guard = init_process(&config.runtime.process).await;
    let runtime = CymbalRuntime::from_config(&config.runtime).await?;
    let stage_ids = parse_stage_ids(&config.cymbal_stage_ids);
    let accepting_traffic = Arc::new(AtomicBool::new(false));
    let in_flight_counter = Arc::new(AtomicUsize::new(0));
    let in_flight_tracker = InFlightBatchTracker::new(
        in_flight_counter.clone(),
        config.cymbal_max_in_flight_batches,
    );
    spawn_management_server(config.metrics_port, accepting_traffic.clone()).await?;
    accepting_traffic.store(true, Ordering::Relaxed);

    // Keep this plain stdout line in addition to the structured tracing event.
    // phrocs readiness is log-pattern based, and this line must remain visible
    // even if a local RUST_LOG override filters structured logs.
    println!(
        "starting Cymbal gRPC server grpc_address={} metrics_port={} mode={:?} stage_ids={:?}",
        config.grpc_address, config.metrics_port, config.cymbal_mode, stage_ids
    );

    tracing::info!(
        grpc_address = %config.grpc_address,
        metrics_port = config.metrics_port,
        mode = ?config.cymbal_mode,
        stage_ids = ?stage_ids,
        "starting Cymbal gRPC server"
    );

    match config.cymbal_mode {
        ServerMode::Pipeline => {
            let pipeline_service =
                build_pipeline_service(&config, &runtime, in_flight_tracker.clone()).await?;
            Server::builder()
                .add_service(CymbalIngestionServer::new(pipeline_service))
                .serve_with_shutdown(
                    config.grpc_address,
                    shutdown_signal(
                        Duration::from_millis(config.cymbal_shutdown_drain_delay_ms),
                        in_flight_counter.clone(),
                        Duration::from_millis(config.cymbal_shutdown_max_wait_ms),
                        accepting_traffic.clone(),
                    ),
                )
                .await?;
        }
        ServerMode::Stage => {
            let stage_service =
                build_stage_service(&stage_ids, &config, &runtime, in_flight_tracker.clone())?;
            Server::builder()
                .add_service(CymbalStageRuntimeServer::new(stage_service))
                .serve_with_shutdown(
                    config.grpc_address,
                    shutdown_signal(
                        Duration::from_millis(config.cymbal_shutdown_drain_delay_ms),
                        in_flight_counter.clone(),
                        Duration::from_millis(config.cymbal_shutdown_max_wait_ms),
                        accepting_traffic.clone(),
                    ),
                )
                .await?;
        }
        ServerMode::All => {
            let pipeline_service =
                build_pipeline_service(&config, &runtime, in_flight_tracker.clone()).await?;
            let stage_service =
                build_stage_service(&stage_ids, &config, &runtime, in_flight_tracker.clone())?;
            Server::builder()
                .add_service(CymbalIngestionServer::new(pipeline_service))
                .add_service(CymbalStageRuntimeServer::new(stage_service))
                .serve_with_shutdown(
                    config.grpc_address,
                    shutdown_signal(
                        Duration::from_millis(config.cymbal_shutdown_drain_delay_ms),
                        in_flight_counter.clone(),
                        Duration::from_millis(config.cymbal_shutdown_max_wait_ms),
                        accepting_traffic.clone(),
                    ),
                )
                .await?;
        }
    }

    runtime_guard.shutdown().await;
    Ok(())
}

async fn build_pipeline_service(
    config: &Config,
    runtime: &CymbalRuntime,
    in_flight_tracker: InFlightBatchTracker,
) -> Result<CymbalPipelineService, Box<dyn std::error::Error>> {
    let mut registry = StageRegistry::local_default();
    let remote_targets = parse_remote_targets(&config.cymbal_remote_targets)?;
    let remote_routes = resolve_remote_stage_routes(&config.cymbal_remote_stages, &remote_targets)?;
    if !remote_routes.is_empty() && remote_targets.is_empty() {
        return Err("CYMBAL_REMOTE_STAGES requires CYMBAL_REMOTE_TARGETS".into());
    }
    for (stage_id, target_name) in remote_routes {
        if !remote_targets
            .iter()
            .any(|target| target.name == target_name)
        {
            return Err(
                format!("remote stage {stage_id} references unknown target {target_name}").into(),
            );
        }
        registry.set_remote_stage(&stage_id, target_name)?;
    }

    let mut service = CymbalPipelineService::with_registry(registry)
        .with_runtime_stages(runtime.stages.clone())
        .with_limits(PipelineLimits {
            max_batch_events: config.cymbal_max_batch_events,
        })
        .with_in_flight_tracker(in_flight_tracker);
    if !remote_targets.is_empty() {
        let remote_connections = RemoteStageConnectionManager::with_options_and_routing(
            remote_connection_options(config),
            remote_routing_config(config)?,
        );
        remote_connections.refresh_targets(&remote_targets).await?;
        if config.cymbal_remote_refresh_interval_ms > 0 {
            remote_connections.spawn_refresh_loop(
                remote_targets,
                Duration::from_millis(config.cymbal_remote_refresh_interval_ms),
            );
        }
        service = service.with_remote_connections(remote_connections);
    }

    Ok(service)
}

fn build_stage_service(
    stage_ids: &[String],
    config: &Config,
    runtime: &CymbalRuntime,
    in_flight_tracker: InFlightBatchTracker,
) -> Result<CymbalStageService, Box<dyn std::error::Error>> {
    let stage_registry = StageRegistry::local_for_stage_ids(stage_ids)?;
    Ok(CymbalStageService::new(stage_registry)
        .with_runtime_stages(runtime.stages.clone())
        .with_limits(stage_service_limits(config)?)
        .with_in_flight_tracker(in_flight_tracker))
}

fn stage_service_limits(config: &Config) -> Result<StageServiceLimits, Box<dyn std::error::Error>> {
    let default_max_in_flight_stage_items = if config.cymbal_max_in_flight_stage_items == 0 {
        config
            .cymbal_max_stage_items
            .saturating_mul(config.cymbal_max_in_flight_batches)
            .max(1)
    } else {
        config.cymbal_max_in_flight_stage_items
    };

    Ok(StageServiceLimits {
        max_stage_items: config.cymbal_max_stage_items,
        default_max_in_flight_stage_items,
        per_stage_max_in_flight_items: parse_stage_item_limits(
            &config.cymbal_stage_max_in_flight_items,
        )?
        .into_iter()
        .collect(),
    })
}

fn warn_if_postgres_pool_undersized(config: &Config) {
    let minimum_connections =
        (config.runtime.symbol_store.symbol_resolution_concurrency / 4).max(1);
    if (config.runtime.postgres.max_pg_connections as usize) >= minimum_connections {
        return;
    }

    tracing::warn!(
        max_pg_connections = config.runtime.postgres.max_pg_connections,
        symbol_resolution_concurrency = config.runtime.symbol_store.symbol_resolution_concurrency,
        recommended_min_pg_connections = minimum_connections,
        "Cymbal Postgres pool may be undersized for symbol resolution concurrency"
    );
}

/// Shutdown is cooperative: stages are not cancel-safe because they can perform
/// repository writes and side effects in the middle of a batch. Kubernetes must
/// stop sending new requests first (readiness removal + `drain_delay`), and the
/// hard wait below must be longer than normal batch latency so in-flight stage
/// work can finish before tonic stops serving.
async fn shutdown_signal(
    drain_delay: Duration,
    in_flight_counter: Arc<AtomicUsize>,
    max_wait: Duration,
    accepting_traffic: Arc<AtomicBool>,
) {
    let ctrl_c = async {
        if let Err(error) = tokio::signal::ctrl_c().await {
            tracing::warn!(?error, "failed to install Ctrl+C shutdown handler");
        }
    };

    #[cfg(unix)]
    {
        use tokio::signal::unix::{signal, SignalKind};

        let terminate = async {
            match signal(SignalKind::terminate()) {
                Ok(mut stream) => {
                    stream.recv().await;
                }
                Err(error) => {
                    tracing::warn!(?error, "failed to install SIGTERM shutdown handler");
                    std::future::pending::<()>().await;
                }
            }
        };

        tokio::select! {
            _ = ctrl_c => {}
            _ = terminate => {}
        }
    }

    #[cfg(not(unix))]
    {
        ctrl_c.await;
    }

    accepting_traffic.store(false, Ordering::Relaxed);

    if !drain_delay.is_zero() {
        tracing::info!(?drain_delay, "waiting for Kubernetes readiness drain delay");
        tokio::time::sleep(drain_delay).await;
    }

    let log_interval = Duration::from_millis(1_000);
    let drained = wait_for_in_flight_drain(in_flight_counter, max_wait, log_interval).await;
    if !drained {
        tracing::warn!(
            max_wait_ms = max_wait.as_millis(),
            "continuing Cymbal shutdown with in-flight batches still running"
        );
    }

    tracing::info!("shutting down Cymbal gRPC server");
}
