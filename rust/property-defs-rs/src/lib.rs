use std::{sync::Arc, time::Duration};

use app_context::AppContext;
use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use config::Config;
use metrics_consts::{
    BATCH_ACQUIRE_TIME, CACHE_CONSUMED, CHUNK_SIZE, COMPACTED_UPDATES, DUPLICATES_IN_BATCH,
    EMPTY_EVENTS, EVENTS_RECEIVED, EVENT_PARSE_ERROR, FORCED_SMALL_BATCH, ISSUE_FAILED,
    RECV_DEQUEUED, SKIPPED_DUE_TO_TEAM_FILTER, UPDATES_CACHE, UPDATES_DROPPED,
    UPDATES_FILTERED_BY_CACHE, UPDATES_PER_EVENT, UPDATES_SEEN, UPDATE_ISSUE_TIME,
    UPDATE_PRODUCER_OFFSET, V2_ISOLATED_DB_SELECTED, WORKER_BLOCKED,
};
use types::{Event, Update};
use v2_batch_ingestion::process_batch_v2;

use ahash::AHashSet;
use quick_cache::sync::Cache;

use tokio::sync::mpsc::{self, error::TrySendError};
use tracing::{error, warn};

pub mod api;
pub mod app_context;
pub mod config;
pub mod metrics_consts;
pub mod types;
pub mod update_cache;
pub mod v2_batch_ingestion;

const BATCH_UPDATE_MAX_ATTEMPTS: u64 = 2;
const UPDATE_RETRY_DELAY_MS: u64 = 50;

pub async fn update_consumer_loop(
    config: Config,
    cache: Arc<Cache<Update, ()>>,
    context: Arc<AppContext>,
    mut channel: mpsc::Receiver<Update>,
) {
    loop {
        let mut batch = Vec::with_capacity(config.update_batch_size);

        let batch_start = tokio::time::Instant::now();
        let batch_time = common_metrics::timing_guard(BATCH_ACQUIRE_TIME, &[]);
        while batch.len() < config.update_batch_size {
            context.worker_liveness.report_healthy().await;

            let remaining_capacity = config.update_batch_size - batch.len();
            // We race these two, so we can escape this loop and do a small batch if we've been waiting too long
            let recv = channel.recv_many(&mut batch, remaining_capacity);
            let sleep = tokio::time::sleep(Duration::from_secs(1));

            tokio::select! {
                got = recv => {
                    if got == 0 {
                        // Indicates all workers have exited, so we should too
                        panic!("Coordinator recv failed, dying");
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

        // We de-duplicate the batch, in case racing inserts slipped through the shared-cache filter. This
        // is important because duplicate updates touch the same row, and we issue in parallel, so we'd end
        // up deadlocking ourselves. We can still encounter deadlocks due to other pods, but those should
        // be rarer, and we use retries to handle them.
        let start_len = batch.len();
        batch.sort_unstable();
        batch.dedup();

        metrics::counter!(DUPLICATES_IN_BATCH).increment((start_len - batch.len()) as u64);

        let cache_utilization = cache.len() as f64 / config.cache_capacity as f64;
        metrics::gauge!(CACHE_CONSUMED).set(cache_utilization);

        // the new mirror deployment should point all Postgres writes
        // at the new isolated "propdefs" DB instance in all envs.
        // THE ORIGINAL property-defs-rs deployment should NEVER DO THIS
        let mut resolved_pool = &context.pool;
        if config.enable_mirror {
            // for safely, the original propdefs deploy will not set the
            // DATABASE_PROPDEFS_URL and local defaults set it the same
            // as DATABASE_URL (the std posthog Cloud DB) so only if
            // this context var != None will it be enabled
            if let Some(resolved) = &context.propdefs_pool {
                metrics::counter!(
                    V2_ISOLATED_DB_SELECTED,
                    &[(String::from("processor"), String::from("v2"))]
                )
                .increment(1);
                resolved_pool = resolved;
            }
        }

        // conditionally enable new v2 batch write path. While the new write
        // path is being tested and not the default, THIS IS INDEPENDENT of
        // whether config.enable_mirror is set, or which deploy we're in
        if config.enable_v2 {
            // enrich batch group events with resolved group_type_indices
            // before passing along to process_batch_v2. We can refactor this
            // to make it less awkward soon.
            let _unused = context
                .resolve_group_types_indexes(&mut batch)
                .await
                .map_err(|e| {
                    warn!(
                        "Failed resolving group type indices for batch, got: {:?}",
                        e
                    )
                });

            process_batch_v2(&config, cache.clone(), resolved_pool, batch).await;
        } else {
            process_batch_v1(&config, cache.clone(), context.clone(), batch).await;
        }
    }
}

async fn process_batch_v1(
    config: &Config,
    cache: Arc<Cache<Update, ()>>,
    context: Arc<AppContext>,
    mut batch: Vec<Update>,
) {
    // unused in v2 as a throttling mechanism, but still useful to measure
    let cache_utilization = cache.len() as f64 / config.cache_capacity as f64;
    metrics::gauge!(CACHE_CONSUMED).set(cache_utilization);

    // We split our update batch into chunks, one per transaction. We know each update touches
    // exactly one row, so we can issue the chunks in parallel, and smaller batches issue faster,
    // which helps us with inter-pod deadlocking and retries.
    let chunk_size = batch.len() / config.max_concurrent_transactions;
    let mut chunks = vec![Vec::with_capacity(chunk_size); config.max_concurrent_transactions];
    for (i, update) in batch.drain(..).enumerate() {
        chunks[i % config.max_concurrent_transactions].push(update);
    }

    metrics::gauge!(CHUNK_SIZE).set(chunk_size as f64);

    let mut handles = Vec::new();
    let issue_time = common_metrics::timing_guard(UPDATE_ISSUE_TIME, &[]);
    for mut chunk in chunks {
        let m_context = context.clone();
        let m_cache = cache.clone();
        let handle = tokio::spawn(async move {
            let mut tries: u64 = 0;
            // We occasionally encounter deadlocks while issuing updates, so we retry a few times, and
            // if we still fail, we drop the batch and clear it's content from the cached update set, because
            // we assume everything in it will be seen again.
            while let Err(e) = m_context.issue(&mut chunk, cache_utilization).await {
                tries += 1;
                if tries > BATCH_UPDATE_MAX_ATTEMPTS {
                    let chunk_len = chunk.len() as u64;
                    metrics::counter!(ISSUE_FAILED, &[("reason", "failed")]).increment(1);
                    metrics::counter!(UPDATES_DROPPED, &[("reason", "batch_write_fail")])
                        .increment(chunk_len);
                    error!(
                        "Issue failed: retries exhausted, dropping batch of size {} with error: {:?}",
                        chunk_len, e,
                    );
                    // We clear any updates that were in this batch from the cache, so that
                    // if we see them again we'll try again to issue them.
                    chunk.iter().for_each(|u| {
                        if m_cache.remove(u).is_some() {
                            metrics::counter!(UPDATES_CACHE, &[("action", "removed")]).increment(1);
                        } else {
                            metrics::counter!(UPDATES_CACHE, &[("action", "not_cached")])
                                .increment(1);
                        }
                    });
                    return;
                }

                let jitter = rand::random::<u64>() % 50;
                let delay: u64 = tries * UPDATE_RETRY_DELAY_MS + jitter;
                metrics::counter!(ISSUE_FAILED, &[("attempt", format!("retry_{}", tries))])
                    .increment(1);
                warn!("Issue failed: {:?}, sleeping for {}ms", e, delay);
                tokio::time::sleep(Duration::from_millis(delay)).await;
            }
        });
        handles.push(handle);
    }

    for handle in handles {
        handle.await.expect("Issue task failed, exiting");
    }
    issue_time.fin();
}

pub async fn update_producer_loop(
    config: Config,
    consumer: SingleTopicConsumer,
    channel: mpsc::Sender<Update>,
    shared_cache: Arc<Cache<Update, ()>>,
) {
    let mut batch = AHashSet::with_capacity(config.compaction_batch_size);
    let mut last_send = tokio::time::Instant::now();
    loop {
        let (event, offset): (Event, _) = match consumer.json_recv().await {
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
                panic!("Kafka error: {:?}", e); // We just panic if we fail to recv from kafka, if it's down, we're down
            }
        };

        // TODO(eli): librdkafka auto_commit is probably making this a no-op anyway. we may want to
        // extend the autocommit time interval either way to ensure we replay consumed messages that
        // could be part of a lost batch or chunk during a redeploy. stay tuned...
        let curr_offset = offset.get_value();
        match offset.store() {
            Ok(_) => (),
            Err(e) => {
                metrics::counter!(UPDATE_PRODUCER_OFFSET, &[("op", "store_fail")]).increment(1);
                // TODO: consumer json_recv() should expose the source partition ID too
                error!(
                    "update_producer_loop: failed to store offset {}, got: {}",
                    curr_offset, e
                );
            }
        }

        if !config
            .filter_mode
            .should_process(&config.filtered_teams.teams, event.team_id)
        {
            metrics::counter!(SKIPPED_DUE_TO_TEAM_FILTER).increment(1);
            continue;
        }

        let updates = event.into_updates(config.update_count_skip_threshold);

        metrics::counter!(EVENTS_RECEIVED).increment(1);
        metrics::counter!(UPDATES_SEEN).increment(updates.len() as u64);
        metrics::histogram!(UPDATES_PER_EVENT).record(updates.len() as f64);

        for update in updates {
            if batch.contains(&update) {
                metrics::counter!(COMPACTED_UPDATES).increment(1);
                continue;
            }
            batch.insert(update);
        }

        // We do the full batch insert before checking the time/batch size, because if we did this
        // inside the for update in updates loop, under extremely low-load situations, we'd push a
        // single update into the channel, then push the rest into the batch, and loop around to
        // wait on the next event, which might come an arbitrary amount of time later. This bit me
        // in testing, and while it's not a correctness problem and under normal load we'd never
        // see it, we may as well just do the full batch insert first.
        if batch.len() >= config.compaction_batch_size
            || last_send.elapsed() > Duration::from_secs(10)
        {
            last_send = tokio::time::Instant::now();
            for update in batch.drain() {
                if shared_cache.get(&update).is_some() {
                    metrics::counter!(UPDATES_CACHE, &[("action", "hit")]).increment(1);
                    // the above can replace this metric when we have new hit/miss stats both flowing
                    metrics::counter!(UPDATES_FILTERED_BY_CACHE).increment(1);
                    continue;
                }

                // for v1 processing pipeline, we cache before we know the batch is
                // persisted safely. for v2, we do this downstream. The bonus: this
                // avoids the internal queue backups that can occur when batch writes
                // fail and the entire contents must be manually removed from the cache
                if !config.enable_v2 {
                    metrics::counter!(UPDATES_CACHE, &[("action", "miss")]).increment(1);
                    shared_cache.insert(update.clone(), ());
                }

                match channel.try_send(update) {
                    Ok(_) => {}
                    Err(TrySendError::Full(update)) => {
                        warn!("Worker blocked");
                        metrics::counter!(WORKER_BLOCKED).increment(1);
                        // Workers should just die if the channel is dropped, since that indicates
                        // the main loop is dead.
                        channel.send(update).await.unwrap();
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
