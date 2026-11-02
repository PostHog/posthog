//! Every recorder pod sends each reference it sees once a day, so without a read of the fetcher's crawl history most
//! jobs are ones the fetcher drops on arrival.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use aws_sdk_dynamodb::types::{AttributeValue, KeysAndAttributes};
use futures::stream::{self, StreamExt};
use metrics::{counter, histogram};
use rand::Rng;
use serde::Deserialize;
use serde_json::Value;

pub const DYNAMODB_BATCH_GET_KEY_LIMIT: usize = 100;
const READS_IN_FLIGHT: usize = 16;

/// At most the fetcher's `REFRESH_INTERVAL_MS` in `image-fetch-v4/raw-image-store.ts`. A longer interval here drops
/// the jobs that refresh a stored image, and S3 then expires images that blocks still reference.
const REFRESH_INTERVAL_MS: f64 = 7.0 * 24.0 * 3600.0 * 1000.0;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct UrlHistory {
    pub next_fetch_at_ms: f64,
    pub stored_at_ms: Option<f64>,
}

impl UrlHistory {
    /// The rule in `image-fetch-v4/url-fetch-consumer.ts`: before its next fetch time, a job only refreshes a stored
    /// image that is at least the refresh interval old.
    pub fn fetcher_drops(&self, now_ms: i64) -> bool {
        let now_ms = now_ms as f64;
        let refresh_due = self
            .stored_at_ms
            .is_some_and(|stored_at_ms| now_ms - stored_at_ms >= REFRESH_INTERVAL_MS);
        self.next_fetch_at_ms > now_ms && !refresh_due
    }
}

#[derive(Debug, thiserror::Error)]
#[error("reading the image fetch history failed: {0}")]
pub struct HistoryError(pub String);

#[async_trait]
pub trait FetchHistory: Send + Sync {
    /// Reads at most [`DYNAMODB_BATCH_GET_KEY_LIMIT`] references. A reference without a URL entry that parses is absent.
    async fn read(
        &self,
        references: &[String],
    ) -> Result<HashMap<String, UrlHistory>, HistoryError>;
}

pub struct AwsFetchHistory {
    client: aws_sdk_dynamodb::Client,
    table: String,
}

impl AwsFetchHistory {
    pub fn new(client: aws_sdk_dynamodb::Client, table: String) -> Self {
        Self { client, table }
    }
}

#[async_trait]
impl FetchHistory for AwsFetchHistory {
    async fn read(
        &self,
        references: &[String],
    ) -> Result<HashMap<String, UrlHistory>, HistoryError> {
        let mut pending: Vec<HashMap<String, AttributeValue>> = references
            .iter()
            .map(|reference| {
                HashMap::from([("key".to_owned(), AttributeValue::S(reference.clone()))])
            })
            .collect();
        let mut entries = HashMap::new();
        let mut attempt = 0;
        // The caller's deadline ends this loop. DynamoDB returns the keys it skipped under throttling.
        while !pending.is_empty() {
            if attempt > 0 {
                tokio::time::sleep(backoff(attempt)).await;
            }
            attempt += 1;
            // `key` and `value` are DynamoDB reserved words.
            let request = KeysAndAttributes::builder()
                .set_keys(Some(std::mem::take(&mut pending)))
                .projection_expression("#k, #v")
                .expression_attribute_names("#k", "key")
                .expression_attribute_names("#v", "value")
                .build()
                .map_err(|e| HistoryError(e.to_string()))?;
            let output = self
                .client
                .batch_get_item()
                .request_items(&self.table, request)
                .send()
                .await
                .map_err(|e| HistoryError(e.to_string()))?;
            for item in output
                .responses()
                .and_then(|r| r.get(&self.table))
                .into_iter()
                .flatten()
            {
                if let Some((reference, entry)) = url_history(item) {
                    entries.insert(reference, entry);
                }
            }
            pending = output
                .unprocessed_keys()
                .and_then(|u| u.get(&self.table))
                .map(|u| u.keys().to_vec())
                .unwrap_or_default();
        }
        Ok(entries)
    }
}

/// The JSON that `image-fetch-v4/dynamodb-crawl-history.ts` stores in `value`.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct StoredEntry {
    kind: String,
    key: String,
    next_fetch_at_ms: f64,
    stored_at_ms: Option<f64>,
}

fn url_history(item: &HashMap<String, AttributeValue>) -> Option<(String, UrlHistory)> {
    let reference = item.get("key")?.as_s().ok()?;
    let stored: StoredEntry = serde_json::from_str(item.get("value")?.as_s().ok()?).ok()?;
    if stored.kind != "url" || &stored.key != reference {
        return None;
    }
    let entry = UrlHistory {
        next_fetch_at_ms: stored.next_fetch_at_ms,
        stored_at_ms: stored.stored_at_ms,
    };
    Some((stored.key, entry))
}

fn backoff(attempt: u32) -> Duration {
    let ceiling = 3_000u64.min(50u64.saturating_mul(1 << attempt.min(16)));
    Duration::from_millis(rand::thread_rng().gen_range(ceiling / 2..=ceiling))
}

/// Returns the jobs to send and the references it dropped. A read that fails or is still running at `deadline` drops
/// none of its jobs, so the fetcher decides them.
pub async fn without_fresh(
    history: &dyn FetchHistory,
    mut jobs: BTreeMap<String, Vec<Value>>,
    now_ms: i64,
    deadline: tokio::time::Instant,
) -> (BTreeMap<String, Vec<Value>>, Vec<String>) {
    let references: Vec<String> = jobs
        .values()
        .flatten()
        .filter_map(|job| job["originalRef"].as_str().map(str::to_owned))
        .collect();
    if references.is_empty() {
        return (jobs, Vec::new());
    }
    let started = Instant::now();
    let reads: Vec<_> = references
        .chunks(DYNAMODB_BATCH_GET_KEY_LIMIT)
        .map(|chunk| async move {
            let read = tokio::time::timeout_at(deadline, history.read(chunk)).await;
            (chunk.len(), read)
        })
        .collect();
    let reads: Vec<_> = stream::iter(reads)
        .buffer_unordered(READS_IN_FLIGHT)
        .collect()
        .await;
    histogram!("ai_research_v4_recorder_image_fetch_history_duration_seconds")
        .record(started.elapsed().as_secs_f64());

    let mut fresh = HashSet::new();
    let mut unread = 0;
    let mut first_error = None;
    for (count, read) in reads {
        match read {
            Ok(Ok(entries)) => fresh.extend(
                entries
                    .into_iter()
                    .filter(|(_, entry)| entry.fetcher_drops(now_ms))
                    .map(|(reference, _)| reference),
            ),
            Ok(Err(error)) => {
                unread += count;
                first_error.get_or_insert_with(|| error.to_string());
            }
            Err(_) => {
                unread += count;
                first_error.get_or_insert_with(|| "the read ran past its deadline".to_owned());
            }
        }
    }
    if let Some(error) = first_error {
        tracing::warn!(%error, references = unread, "image fetch history read failed: those jobs go out unchecked");
    }
    for domain_jobs in jobs.values_mut() {
        domain_jobs.retain(|job| {
            !job["originalRef"]
                .as_str()
                .is_some_and(|reference| fresh.contains(reference))
        });
    }
    jobs.retain(|_, domain_jobs| !domain_jobs.is_empty());

    let checked = references.len() - unread;
    counter!("ai_research_v4_recorder_image_fetch_history_total", "outcome" => "fresh")
        .increment(fresh.len() as u64);
    counter!("ai_research_v4_recorder_image_fetch_history_total", "outcome" => "miss")
        .increment(checked.saturating_sub(fresh.len()) as u64);
    counter!("ai_research_v4_recorder_image_fetch_history_total", "outcome" => "error")
        .increment(unread as u64);
    (jobs, fresh.into_iter().collect())
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    const NOW_MS: i64 = 1_793_000_000_000;
    const DAY_MS: f64 = 24.0 * 3600.0 * 1000.0;

    struct MemoryHistory(HashMap<String, UrlHistory>);

    #[async_trait]
    impl FetchHistory for MemoryHistory {
        async fn read(
            &self,
            references: &[String],
        ) -> Result<HashMap<String, UrlHistory>, HistoryError> {
            Ok(references
                .iter()
                .filter_map(|r| self.0.get(r).map(|entry| (r.clone(), *entry)))
                .collect())
        }
    }

    enum Broken {
        Failing,
        Stalled,
    }

    #[async_trait]
    impl FetchHistory for Broken {
        async fn read(&self, _: &[String]) -> Result<HashMap<String, UrlHistory>, HistoryError> {
            match self {
                Broken::Failing => Err(HistoryError("AccessDeniedException".to_owned())),
                Broken::Stalled => std::future::pending().await,
            }
        }
    }

    fn jobs(references: &[&str]) -> BTreeMap<String, Vec<Value>> {
        BTreeMap::from([(
            "example.com".to_owned(),
            references
                .iter()
                .map(|r| json!({"originalRef": r}))
                .collect(),
        )])
    }

    fn sent(jobs: &BTreeMap<String, Vec<Value>>) -> Vec<String> {
        let mut references: Vec<_> = jobs
            .values()
            .flatten()
            .map(|j| j["originalRef"].as_str().unwrap().to_owned())
            .collect();
        references.sort();
        references
    }

    #[tokio::test]
    async fn sends_only_the_jobs_the_fetcher_would_not_drop() {
        let now = NOW_MS as f64;
        let entry = |next_fetch_in_days: f64, stored_days_ago: Option<f64>| UrlHistory {
            next_fetch_at_ms: now + next_fetch_in_days * DAY_MS,
            stored_at_ms: stored_days_ago.map(|days| now - days * DAY_MS),
        };
        let history = MemoryHistory(HashMap::from([
            ("stored".to_owned(), entry(20.0, Some(1.0))),
            ("refused".to_owned(), entry(20.0, None)),
            ("refresh_due".to_owned(), entry(20.0, Some(7.0))),
            ("refetch_due".to_owned(), entry(0.0, Some(1.0))),
        ]));

        let (kept, mut dropped) = without_fresh(
            &history,
            jobs(&["stored", "refused", "refresh_due", "refetch_due", "unknown"]),
            NOW_MS,
            tokio::time::Instant::now() + Duration::from_secs(5),
        )
        .await;

        dropped.sort();
        assert_eq!(dropped, ["refused", "stored"]);
        assert_eq!(sent(&kept), ["refetch_due", "refresh_due", "unknown"]);
    }

    #[tokio::test(start_paused = true)]
    async fn sends_every_job_when_the_read_fails_or_stalls() {
        for history in [Broken::Failing, Broken::Stalled] {
            let references: Vec<String> = (0..2 * DYNAMODB_BATCH_GET_KEY_LIMIT)
                .map(|i| format!("r{i:03}"))
                .collect();
            let all: Vec<&str> = references.iter().map(String::as_str).collect();
            let (kept, dropped) = without_fresh(
                &history,
                jobs(&all),
                NOW_MS,
                tokio::time::Instant::now() + Duration::from_secs(5),
            )
            .await;
            assert!(dropped.is_empty());
            assert_eq!(sent(&kept), references);
        }
    }

    #[test]
    fn reads_only_url_entries_the_fetcher_wrote_for_their_key() {
        let reference = "imageurl:v4:7:2026-10:AAAAAAAAAAAAAAAAAAAAAA";
        let item = |key: &str, value: Value| {
            HashMap::from([
                ("key".to_owned(), AttributeValue::S(key.to_owned())),
                (
                    "expires_at".to_owned(),
                    AttributeValue::N("1794000000".to_owned()),
                ),
                ("value".to_owned(), AttributeValue::S(value.to_string())),
            ])
        };
        let url_entry = json!({
            "kind": "url",
            "key": reference,
            "nextFetchAtMs": 1_795_000_000_000i64,
            "storageExpiresAtMs": 1_794_000_000_000i64,
            "outcome": "ok",
            "cache": {"requestTimeMs": 1, "responseTimeMs": 2, "etag": "\"x\""},
            "storedAtMs": 1_792_000_000_000i64,
        });

        assert_eq!(
            url_history(&item(reference, url_entry.clone())),
            Some((
                reference.to_owned(),
                UrlHistory {
                    next_fetch_at_ms: 1_795_000_000_000.0,
                    stored_at_ms: Some(1_792_000_000_000.0),
                }
            ))
        );
        let robots = json!({"kind": "robots", "key": reference, "nextFetchAtMs": 1});
        for item in [
            item("imageurl:v4:7:2026-10:other", url_entry),
            item(reference, robots),
        ] {
            assert_eq!(url_history(&item), None);
        }
    }
}
