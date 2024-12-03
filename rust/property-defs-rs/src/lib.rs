use std::{sync::Arc, time::Duration};

use ahash::AHashSet;
use app_context::AppContext;
use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use config::{Config, TeamFilterMode, TeamList};
use metrics_consts::{
    BATCH_ACQUIRE_TIME, CACHE_CONSUMED, CHUNK_SIZE, COMPACTED_UPDATES, DUPLICATES_IN_BATCH,
    EMPTY_EVENTS, EVENTS_RECEIVED, EVENT_PARSE_ERROR, FORCED_SMALL_BATCH, ISSUE_FAILED,
    RECV_DEQUEUED, SKIPPED_DUE_TO_TEAM_FILTER, UPDATES_FILTERED_BY_CACHE, UPDATES_PER_EVENT,
    UPDATES_SEEN, UPDATE_ISSUE_TIME, WORKER_BLOCKED,
};
use quick_cache::sync::Cache;
use tokio::sync::mpsc::{self, error::TrySendError};
use tracing::{error, warn};
use types::{Event, Update};

pub mod app_context;
pub mod config;
pub mod metrics_consts;
pub mod types;

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
                let mut tries = 0;
                // We occasionally enocounter deadlocks while issuing updates, so we retry a few times, and
                // if we still fail, we drop the batch and clear it's content from the cached update set, because
                // we assume everything in it will be seen again.
                while let Err(e) = m_context.issue(&mut chunk, cache_utilization).await {
                    tries += 1;
                    if tries > 3 {
                        metrics::counter!(ISSUE_FAILED).increment(1);
                        error!("Too many tries, dropping batch");
                        // We clear any updates that were in this batch from the cache, so that
                        // if we see them again we'll try again to issue them.
                        chunk.iter().for_each(|u| {
                            m_cache.remove(u);
                        });
                        return;
                    }

                    let jitter = rand::random::<u64>() % 50;
                    warn!("Issue failed: {:?}, sleeping for {}ms", e, jitter);
                    tokio::time::sleep(Duration::from_millis(jitter)).await;
                }
            });
            handles.push(handle);
        }

        for handle in handles {
            handle.await.expect("Issue task failed, exiting");
        }
        issue_time.fin();
    }
}

pub async fn update_producer_loop(
    consumer: SingleTopicConsumer,
    channel: mpsc::Sender<Update>,
    shared_cache: Arc<Cache<Update, ()>>,
    skip_threshold: usize,
    compaction_batch_size: usize,
    team_filter_mode: TeamFilterMode,
    team_list: TeamList,
) {
    let mut batch = AHashSet::with_capacity(compaction_batch_size);
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

        // Panicking on offset store failure, same reasoning as the panic above - if kafka's down, we're down
        offset.store().expect("Failed to store offset");

        if !team_filter_mode.should_process(&team_list.teams, event.team_id) {
            metrics::counter!(SKIPPED_DUE_TO_TEAM_FILTER).increment(1);
            continue;
        }

        let updates = event.into_updates(skip_threshold);

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
        if batch.len() >= compaction_batch_size || last_send.elapsed() > Duration::from_secs(10) {
            last_send = tokio::time::Instant::now();
            for update in batch.drain() {
                if shared_cache.get(&update).is_some() {
                    metrics::counter!(UPDATES_FILTERED_BY_CACHE).increment(1);
                    continue;
                }
                shared_cache.insert(update.clone(), ());
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
