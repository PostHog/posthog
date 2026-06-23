//! Notifications mode: consumes the `error-tracking-ingestion-notifications`
//! Kafka topic and logs each message. This is the initial read-and-display
//! stage; downstream handling (routing, delivery) is layered on later. It
//! starts only a Kafka consumer plus the metrics/health server — no Postgres,
//! Redis, symbol resolution, or HTTP `/process` pipeline.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;

use axum::{http::StatusCode, routing::get, Router};
use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};

use crate::core::{shutdown::wait_for_shutdown, types::notification::IngestionNotification};

pub mod config;

pub use config::NotificationsConfig;

const NOTIFICATIONS_RECEIVED_TOTAL: &str = "cymbal_notifications_received_total";
const NOTIFICATIONS_SKIPPED_TOTAL: &str = "cymbal_notifications_skipped_total";
const NOTIFICATIONS_KAFKA_ERRORS_TOTAL: &str = "cymbal_notifications_kafka_errors_total";

/// Boot the notifications consumer plus its metrics/health server and run until
/// shutdown.
pub async fn run(config: NotificationsConfig) {
    let consumer = SingleTopicConsumer::new(config.kafka.clone(), config.consumer.clone())
        .expect("failed to create notifications Kafka consumer");

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

    consume_loop(consumer, shutdown_rx).await;

    let _ignored = shutdown_tx.send(true);
    if let Err(err) = metrics_handle.await {
        warn!(error = %err, "metrics server task failed during shutdown");
    }
    shutdown_handle.abort();
}

/// Receive messages until shutdown, logging each one. Offsets for successfully
/// received messages are stored and auto-committed by the consumer; serde and
/// empty failures are auto-stored as poison pills inside `json_recv`.
async fn consume_loop(consumer: SingleTopicConsumer, mut shutdown_rx: watch::Receiver<bool>) {
    loop {
        tokio::select! {
            biased;
            changed = shutdown_rx.changed() => {
                if changed.is_err() || *shutdown_rx.borrow() {
                    info!("notifications consumer shutting down");
                    break;
                }
            }
            result = consumer.json_recv::<IngestionNotification>() => {
                match result {
                    Ok((notification, offset)) => {
                        log_notification_summary(&notification);
                        metrics::counter!(NOTIFICATIONS_RECEIVED_TOTAL).increment(1);
                        if let Err(e) = offset.store() {
                            warn!(error = %e, "failed to store notification offset");
                        }
                    }
                    Err(RecvErr::Serde(e)) => {
                        warn!(error = %e, "notification serde error (poison pill skipped)");
                        metrics::counter!(NOTIFICATIONS_SKIPPED_TOTAL, "reason" => "serde").increment(1);
                    }
                    Err(RecvErr::Empty) => {
                        metrics::counter!(NOTIFICATIONS_SKIPPED_TOTAL, "reason" => "empty").increment(1);
                    }
                    Err(RecvErr::Kafka(e)) => {
                        error!(error = %e, "notifications kafka error");
                        metrics::counter!(NOTIFICATIONS_KAFKA_ERRORS_TOTAL).increment(1);
                        tokio::time::sleep(Duration::from_millis(100)).await;
                    }
                }
            }
        }
    }
}

fn log_notification_summary(notification: &IngestionNotification) {
    match notification {
        IngestionNotification::IssueCreated(issue_created) => {
            info!(
                notification_type = "issue_created",
                team_id = issue_created.team_id,
                issue_id = %issue_created.issue_id,
                event_uuid = %issue_created.event.uuid,
                "received error-tracking ingestion notification"
            );
        }
    }
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
