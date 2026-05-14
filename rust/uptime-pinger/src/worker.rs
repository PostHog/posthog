use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use futures::stream::{FuturesUnordered, StreamExt};
use lifecycle::Handle;
use tracing::{debug, error, info, warn};

use crate::app_context::AppContext;
use crate::claim::{claim_due_monitors, ClaimedMonitor};
use crate::kafka_writer::{
    build_status_change_event, outcome_to_status, produce_pings, produce_status_change, PingRow,
};
use crate::ping::ping;
use crate::status_change::swap_status;

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
    let mut status_changes: Vec<crate::kafka_writer::StatusChange> = Vec::new();

    while let Some((row, change)) = in_flight.next().await {
        rows.push(row);
        if let Some(change) = change {
            status_changes.push(change);
        }
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

    for change in status_changes {
        let event = build_status_change_event(&change, Utc::now());
        if let Err(e) = produce_status_change(
            &context.kafka_producer,
            &context.config.kafka_internal_events_topic,
            event,
        )
        .await
        {
            warn!(
                "failed to produce status_change event for monitor {}: {e}",
                change.monitor_id
            );
        }
    }
}

async fn execute_one(
    context: Arc<AppContext>,
    monitor: ClaimedMonitor,
) -> (PingRow, Option<crate::kafka_writer::StatusChange>) {
    let execution = ping(&context.http, &monitor.url).await;
    let row = PingRow::from_execution(monitor.team_id, monitor.id, &execution);

    let new_status = outcome_to_status(execution.outcome);
    let mut redis = context.redis.clone();
    let previous = match swap_status(&mut redis, monitor.id, new_status).await {
        Ok(prev) => prev,
        Err(e) => {
            warn!("redis swap_status for monitor {} failed: {e}", monitor.id);
            // Treat redis failure as "unchanged" so we don't spam status_change events on
            // transient outages. A bona-fide change next cycle will still flip.
            return (row, None);
        }
    };

    if previous == new_status {
        return (row, None);
    }

    (
        row,
        Some(crate::kafka_writer::StatusChange {
            team_id: monitor.team_id,
            monitor_id: monitor.id,
            monitor_name: monitor.name,
            monitor_url: monitor.url,
            previous_status: previous,
            new_status,
            status_code: execution.status_code,
            latency_ms: execution.latency_ms,
        }),
    )
}
