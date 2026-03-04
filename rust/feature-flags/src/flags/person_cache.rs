//! Cross-request person cache to reduce PostgreSQL load.
//!
//! Caches `(team_id, distinct_id) → Option<Person>` results for a short TTL,
//! avoiding repeated DB queries when the same person is looked up across
//! multiple `/flags` requests within seconds.

use common_types::Person;
use moka::future::Cache;
use std::time::Duration;

/// In-memory cross-request cache for person lookups, keyed by `(team_id, distinct_id)`.
///
/// Caches both found persons (`Some(Person)`) and not-found results (`None`)
/// to avoid repeated DB queries for anonymous or cookieless users.
#[derive(Clone)]
pub struct PersonCache {
    cache: Cache<(i32, String), Option<Person>>,
    enabled: bool,
}

impl PersonCache {
    pub fn new(max_capacity: u64, ttl_seconds: u64, enabled: bool) -> Self {
        let cache = Cache::builder()
            .max_capacity(max_capacity)
            .time_to_live(Duration::from_secs(ttl_seconds))
            .build();

        Self { cache, enabled }
    }

    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    /// Look up a cached person result. Returns `Some(Option<Person>)` on cache hit
    /// (where the inner `Option` distinguishes found vs not-found persons),
    /// or `None` on cache miss.
    pub async fn get(&self, team_id: i32, distinct_id: &str) -> Option<Option<Person>> {
        if !self.enabled {
            return None;
        }
        self.cache.get(&(team_id, distinct_id.to_string())).await
    }

    /// Insert a person lookup result into the cache.
    pub async fn insert(&self, team_id: i32, distinct_id: String, person: Option<Person>) {
        if !self.enabled {
            return;
        }
        self.cache.insert((team_id, distinct_id), person).await;
    }

    pub fn entry_count(&self) -> u64 {
        self.cache.entry_count()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use serde_json::json;
    use uuid::Uuid;

    fn make_person(team_id: i32) -> Person {
        Person {
            id: 42,
            created_at: Utc::now(),
            team_id,
            uuid: Uuid::new_v4(),
            properties: json!({"email": "test@example.com"}),
            is_identified: true,
            is_user_id: None,
            version: Some(1),
        }
    }

    #[tokio::test]
    async fn cache_miss_returns_none() {
        let cache = PersonCache::new(100, 60, true);
        assert!(cache.get(1, "missing").await.is_none());
    }

    #[tokio::test]
    async fn insert_and_get_round_trip() {
        let cache = PersonCache::new(100, 60, true);
        let person = make_person(1);

        cache
            .insert(1, "user-1".to_string(), Some(person.clone()))
            .await;

        let result = cache.get(1, "user-1").await;
        assert!(result.is_some());
        let cached_person = result.unwrap();
        assert!(cached_person.is_some());
        assert_eq!(cached_person.unwrap().id, person.id);
    }

    #[tokio::test]
    async fn negative_caching_stores_none_person() {
        let cache = PersonCache::new(100, 60, true);

        cache.insert(1, "anonymous".to_string(), None).await;

        let result = cache.get(1, "anonymous").await;
        // Cache hit (Some) with a not-found person (None)
        assert!(result.is_some());
        assert!(result.unwrap().is_none());
    }

    #[tokio::test]
    async fn different_team_ids_are_separate_entries() {
        let cache = PersonCache::new(100, 60, true);
        let person = make_person(1);

        cache.insert(1, "user-1".to_string(), Some(person)).await;

        // Same distinct_id, different team
        assert!(cache.get(2, "user-1").await.is_none());
    }

    #[tokio::test]
    async fn ttl_expiration() {
        let cache = PersonCache::new(100, 1, true);
        let person = make_person(1);

        cache.insert(1, "user-1".to_string(), Some(person)).await;
        assert!(cache.get(1, "user-1").await.is_some());

        tokio::time::sleep(Duration::from_secs(2)).await;

        assert!(cache.get(1, "user-1").await.is_none());
    }

    #[tokio::test]
    async fn disabled_cache_always_misses() {
        let cache = PersonCache::new(100, 60, false);
        let person = make_person(1);

        cache.insert(1, "user-1".to_string(), Some(person)).await;

        assert!(cache.get(1, "user-1").await.is_none());
    }

    #[tokio::test]
    async fn multiple_entries_are_independent() {
        let cache = PersonCache::new(100, 60, true);

        cache.insert(1, "a".to_string(), None).await;
        cache.insert(1, "b".to_string(), Some(make_person(1))).await;

        // Both entries are independently retrievable
        let a = cache.get(1, "a").await;
        assert!(a.is_some());
        assert!(a.unwrap().is_none()); // "a" was stored as not-found

        let b = cache.get(1, "b").await;
        assert!(b.is_some());
        assert!(b.unwrap().is_some()); // "b" was stored as found
    }
}
