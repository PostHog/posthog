use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};

use anyhow::Result;
use axum::async_trait;
use chrono::{DateTime, Duration, Utc};

use crate::{
    config::Config,
    recently_seen::{dynamo::build_dynamodb_store, in_memory::InMemoryStore},
};

pub mod dynamo;
pub mod in_memory;

#[derive(Debug, Clone, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
pub struct DocumentKey {
    pub product: String,
    pub document_type: String,
    pub rendering: String,
    pub document_id: String,
}

#[derive(Debug, Clone)]
pub struct SeenRecord {
    pub team_id: i32,
    pub key: DocumentKey,
    pub emitted_at: DateTime<Utc>,
}

#[async_trait]
pub trait RecentlySeenStore: Send + Sync {
    /// Records are best effort; backend failures are logged and metered.
    async fn record(&self, documents: &[SeenRecord]);

    /// Missing and expired documents map to `None`.
    async fn lookup(
        &self,
        team_id: i32,
        keys: Vec<DocumentKey>,
    ) -> HashMap<DocumentKey, Option<DateTime<Utc>>>;
}

pub async fn build_store(config: &Config) -> Result<Arc<dyn RecentlySeenStore>> {
    match config.recent_ids_store.as_str() {
        "dynamodb" => Ok(Arc::new(build_dynamodb_store(config).await)),
        "memory" => Ok(Arc::new(InMemoryStore::new(Duration::seconds(
            config.recent_ids_ttl_seconds,
        )))),
        other => Err(anyhow::anyhow!("Unknown RECENT_IDS_STORE '{other}'")),
    }
}

/// Embedding records are per model; the store is per document.
pub fn dedup_seen(records: impl IntoIterator<Item = SeenRecord>) -> Vec<SeenRecord> {
    let mut seen = HashSet::new();
    records
        .into_iter()
        .filter(|r| seen.insert((r.team_id, r.key.clone())))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(id: &str) -> DocumentKey {
        DocumentKey {
            product: "signals".to_string(),
            document_type: "signal".to_string(),
            rendering: "plain".to_string(),
            document_id: id.to_string(),
        }
    }

    #[tokio::test]
    async fn records_and_looks_up_emit_times_scoped_by_team() {
        let store = InMemoryStore::new(Duration::seconds(604800));
        let ts = Utc::now();
        store
            .record(&[SeenRecord {
                team_id: 1,
                key: key("abc"),
                emitted_at: ts,
            }])
            .await;

        let hits = store.lookup(1, vec![key("abc"), key("missing")]).await;
        assert_eq!(hits.get(&key("abc")), Some(&Some(ts)));
        assert_eq!(hits.get(&key("missing")), Some(&None));

        let other_team = store.lookup(2, vec![key("abc")]).await;
        assert_eq!(other_team.get(&key("abc")), Some(&None));
    }

    #[tokio::test]
    async fn distinguishes_same_id_across_dimensions() {
        let store = InMemoryStore::new(Duration::seconds(604800));
        let ts = Utc::now();
        let signals_doc = key("dup");
        let mut error_doc = key("dup");
        error_doc.product = "error_tracking".to_string();

        store
            .record(&[SeenRecord {
                team_id: 1,
                key: signals_doc.clone(),
                emitted_at: ts,
            }])
            .await;

        let hits = store
            .lookup(1, vec![signals_doc.clone(), error_doc.clone()])
            .await;
        assert_eq!(hits.get(&signals_doc), Some(&Some(ts)));
        assert_eq!(hits.get(&error_doc), Some(&None));
    }

    #[tokio::test]
    async fn ttl_starts_when_record_is_observed() {
        let store = InMemoryStore::new(Duration::seconds(604800));
        let stale = Utc::now() - chrono::Duration::weeks(1) - chrono::Duration::hours(1);
        store
            .record(&[SeenRecord {
                team_id: 1,
                key: key("old"),
                emitted_at: stale,
            }])
            .await;

        let hits = store.lookup(1, vec![key("old")]).await;
        assert_eq!(hits.get(&key("old")), Some(&Some(stale)));
    }

    #[tokio::test]
    async fn expired_records_are_not_returned() {
        let store = InMemoryStore::new(Duration::seconds(-1));
        store
            .record(&[SeenRecord {
                team_id: 1,
                key: key("old"),
                emitted_at: Utc::now(),
            }])
            .await;

        let hits = store.lookup(1, vec![key("old")]).await;
        assert_eq!(hits.get(&key("old")), Some(&None));
    }

    #[test]
    fn dedup_collapses_per_model_records_to_one_per_document() {
        let ts = Utc::now();
        let record = |id: &str| SeenRecord {
            team_id: 1,
            key: key(id),
            emitted_at: ts,
        };
        let deduped = dedup_seen(vec![record("a"), record("a"), record("b")]);
        assert_eq!(deduped.len(), 2);
    }
}
