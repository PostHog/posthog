use std::sync::Arc;
use std::time::Duration;

use futures::stream::{FuturesUnordered, StreamExt};
use lifecycle::Handle;
use tracing::{debug, error, info, warn};

use crate::app_context::AppContext;
use crate::claim::{claim_due_monitors, ClaimedMonitor};
use crate::kafka_writer::{produce_pings, PingRow};
use crate::ping::ping;

pub async fn run_worker_loop(context: Arc<AppContext>, handle: Handle) {
    let idle = Duration::from_millis(context.config.idle_sleep_ms);
    info!(
        "uptime-pinger worker started (batch={}, lease_ttl={}s, idle={}ms)",
        context.config.claim_batch_size,
        context.config.lease_ttl_seconds,
        context.config.idle_sleep_ms
    );

    loop {
        if handle.is_shutting_down() {
            info!("uptime-pinger worker received shutdown signal");
            return;
        }

        let claimed = match claim_due_monitors(
            &context.pool,
            context.config.claim_batch_size,
            context.config.lease_ttl_seconds,
        )
        .await
        {
            Ok(rows) => rows,
            Err(e) => {
                error!("claim_due_monitors failed: {e}");
                tokio::select! {
                    _ = tokio::time::sleep(idle) => {},
                    _ = handle.shutdown_recv() => return,
                }
                continue;
            }
        };

        handle.report_healthy();

        if claimed.is_empty() {
            tokio::select! {
                _ = tokio::time::sleep(idle) => {},
                _ = handle.shutdown_recv() => return,
            }
            continue;
        }

        debug!("claimed {} monitors", claimed.len());
        ping_and_publish(&context, claimed).await;
    }
}

async fn ping_and_publish(context: &Arc<AppContext>, monitors: Vec<ClaimedMonitor>) {
    let mut in_flight = FuturesUnordered::new();
    let concurrency = context.config.ping_concurrency.max(1);

    let mut monitors = monitors.into_iter();
    // Prime the in-flight set up to the concurrency cap, then refill as each ping completes.
    for monitor in monitors.by_ref().take(concurrency) {
        in_flight.push(execute_one(Arc::clone(context), monitor));
    }

    let mut rows: Vec<PingRow> = Vec::new();
    while let Some(row) = in_flight.next().await {
        rows.push(row);
        if let Some(next) = monitors.next() {
            in_flight.push(execute_one(Arc::clone(context), next));
        }
    }

    if !rows.is_empty() {
        let results = produce_pings(
            &context.kafka_producer,
            &context.config.kafka_pings_topic,
            rows,
        )
        .await;
        for (i, result) in results.into_iter().enumerate() {
            if let Err(e) = result {
                warn!("failed to produce ping #{i}: {e}");
            }
        }
    }
}

async fn execute_one(context: Arc<AppContext>, monitor: ClaimedMonitor) -> PingRow {
    let execution = ping(&context.http, &monitor.url).await;
    PingRow::from_execution(monitor.team_id, monitor.id, &execution)
}
