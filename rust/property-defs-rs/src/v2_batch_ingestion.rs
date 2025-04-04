use std::{collections::VecDeque, sync::Arc, time::Duration};

use chrono::{DateTime, Utc};
use quick_cache::sync::Cache;
use sqlx::PgPool;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};
use uuid::Uuid;

use crate::{
    config::Config,
    metrics_consts::{
        CACHE_CONSUMED, V2_EVENT_DEFS_BATCH_ATTEMPT, V2_EVENT_DEFS_BATCH_CACHE_TIME,
        V2_EVENT_DEFS_BATCH_ROWS_AFFECTED, V2_EVENT_DEFS_BATCH_WRITE_TIME, V2_EVENT_DEFS_CACHE_HIT,
        V2_EVENT_DEFS_CACHE_MISS, V2_EVENT_PROPS_BATCH_ATTEMPT, V2_EVENT_PROPS_BATCH_CACHE_TIME,
        V2_EVENT_PROPS_BATCH_ROWS_AFFECTED, V2_EVENT_PROPS_BATCH_WRITE_TIME,
        V2_EVENT_PROPS_CACHE_HIT, V2_EVENT_PROPS_CACHE_MISS, V2_PROP_DEFS_BATCH_ATTEMPT,
        V2_PROP_DEFS_BATCH_CACHE_TIME, V2_PROP_DEFS_BATCH_ROWS_AFFECTED,
        V2_PROP_DEFS_BATCH_WRITE_TIME, V2_PROP_DEFS_CACHE_HIT, V2_PROP_DEFS_CACHE_MISS,
    },
    types::{
        EventDefinition, EventProperty, GroupType, PropertyDefinition, PropertyParentType, Update,
    },
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

    pub to_cache: VecDeque<Update>,
}

impl EventPropertiesBatch {
    pub fn new(batch_size: usize) -> Self {
        Self {
            batch_size,
            team_ids: Vec::with_capacity(batch_size),
            project_ids: Vec::with_capacity(batch_size),
            event_names: Vec::with_capacity(batch_size),
            property_names: Vec::with_capacity(batch_size),
            to_cache: VecDeque::with_capacity(batch_size),
        }
    }

    pub fn append(&mut self, ep: EventProperty) {
        self.team_ids.push(ep.team_id);
        self.project_ids.push(ep.project_id);
        self.event_names.push(ep.event.clone());
        self.property_names.push(ep.property.clone());

        self.to_cache.push_back(Update::EventProperty(ep));
    }

    pub fn should_flush_batch(&self) -> bool {
        self.team_ids.len() >= self.batch_size
    }

    pub fn is_empty(&self) -> bool {
        self.team_ids.len() == 0
    }

    pub fn cache_batch(&mut self, cache: &Arc<Cache<Update, ()>>) {
        let timer = common_metrics::timing_guard(V2_EVENT_PROPS_BATCH_CACHE_TIME, &[]);

        for update in self.to_cache.drain(..) {
            if cache.contains_key(&update) {
                metrics::counter!(V2_EVENT_PROPS_CACHE_HIT).increment(1);
            } else {
                cache.insert(update, ());
                metrics::counter!(V2_EVENT_PROPS_CACHE_MISS).increment(1);
            }
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
    pub to_cache: VecDeque<Update>,
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
            to_cache: VecDeque::with_capacity(batch_size),
        }
    }

    pub fn append(&mut self, ed: EventDefinition) {
        self.ids.push(Uuid::now_v7());
        self.names.push(ed.name.clone());
        self.team_ids.push(ed.team_id);
        self.project_ids.push(ed.project_id);
        self.last_seen_ats.push(ed.last_seen_at);

        self.to_cache.push_back(Update::Event(ed));
    }

    pub fn should_flush_batch(&self) -> bool {
        self.ids.len() >= self.batch_size
    }

    pub fn is_empty(&self) -> bool {
        self.ids.len() == 0
    }

    pub fn cache_batch(mut self, cache: &Arc<Cache<Update, ()>>) {
        let timer = common_metrics::timing_guard(V2_EVENT_DEFS_BATCH_CACHE_TIME, &[]);
        for update in self.to_cache.drain(..) {
            if cache.contains_key(&update) {
                metrics::counter!(V2_EVENT_DEFS_CACHE_HIT).increment(1);
            } else {
                cache.insert(update, ());
                metrics::counter!(V2_EVENT_DEFS_CACHE_MISS).increment(1);
            }
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
    pub to_cache: VecDeque<Update>,
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
            to_cache: VecDeque::with_capacity(batch_size),
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

        self.to_cache.push_back(Update::Property(pd));
    }

    pub fn should_flush_batch(&self) -> bool {
        self.ids.len() >= self.batch_size
    }

    pub fn is_empty(&self) -> bool {
        self.ids.len() == 0
    }

    pub fn cache_batch(&mut self, cache: &Arc<Cache<Update, ()>>) {
        let timer = common_metrics::timing_guard(V2_PROP_DEFS_BATCH_CACHE_TIME, &[]);
        for update in self.to_cache.drain(..) {
            if cache.contains_key(&update) {
                metrics::counter!(V2_PROP_DEFS_CACHE_HIT).increment(1);
            } else {
                cache.insert(update, ());
                metrics::counter!(V2_PROP_DEFS_CACHE_MISS).increment(1);
            }
        }
        timer.fin();
    }
}

// HACK: making this public so the test suite file can live under "../tests/" dir
pub async fn process_batch_v2(
    config: &Config,
    cache: Arc<Cache<Update, ()>>,
    pool: &PgPool,
    batch: Vec<Update>,
) {
    let cache_utilization = cache.len() as f64 / config.cache_capacity as f64;
    metrics::gauge!(CACHE_CONSUMED).set(cache_utilization);

    // TODO(eli): implement v1-style delay while cache is warming?

    // prep reshaped, isolated data batch bufffers and async join handles
    let mut event_defs = EventDefinitionsBatch::new(config.v2_ingest_batch_size);
    let mut event_props = EventPropertiesBatch::new(config.v2_ingest_batch_size);
    let mut prop_defs = PropertyDefinitionsBatch::new(config.v2_ingest_batch_size);
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
                event_defs.append(ed);
                if event_defs.should_flush_batch() {
                    let pool = pool.clone();
                    let cache = cache.clone();
                    handles.push(tokio::spawn(async move {
                        write_event_definitions_batch(cache, event_defs, &pool).await
                    }));
                    event_defs = EventDefinitionsBatch::new(config.v2_ingest_batch_size);
                }
            }
            Update::EventProperty(ep) => {
                event_props.append(ep);
                if event_props.should_flush_batch() {
                    let pool = pool.clone();
                    let cache = cache.clone();
                    handles.push(tokio::spawn(async move {
                        write_event_properties_batch(cache, event_props, &pool).await
                    }));
                    event_props = EventPropertiesBatch::new(config.v2_ingest_batch_size);
                }
            }
            Update::Property(pd) => {
                prop_defs.append(pd);
                if prop_defs.should_flush_batch() {
                    let pool = pool.clone();
                    let cache = cache.clone();
                    handles.push(tokio::spawn(async move {
                        write_property_definitions_batch(cache, prop_defs, &pool).await
                    }));
                    prop_defs = PropertyDefinitionsBatch::new(config.v2_ingest_batch_size);
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

    for handle in handles {
        match handle.await {
            Ok(result) => match result {
                Ok(_) => continue,
                Err(db_err) => {
                    error!("Batch write exhausted retries: {:?}", db_err);
                }
            },
            Err(join_err) => {
                warn!("Batch query JoinError: {:?}", join_err);
            }
        }
    }
}

async fn write_event_properties_batch(
    cache: Arc<Cache<Update, ()>>,
    mut batch: EventPropertiesBatch,
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

                // now it's safe to cache the original updates
                // timing is measured internally for this step
                batch.cache_batch(&cache);

                // don't report success if the batch cache insetions failed!
                metrics::counter!(V2_EVENT_PROPS_BATCH_ATTEMPT, &[("result", "success")])
                    .increment(1);
                metrics::counter!(V2_EVENT_PROPS_BATCH_ROWS_AFFECTED).increment(count);
                info!(
                    "Event properties batch of size {} written successfully",
                    count
                );

                return Ok(());
            }
        }
    }
}

async fn write_property_definitions_batch(
    cache: Arc<Cache<Update, ()>>,
    mut batch: PropertyDefinitionsBatch,
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
                if tries == V2_BATCH_MAX_RETRY_ATTEMPTS {
                    metrics::counter!(V2_PROP_DEFS_BATCH_ATTEMPT, &[("result", "failed")])
                        .increment(1);
                    total_time.fin();
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

                // now it's safe to cache the original updates
                batch.cache_batch(&cache);

                // don't report success if the batch cache insetions failed!
                metrics::counter!(V2_PROP_DEFS_BATCH_ATTEMPT, &[("result", "success")])
                    .increment(1);
                metrics::counter!(V2_PROP_DEFS_BATCH_ROWS_AFFECTED).increment(count);
                info!(
                    "Property definitions batch of size {} written successfully",
                    count
                );

                return Ok(());
            }
        }
    }
}

async fn write_event_definitions_batch(
    cache: Arc<Cache<Update, ()>>,
    batch: EventDefinitionsBatch,
    pool: &PgPool,
) -> Result<(), sqlx::Error> {
    let total_time = common_metrics::timing_guard(V2_EVENT_DEFS_BATCH_WRITE_TIME, &[]);
    let mut tries: u64 = 1;

    loop {
        // TODO: is last_seen_at critical to the product UX? "ON CONFLICT DO NOTHING" may be much cheaper...
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
        .bind(&batch.last_seen_ats)
        .execute(pool)
        .await;

        match result {
            Err(e) => {
                if tries == V2_BATCH_MAX_RETRY_ATTEMPTS {
                    metrics::counter!(V2_EVENT_DEFS_BATCH_ATTEMPT, &[("result", "failed")])
                        .increment(1);
                    total_time.fin();
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

                // now it's safe to cache the original updates
                batch.cache_batch(&cache);

                // don't report success if the batch cache insertions failed!
                metrics::counter!(V2_EVENT_DEFS_BATCH_ATTEMPT, &[("result", "retry")]).increment(1);
                metrics::counter!(V2_EVENT_DEFS_BATCH_ROWS_AFFECTED).increment(count);
                info!(
                    "Event definitions batch of size {} written successfully",
                    count
                );

                return Ok(());
            }
        }
    }
}
