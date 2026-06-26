//! "Recently emitted" document store.
//!
//! Every document the worker emits to ClickHouse is also recorded here, so callers
//! can cheaply ask "was this document processed, and when?" without running a slow
//! ClickHouse query. Records expire after a configurable TTL (1 week by default).
//!
//! Two backends, chosen by config: an in-memory map for local dev / tests, and
//! DynamoDB for production. Writes are best-effort — the document is already
//! committed to the downstream pipeline by the time we record it, so a store
//! failure must never block or fail ingestion.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use async_trait::async_trait;
use aws_sdk_dynamodb::types::{AttributeValue, KeysAndAttributes, PutRequest, WriteRequest};
use chrono::{DateTime, Utc};
use metrics::counter;
use tokio::sync::Mutex;
use tracing::{error, warn};

use crate::config::Config;
use crate::metrics_utils::{RECENTLY_SEEN_READ_ERRORS, RECENTLY_SEEN_WRITE_ERRORS};

/// Identity of a single emitted document. `document_id` is not unique on its own —
/// the same id recurs across products, document types and renderings — so the full
/// tuple is the key. `team_id` is carried separately on the store API because it is
/// the one dimension a lookup request is guaranteed to share across its documents.
#[derive(Debug, Clone, PartialEq, Eq, Hash, serde::Serialize, serde::Deserialize)]
pub struct DocumentKey {
    pub product: String,
    pub document_type: String,
    pub rendering: String,
    pub document_id: String,
}

/// A document the worker emitted, with the moment it was emitted.
#[derive(Debug, Clone)]
pub struct SeenRecord {
    pub team_id: i32,
    pub key: DocumentKey,
    pub emitted_at: DateTime<Utc>,
}

#[async_trait]
pub trait RecentlySeenStore: Send + Sync {
    /// Best-effort record that `documents` were emitted. Failures are logged and
    /// metered, never propagated.
    async fn record(&self, documents: Vec<SeenRecord>);

    /// For a single team, return the emit timestamp of each requested document, or
    /// `None` for documents never emitted (or whose record has expired).
    async fn lookup(
        &self,
        team_id: i32,
        keys: Vec<DocumentKey>,
    ) -> HashMap<DocumentKey, Option<DateTime<Utc>>>;
}

/// Build the store backend named by config. A DynamoDB init failure falls back to
/// in-memory (loudly) rather than taking down the worker — the recently-seen store
/// is an auxiliary cache, not on the critical embedding path.
pub async fn build_store(config: &Config) -> Arc<dyn RecentlySeenStore> {
    let ttl = Duration::from_secs(config.recent_ids_ttl_seconds);
    match config.recent_ids_backend.to_lowercase().as_str() {
        "dynamodb" => match build_dynamodb_store(config, ttl).await {
            Ok(store) => Arc::new(store),
            Err(e) => {
                error!(
                    "Failed to initialise DynamoDB recently-seen store, falling back to in-memory: {e:?}"
                );
                Arc::new(InMemoryStore::new(ttl))
            }
        },
        "memory" => Arc::new(InMemoryStore::new(ttl)),
        other => {
            warn!("Unknown RECENT_IDS_BACKEND '{other}', defaulting to in-memory");
            Arc::new(InMemoryStore::new(ttl))
        }
    }
}

async fn build_dynamodb_store(config: &Config, ttl: Duration) -> Result<DynamoDbStore> {
    let mut loader = aws_config::defaults(aws_config::BehaviorVersion::latest());
    if let Some(region) = &config.recent_ids_aws_region {
        loader = loader.region(aws_sdk_dynamodb::config::Region::new(region.clone()));
    }
    let shared = loader.load().await;

    let mut builder = aws_sdk_dynamodb::config::Builder::from(&shared);
    if let Some(endpoint) = &config.recent_ids_dynamodb_endpoint {
        builder = builder.endpoint_url(endpoint);
    }
    let client = aws_sdk_dynamodb::Client::from_conf(builder.build());

    Ok(DynamoDbStore {
        client,
        table: config.recent_ids_dynamodb_table.clone(),
        ttl,
    })
}

// ---------------------------------------------------------------------------
// In-memory backend
// ---------------------------------------------------------------------------

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

    fn ttl_chrono(&self) -> chrono::Duration {
        chrono::Duration::from_std(self.ttl).unwrap_or_else(|_| chrono::Duration::weeks(1))
    }
}

#[async_trait]
impl RecentlySeenStore for InMemoryStore {
    async fn record(&self, documents: Vec<SeenRecord>) {
        let ttl = self.ttl_chrono();
        let mut entries = self.entries.lock().await;
        for doc in documents {
            let expires_at = doc.emitted_at + ttl;
            entries.insert((doc.team_id, doc.key), (doc.emitted_at, expires_at));
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

// ---------------------------------------------------------------------------
// DynamoDB backend
// ---------------------------------------------------------------------------

const PK: &str = "pk";
const SK: &str = "sk";
const EMITTED_AT: &str = "emitted_at";
const TTL_ATTR: &str = "ttl";
// DynamoDB caps BatchWriteItem at 25 items and BatchGetItem at 100 keys per request.
const BATCH_WRITE_CHUNK: usize = 25;
const BATCH_GET_CHUNK: usize = 100;

/// Partition key encodes the dimensions a lookup shares; the document id is the sort
/// key. This lets a single lookup fan out efficiently within a team's partitions.
fn partition_key(team_id: i32, key: &DocumentKey) -> String {
    format!(
        "{}#{}#{}#{}",
        team_id, key.product, key.document_type, key.rendering
    )
}

pub struct DynamoDbStore {
    client: aws_sdk_dynamodb::Client,
    table: String,
    ttl: Duration,
}

#[async_trait]
impl RecentlySeenStore for DynamoDbStore {
    async fn record(&self, documents: Vec<SeenRecord>) {
        let ttl_secs = self.ttl.as_secs() as i64;
        for chunk in documents.chunks(BATCH_WRITE_CHUNK) {
            let mut write_requests = Vec::with_capacity(chunk.len());
            for doc in chunk {
                let expires_at = doc.emitted_at.timestamp() + ttl_secs;
                let item = HashMap::from([
                    (
                        PK.to_string(),
                        AttributeValue::S(partition_key(doc.team_id, &doc.key)),
                    ),
                    (SK.to_string(), AttributeValue::S(doc.key.document_id.clone())),
                    (
                        EMITTED_AT.to_string(),
                        AttributeValue::S(doc.emitted_at.to_rfc3339()),
                    ),
                    (TTL_ATTR.to_string(), AttributeValue::N(expires_at.to_string())),
                ]);
                match PutRequest::builder().set_item(Some(item)).build() {
                    Ok(put) => write_requests.push(WriteRequest::builder().put_request(put).build()),
                    Err(e) => warn!("Failed to build recently-seen put request: {e:?}"),
                }
            }

            if write_requests.is_empty() {
                continue;
            }

            // UnprocessedItems (throttling) aren't retried — this is a best-effort cache.
            if let Err(e) = self
                .client
                .batch_write_item()
                .request_items(self.table.clone(), write_requests)
                .send()
                .await
            {
                error!("Failed to write recently-seen records to DynamoDB: {e:?}");
                counter!(RECENTLY_SEEN_WRITE_ERRORS).increment(chunk.len() as u64);
            }
        }
    }

    async fn lookup(
        &self,
        team_id: i32,
        keys: Vec<DocumentKey>,
    ) -> HashMap<DocumentKey, Option<DateTime<Utc>>> {
        // Start every requested key at None so unseen documents are represented.
        let mut results: HashMap<DocumentKey, Option<DateTime<Utc>>> =
            keys.iter().cloned().map(|k| (k, None)).collect();

        for chunk in keys.chunks(BATCH_GET_CHUNK) {
            // Reverse index from the encoded (pk, sk) back to the DocumentKey, and dedup
            // identical keys — BatchGetItem rejects duplicate keys in one request.
            let mut index: HashMap<(String, String), DocumentKey> = HashMap::new();
            let mut request_keys = Vec::with_capacity(chunk.len());
            for key in chunk {
                let pk = partition_key(team_id, key);
                let sk = key.document_id.clone();
                if index.insert((pk.clone(), sk.clone()), key.clone()).is_some() {
                    continue;
                }
                request_keys.push(HashMap::from([
                    (PK.to_string(), AttributeValue::S(pk)),
                    (SK.to_string(), AttributeValue::S(sk)),
                ]));
            }

            if request_keys.is_empty() {
                continue;
            }

            let keys_and_attributes = match KeysAndAttributes::builder()
                .set_keys(Some(request_keys))
                .projection_expression(format!("{PK}, {SK}, {EMITTED_AT}"))
                .build()
            {
                Ok(k) => k,
                Err(e) => {
                    warn!("Failed to build recently-seen get request: {e:?}");
                    continue;
                }
            };

            let response = match self
                .client
                .batch_get_item()
                .request_items(self.table.clone(), keys_and_attributes)
                .send()
                .await
            {
                Ok(r) => r,
                Err(e) => {
                    error!("Failed to read recently-seen records from DynamoDB: {e:?}");
                    counter!(RECENTLY_SEEN_READ_ERRORS).increment(chunk.len() as u64);
                    continue;
                }
            };

            let Some(items) = response
                .responses
                .as_ref()
                .and_then(|r| r.get(&self.table))
            else {
                continue;
            };

            for item in items {
                let (Some(Ok(pk)), Some(Ok(sk))) = (
                    item.get(PK).map(AttributeValue::as_s),
                    item.get(SK).map(AttributeValue::as_s),
                ) else {
                    continue;
                };
                if let Some(doc_key) = index.get(&(pk.clone(), sk.clone())) {
                    let emitted = item
                        .get(EMITTED_AT)
                        .and_then(|v| v.as_s().ok())
                        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
                        .map(|dt| dt.with_timezone(&Utc));
                    results.insert(doc_key.clone(), emitted);
                }
            }
        }

        results
    }
}

/// Deduplicate emitted documents to one `SeenRecord` per identity, keeping the first
/// `emitted_at` seen. A single batch produces one record per model, but the store
/// only cares about the document.
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
        let store = InMemoryStore::new(Duration::from_secs(604800));
        let ts = Utc::now();
        store
            .record(vec![SeenRecord {
                team_id: 1,
                key: key("abc"),
                emitted_at: ts,
            }])
            .await;

        // Seen document for the recording team returns its emit time.
        let hits = store.lookup(1, vec![key("abc"), key("missing")]).await;
        assert_eq!(hits.get(&key("abc")), Some(&Some(ts)));
        // Never-emitted document is None, not absent.
        assert_eq!(hits.get(&key("missing")), Some(&None));

        // Same id under a different team is isolated — team_id is the scoping boundary.
        let other_team = store.lookup(2, vec![key("abc")]).await;
        assert_eq!(other_team.get(&key("abc")), Some(&None));
    }

    #[tokio::test]
    async fn distinguishes_same_id_across_dimensions() {
        let store = InMemoryStore::new(Duration::from_secs(604800));
        let ts = Utc::now();
        let signals_doc = key("dup");
        let mut error_doc = key("dup");
        error_doc.product = "error_tracking".to_string();

        store
            .record(vec![SeenRecord {
                team_id: 1,
                key: signals_doc.clone(),
                emitted_at: ts,
            }])
            .await;

        let hits = store
            .lookup(1, vec![signals_doc.clone(), error_doc.clone()])
            .await;
        assert_eq!(hits.get(&signals_doc), Some(&Some(ts)));
        // Identical document_id under a different product was never emitted.
        assert_eq!(hits.get(&error_doc), Some(&None));
    }

    #[tokio::test]
    async fn expired_records_are_not_returned() {
        let store = InMemoryStore::new(Duration::from_secs(604800));
        // Emitted just over a week ago — past the 1-week TTL.
        let stale = Utc::now() - chrono::Duration::weeks(1) - chrono::Duration::hours(1);
        store
            .record(vec![SeenRecord {
                team_id: 1,
                key: key("old"),
                emitted_at: stale,
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
