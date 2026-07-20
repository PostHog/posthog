use std::collections::HashMap;

use aws_sdk_dynamodb::types::{AttributeValue, KeysAndAttributes, PutRequest, WriteRequest};
use axum::async_trait;
use chrono::{DateTime, Duration, Utc};
use metrics::counter;
use tracing::{error, warn};

use crate::{
    config::Config,
    metrics_utils::{RECENTLY_SEEN_READ_ERRORS, RECENTLY_SEEN_WRITE_ERRORS},
    recently_seen::{DocumentKey, RecentlySeenStore, SeenRecord},
};
use anyhow::Result;

const PK: &str = "pk";
const SK: &str = "sk";
const EMITTED_AT: &str = "emitted_at";
const TTL_ATTR: &str = "expires_at";
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

pub async fn build_dynamodb_store(config: &Config) -> Result<DynamoDbStore> {
    let ttl = Duration::seconds(config.recent_ids_ttl_seconds);
    let mut loader = aws_config::defaults(aws_config::BehaviorVersion::latest());
    if let Some(region) = &config.aws_region {
        loader = loader.region(aws_sdk_dynamodb::config::Region::new(region.clone()));
    }
    let shared = loader.load().await;
    let client = aws_sdk_dynamodb::Client::new(&shared);

    Ok(DynamoDbStore {
        client,
        table: config.recent_ids_dynamodb_table.clone(),
        ttl,
    })
}

#[async_trait]
impl RecentlySeenStore for DynamoDbStore {
    async fn record(&self, documents: &[SeenRecord]) {
        let ttl_secs = self.ttl.num_seconds();
        for chunk in documents.chunks(BATCH_WRITE_CHUNK) {
            let mut write_requests = Vec::with_capacity(chunk.len());
            for doc in chunk {
                let expires_at = doc.emitted_at.timestamp() + ttl_secs;
                let item = HashMap::from([
                    (
                        PK.to_string(),
                        AttributeValue::S(partition_key(doc.team_id, &doc.key)),
                    ),
                    (
                        SK.to_string(),
                        AttributeValue::S(doc.key.document_id.clone()),
                    ),
                    (
                        EMITTED_AT.to_string(),
                        AttributeValue::S(doc.emitted_at.to_rfc3339()),
                    ),
                    (
                        TTL_ATTR.to_string(),
                        AttributeValue::N(expires_at.to_string()),
                    ),
                ]);
                match PutRequest::builder().set_item(Some(item)).build() {
                    Ok(put) => {
                        write_requests.push(WriteRequest::builder().put_request(put).build())
                    }
                    Err(e) => warn!("Failed to build recently-seen put request: {e:?}"),
                }
            }

            if write_requests.is_empty() {
                continue;
            }

            // UnprocessedItems (throttling) aren't retried — this is a best-effort cache.
            match self
                .client
                .batch_write_item()
                .request_items(self.table.clone(), write_requests)
                .send()
                .await
            {
                Ok(response) => {
                    let unprocessed_count = response
                        .unprocessed_items()
                        .get(&self.table)
                        .map(Vec::len)
                        .unwrap_or_default();
                    if unprocessed_count > 0 {
                        warn!(
                            "DynamoDB left {unprocessed_count} recently-seen records unprocessed"
                        );
                        counter!(RECENTLY_SEEN_WRITE_ERRORS).increment(unprocessed_count as u64);
                    }
                }
                Err(e) => {
                    error!("Failed to write recently-seen records to DynamoDB: {e:?}");
                    counter!(RECENTLY_SEEN_WRITE_ERRORS).increment(chunk.len() as u64);
                }
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
                if index
                    .insert((pk.clone(), sk.clone()), key.clone())
                    .is_some()
                {
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

            let unprocessed_count = response
                .unprocessed_keys()
                .get(&self.table)
                .map(|keys| keys.keys().len())
                .unwrap_or_default();
            if unprocessed_count > 0 {
                warn!("DynamoDB left {unprocessed_count} recently-seen lookups unprocessed");
                counter!(RECENTLY_SEEN_READ_ERRORS).increment(unprocessed_count as u64);
            }

            let Some(items) = response.responses.as_ref().and_then(|r| r.get(&self.table)) else {
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
