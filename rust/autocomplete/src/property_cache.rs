use std::{num::NonZeroUsize, str::FromStr, sync::Arc};

use lru::LruCache;
use serde_json::Value;
use sqlx::PgPool;
use thiserror::Error;
use chrono::{Duration, Utc};
use tokio::sync::{Mutex, RwLock};
use tracing::warn;

use crate::{app_context::AppContext, types::{Event, EventDefinition, EventProperty, PropertyDefinition, TeamEventId, TeamId}};

#[derive(Debug, Error)]
pub enum CacheError {
    #[error("Database error: {0}")]
    DatabaseError(#[from] sqlx::Error)
}

/*
Right now all the caching is on a per-team basis (for event-props, it's per-team-event). This means if some team
has a lot of properties that are rarely seen, there'll be a lot of cold entries in the cache. We can push the unique
identifiers for a given defitinion into the cache key pretty easily, but that means doing things like pre-loading all
the definitions for a team the first time we see them stops making sense (since it will artificially warm cold entries).

Generally, my view is that the tradeoff here is:
- Have the cache be a 1:1 mapping of key:definition, rather than per-team - this protects us from cold entries and
  makes eviction due to cache pressure much more reasonable (right now all the "cache size limits" are really "team count"
  limits, which means we can still have arbitrary cache sizes if we have a small number of teams with a lot of definitions).
- Have the cache be per-team, which lets us preload nicely, but carries risk of cold entries and of unbounded resident memory
  usage.

Thoughts/todos on caching (figuring what strategy is good):
- [ ] Add metrics on P10-P99 event/property/eventprop count on a per-team basis
- [ ] Track the last time definitions are seen, so we can report if a given team has a lot of
      definitions that are seen very rarely
- [ ] Start tracking per-team definition sparsity - if some teams have a lot of definitions
      that are very rarely seen, then caching on a per-team basis is a bad idea, and we should
      push property names into the cache key.


The other TODO here is that I make heavy use of the assumption "the number of definitions of any given type, per team, is small".
I use Vec's everywhere instead of Set's or HashMaps. If anyone ever looks at the CPU utilisation of this service and it's
higher than expected, this is the first place to look. I did this for convenience when writing the code (I didn't want to define
the hash/eq impls for the types up front, it was easier just to write the filter fn's where they're used, as I went)
*/
type EventDefinitionCache = LruCache<TeamId, Arc<Mutex<Vec<EventDefinition>>>>;
type EventPropertyCache = LruCache<TeamEventId, Arc<Mutex<Vec<EventProperty>>>>;
type TeamFirstEventCache = LruCache<TeamId, bool>;
// TODO - this is a divergence from the TS impl, which maintains a permanent Map<TeamId, LRU>, meaning
// cache invalidation happens on property definition bases across all teams, rather than here, where we're
// doing it on a per-team basis. I'm open to changing this, but as a start point, it feels ok to do it
// this way. The caches above are all identical to the TS impl.
type PropertyDefinitionCache = LruCache<TeamId, Arc<Mutex<Vec<PropertyDefinition>>>>;

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

    pub async fn flush(&self) {
        self.event_definitions.write().await.clear();
        self.property_definitions.write().await.clear();
        self.event_properties.write().await.clear();
        self.team_first_event_cache.write().await.clear();
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
    
    let cache = &context.property_cache;
    let team_id = event.team_id;
    let mut txn = cache.pool.begin().await?;

    let event_defs = {
        cache.event_definitions.write().await.get_or_insert(team_id, Default::default).clone()
    };
    update_event_definitions(&mut txn, &mut *event_defs.lock().await, &event).await?;
    drop(event_defs);

    let prop_defs = {
        cache.property_definitions.write().await.get_or_insert(team_id, Default::default).clone()
    };
    update_property_definitions(&mut txn, &mut *prop_defs.lock().await, &event, context).await?;
    drop(prop_defs);

    let event_props = {
        let team_event_id = TeamEventId { team_id, event_name: event.event.clone() };
        cache.event_properties.write().await.get_or_insert(team_event_id, Default::default).clone()
    };
    update_event_properties(&mut txn, &mut *event_props.lock().await, &event).await?;
    drop(event_props);


    update_team_first_event(&mut txn, &mut *cache.team_first_event_cache.write().await, &event).await?;

    txn.commit().await?;


    Ok(())
}

async fn update_event_definitions<'c>(db: &mut Transaction<'c>, defs: &mut Vec<EventDefinition>, event: &Event) -> Result<(), CacheError> {
    let mut new_definition: EventDefinition = event.into();
    new_definition.set_last_seen();

    // If we haven't seen this event in the cache, add it, also adding to the DB
    let Some(found_definition) = defs.iter_mut().find(|d| d.name == new_definition.name) else {
        // One of the sillier de/ref stacks I've seen, the explanation is: Transaction can be treated as a DerefMut to a DB connectin,
        // but &mut transaction can't, so we * to go &mut Transaction -> Transaction, then * to go Transaction -> DB::Connection,
        // then pass a &mut Connection to something that needs an "executor" (which a &mut Connection is)
        new_definition.upsert(&mut **db).await?;
        defs.push(new_definition);
        return Ok(());
    };

    // Symbolic - we have found a definition in the cache, we don't need to insert it, so drop the "new" one to force us to
    // remember to update the last_seen_at field, if we need to.
    drop(new_definition);

    // Handle events mis-written into the DB without a last seen field.
    let Some(found_last_seen) = found_definition.last_seen_at else {
        found_definition.set_last_seen();
        found_definition.upsert(&mut **db).await?;
        return Ok(());
    };

    // If we need to update the last seen field, do so.
    if LAST_SEEN_AT_UPDATE_LAG < (Utc::now() - found_last_seen) {
        found_definition.set_last_seen();
        found_definition.upsert(&mut **db).await?;
    }

    Ok(())
}

async fn update_property_definitions<'c>(db: &mut Transaction<'c>, known_defs: &mut Vec<PropertyDefinition>, event: &Event, context: &AppContext) -> Result<(), CacheError> {
    let found_props = event.get_properties(context).await?;

    let prop_def_eq = |a: &PropertyDefinition, b: &PropertyDefinition| {
        a.team_id == b.team_id
        && a.name == b.name
        && a.event_type == b.event_type
        && a.group_type_index == b.group_type_index
    };

    for found in found_props {

        let seen: bool = known_defs.iter().any(|d| prop_def_eq(d, &found));
        if seen {
            continue;
        }

        // We've never seen this property before, so insert it
        found.upsert(&mut **db).await?;
        known_defs.push(found);

    }
    Ok(())
}

async fn update_event_properties<'c>(db: &mut Transaction<'c>, cache: &mut Vec<EventProperty> , event: &Event) -> Result<(), CacheError> {
    let Some(Ok(Value::Object(props))) = event.properties.as_ref().map(|s| Value::from_str(s)) else {
        return Ok(());
    };

    let found_keys = props.keys()
        .filter(|k| !SKIP_PROPERTIES.contains(&k.as_str()))
        .map(|k| EventProperty(k.clone()))
        .filter(|p| !cache.contains(p)).collect::<Vec<EventProperty>>();

    for key in found_keys {
        EventProperty::upsert(&mut **db, event.team_id, event.event.clone(), key.clone()).await?;
        cache.push(key);
    }

    Ok(())
}

async fn update_team_first_event<'c>(db: &mut Transaction<'c>, cache: &mut TeamFirstEventCache, event: &Event) -> Result<(), CacheError> {
    let team_id = event.team_id;
    let seen = cache.contains(&team_id);

    if seen {
        return Ok(());
    }

    sqlx::query!("UPDATE posthog_team SET ingested_event = $1 WHERE id = $2",
        true,
        team_id.0
    ).execute(&mut **db).await?;

    cache.put(team_id, true);

    Ok(())
}
