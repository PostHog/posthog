use std::{collections::HashMap, time::Duration as StdDuration};

use aws_config::retry::RetryConfig;
use aws_sdk_dynamodb::types::{AttributeValue, KeysAndAttributes, PutRequest, WriteRequest};
use axum::async_trait;
use chrono::{DateTime, Duration, Utc};
use metrics::counter;
use rand::Rng;
use tokio::time::sleep;
use tracing::{error, warn};

use crate::{
    config::Config,
    metrics_utils::{RECENTLY_SEEN_READ_ERRORS, RECENTLY_SEEN_RETRIES, RECENTLY_SEEN_WRITE_ERRORS},
    recently_seen::{DocumentKey, RecentlySeenStore, SeenRecord},
};
const PK: &str = "pk";
const SK: &str = "sk";
const EMITTED_AT: &str = "emitted_at";
const TTL_ATTR: &str = "expires_at";
// DynamoDB caps BatchWriteItem at 25 items and BatchGetItem at 100 keys per request.
const BATCH_WRITE_CHUNK: usize = 25;
const BATCH_GET_CHUNK: usize = 100;
const AWS_MAX_ATTEMPTS: u32 = 5;
const UNPROCESSED_MAX_ATTEMPTS: usize = 5;
const UNPROCESSED_INITIAL_BACKOFF_MS: u64 = 50;

async fn backoff_before_retry(operation: &'static str, attempt: usize) {
    counter!(RECENTLY_SEEN_RETRIES, "operation" => operation).increment(1);
    let max_delay_ms = UNPROCESSED_INITIAL_BACKOFF_MS * 2_u64.pow((attempt - 1) as u32);
    let delay_ms = rand::thread_rng().gen_range(max_delay_ms / 2..=max_delay_ms);
    sleep(StdDuration::from_millis(delay_ms)).await;
}

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

pub async fn build_dynamodb_store(config: &Config) -> DynamoDbStore {
    let ttl = Duration::seconds(config.recent_ids_ttl_seconds);
    let mut loader = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .retry_config(RetryConfig::standard().with_max_attempts(AWS_MAX_ATTEMPTS));
    if let Some(region) = &config.aws_region {
        loader = loader.region(aws_sdk_dynamodb::config::Region::new(region.clone()));
    }
    let shared = loader.load().await;
    let client = aws_sdk_dynamodb::Client::new(&shared);

    DynamoDbStore {
        client,
        table: config.recent_ids_dynamodb_table.clone(),
        ttl,
    }
}

#[async_trait]
impl RecentlySeenStore for DynamoDbStore {
    async fn record(&self, documents: &[SeenRecord]) {
        let expires_at = Utc::now().timestamp() + self.ttl.num_seconds();
        for chunk in documents.chunks(BATCH_WRITE_CHUNK) {
            let mut write_requests = Vec::with_capacity(chunk.len());
            for doc in chunk {
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
                let put = PutRequest::builder()
                    .set_item(Some(item))
                    .build()
                    .expect("item is set");
                write_requests.push(WriteRequest::builder().put_request(put).build());
            }

            let mut pending = write_requests;
            for attempt in 1..=UNPROCESSED_MAX_ATTEMPTS {
                let pending_count = pending.len();
                let mut response = match self
                    .client
                    .batch_write_item()
                    .request_items(self.table.clone(), pending)
                    .send()
                    .await
                {
                    Ok(response) => response,
                    Err(e) => {
                        error!("Failed to write recently-seen records to DynamoDB: {e:?}");
                        counter!(RECENTLY_SEEN_WRITE_ERRORS).increment(pending_count as u64);
                        break;
                    }
                };

                pending = response
                    .unprocessed_items
                    .as_mut()
                    .and_then(|items| items.remove(&self.table))
                    .unwrap_or_default();
                if pending.is_empty() {
                    break;
                }
                if attempt == UNPROCESSED_MAX_ATTEMPTS {
                    warn!(
                        "DynamoDB left {} recently-seen records unprocessed after {attempt} attempts",
                        pending.len()
                    );
                    counter!(RECENTLY_SEEN_WRITE_ERRORS).increment(pending.len() as u64);
                    break;
                }

                backoff_before_retry("write", attempt).await;
            }
        }
    }

    async fn lookup(
        &self,
        team_id: i32,
        keys: Vec<DocumentKey>,
    ) -> HashMap<DocumentKey, Option<DateTime<Utc>>> {
        let mut results: HashMap<DocumentKey, Option<DateTime<Utc>>> =
            keys.iter().cloned().map(|k| (k, None)).collect();

        for chunk in keys.chunks(BATCH_GET_CHUNK) {
            // BatchGetItem rejects duplicate keys, so the reverse index also deduplicates.
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

            let mut pending = KeysAndAttributes::builder()
                .set_keys(Some(request_keys))
                .projection_expression(format!("{PK}, {SK}, {EMITTED_AT}"))
                .build()
                .expect("keys are set");

            for attempt in 1..=UNPROCESSED_MAX_ATTEMPTS {
                let pending_count = pending.keys().len();
                let mut response = match self
                    .client
                    .batch_get_item()
                    .request_items(self.table.clone(), pending)
                    .send()
                    .await
                {
                    Ok(response) => response,
                    Err(e) => {
                        error!("Failed to read recently-seen records from DynamoDB: {e:?}");
                        counter!(RECENTLY_SEEN_READ_ERRORS).increment(pending_count as u64);
                        break;
                    }
                };

                if let Some(items) = response
                    .responses
                    .as_mut()
                    .and_then(|responses| responses.remove(&self.table))
                {
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

                let Some(next_pending) = response
                    .unprocessed_keys
                    .as_mut()
                    .and_then(|keys| keys.remove(&self.table))
                else {
                    break;
                };
                if next_pending.keys().is_empty() {
                    break;
                }
                pending = next_pending;

                if attempt == UNPROCESSED_MAX_ATTEMPTS {
                    warn!(
                        "DynamoDB left {} recently-seen lookups unprocessed after {attempt} attempts",
                        pending.keys().len()
                    );
                    counter!(RECENTLY_SEEN_READ_ERRORS).increment(pending.keys().len() as u64);
                    break;
                }

                backoff_before_retry("read", attempt).await;
            }
        }

        results
    }
}
