use std::{num::NonZeroUsize, str::FromStr};

use lru::LruCache;
use serde_json::Value;
use sqlx::{Executor, Postgres};
use thiserror::Error;
use chrono::{Duration, Utc};
use tokio::sync::Mutex;
use tracing::warn;

use crate::{app_context::{AppContext}, types::{Event, EventDefinition, PropertyDefinition, TeamId}};

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
// TODO - this is a divergence from the TS impl, which maintains a permanent Map<TeamId, LRU>, meaning
// cache invalidation happens on property definition bases across all teams, rather than here, where we're
// doing it on a per-team basis. I'm open to changing this, but as a start point, it feels ok to do it
// this way. The caches above are all identical to the TS impl.
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
pub async fn handle_event(event: Event, context: &AppContext) -> Result<(), CacheError> {

    
    if SKIP_EVENTS.contains(&event.event.as_str()) {
        return Ok(());
    }
    
    if event.event.len() > EVENT_NAME_CHARFIELD_LENGTH / 2 {
        warn!("Event name too long, skipping: {}", event.event);
        return Ok(())
    }


    // We structure this such that we don't update out cache if the transaction fails, to prevent ignoring
    // future updates to the DB that might be needed. This means we end up contending on the cache locks a
    // little bit more, but I think the correctness is worth it. The alternative is to periodically flush
    // the cache, so we're guarenteed to /eventually/ write anything seen frequently, but that means more
    // DB writes, so, :shrug:
    // TODO - It would be much nicer to figure out if we need a transaction, AND THEN create one, rather than
    // preemptively creating one. SQLx has query builder, but you lose a lot of nice stuff if you use them :/
    let mut txn = context.pool.begin().await?;

    let event_def_update = update_event_definitions(&mut txn, &context, &event).await?;
    let prop_def_updates = update_property_definitions(&mut txn, &context, &event).await?;
    let event_prop_updates = update_event_properties(&mut txn, &context, &event).await?;
    let first_event_update = update_team_first_event(&mut txn, &context, &event).await?;

    let need_to_commit = event_def_update.is_some() || prop_def_updates.len() > 0 || event_prop_updates.len() > 0 || first_event_update.is_some();

    if need_to_commit {
        txn.commit().await?;
    } else {
        txn.rollback().await?;
    }

    if let Some(update) = event_def_update {
        context.property_cache.event_definitions.lock().await.put((&update).into(), update);
    }

    if prop_def_updates.len() > 0 {
        let mut lock = context.property_cache.property_definitions.lock().await;
        for update in prop_def_updates {
            lock.put((&update).into(), update);
        }
    }

    if event_prop_updates.len() > 0 {
        let mut lock = context.property_cache.event_properties.lock().await;
        for update in event_prop_updates {
            lock.put(update, true);
        }
    }

    if let Some(team_id) = first_event_update {
        context.property_cache.team_first_event_cache.lock().await.put(team_id, true);
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
        new_definition.upsert(&mut **db).await?;
        return Ok(Some(new_definition));
    };

    // Handle events mis-written into the DB without a last seen field
    let Some(found_last_seen) = existing.last_seen_at else {
        // To prevent the last_seen from being updated in the cache if the DB transaction fails,
        // we clone the existing defintion, update it's last time, use it to update the transaction,
        // and then return it to be "re-inserted" into the cache.
        let mut clone = existing.clone();
        clone.set_last_seen();
        clone.upsert(&mut **db).await?;
        return Ok(Some(clone));
    };

    // If we need to update the last seen field, do so.
    if LAST_SEEN_AT_UPDATE_LAG < (Utc::now() - found_last_seen) {
        // We handle last seen updates exactly the same as if we didn't have a last seen field
        let mut clone = existing.clone();
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
            found.upsert(&mut **db).await?;
            updates.push(found);
            continue;
        };

        // If we have a null we can update, do it.
        if known.property_type.is_none() && found.property_type.is_some() {
            let mut clone = known.clone();
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

    for key in &new_keys {
        key.upsert(&mut **db).await?;
    }

    Ok(new_keys)
}

async fn update_team_first_event<'c>(db: &mut Transaction<'c>, context: &AppContext, event: &Event) -> Result<Option<TeamId>, CacheError> {
    let team_id = event.team_id;
    let cache_guard = context.property_cache.team_first_event_cache.lock().await;
    let seen = cache_guard.contains(&team_id);

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