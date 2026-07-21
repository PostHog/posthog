//! Notifications mode: consumes the `error_tracking_ingestion_notifications`
//! Kafka topic and fans ingestion notifications out to downstream side effects.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

use axum::{http::StatusCode, routing::get, Router};
use common_kafka::kafka_consumer::SingleTopicConsumer;
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};

use crate::core::shutdown::wait_for_shutdown;
use crate::modes::notifications::consumer_loop::consume_loop;
use crate::modes::notifications::context::NotificationsContext;

pub mod analytics;
pub mod config;
mod consumer_loop;
mod context;
mod handler;
mod issue_handler;
pub mod side_effects;
pub mod signals;
pub mod stacktrace;
pub mod types;

pub use config::NotificationsConfig;

/// Boot the notifications consumer plus its metrics/health server and run until
/// shutdown.
pub async fn run(config: NotificationsConfig) {
    let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())
        .expect("failed to create notifications Kafka consumer");
    let context = NotificationsContext::from_config(&config)
        .await
        .expect("failed to create notifications context");

    info!(
        topic = %config.consumer.kafka_consumer_topic,
        group = %config.consumer.kafka_consumer_group,
        "Starting cymbal-notifications consumer",
    );

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let draining = Arc::new(AtomicBool::new(false));
    let shutdown_handle = spawn_shutdown_listener(shutdown_tx.clone(), draining.clone());
    let metrics_handle =
        spawn_metrics_server(config.metrics_port, shutdown_rx.clone(), draining.clone());

    consume_loop(consumer, context, shutdown_rx).await;

    let _ignored = shutdown_tx.send(true);
    if let Err(err) = metrics_handle.await {
        warn!(error = %err, "metrics server task failed during shutdown");
    }
    shutdown_handle.abort();
}

fn spawn_metrics_server(
    port: u16,
    shutdown_rx: watch::Receiver<bool>,
    draining: Arc<AtomicBool>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        let readiness_draining = draining.clone();
        let router = Router::new()
            .route("/_liveness", get(|| async { "ok" }))
            .route(
                "/_readiness",
                get(move || readiness(readiness_draining.clone())),
            );
        let router =
            common_metrics::setup_metrics_routes_for_product(router, "cymbal-notifications");

        let bind = format!("0.0.0.0:{port}");
        info!("Metrics server listening on {}", bind);
        let listener = match tokio::net::TcpListener::bind(&bind).await {
            Ok(listener) => listener,
            Err(e) => {
                error!("Metrics server bind error: {e}");
                return;
            }
        };
        if let Err(e) = axum::serve(listener, router)
            .with_graceful_shutdown(wait_for_shutdown(shutdown_rx))
            .await
        {
            error!("Metrics server error: {e}");
        }
    })
}

fn spawn_shutdown_listener(
    shutdown_tx: watch::Sender<bool>,
    draining: Arc<AtomicBool>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        shutdown_signal().await;
        info!("shutdown signal received, marking cymbal-notifications as draining");
        draining.store(true, Ordering::Relaxed);
        let _ignored = shutdown_tx.send(true);
    })
}

async fn readiness(draining: Arc<AtomicBool>) -> (StatusCode, &'static str) {
    if draining.load(Ordering::Relaxed) {
        return (StatusCode::SERVICE_UNAVAILABLE, "draining");
    }

    (StatusCode::OK, "ok")
}

#[cfg(unix)]
async fn shutdown_signal() {
    use tokio::signal::unix::{signal, SignalKind};

    let mut sigterm = signal(SignalKind::terminate()).expect("failed to listen for SIGTERM");
    tokio::select! {
        result = tokio::signal::ctrl_c() => {
            if let Err(err) = result {
                warn!(error = %err, "failed to listen for Ctrl+C");
            }
        }
        _ = sigterm.recv() => {}
    }
}

#[cfg(not(unix))]
async fn shutdown_signal() {
    if let Err(err) = tokio::signal::ctrl_c().await {
        warn!(error = %err, "failed to listen for Ctrl+C");
    }
}
