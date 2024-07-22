use std::num::NonZeroUsize;

use lru::LruCache;
use sqlx::{postgres::PgPoolOptions, Executor, PgPool, Postgres};
use thiserror::Error;
use time::{Duration, OffsetDateTime};
use tokio::sync::Mutex;
use tracing::warn;

use crate::{config::Config, types::{Event, EventDefinition, EventProperty, PropertyDefinition, TeamEventId, TeamId}};

#[derive(Debug, Error)]
pub enum CacheError {
    #[error("Database error: {0}")]
    DatabaseError(#[from] sqlx::Error)
}

type EventDefinitionCache = LruCache<TeamId, Vec<EventDefinition>>;
type PropertyDefinitionCache = LruCache<TeamId, Vec<PropertyDefinition>>;
type EventPropertyCache = LruCache<TeamEventId, Vec<EventProperty>>;
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
    event_definitions: Mutex<EventDefinitionCache>,
    property_definitions: Mutex<PropertyDefinitionCache>,

    // Per-team, per-event caches
    event_properties: Mutex<EventPropertyCache>,

    // Track if this team has ever inserted an event
    team_first_event_cache: Mutex<TeamFirstEventCache>,
}

impl PropertyCacheManager {

    pub async fn new(config: &Config) -> Result<Self, sqlx::Error> {
        let options = PgPoolOptions::new()
            .max_connections(config.max_pg_connections);

        let pool = options.connect(&config.database_url).await?;

        let capacity = NonZeroUsize::new(10_000).unwrap();

        Ok(Self {
            pool,
            event_definitions: Mutex::new(LruCache::new(capacity)),
            property_definitions: Mutex::new(LruCache::new(capacity)),
            event_properties: Mutex::new(LruCache::new(capacity)),
            team_first_event_cache: Mutex::new(LruCache::new(capacity)),
        })
    }

    pub async fn handle_event(&self, event: Event) -> Result<(), CacheError> {
        let mut tx = self.pool.begin().await?;

        if SKIP_EVENTS.contains(&event.event.as_str()) {
            return Ok(());
        }

        if event.event.len() > EVENT_NAME_CHARFIELD_LENGTH / 2 {
            warn!("Event name too long, skipping: {}", event.event);
            return Ok(())
        }

        // TODO - it would be nicer to hand out read locks here to the cache, and then let them be upgraded to
        // write locks if necessary, but right now this will do.
        update_event_definitions(&mut *tx, &mut *self.event_definitions.lock().await, &event).await?;
        update_property_definitions(&mut *tx, &mut *self.property_definitions.lock().await, &event).await?;
        update_event_properties(&mut *tx, &mut *self.event_properties.lock().await, &event).await?;
        update_team_first_event(&mut *tx, &mut *self.team_first_event_cache.lock().await, &event).await?;

        tx.commit().await?;

        Ok(())
    }
}

async fn update_event_definitions<'c>(db: impl Executor<'c, Database = Postgres>, cache: &mut EventDefinitionCache, event: &Event) -> Result<(), CacheError> {
    let team_id = TeamId(event.team_id);
    let mut new_definition: EventDefinition = event.into();
    new_definition.set_last_seen();

    // If we've never seen any events for this team, insert the first one, and push into the DB
    let Some(definitions) = cache.get_mut(&team_id) else {
        new_definition.upsert(db).await?;
        cache.push(team_id, vec![new_definition]);
        return Ok(());
    };

    // If we haven't seen this event in the cache, add it, also adding to the DB
    let Some(found_definition) = definitions.iter_mut().find(|d| d.name == new_definition.name) else {
        new_definition.upsert(db).await?;
        definitions.push(new_definition);
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
    if LAST_SEEN_AT_UPDATE_LAG < OffsetDateTime::now_utc() - found_last_seen {
        found_definition.set_last_seen();
        found_definition.upsert(db).await?;
    }

    Ok(())
}

async fn update_property_definitions<'c>(db: impl Executor<'c, Database = Postgres>, cache: &mut PropertyDefinitionCache, event: &Event) -> Result<(), CacheError> {
    todo!()
}

async fn update_event_properties<'c>(db: impl Executor<'c, Database = Postgres>, cache: &mut EventPropertyCache , event: &Event) -> Result<(), CacheError> {
    todo!()
}

async fn update_team_first_event<'c>(db: impl Executor<'c, Database = Postgres>, cache: &mut TeamFirstEventCache, event: &Event) -> Result<(), CacheError> {
    todo!()
}

fn sanitize_event_name(event_name: &str) -> String {
    event_name.replace("\u{0000}", "\u{FFFD}")
}