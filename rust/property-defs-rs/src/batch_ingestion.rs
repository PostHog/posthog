use std::{sync::Arc, time::Duration};

use chrono::{DateTime, Utc};
use sqlx::PgPool;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};
use uuid::Uuid;

use crate::{
    config::Config,
    metrics_consts::{
        ISSUE_FAILED, V2_EVENT_DEFS_BATCH_ATTEMPT, V2_EVENT_DEFS_BATCH_CACHE_TIME,
        V2_EVENT_DEFS_BATCH_ROWS_AFFECTED, V2_EVENT_DEFS_BATCH_SIZE,
        V2_EVENT_DEFS_BATCH_WRITE_TIME, V2_EVENT_DEFS_CACHE_REMOVED, V2_EVENT_PROPS_BATCH_ATTEMPT,
        V2_EVENT_PROPS_BATCH_CACHE_TIME, V2_EVENT_PROPS_BATCH_ROWS_AFFECTED,
        V2_EVENT_PROPS_BATCH_SIZE, V2_EVENT_PROPS_BATCH_WRITE_TIME, V2_EVENT_PROPS_CACHE_REMOVED,
        V2_PROP_DEFS_BATCH_ATTEMPT, V2_PROP_DEFS_BATCH_CACHE_TIME,
        V2_PROP_DEFS_BATCH_ROWS_AFFECTED, V2_PROP_DEFS_BATCH_SIZE, V2_PROP_DEFS_BATCH_WRITE_TIME,
        V2_PROP_DEFS_CACHE_REMOVED,
    },
    types::{
        EventDefinition, EventProperty, GroupType, PropertyDefinition, PropertyParentType, Update,
    },
    update_cache::Cache,
};

const V2_BATCH_MAX_RETRY_ATTEMPTS: u64 = 3;
const V2_BATCH_RETRY_DELAY_MS: u64 = 50;

// Derived hash since these are keyed on all fields in the DB
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EventPropertiesBatch {
    batch_size: usize,
    pub team_ids: Vec<i32>,
    pub project_ids: Vec<i64>,
    pub event_names: Vec<String>,
    pub property_names: Vec<String>,

    pub cached: Vec<Update>,
}

impl EventPropertiesBatch {
    pub fn new(batch_size: usize) -> Self {
        Self {
            batch_size,
            team_ids: Vec::with_capacity(batch_size),
            project_ids: Vec::with_capacity(batch_size),
            event_names: Vec::with_capacity(batch_size),
            property_names: Vec::with_capacity(batch_size),
            cached: Vec::with_capacity(batch_size),
        }
    }

    pub fn append(&mut self, ep: EventProperty) {
        self.team_ids.push(ep.team_id);
        self.project_ids.push(ep.project_id);
        self.event_names.push(ep.event.clone());
        self.property_names.push(ep.property.clone());

        self.cached.push(Update::EventProperty(ep));
    }

    pub fn len(&self) -> usize {
        self.team_ids.len()
    }

    pub fn should_flush_batch(&self) -> bool {
        self.len() >= self.batch_size
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn uncache_batch(&self, cache: &Arc<Cache>) {
        let timer = common_metrics::timing_guard(V2_EVENT_PROPS_BATCH_CACHE_TIME, &[]);

        for update in &self.cached {
            cache.remove(update);
            metrics::counter!(V2_EVENT_PROPS_CACHE_REMOVED).increment(1);
        }

        timer.fin();
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EventDefinitionsBatch {
    batch_size: usize,
    pub ids: Vec<Uuid>,
    pub names: Vec<String>,
    pub team_ids: Vec<i32>,
    pub project_ids: Vec<i64>,
    pub last_seen_ats: Vec<DateTime<Utc>>,

    pub cached: Vec<Update>,
}

impl EventDefinitionsBatch {
    pub fn new(batch_size: usize) -> Self {
        Self {
            batch_size,
            ids: Vec::with_capacity(batch_size),
            names: Vec::with_capacity(batch_size),
            team_ids: Vec::with_capacity(batch_size),
            project_ids: Vec::with_capacity(batch_size),
            last_seen_ats: Vec::with_capacity(batch_size),
            cached: Vec::with_capacity(batch_size),
        }
    }

    pub fn append(&mut self, ed: EventDefinition) {
        self.ids.push(Uuid::now_v7());
        self.names.push(ed.name.clone());
        self.team_ids.push(ed.team_id);
        self.project_ids.push(ed.project_id);
        self.last_seen_ats.push(ed.last_seen_at);

        self.cached.push(Update::Event(ed));
    }

    pub fn len(&self) -> usize {
        self.ids.len()
    }

    pub fn should_flush_batch(&self) -> bool {
        self.len() >= self.batch_size
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn uncache_batch(&self, cache: &Arc<Cache>) {
        let timer = common_metrics::timing_guard(V2_EVENT_DEFS_BATCH_CACHE_TIME, &[]);

        for update in &self.cached {
            cache.remove(update);
            metrics::counter!(V2_EVENT_DEFS_CACHE_REMOVED).increment(1);
        }

        timer.fin();
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PropertyDefinitionsBatch {
    batch_size: usize,
    pub ids: Vec<Uuid>,
    pub team_ids: Vec<i32>,
    pub project_ids: Vec<i64>,
    pub names: Vec<String>,
    pub are_numerical: Vec<bool>,
    pub event_types: Vec<i16>,
    pub property_types: Vec<Option<String>>,
    pub group_type_indices: Vec<Option<i16>>,
    // note: I left off deprecated fields we null out on writes
    pub cached: Vec<Update>,
}

impl PropertyDefinitionsBatch {
    pub fn new(batch_size: usize) -> Self {
        Self {
            batch_size,
            ids: Vec::with_capacity(batch_size),
            team_ids: Vec::with_capacity(batch_size),
            project_ids: Vec::with_capacity(batch_size),
            names: Vec::with_capacity(batch_size),
            are_numerical: Vec::with_capacity(batch_size),
            property_types: Vec::with_capacity(batch_size),
            event_types: Vec::with_capacity(batch_size),
            group_type_indices: Vec::with_capacity(batch_size),
            cached: Vec::with_capacity(batch_size),
        }
    }

    pub fn append(&mut self, pd: PropertyDefinition) {
        let group_type_index = match &pd.group_type_index {
            Some(GroupType::Resolved(_, i)) => Some(*i as i16),
            Some(GroupType::Unresolved(group_name)) => {
                warn!(
                    "Group type {} not resolved for property definition {} for team {}, skipping update",
                    group_name, pd.name, pd.team_id
                );
                None
            }
            _ => {
                // We don't have a group type, so we don't have a group type index
                None
            }
        };

        if group_type_index.is_none() && matches!(pd.event_type, PropertyParentType::Group) {
            // Some teams/users wildly misuse group-types, and if we fail to issue an update
            // during the transaction (which we do if we don't have a group-type index for a
            // group property), the entire transaction is aborted, so instead we just warn
            // loudly about this (above, and at resolve time), and drop the update.
            return;
        }

        let property_type: Option<String> = pd.property_type.clone().map(|pvt| pvt.to_string());

        self.ids.push(Uuid::now_v7());
        self.team_ids.push(pd.team_id);
        self.project_ids.push(pd.project_id);
        self.names.push(pd.name.clone());
        self.are_numerical.push(pd.is_numerical);
        self.property_types.push(property_type);
        self.event_types.push(pd.event_type as i16);
        self.group_type_indices.push(group_type_index);

        self.cached.push(Update::Property(pd));
    }

    pub fn len(&self) -> usize {
        self.ids.len()
    }

    pub fn should_flush_batch(&self) -> bool {
        self.len() >= self.batch_size
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn uncache_batch(&self, cache: &Arc<Cache>) {
        let timer = common_metrics::timing_guard(V2_PROP_DEFS_BATCH_CACHE_TIME, &[]);

        for update in &self.cached {
            cache.remove(update);
            metrics::counter!(V2_PROP_DEFS_CACHE_REMOVED).increment(1);
        }

        timer.fin();
    }
}

// HACK: making this public so the test suite file can live under "../tests/" dir
pub async fn process_batch(config: &Config, cache: Arc<Cache>, pool: &PgPool, batch: Vec<Update>) {
    // prep reshaped, isolated data batch bufffers and async join handles
    let mut event_defs = EventDefinitionsBatch::new(config.write_batch_size);
    let mut event_props = EventPropertiesBatch::new(config.write_batch_size);
    let mut prop_defs = PropertyDefinitionsBatch::new(config.write_batch_size);
    let mut handles: Vec<JoinHandle<Result<(), sqlx::Error>>> = vec![];

    // loop over Update batch, grouping by record type into single-target-table
    // batches for async write attempts with retries
    for update in batch {
        match update {
            Update::Event(ed) => {
                event_defs.append(ed);
                if event_defs.should_flush_batch() {
                    let pool = pool.clone();
                    let cache = cache.clone();
                    let outbound = event_defs;
                    event_defs = EventDefinitionsBatch::new(config.write_batch_size);
                    handles.push(tokio::spawn(async move {
                        write_event_definitions_batch(cache, outbound, &pool).await
                    }));
                }
            }
            Update::EventProperty(ep) => {
                event_props.append(ep);
                if event_props.should_flush_batch() {
                    let pool = pool.clone();
                    let cache = cache.clone();
                    let outbound = event_props;
                    event_props = EventPropertiesBatch::new(config.write_batch_size);
                    handles.push(tokio::spawn(async move {
                        write_event_properties_batch(cache, outbound, &pool).await
                    }));
                }
            }
            Update::Property(pd) => {
                prop_defs.append(pd);
                if prop_defs.should_flush_batch() {
                    let pool = pool.clone();
                    let cache = cache.clone();
                    let outbound = prop_defs;
                    prop_defs = PropertyDefinitionsBatch::new(config.write_batch_size);
                    handles.push(tokio::spawn(async move {
                        write_property_definitions_batch(cache, outbound, &pool).await
                    }));
                }
            }
        }
    }

    // ensure partial batches are flushed to Postgres too
    if !event_defs.is_empty() {
        let pool = pool.clone();
        let cache = cache.clone();
        handles.push(tokio::spawn(async move {
            write_event_definitions_batch(cache, event_defs, &pool).await
        }));
    }
    if !prop_defs.is_empty() {
        let pool = pool.clone();
        let cache = cache.clone();
        handles.push(tokio::spawn(async move {
            write_property_definitions_batch(cache, prop_defs, &pool).await
        }));
    }
    if !event_props.is_empty() {
        let pool = pool.clone();
        let cache = cache.clone();
        handles.push(tokio::spawn(async move {
            write_event_properties_batch(cache, event_props, &pool).await
        }));
    }

    // Execute final batch handles concurrently
    let final_results = futures::future::join_all(handles).await;
    for result in final_results {
        match result {
            Ok(batch_result) => match batch_result {
                Ok(_) => continue,
                // fanned-out write attempts are instrumented locally w/more
                // detail, so we only publish global error metric here
                Err(_) => {
                    metrics::counter!(ISSUE_FAILED, &[("reason", "failed")]).increment(1);
                }
            },
            Err(join_err) => {
                warn!("Batch query JoinError: {:?}", join_err);
            }
        }
    }
}

async fn write_event_properties_batch(
    cache: Arc<Cache>,
    batch: EventPropertiesBatch,
    pool: &PgPool,
) -> Result<(), sqlx::Error> {
    let total_time = common_metrics::timing_guard(V2_EVENT_PROPS_BATCH_WRITE_TIME, &[]);
    let mut tries = 1;

    loop {
        let result = sqlx::query(
            r#"
            INSERT INTO posthog_eventproperty (event, property, team_id, project_id)
                (SELECT * FROM UNNEST(
                    $1::text[],
                    $2::text[],
                    $3::int[],
                    $4::bigint[])) ON CONFLICT DO NOTHING"#,
        )
        .bind(&batch.event_names)
        .bind(&batch.property_names)
        .bind(&batch.team_ids)
        .bind(&batch.project_ids)
        .execute(pool)
        .await;

        match result {
            Err(e) => {
                if tries == V2_BATCH_MAX_RETRY_ATTEMPTS {
                    metrics::counter!(V2_EVENT_PROPS_BATCH_ATTEMPT, &[("result", "failed")])
                        .increment(1);
                    total_time.fin();
                    error!(
                        "Batch write to posthog_eventproperty exhausted retries: {:?}",
                        &e
                    );

                    // following the old strategy - if the batch write fails,
                    // remove all entries from cache so they get another shot
                    // at persisting on future event submissions
                    batch.uncache_batch(&cache);

                    return Err(e);
                }

                metrics::counter!(V2_EVENT_PROPS_BATCH_ATTEMPT, &[("result", "retry")])
                    .increment(1);
                let jitter = rand::random::<u64>() % 50;
                let delay: u64 = tries * V2_BATCH_RETRY_DELAY_MS + jitter;
                tokio::time::sleep(Duration::from_millis(delay)).await;
                tries += 1;
            }

            Ok(pgq_result) => {
                let count = pgq_result.rows_affected();
                total_time.fin();

                metrics::counter!(V2_EVENT_PROPS_BATCH_ATTEMPT, &[("result", "success")])
                    .increment(1);
                metrics::counter!(V2_EVENT_PROPS_BATCH_SIZE).increment(batch.len() as u64);
                metrics::counter!(V2_EVENT_PROPS_BATCH_ROWS_AFFECTED).increment(count);
                info!(
                    "Event properties batch of size {} written successfully with {} rows changed",
                    batch.len(),
                    count
                );

                return Ok(());
            }
        }
    }
}

async fn write_property_definitions_batch(
    cache: Arc<Cache>,
    batch: PropertyDefinitionsBatch,
    pool: &PgPool,
) -> Result<(), sqlx::Error> {
    let total_time = common_metrics::timing_guard(V2_PROP_DEFS_BATCH_WRITE_TIME, &[]);
    let mut tries: u64 = 1;

    loop {
        // what if we just ditch properties without a property_type set? why update on conflict at all?
        let result = sqlx::query(r#"
            INSERT INTO posthog_propertydefinition (id, name, type, group_type_index, is_numerical, team_id, project_id, property_type)
                (SELECT * FROM UNNEST(
                    $1::uuid[],
                    $2::varchar[],
                    $3::smallint[],
                    $4::smallint[],
                    $5::boolean[],
                    $6::int[],
                    $7::bigint[],
                    $8::varchar[]))
                ON CONFLICT (
                    COALESCE(project_id, team_id::bigint), name, type,
                    COALESCE(group_type_index, -1))
                DO UPDATE SET
                    property_type=EXCLUDED.property_type,
                    is_numerical=EXCLUDED.is_numerical
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
                if tries == V2_BATCH_MAX_RETRY_ATTEMPTS {
                    metrics::counter!(V2_PROP_DEFS_BATCH_ATTEMPT, &[("result", "failed")])
                        .increment(1);
                    total_time.fin();
                    error!(
                        "Batch write to posthog_propertydefinition exhausted retries: {:?}",
                        &e
                    );

                    // following the old strategy - if the batch write fails,
                    // remove all entries from cache so they get another shot
                    // at persisting on future event submissions
                    batch.uncache_batch(&cache);

                    return Err(e);
                }

                metrics::counter!(V2_PROP_DEFS_BATCH_ATTEMPT, &[("result", "retry")]).increment(1);
                let jitter = rand::random::<u64>() % 50;
                let delay: u64 = tries * V2_BATCH_RETRY_DELAY_MS + jitter;
                tokio::time::sleep(Duration::from_millis(delay)).await;
                tries += 1;
            }

            Ok(pgq_result) => {
                let count = pgq_result.rows_affected();
                total_time.fin();

                metrics::counter!(V2_PROP_DEFS_BATCH_ATTEMPT, &[("result", "success")])
                    .increment(1);
                metrics::counter!(V2_PROP_DEFS_BATCH_SIZE).increment(batch.len() as u64);
                metrics::counter!(V2_PROP_DEFS_BATCH_ROWS_AFFECTED).increment(count);
                info!(
                    "Property definitions batch of size {} written successfully with {} rows changed",
                    batch.len(),
                    count
                );

                return Ok(());
            }
        }
    }
}

async fn write_event_definitions_batch(
    cache: Arc<Cache>,
    batch: EventDefinitionsBatch,
    pool: &PgPool,
) -> Result<(), sqlx::Error> {
    let total_time = common_metrics::timing_guard(V2_EVENT_DEFS_BATCH_WRITE_TIME, &[]);
    let mut tries: u64 = 1;

    loop {
        // last_seen_ats are manipulated on event defs for cache expiration
        // at the moment; as in v1 writes, let's keep these fresh per-attempt
        // to ensure the values in the UI are more accurate, and avoid PG 21000
        // errors (constraint violations) when retrying writes w/o tx wrapper
        let mut per_attempt_last_seen_ats: Vec<DateTime<Utc>> = Vec::with_capacity(batch.len());
        let per_attempt_ts = Utc::now();
        for _ in 0..batch.len() {
            per_attempt_last_seen_ats.push(per_attempt_ts);
        }

        // TODO: see if we can eliminate last_seen_at from being exposed in the UI,
        // then convert this stmt to ON CONFLICT DO NOTHING
        let result = sqlx::query(
            r#"
            INSERT INTO posthog_eventdefinition (id, name, team_id, project_id, last_seen_at, created_at)
                (SELECT * FROM UNNEST (
                    $1::uuid[],
                    $2::varchar[],
                    $3::int[],
                    $4::bigint[],
                    $5::timestamptz[],
                    $5::timestamptz[]))
                ON CONFLICT (coalesce(project_id, team_id::bigint), name) DO UPDATE
                    SET last_seen_at=EXCLUDED.last_seen_at
                    WHERE posthog_eventdefinition.last_seen_at < EXCLUDED.last_seen_at"#,
        )
        .bind(&batch.ids)
        .bind(&batch.names)
        .bind(&batch.team_ids)
        .bind(&batch.project_ids)
        .bind(per_attempt_last_seen_ats)
        .execute(pool)
        .await;

        match result {
            Err(e) => {
                if tries == V2_BATCH_MAX_RETRY_ATTEMPTS {
                    metrics::counter!(V2_EVENT_DEFS_BATCH_ATTEMPT, &[("result", "failed")])
                        .increment(1);
                    total_time.fin();
                    error!(
                        "Batch write to posthog_eventdefinition exhausted retries: {:?}",
                        &e
                    );

                    // following the old strategy - if the batch write fails,
                    // remove all entries from cache so they get another shot
                    // at persisting on future event submissions
                    batch.uncache_batch(&cache);

                    return Err(e);
                }

                metrics::counter!(V2_EVENT_DEFS_BATCH_ATTEMPT, &[("result", "retry")]).increment(1);
                let jitter = rand::random::<u64>() % 50;
                let delay: u64 = tries * V2_BATCH_RETRY_DELAY_MS + jitter;
                tokio::time::sleep(Duration::from_millis(delay)).await;
                tries += 1;
            }
            Ok(pgq_result) => {
                let count = pgq_result.rows_affected();
                total_time.fin();

                metrics::counter!(V2_EVENT_DEFS_BATCH_ATTEMPT, &[("result", "success")])
                    .increment(1);
                metrics::counter!(V2_EVENT_DEFS_BATCH_SIZE).increment(batch.len() as u64);
                metrics::counter!(V2_EVENT_DEFS_BATCH_ROWS_AFFECTED).increment(count);
                info!(
                    "Event definitions batch of size {} written successfully with {} rows changed",
                    batch.len(),
                    count
                );

                return Ok(());
            }
        }
    }
}
