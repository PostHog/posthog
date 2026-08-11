use std::collections::HashMap;

use axum::async_trait;
use chrono::{DateTime, Duration, Utc};
use moka::sync::Cache;

use crate::recently_seen::{DocumentKey, RecentlySeenStore, SeenRecord};

const MAX_CAPACITY: u64 = 100_000;

pub struct InMemoryStore {
    entries: Cache<(i32, DocumentKey), DateTime<Utc>>,
}

impl InMemoryStore {
    pub fn new(ttl: Duration) -> Self {
        Self::with_capacity(ttl, MAX_CAPACITY)
    }

    fn with_capacity(ttl: Duration, max_capacity: u64) -> Self {
        Self {
            entries: Cache::builder()
                .max_capacity(max_capacity)
                .time_to_live(ttl.to_std().unwrap_or_default())
                .build(),
        }
    }
}

#[async_trait]
impl RecentlySeenStore for InMemoryStore {
    async fn record(&self, documents: &[SeenRecord]) {
        for doc in documents {
            self.entries
                .insert((doc.team_id, doc.key.clone()), doc.emitted_at);
        }
    }

    async fn lookup(
        &self,
        team_id: i32,
        keys: Vec<DocumentKey>,
    ) -> HashMap<DocumentKey, Option<DateTime<Utc>>> {
        keys.into_iter()
            .map(|key| {
                let emitted = self.entries.get(&(team_id, key.clone()));
                (key, emitted)
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(id: &str) -> SeenRecord {
        SeenRecord {
            team_id: 1,
            key: DocumentKey {
                product: "signals".to_string(),
                document_type: "signal".to_string(),
                rendering: "plain".to_string(),
                document_id: id.to_string(),
            },
            emitted_at: Utc::now(),
        }
    }

    #[tokio::test]
    async fn evicts_entries_when_capacity_is_reached() {
        let store = InMemoryStore::with_capacity(Duration::hours(1), 1);
        let first = record("first");
        let second = record("second");

        store.record(&[first.clone(), second.clone()]).await;
        store.entries.run_pending_tasks();

        let results = store.lookup(1, vec![first.key, second.key]).await;
        assert_eq!(results.values().filter(|value| value.is_some()).count(), 1);
    }
}
