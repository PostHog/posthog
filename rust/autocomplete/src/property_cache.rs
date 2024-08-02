use std::{num::NonZeroUsize, str::FromStr, time::Instant};

use lru::LruCache;
use metrics::counter;
use serde_json::Value;
use sqlx::{Executor, Postgres};
use thiserror::Error;
use chrono::{Duration, Utc};
use tokio::sync::Mutex;
use tracing::{info, warn};

use crate::{app_context::AppContext, types::{Event, EventDefinition, PropertyDefinition, TeamId}};

#[derive(Debug, Error)]
pub enum CacheError {
    #[error("Database error: {0}")]
    DatabaseError(#[from] sqlx::Error)
}

// Keys for fine-grained caching
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
struct EventDefinitionKey {
    team_id: TeamId,
    event_name: String,
}

impl From<&EventDefinition> for EventDefinitionKey {
    fn from(def: &EventDefinition) -> Self {
        Self {
            team_id: def.team_id,
            event_name: def.name.clone(),
        }
    }
}

#[derive(Debug, Clone, Eq, PartialEq, Hash)]
struct EventPropertyKey {
    team_id: TeamId,
    event_name: String,
    property_name: String,
}

impl EventPropertyKey {
    fn new(team_id: TeamId, event_name: &str, prop: &str) -> Self {
        Self {
            team_id,
            event_name: event_name.to_string(),
            property_name: prop.to_string()
        }
    }
}

#[derive(Debug, Clone, Eq, PartialEq, Hash)]
struct PropertyDefinitionKey {
    team_id: TeamId,
    property_name: String,
    group_type_index: Option<i32>,
}

impl From<&PropertyDefinition> for PropertyDefinitionKey {
    fn from(prop: &PropertyDefinition) -> Self {
        Self {
            team_id: prop.team_id,
            property_name: prop.name.clone(),
            group_type_index: prop.group_type_index,
        }
    }
}

// The fine-grained caching here makes fine-grained locking (on a per-team basis, for example) not possible - if we decide
// we need fine-grained locking due to contention, we should switch to a concurrent cache type.
type EventDefinitionCache = LruCache<EventDefinitionKey, EventDefinition>;
type EventPropertyCache = LruCache<EventPropertyKey, bool>; // We don't actually need a value here, we just need to know if we've seen it before, since this is basically a join
type TeamFirstEventCache = LruCache<TeamId, bool>;
type PropertyDefinitionCache = LruCache<PropertyDefinitionKey, PropertyDefinition>;

type Transaction<'a> = sqlx::Transaction<'a, sqlx::Postgres>;

// TODO: these could be sets and use hashing etc, but I expect the runtime impact
// will be so minimal that it's not worth the effort.
pub const SKIP_EVENTS: &[&str] = &["$$plugin_metrics"];
pub const SKIP_PROPERTIES: &[&str] = &[
    "$set",
    "$set_once",
    "$unset",
    "$group_0",
    "$group_1",
    "$group_2",
    "$group_3",
    "$group_4",
    "$groups",
];

pub const EVENT_NAME_CHARFIELD_LENGTH: usize = 400;
pub const LAST_SEEN_AT_UPDATE_LAG: Duration = Duration::hours(1);

pub struct PropertyCache {

    // Per-team caches
    event_definitions: Mutex<EventDefinitionCache>,
    property_definitions: Mutex<PropertyDefinitionCache>,

    // Per-team, per-event caches
    event_properties: Mutex<EventPropertyCache>,

    // Track if this team has ever inserted an event
    team_first_event_cache: Mutex<TeamFirstEventCache>,
}

impl PropertyCache {

    pub fn new() -> Self {

        let capacity = NonZeroUsize::new(100_000).unwrap(); // TODO - pull this from the environment

        Self {
            event_definitions: Mutex::new(LruCache::new(capacity)),
            property_definitions: Mutex::new(LruCache::new(capacity)),
            event_properties: Mutex::new(LruCache::new(capacity)),
            team_first_event_cache: Mutex::new(LruCache::new(capacity)),
        }
    }

    pub async fn flush(&self) {
        self.event_definitions.lock().await.clear();
        self.property_definitions.lock().await.clear();
        self.event_properties.lock().await.clear();
        self.team_first_event_cache.lock().await.clear();
    }
}

#[derive(Default)]
struct CacheUpdate {
    event_def: Vec<EventDefinition>,
    prop_defs: Vec<PropertyDefinition>,
    event_props: Vec<EventPropertyKey>,
    first_event: Vec<TeamId>,
}

impl CacheUpdate {
    fn is_empty(&self) -> bool {
        self.event_def.is_empty() && self.prop_defs.is_empty() && self.event_props.is_empty() && self.first_event.is_empty()
    }

    async fn do_update(self, context: &AppContext) {
        let mut event_def_cache = context.property_cache.event_definitions.lock().await;
        let mut prop_def_cache = context.property_cache.property_definitions.lock().await;
        let mut event_prop_cache = context.property_cache.event_properties.lock().await;
        let mut first_event_cache = context.property_cache.team_first_event_cache.lock().await;

        for def in self.event_def {
            event_def_cache.put((&def).into(), def);
        }

        for def in self.prop_defs {
            prop_def_cache.put((&def).into(), def);
        }

        for key in self.event_props {
            event_prop_cache.put(key, true);
        }

        for team_id in self.first_event {
            first_event_cache.put(team_id, true);
        }
    }
}

// TODO - there is a problem here - because cache updates are saved until /after/ processing every event, every update
// *within* a transaction batch will be saved, even if a previous event in the same batch would have caused the same update.
// This isn't the end of the world, but does mean on startup or when operating on a very homogenous event stream, we're harder
// on th DB than we need to be.
pub async fn handle_event_batch(events: Vec<Event>, context: &AppContext) -> Result<(), CacheError> {
    let start = Instant::now();
    let mut txn = context.pool.begin().await?;
    info!("Handling transaction batch of {} events", events.len());

    let mut update = CacheUpdate::default();
    for event in events {
        handle_event(event, &mut txn, context, &mut update).await?;
        metrics::counter!("event_handled").increment(1)
    }

    let update_needed = !update.is_empty();
    if update_needed {
        counter!("event_definitions_updated").increment(update.event_def.len() as u64);
        counter!("property_definitions_updated").increment(update.prop_defs.len() as u64);
        counter!("event_properties_updated").increment(update.event_props.len() as u64);
        counter!("team_first_event_updated").increment(update.first_event.len() as u64);
        txn.commit().await?;
        update.do_update(context).await;
    }

    let elapsed = start.elapsed();
    metrics::histogram!("transaction_batch_handle_time_millis", "did_update" => update_needed.to_string()).record(elapsed.as_millis() as f64);

    Ok(())
}

async fn handle_event<'c>(event: Event, txn: &mut Transaction<'c> ,context: &AppContext, update: &mut CacheUpdate) -> Result<(), CacheError> {

    
    if SKIP_EVENTS.contains(&event.event.as_str()) {
        return Ok(());
    }
    
    if event.event.len() > EVENT_NAME_CHARFIELD_LENGTH / 2 {
        warn!("Event name too long, skipping: {}", event.event);
        return Ok(())
    }

    let event_def_update = update_event_definitions(txn, &context, &event).await?;
    let prop_def_updates = update_property_definitions(txn, &context, &event).await?;
    let event_prop_updates = update_event_properties(txn, &context, &event).await?;
    let first_event_update = update_team_first_event(txn, &context, &event).await?;

    if let Some(event_def) = event_def_update {
        update.event_def.push(event_def);
    }

    update.prop_defs.extend(prop_def_updates);
    update.event_props.extend(event_prop_updates);

    if let Some(first_event) = first_event_update {
        update.first_event.push(first_event);
    }


    Ok(())
}

async fn update_event_definitions<'c>(db: &mut Transaction<'c>, context: &AppContext, event: &Event) -> Result<Option<EventDefinition>, CacheError> {
    let mut new_definition: EventDefinition = event.into();
    new_definition.set_last_seen();

    let key = (&new_definition).into();

    let mut cache_guard = context.property_cache.event_definitions.lock().await;

    let existing = cache_guard.get(&key);

    // The event is totally new, so add the DB insert to the txn and return the cache update
    let Some(existing) = existing else {
        drop(cache_guard);
        new_definition.upsert(&mut **db).await?;
        return Ok(Some(new_definition));
    };

    // Handle events mis-written into the DB without a last seen field
    let Some(found_last_seen) = existing.last_seen_at else {
        // To prevent the last_seen from being updated in the cache if the DB transaction fails,
        // we clone the existing defintion, update it's last time, use it to update the transaction,
        // and then return it to be "re-inserted" into the cache.
        let mut clone = existing.clone();
        drop(cache_guard);
        clone.set_last_seen();
        clone.upsert(&mut **db).await?;
        return Ok(Some(clone));
    };

    // If we need to update the last seen field, do so.
    if LAST_SEEN_AT_UPDATE_LAG < (Utc::now() - found_last_seen) {
        // We handle last seen updates exactly the same as if we didn't have a last seen field
        let mut clone = existing.clone();
        drop(cache_guard);
        clone.set_last_seen();
        clone.upsert(&mut **db).await?;
        return Ok(Some(clone));
    }

    Ok(None)
}

async fn update_property_definitions<'c>(db: &mut Transaction<'c>, context: &AppContext, event: &Event) -> Result<Vec<PropertyDefinition>, CacheError> {
    let found_props = event.get_properties(context).await?;

    let mut updates = Vec::with_capacity(found_props.len());

    for found in found_props {

        let key = (&found).into();
        let mut lock = context.property_cache.property_definitions.lock().await;
        let known = lock.get(&key);

        // We've never seen this property before, so insert it
        let Some(known) = known else {
            drop(lock);
            found.upsert(&mut **db).await?;
            updates.push(found);
            continue;
        };

        // If we have a null we can update, do it.
        if known.property_type.is_none() && found.property_type.is_some() {
            let mut clone = known.clone();
            drop(lock);
            clone.property_type = found.property_type;
            clone.upsert(&mut **db).await?;
            updates.push(clone);
            continue;
        }
    }
    Ok(updates)
}

async fn update_event_properties<'c>(db: &mut Transaction<'c>, context: &AppContext, event: &Event) -> Result<Vec<EventPropertyKey>, CacheError> {
    let Some(Ok(Value::Object(props))) = event.properties.as_ref().map(|s| Value::from_str(s)) else {
        return Ok(vec![]);
    };

    let cache_guard = context.property_cache.event_properties.lock().await;

    let new_keys = props.keys()
        .filter(|k| !SKIP_PROPERTIES.contains(&k.as_str()))
        .map(|k| EventPropertyKey::new(event.team_id, &event.event, k))
        .filter(|p| !cache_guard.contains(p)).collect::<Vec<EventPropertyKey>>();

    drop(cache_guard);

    for key in &new_keys {
        key.upsert(&mut **db).await?;
    }

    Ok(new_keys)
}

async fn update_team_first_event<'c>(db: &mut Transaction<'c>, context: &AppContext, event: &Event) -> Result<Option<TeamId>, CacheError> {
    let team_id = event.team_id;
    let cache_guard = context.property_cache.team_first_event_cache.lock().await;
    let seen = cache_guard.contains(&team_id);
    drop(cache_guard);

    if seen {
        return Ok(None);
    }

    sqlx::query!("UPDATE posthog_team SET ingested_event = $1 WHERE id = $2",
        true,
        team_id.0
    ).execute(&mut **db).await?;

    Ok(Some(team_id))
}


impl EventPropertyKey {
    pub async fn upsert<'c>(&self, db: impl Executor<'c, Database = Postgres>) -> Result<(), CacheError> {
        sqlx::query!(
            r#"
            INSERT INTO posthog_eventproperty (team_id, event, property)
            VALUES ($1, $2, $3)
            ON CONFLICT DO NOTHING
            "#,
            self.team_id.0,
            self.event_name,
            self.property_name
        )
            .execute(db)
            .await
            .map_err(CacheError::from)
            .map(|_| ())
    }
}