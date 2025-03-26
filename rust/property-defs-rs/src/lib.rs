use std::{sync::Arc, time::Duration};

use app_context::AppContext;
use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use config::{Config, TeamFilterMode, TeamList};
use metrics_consts::{
    BATCH_ACQUIRE_TIME, CACHE_CONSUMED, CHUNK_SIZE, COMPACTED_UPDATES, DUPLICATES_IN_BATCH,
    EMPTY_EVENTS, EVENTS_RECEIVED, EVENT_PARSE_ERROR, FORCED_SMALL_BATCH, ISSUE_FAILED,
    RECV_DEQUEUED, SKIPPED_DUE_TO_TEAM_FILTER, UPDATES_CACHE, UPDATES_DROPPED,
    UPDATES_FILTERED_BY_CACHE, UPDATES_PER_EVENT, UPDATES_SEEN, UPDATE_ISSUE_TIME,
    UPDATE_PRODUCER_OFFSET, V2_EVENT_DEFS_BATCH_ATTEMPT, V2_EVENT_DEFS_BATCH_ROWS_AFFECTED,
    V2_EVENT_DEFS_BATCH_TIME, V2_EVENT_PROPS_BATCH_ATTEMPT, V2_EVENT_PROPS_BATCH_ROWS_AFFECTED,
    V2_EVENT_PROPS_BATCH_TIME, V2_PROP_DEFS_BATCH_ATTEMPT, V2_PROP_DEFS_BATCH_ROWS_AFFECTED,
    V2_PROP_DEFS_BATCH_TIME, WORKER_BLOCKED,
};
use types::{Event, EventDefinitionsBatch, EventPropertiesBatch, PropertyDefinitionsBatch, Update};

use ahash::AHashSet;
use quick_cache::sync::Cache;
use sqlx::PgPool;
use tokio::sync::mpsc::{self, error::TrySendError};
use tokio::task::JoinHandle;
use tracing::{error, warn};

// allows us to import private functions from lib.rs to test
// module under "../tests/" directory
#[cfg(test)]
#[path = "../tests/v2_batch_ingestion.rs"]
mod v2_batch_ingestion_test;

pub mod api;
pub mod app_context;
pub mod config;
pub mod metrics_consts;
pub mod types;

const BATCH_UPDATE_MAX_ATTEMPTS: u64 = 2;
const UPDATE_RETRY_DELAY_MS: u64 = 50;
const MAX_V2_BATCH_RETRY_ATTEMPTS: u64 = 3;

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

        // conditionall enable new write path
        if config.enable_v2 {
            process_batch_v2(&config, cache.clone(), &context.pool, batch).await;
        } else {
            process_batch_v1(&config, cache.clone(), context.clone(), batch).await;
        }
    }
}

async fn process_batch_v2(
    config: &Config,
    cache: Arc<Cache<Update, ()>>,
    pool: &PgPool,
    batch: Vec<Update>,
) {
    let cache_utilization = cache.len() as f64 / config.cache_capacity as f64;
    metrics::gauge!(CACHE_CONSUMED).set(cache_utilization);

    // prep reshaped, isolated data batch bufffers and async join handles
    let mut event_defs = EventDefinitionsBatch::new();
    let mut event_props = EventPropertiesBatch::new();
    let mut prop_defs = PropertyDefinitionsBatch::new();
    let mut handles: Vec<JoinHandle<Result<(), sqlx::Error>>> = vec![];

    // loop on the Update batch, splitting into smaller vectorized PG write batches
    // and submitted async. note for testing and simplicity, we don't work with
    // the AppContext in process_batch_v2, just it's PgPool. We clone that all over
    // the place to pass into `tokio::spawn()` which is fine b/c it's designed for
    // this and manages concurrent access internaly. Some details here:
    // https://github.com/launchbadge/sqlx/blob/main/sqlx-core/src/pool/mod.rs#L109-L111
    for update in batch {
        match update {
            Update::Event(ed) => {
                if event_defs.append(ed) {
                    let pool = pool.clone();
                    handles.push(tokio::spawn(async move {
                        write_event_definitions_batch(event_defs, &pool).await
                    }));
                    event_defs = EventDefinitionsBatch::new();
                }
            }
            Update::EventProperty(ep) => {
                if event_props.append(ep) {
                    let pool = pool.clone();
                    handles.push(tokio::spawn(async move {
                        write_event_properties_batch(event_props, &pool).await
                    }));
                    event_props = EventPropertiesBatch::new();
                }
            }
            Update::Property(pd) => {
                if prop_defs.append(pd) {
                    let pool = pool.clone();
                    handles.push(tokio::spawn(async move {
                        write_property_definitions_batch(prop_defs, &pool).await
                    }));
                    prop_defs = PropertyDefinitionsBatch::new();
                }
            }
        }
    }

    // ensure partial batches are flushed to Postgres too
    if !event_defs.is_empty() {
        let pool = pool.clone();
        handles.push(tokio::spawn(async move {
            write_event_definitions_batch(event_defs, &pool).await
        }));
    }
    if !prop_defs.is_empty() {
        let pool = pool.clone();
        handles.push(tokio::spawn(async move {
            write_property_definitions_batch(prop_defs, &pool).await
        }));
    }
    if !event_props.is_empty() {
        let pool = pool.clone();
        handles.push(tokio::spawn(async move {
            write_event_properties_batch(event_props, &pool).await
        }));
    }

    for handle in handles {
        match handle.await {
            Ok(result) => match result {
                Ok(_) => continue,
                Err(db_err) => {
                    warn!("Batch write exhausted retries: {:?}", db_err);
                }
            },
            Err(join_err) => {
                warn!("Batch query JoinError: {:?}", join_err);
            }
        }
    }
}

async fn write_event_properties_batch(
    batch: EventPropertiesBatch,
    pool: &PgPool,
) -> Result<(), sqlx::Error> {
    let total_time = common_metrics::timing_guard(V2_EVENT_PROPS_BATCH_TIME, &[]);
    let mut tries = 1;

    loop {
        let result = sqlx::query(r#"
            INSERT INTO posthog_eventproperty (event, property, team_id, project_id)
                VALUES (UNNEST($1::text[]), UNNEST($2::text[]), UNNEST($3::int[]), UNNEST($4::int[]))
                ON CONFLICT DO NOTHING"#,
        )
        .bind(&batch.event_names)
        .bind(&batch.property_names)
        .bind(&batch.team_ids)
        .bind(&batch.project_ids)
        .execute(pool).await;

        match result {
            Err(e) => {
                if tries == MAX_V2_BATCH_RETRY_ATTEMPTS {
                    metrics::counter!(V2_EVENT_PROPS_BATCH_ATTEMPT, &[("result", "failed")]);
                    total_time.fin();
                    return Err(e);
                }

                metrics::counter!(V2_EVENT_PROPS_BATCH_ATTEMPT, &[("result", "retry")]);
                let jitter = rand::random::<u64>() % 50;
                let delay: u64 = tries * UPDATE_RETRY_DELAY_MS + jitter;
                let _unused = tokio::time::sleep(Duration::from_millis(delay));
                tries += 1;
            }

            Ok(pgq_result) => {
                let count = pgq_result.rows_affected();
                metrics::counter!(V2_EVENT_PROPS_BATCH_ATTEMPT, &[("result", "success")]);
                common_metrics::inc(V2_EVENT_PROPS_BATCH_ROWS_AFFECTED, &[], count);
                total_time.fin();
                return Ok(());
            }
        }
    }
}

async fn write_property_definitions_batch(
    batch: PropertyDefinitionsBatch,
    pool: &PgPool,
) -> Result<(), sqlx::Error> {
    let total_time = common_metrics::timing_guard(V2_PROP_DEFS_BATCH_TIME, &[]);
    let mut tries: u64 = 1;

    loop {
        // what if we just ditch properties without a property_type set? why update on conflict at all?
        let result = sqlx::query(r#"
            INSERT INTO posthog_propertydefinition (id, name, type, group_type_index, is_numerical, team_id, project_id, property_type, volume_30_day, query_usage_30_day)
                VALUES (UNNEST($1::uuid[]), UNNEST($2::text[]), UNNEST($3::smallint[]), UNNEST($4::smallint[]), UNNEST($5::boolean[]), UNNEST($6::int[]), UNNEST($7::int[]), UNNEST($8::text[]), NULL, NULL)
                ON CONFLICT (coalesce(project_id, team_id::bigint), name, type, coalesce(group_type_index, -1))
                DO UPDATE SET property_type=EXCLUDED.property_type
                WHERE posthog_propertydefinition.property_type IS NULL"#,
            )
            .bind(&batch.ids)
            .bind(&batch.names)
            .bind(&batch.event_types)
            .bind(&batch.group_type_indices)
            .bind(&batch.are_numerical)
            .bind(&batch.team_ids)
            .bind(&batch.project_ids)
            .bind(&batch.property_types)
            .execute(pool).await;

        match result {
            Err(e) => {
                if tries == MAX_V2_BATCH_RETRY_ATTEMPTS {
                    metrics::counter!(V2_PROP_DEFS_BATCH_ATTEMPT, &[("result", "failed")]);
                    total_time.fin();
                    return Err(e);
                }

                metrics::counter!(V2_PROP_DEFS_BATCH_ATTEMPT, &[("result", "retry")]);
                let jitter = rand::random::<u64>() % 50;
                let delay: u64 = tries * UPDATE_RETRY_DELAY_MS + jitter;
                let _unused = tokio::time::sleep(Duration::from_millis(delay));
                tries += 1;
            }

            Ok(pgq_result) => {
                let count = pgq_result.rows_affected();
                metrics::counter!(V2_PROP_DEFS_BATCH_ATTEMPT, &[("result", "success")]);
                common_metrics::inc(V2_PROP_DEFS_BATCH_ROWS_AFFECTED, &[], count);
                total_time.fin();
                return Ok(());
            }
        }
    }
}

async fn write_event_definitions_batch(
    batch: EventDefinitionsBatch,
    pool: &PgPool,
) -> Result<(), sqlx::Error> {
    let total_time = common_metrics::timing_guard(V2_EVENT_DEFS_BATCH_TIME, &[]);
    let mut tries: u64 = 1;

    loop {
        // TODO: is last_seen_at critical to the product UX? "ON CONFLICT DO NOTHING" may be much cheaper...
        let result = sqlx::query(
            r#"
            INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day,
                team_id, project_id, last_seen_at, created_at)
            VALUES (UNNEST($1::[]uuid), UNNEST($2::text[]), NULL, NULL, UNNEST($3::int[]),
                    UNNEST($4::int[]), UNNEST($5::timestamptz[]), UNNEST($5::timestamptz[]))
            ON CONFLICT (coalesce(project_id, team_id::bigint), name) DO UPDATE
                SET last_seen_at=EXCLUDED.last_seen_at
                WHERE posthog_eventdefinition.last_seen_at < EXCLUDED.last_seen_at"#,
        )
        .bind(&batch.ids)
        .bind(&batch.names)
        .bind(&batch.team_ids)
        .bind(&batch.project_ids)
        .bind(&batch.last_seen_ats)
        .execute(pool)
        .await;

        match result {
            Err(e) => {
                if tries == MAX_V2_BATCH_RETRY_ATTEMPTS {
                    metrics::counter!(V2_EVENT_DEFS_BATCH_ATTEMPT, &[("result", "failed")]);
                    total_time.fin();
                    return Err(e);
                }

                metrics::counter!(V2_EVENT_DEFS_BATCH_ATTEMPT, &[("result", "retry")]);
                let jitter = rand::random::<u64>() % 50;
                let delay: u64 = tries * UPDATE_RETRY_DELAY_MS + jitter;
                let _unused = tokio::time::sleep(Duration::from_millis(delay));
                tries += 1;
            }
            Ok(pgq_result) => {
                let count = pgq_result.rows_affected();
                metrics::counter!(V2_EVENT_DEFS_BATCH_ATTEMPT, &[("result", "success")]);
                common_metrics::inc(V2_EVENT_DEFS_BATCH_ROWS_AFFECTED, &[], count);
                total_time.fin();
                return Ok(());
            }
        }
    }
}

async fn process_batch_v1(
    config: &Config,
    cache: Arc<Cache<Update, ()>>,
    context: Arc<AppContext>,
    mut batch: Vec<Update>,
) {
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
                    metrics::counter!(UPDATES_CACHE, &[("action", "hit")]).increment(1);
                    // the above can replace this metric when we have new hit/miss stats both flowing
                    metrics::counter!(UPDATES_FILTERED_BY_CACHE).increment(1);
                    continue;
                }
                metrics::counter!(UPDATES_CACHE, &[("action", "miss")]).increment(1);
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
