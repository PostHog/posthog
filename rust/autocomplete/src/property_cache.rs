use std::num::NonZeroUsize;

use lru::LruCache;
use sqlx::{Executor, PgPool, Postgres};
use thiserror::Error;
use chrono::{Duration, Utc};
use tokio::sync::{Mutex, RwLock};
use tracing::warn;

use crate::types::{Event, EventDefinition, EventProperty, PropertyDefinition, TeamEventId, TeamId};

#[derive(Debug, Error)]
pub enum CacheError {
    #[error("Database error: {0}")]
    DatabaseError(#[from] sqlx::Error)
}

type EventDefinitionCache = LruCache<TeamId, Mutex<Vec<EventDefinition>>>;
type PropertyDefinitionCache = LruCache<TeamId, Mutex<Vec<PropertyDefinition>>>;
type EventPropertyCache = LruCache<TeamEventId, Mutex<Vec<EventProperty>>>;
type TeamFirstEventCache = LruCache<TeamId, bool>;

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

pub struct PropertyCacheManager {
    pool: PgPool,

    // Per-team caches
    event_definitions: RwLock<EventDefinitionCache>,
    property_definitions: RwLock<PropertyDefinitionCache>,

    // Per-team, per-event caches
    event_properties: RwLock<EventPropertyCache>,

    // Track if this team has ever inserted an event
    team_first_event_cache: RwLock<TeamFirstEventCache>,
}

impl PropertyCacheManager {

    pub fn new(pool: &PgPool) -> Self {

        let capacity = NonZeroUsize::new(10_000).unwrap(); // TODO - pull this from the environment

        Self {
            pool: pool.clone(),
            event_definitions: RwLock::new(LruCache::new(capacity)),
            property_definitions: RwLock::new(LruCache::new(capacity)),
            event_properties: RwLock::new(LruCache::new(capacity)),
            team_first_event_cache: RwLock::new(LruCache::new(capacity)),
        }
    }

    pub async fn handle_event(&self, event: Event) -> Result<(), CacheError> {

        if SKIP_EVENTS.contains(&event.event.as_str()) {
            return Ok(());
        }

        if event.event.len() > EVENT_NAME_CHARFIELD_LENGTH / 2 {
            warn!("Event name too long, skipping: {}", event.event);
            return Ok(())
        }

        let team_id = event.team_id;


        let mut event_defs = {
            let lock = self.event_definitions.read().await;
            lock.get_or_insert_mut(team_id, Default::default).lock().await
        };
        update_event_definitions(&self.pool, &mut event_defs, &event).await?;
        drop(event_defs);

        let mut prop_defs = {
            let lock = self.property_definitions.read().await;
            lock.get_or_insert_mut(team_id, Default::default).lock().await
        };
        update_property_definitions(&self.pool, &mut prop_defs, &event).await?;
        drop(prop_defs);

        let mut event_props = {
            let team_event_key = TeamEventId { team_id, event_name: event.event.clone() };
            let lock = self.event_properties.read().await;
            lock.get_or_insert_mut(team_event_key, Default::default).lock().await
        };
        update_event_properties(&self.pool, &mut event_props, &event).await?;
        drop(event_props);


        update_team_first_event(&self.pool, &mut *self.team_first_event_cache.lock().await, &event).await?;


        Ok(())
    }
}

async fn update_event_definitions<'c>(db: impl Executor<'c, Database = Postgres>, defs: &mut Vec<EventDefinition>, event: &Event) -> Result<(), CacheError> {
    let mut new_definition: EventDefinition = event.into();
    new_definition.set_last_seen();

    // If we haven't seen this event in the cache, add it, also adding to the DB
    let Some(found_definition) = defs.iter_mut().find(|d| d.name == new_definition.name) else {
        new_definition.upsert(db).await?;
        defs.push(new_definition);
        return Ok(());
    };

    // Symbolic - we have found a definition in the cache, we don't need to insert it, so drop the "new" one to force us to
    // remember to update the last_seen_at field, if we need to.
    drop(new_definition);

    // Handle events mis-written into the DB without a last seen field.
    let Some(found_last_seen) = found_definition.last_seen_at else {
        found_definition.set_last_seen();
        found_definition.upsert(db).await?;
        return Ok(());
    };

    // If we need to update the last seen field, do so.
    if LAST_SEEN_AT_UPDATE_LAG < (Utc::now() - found_last_seen) {
        found_definition.set_last_seen();
        found_definition.upsert(db).await?;
    }

    Ok(())
}

async fn update_property_definitions<'c>(db: impl Executor<'c, Database = Postgres>, defs: &mut Vec<PropertyDefinition>, event: &Event) -> Result<(), CacheError> {
    let props = event.get_properties().await;
    todo!();
}

async fn update_event_properties<'c>(db: impl Executor<'c, Database = Postgres>, cache: &mut Vec<EventProperty> , event: &Event) -> Result<(), CacheError> {
    todo!()
}

async fn update_team_first_event<'c>(db: impl Executor<'c, Database = Postgres>, cache: &mut TeamFirstEventCache, event: &Event) -> Result<(), CacheError> {
    todo!()
}
