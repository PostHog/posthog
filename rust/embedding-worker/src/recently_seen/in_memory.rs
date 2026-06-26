use std::collections::HashMap;

use axum::async_trait;
use chrono::{DateTime, Duration, Utc};
use tokio::sync::Mutex;

use crate::recently_seen::{DocumentKey, RecentlySeenStore, SeenRecord};

// (emitted_at, expires_at), keyed by the team and document identity.
type Entries = HashMap<(i32, DocumentKey), (DateTime<Utc>, DateTime<Utc>)>;

pub struct InMemoryStore {
    ttl: Duration,
    entries: Mutex<Entries>,
}

impl InMemoryStore {
    pub fn new(ttl: Duration) -> Self {
        Self {
            ttl,
            entries: Mutex::new(HashMap::new()),
        }
    }

    fn ttl_chrono(&self) -> Duration {
        self.ttl
    }
}

#[async_trait]
impl RecentlySeenStore for InMemoryStore {
    async fn record(&self, documents: &[SeenRecord]) {
        let ttl = self.ttl_chrono();
        let mut entries = self.entries.lock().await;
        for doc in documents {
            let expires_at = doc.emitted_at + ttl;
            entries.insert((doc.team_id, doc.key.clone()), (doc.emitted_at, expires_at));
        }
    }

    async fn lookup(
        &self,
        team_id: i32,
        keys: Vec<DocumentKey>,
    ) -> HashMap<DocumentKey, Option<DateTime<Utc>>> {
        let now = Utc::now();
        let mut entries = self.entries.lock().await;
        // Opportunistically drop expired entries so a long-lived dev process can't grow unbounded.
        entries.retain(|_, (_, expires_at)| *expires_at > now);
        keys.into_iter()
            .map(|key| {
                let emitted = entries.get(&(team_id, key.clone())).map(|(ts, _)| *ts);
                (key, emitted)
            })
            .collect()
    }
}
