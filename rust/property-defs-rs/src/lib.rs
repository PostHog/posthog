use std::{sync::Arc, time::Duration};

use app_context::AppContext;
use batch_ingestion::process_batch;
use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use config::Config;
use metrics_consts::{
    BATCH_ACQUIRE_TIME, CACHE_CONSUMED, CACHE_LEN, COMPACTED_UPDATES, DUPLICATES_IN_BATCH,
    EMPTY_EVENTS, EVENTS_RECEIVED, EVENT_PARSE_ERROR, FORCED_SMALL_BATCH, RECV_DEQUEUED,
    SKIPPED_DUE_TO_TEAM_FILTER, UPDATES_FILTERED_BY_CACHE, UPDATES_PER_EVENT, UPDATES_SEEN,
    UPDATE_PRODUCER_OFFSET, WORKER_BLOCKED,
};
use types::{Event, Update};

use ahash::AHashSet;
use tokio::sync::mpsc;
use tokio::sync::mpsc::error::TrySendError;
use tokio::task::JoinSet;
use tracing::{error, info, warn};
use update_cache::Cache;

use crate::{
    measuring_channel::{MeasuringReceiver, MeasuringSender},
    metrics_consts::CHANNEL_MESSAGES_IN_FLIGHT,
};

pub mod api;
pub mod app_context;
pub mod batch_ingestion;
pub mod config;
pub mod group_type_resolver;
pub mod measuring_channel;
pub mod metrics_consts;
pub mod types;
pub mod update_cache;

pub async fn update_consumer_loop(
    config: Config,
    cache: Arc<Cache>,
    context: Arc<AppContext>,
    mut channel: MeasuringReceiver<Update>,
    handle: lifecycle::Handle,
) {
    let _guard = handle.process_scope();

    loop {
        let mut batch = Vec::with_capacity(config.update_batch_size);

        let batch_start = tokio::time::Instant::now();
        let batch_time = common_metrics::timing_guard(BATCH_ACQUIRE_TIME, &[]);
        while batch.len() < config.update_batch_size {
            handle.report_healthy();

            metrics::gauge!(CHANNEL_MESSAGES_IN_FLIGHT)
                .set(channel.get_inflight_messages_count() as f64);

            let remaining_capacity = config.update_batch_size - batch.len();
            // We race these two, so we can escape this loop and do a small batch if we've been waiting too long
            let recv = channel.recv_many(&mut batch, remaining_capacity);
            let sleep = tokio::time::sleep(Duration::from_secs(1));

            tokio::select! {
                _ = handle.shutdown_recv() => {
                    info!("Consumer loop received shutdown signal");
                    return;
                }
                got = recv => {
                    if got == 0 {
                        info!("Channel closed, all producers exited");
                        return;
                    }
                    metrics::gauge!(RECV_DEQUEUED).set(got as f64);
                    continue;
                }
                _ = sleep => {
                    if batch_start.elapsed() > Duration::from_secs(config.max_issue_period) {
                        warn!("Forcing small batch due to time limit");
                        metrics::counter!(FORCED_SMALL_BATCH).increment(1);
                        break;
                    }
                }
            }
        }
        batch_time.fin();

        if batch.is_empty() {
            continue;
        }

        // We de-duplicate the batch, in case racing inserts slipped through the shared-cache filter. This
        // is important because duplicate updates touch the same row, and we issue in parallel, so we'd end
        // up deadlocking ourselves. We can still encounter deadlocks due to other pods, but those should
        // be rarer, and we use retries to handle them.
        let start_len = batch.len();
        batch.sort_unstable();
        batch.dedup();

        metrics::counter!(DUPLICATES_IN_BATCH).increment((start_len - batch.len()) as u64);

        // Per-subcache size gauges once per batch. Hit/miss/eviction counters
        // are emitted from inside `Cache::contains_key` and the EvictingLifecycle
        // impl in `update_cache.rs`, not here.
        let per_cache = [
            (
                config.eventdefs_cache_capacity,
                "eventdefs",
                cache.eventdefs_len(),
            ),
            (
                config.eventprops_cache_capacity,
                "eventprops",
                cache.eventprops_len(),
            ),
            (
                config.propdefs_cache_capacity,
                "propdefs",
                cache.propdefs_len(),
            ),
        ];
        for (cap, label, len) in per_cache {
            let cap_f = cap as f64;
            metrics::gauge!(CACHE_CONSUMED, &[("cache", label)]).set(if cap_f > 0.0 {
                len as f64 / cap_f
            } else {
                0.0
            });
            metrics::gauge!(CACHE_LEN, &[("cache", label)]).set(len as f64);
        }

        // enrich batch group events with resolved group_type_indices
        // before passing along to process_batch
        let _unused = context
            .resolve_group_types_indexes(&mut batch)
            .await
            .map_err(|e| {
                warn!(
                    "Failed resolving group type indices for batch, got: {:?}",
                    e
                )
            });

        process_batch(&config, cache.clone(), &context.pool, batch).await;
    }
}

pub async fn update_producer_loop(
    config: Config,
    consumer: SingleTopicConsumer,
    shared_cache: Arc<Cache>,
    channel: MeasuringSender<Update>,
    handle: lifecycle::Handle,
) {
    let _guard = handle.process_scope();
    let mut batch = AHashSet::with_capacity(config.compaction_batch_size);
    let mut last_send = tokio::time::Instant::now();
    let drain_interval = Duration::from_secs(config.producer_drain_interval_secs);
    loop {
        // Wake on a new event, on shutdown, or on a periodic tick so the batch still drains
        // during a lull (otherwise the tail of a low-traffic stream sits unwritten).
        let recv_result = tokio::select! {
            _ = handle.shutdown_recv() => {
                info!("Producer loop shutting down");
                return;
            }
            r = consumer.json_recv() => Some(r),
            _ = tokio::time::sleep(Duration::from_secs(1)) => None,
        };

        if let Some(recv_result) = recv_result {
            let (event, offset): (Event, _) = match recv_result {
                Ok(r) => r,
                Err(RecvErr::Empty) => {
                    warn!("Received empty event");
                    metrics::counter!(EMPTY_EVENTS).increment(1);
                    continue;
                }
                Err(RecvErr::Serde(e)) => {
                    metrics::counter!(EVENT_PARSE_ERROR).increment(1);
                    warn!("Failed to parse event: {:?}", e);
                    continue;
                }
                Err(RecvErr::Kafka(e)) => {
                    handle.signal_failure(format!("Kafka error: {e:?}"));
                    return;
                }
            };

            // NOTE: we extended the autocommit interval in production envs to 20 seconds
            // as a temporary remediation for events already buffered in a pod's internal
            // queue being skipped when the consumer group rebalances or the service is
            // redeployed. Long-term fix: start tracking max partition offsets in the
            // Update batches and commit them only when each batch succeeds. This will
            // not be perfect, as batch writes are async and can complete out of order,
            // but is better than what we're doing right now
            let curr_offset = offset.get_value();
            match offset.store() {
                Ok(_) => (),
                Err(e) => {
                    metrics::counter!(UPDATE_PRODUCER_OFFSET, &[("op", "store_fail")]).increment(1);
                    // TODO: consumer json_recv() should expose the source partition ID too
                    error!("update_producer_loop: failed to store offset {curr_offset}, got: {e}");
                }
            }

            if !config
                .filter_mode
                .should_process(&config.filtered_teams.teams, event.team_id)
            {
                metrics::counter!(SKIPPED_DUE_TO_TEAM_FILTER).increment(1);
                continue;
            }

            let updates = event.into_updates_with(
                config.update_count_skip_threshold,
                config.eventdef_last_seen_floor_secs,
            );

            metrics::counter!(EVENTS_RECEIVED).increment(1);
            metrics::counter!(UPDATES_SEEN).increment(updates.len() as u64);
            metrics::histogram!(UPDATES_PER_EVENT).record(updates.len() as f64);

            for update in updates {
                if !batch.insert(update) {
                    metrics::counter!(COMPACTED_UPDATES).increment(1);
                }
            }
        }

        // We do the full batch insert before checking the time/batch size, because if we did this
        // inside the for update in updates loop, under extremely low-load situations, we'd push a
        // single update into the channel, then push the rest into the batch, and loop around to
        // wait on the next event, which might come an arbitrary amount of time later. This bit me
        // in testing, and while it's not a correctness problem and under normal load we'd never
        // see it, we may as well just do the full batch insert first.
        if batch.len() >= config.compaction_batch_size
            || (!batch.is_empty() && last_send.elapsed() > drain_interval)
        {
            last_send = tokio::time::Instant::now();
            for update in batch.drain() {
                if shared_cache.contains_key(&update) {
                    // kept for back-compat; equivalent to sum(prop_defs_cache_hits)
                    metrics::counter!(UPDATES_FILTERED_BY_CACHE).increment(1);
                    continue;
                }

                // TEMPORARY: both old (v1) and new (v2) write paths will utilize the old
                // not-great caching strategy for now: optimistically add entries before
                // they are safely persisted to Postgres, and painfully extract them
                // when batch writes fail. This may be a fine trade for now, since
                // v2 batch writes fail much less often than v1
                shared_cache.insert(update.clone());

                match channel.try_send(update) {
                    Ok(_) => {}
                    Err(TrySendError::Full(update)) => {
                        warn!("Worker blocked");
                        metrics::counter!(WORKER_BLOCKED).increment(1);
                        if channel.send(update).await.is_err() {
                            return;
                        }
                    }
                    Err(e) => {
                        warn!("Coordinator send failed: {:?}", e);
                        return;
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Staged pipeline (opt-in via `staged_pipeline`): a dedicated Kafka reader, a pool of
// parallel processors, and a writer with bounded write concurrency, decoupled by bounded
// channels. The reader never blocks on parsing or the slow write path (only on genuine
// downstream backpressure), and slow (~170ms) batch writes overlap instead of serializing.
// ---------------------------------------------------------------------------

/// Stage 1: the sole owner of the Kafka consumer. Pulls events as fast as possible and fans
/// them out round-robin to the processor channels. Reads only stall when every processor
/// channel is full (i.e. real end-to-end backpressure).
pub async fn kafka_reader_loop(
    config: Config,
    consumer: SingleTopicConsumer,
    raw_txs: Vec<mpsc::Sender<Event>>,
    handle: lifecycle::Handle,
) {
    let _guard = handle.process_scope();
    let n = raw_txs.len().max(1);
    let mut next = 0usize;

    loop {
        let recv_result = tokio::select! {
            _ = handle.shutdown_recv() => {
                info!("Kafka reader shutting down");
                return;
            }
            r = consumer.json_recv::<Event>() => r,
        };

        let (event, offset): (Event, _) = match recv_result {
            Ok(r) => r,
            Err(RecvErr::Empty) => {
                metrics::counter!(EMPTY_EVENTS).increment(1);
                continue;
            }
            Err(RecvErr::Serde(e)) => {
                metrics::counter!(EVENT_PARSE_ERROR).increment(1);
                warn!("Failed to parse event: {:?}", e);
                continue;
            }
            Err(RecvErr::Kafka(e)) => {
                handle.signal_failure(format!("Kafka error: {e:?}"));
                return;
            }
        };

        let curr_offset = offset.get_value();
        if let Err(e) = offset.store() {
            metrics::counter!(UPDATE_PRODUCER_OFFSET, &[("op", "store_fail")]).increment(1);
            error!("kafka_reader_loop: failed to store offset {curr_offset}, got: {e}");
        }

        if !config
            .filter_mode
            .should_process(&config.filtered_teams.teams, event.team_id)
        {
            metrics::counter!(SKIPPED_DUE_TO_TEAM_FILTER).increment(1);
            continue;
        }
        metrics::counter!(EVENTS_RECEIVED).increment(1);

        let idx = next % n;
        next = next.wrapping_add(1);
        handle.report_healthy();
        if raw_txs[idx].send(event).await.is_err() {
            info!("Processor channel closed, reader exiting");
            return;
        }
    }
}

/// Stage 2: parallel decompose + dedup. Several of these run at once, each draining its own
/// raw-event channel, turning events into updates, filtering through the shared cache, and
/// forwarding survivors to the writer.
pub async fn processor_loop(
    config: Config,
    cache: Arc<Cache>,
    mut raw_rx: mpsc::Receiver<Event>,
    update_tx: MeasuringSender<Update>,
    handle: lifecycle::Handle,
) {
    let _guard = handle.process_scope();

    loop {
        let event = tokio::select! {
            _ = handle.shutdown_recv() => return,
            maybe = raw_rx.recv() => match maybe {
                Some(e) => e,
                None => return,
            },
        };
        handle.report_healthy();

        let updates = event.into_updates_with(
            config.update_count_skip_threshold,
            config.eventdef_last_seen_floor_secs,
        );
        metrics::counter!(UPDATES_SEEN).increment(updates.len() as u64);

        for update in updates {
            if cache.contains_key(&update) {
                metrics::counter!(UPDATES_FILTERED_BY_CACHE).increment(1);
                continue;
            }
            cache.insert(update.clone());
            if update_tx.send(update).await.is_err() {
                return;
            }
        }
    }
}

/// Stage 3: batch updates and write them with bounded concurrency, so multiple slow batch
/// writes overlap instead of serializing one-at-a-time. `writer_max_concurrency` bounds how
/// many batch writes are in flight.
pub async fn writer_loop(
    config: Config,
    cache: Arc<Cache>,
    context: Arc<AppContext>,
    mut channel: MeasuringReceiver<Update>,
    handle: lifecycle::Handle,
) {
    let _guard = handle.process_scope();
    let max_inflight = config.writer_max_concurrency.max(1);
    let mut inflight: JoinSet<()> = JoinSet::new();

    loop {
        let mut batch = Vec::with_capacity(config.update_batch_size);
        let batch_start = tokio::time::Instant::now();
        let batch_time = common_metrics::timing_guard(BATCH_ACQUIRE_TIME, &[]);
        while batch.len() < config.update_batch_size {
            handle.report_healthy();
            metrics::gauge!(CHANNEL_MESSAGES_IN_FLIGHT)
                .set(channel.get_inflight_messages_count() as f64);

            let remaining_capacity = config.update_batch_size - batch.len();
            let recv = channel.recv_many(&mut batch, remaining_capacity);
            let sleep = tokio::time::sleep(Duration::from_secs(1));

            tokio::select! {
                _ = handle.shutdown_recv() => {
                    info!("Writer loop received shutdown signal");
                    while inflight.join_next().await.is_some() {}
                    return;
                }
                got = recv => {
                    if got == 0 {
                        info!("Channel closed, all processors exited");
                        while inflight.join_next().await.is_some() {}
                        return;
                    }
                    metrics::gauge!(RECV_DEQUEUED).set(got as f64);
                    continue;
                }
                _ = sleep => {
                    if batch_start.elapsed() > Duration::from_secs(config.max_issue_period) {
                        metrics::counter!(FORCED_SMALL_BATCH).increment(1);
                        break;
                    }
                }
            }
        }
        batch_time.fin();

        if batch.is_empty() {
            continue;
        }

        let start_len = batch.len();
        batch.sort_unstable();
        batch.dedup();
        metrics::counter!(DUPLICATES_IN_BATCH).increment((start_len - batch.len()) as u64);

        // Bound the number of concurrent in-flight batch writes.
        while inflight.len() >= max_inflight {
            inflight.join_next().await;
        }

        let task_config = config.clone();
        let task_context = context.clone();
        let task_cache = cache.clone();
        inflight.spawn(async move {
            let mut batch = batch;
            let _unused = task_context
                .resolve_group_types_indexes(&mut batch)
                .await
                .map_err(|e| {
                    warn!(
                        "Failed resolving group type indices for batch, got: {:?}",
                        e
                    )
                });
            process_batch(&task_config, task_cache, &task_context.pool, batch).await;
        });
    }
}
