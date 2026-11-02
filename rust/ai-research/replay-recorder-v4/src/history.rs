use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use aws_sdk_dynamodb::error::DisplayErrorContext;
use aws_sdk_dynamodb::types::{AttributeValue, KeysAndAttributes};
use chrono::NaiveDate;
use futures::stream::{self, StreamExt};
use metrics::{counter, histogram};
use rand::Rng;
use serde_json::Value;

pub const DYNAMODB_BATCH_GET_KEY_LIMIT: usize = 100;
const READS_IN_FLIGHT: usize = 16;
const MAX_CALLS_WITHOUT_PROGRESS: u32 = 5;

/// The fetcher's refresh interval. `image-fetch-v4/drop-rule-vector-v4.json` holds both rules to the same cases.
const REFRESH_INTERVAL_MS: f64 = 7.0 * 24.0 * 3600.0 * 1000.0;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct UrlHistory {
    pub next_fetch_at_ms: f64,
    pub stored_at_ms: Option<f64>,
}

impl UrlHistory {
    /// The rule in `image-fetch-v4/url-fetch-consumer.ts`: before its next fetch time, a job only refreshes a stored
    /// image that is at least the refresh interval old.
    pub fn fetcher_drops(&self, at_ms: i64) -> bool {
        let at_ms = at_ms as f64;
        let refresh_due = self
            .stored_at_ms
            .is_some_and(|stored_at_ms| at_ms - stored_at_ms >= REFRESH_INTERVAL_MS);
        self.next_fetch_at_ms > at_ms && !refresh_due
    }
}

#[derive(Debug, Default, PartialEq)]
pub struct HistoryRead {
    pub entries: HashMap<String, UrlHistory>,
    pub invalid_rows: usize,
    pub unread_references: usize,
    pub error: Option<String>,
}

impl HistoryRead {
    fn unread(references: usize, error: impl Into<String>) -> Self {
        Self {
            unread_references: references,
            error: Some(error.into()),
            ..Self::default()
        }
    }
}

#[async_trait]
pub trait FetchHistory: Send + Sync {
    /// Reads at most [`DYNAMODB_BATCH_GET_KEY_LIMIT`] references, and returns what it read by `deadline`.
    async fn read(&self, references: &[String], deadline: tokio::time::Instant) -> HistoryRead;
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
    async fn read(&self, references: &[String], deadline: tokio::time::Instant) -> HistoryRead {
        let mut pending: Vec<HashMap<String, AttributeValue>> = references
            .iter()
            .map(|reference| {
                HashMap::from([("key".to_owned(), AttributeValue::S(reference.clone()))])
            })
            .collect();
        let mut read = HistoryRead::default();
        let mut calls_without_progress = 0;
        loop {
            // `key` and `value` are DynamoDB reserved words.
            let request = KeysAndAttributes::builder()
                .set_keys(Some(pending.clone()))
                .projection_expression("#k, #e, #v")
                .expression_attribute_names("#k", "key")
                .expression_attribute_names("#e", "expires_at")
                .expression_attribute_names("#v", "value")
                .build();
            let request = match request {
                Ok(request) => request,
                Err(error) => return HistoryRead::unread(pending.len(), error.to_string()),
            };
            let sent = self
                .client
                .batch_get_item()
                .request_items(&self.table, request)
                .send();
            let output = match tokio::time::timeout_at(deadline, sent).await {
                Err(_) => {
                    read.error = Some("the read ran past its deadline".to_owned());
                    break;
                }
                Ok(Err(error)) => {
                    read.error = Some(DisplayErrorContext(&error).to_string());
                    break;
                }
                Ok(Ok(output)) => output,
            };
            for item in output
                .responses()
                .and_then(|r| r.get(&self.table))
                .into_iter()
                .flatten()
            {
                match url_history(item) {
                    Some((reference, entry)) => {
                        read.entries.insert(reference, entry);
                    }
                    None => read.invalid_rows += 1,
                }
            }
            let unprocessed = output
                .unprocessed_keys()
                .and_then(|u| u.get(&self.table))
                .map(|u| u.keys().to_vec())
                .unwrap_or_default();
            calls_without_progress = if unprocessed.len() < pending.len() {
                0
            } else {
                calls_without_progress + 1
            };
            pending = unprocessed;
            if pending.is_empty() {
                break;
            }
            let wake = tokio::time::Instant::now() + backoff(calls_without_progress);
            if calls_without_progress == MAX_CALLS_WITHOUT_PROGRESS || wake >= deadline {
                read.error = Some("DynamoDB left keys unprocessed".to_owned());
                break;
            }
            tokio::time::sleep_until(wake).await;
        }
        read.unread_references = pending.len();
        read
    }
}

/// Accepts only a URL entry that `isCrawlHistoryItem` in `image-fetch-v4/dynamodb-crawl-history.ts` accepts, so that
/// a row the fetcher reads as a miss is a miss here too.
fn url_history(item: &HashMap<String, AttributeValue>) -> Option<(String, UrlHistory)> {
    let reference = item.get("key")?.as_s().ok()?;
    let expires_at: f64 = item.get("expires_at")?.as_n().ok()?.parse().ok()?;
    let value: Value = serde_json::from_str(item.get("value")?.as_s().ok()?).ok()?;
    let number = |field: &str| value.get(field).and_then(Value::as_f64);
    let valid = expires_at.is_finite()
        && value.get("kind").and_then(Value::as_str) == Some("url")
        && value.get("key").and_then(Value::as_str) == Some(reference.as_str())
        && value.get("outcome").is_some_and(Value::is_string)
        && number("storageExpiresAtMs").is_some()
        && value.get("cache").is_none_or(is_http_cache)
        && value.get("storedAtMs").is_none_or(Value::is_number)
        && value.get("_bodyChunks").is_none();
    if !valid {
        return None;
    }
    let entry = UrlHistory {
        next_fetch_at_ms: number("nextFetchAtMs")?,
        stored_at_ms: number("storedAtMs"),
    };
    Some((reference.to_owned(), entry))
}

fn is_http_cache(cache: &Value) -> bool {
    const TEXT_FIELDS: [&str; 8] = [
        "responseUrlHmac",
        "responseUrl",
        "etag",
        "lastModified",
        "date",
        "age",
        "cacheControl",
        "expires",
    ];
    cache.get("requestTimeMs").is_some_and(Value::is_number)
        && cache.get("responseTimeMs").is_some_and(Value::is_number)
        && TEXT_FIELDS
            .iter()
            .all(|field| cache.get(field).is_none_or(Value::is_string))
}

fn day_end_ms(day: &str) -> Option<i64> {
    let next_day = NaiveDate::parse_from_str(day, "%Y-%m-%d")
        .ok()?
        .succ_opt()?;
    Some(next_day.and_hms_opt(0, 0, 0)?.and_utc().timestamp_millis())
}

fn backoff(attempt: u32) -> Duration {
    let ceiling = 3_000u64.min(50u64.saturating_mul(1 << attempt.min(16)));
    Duration::from_millis(rand::thread_rng().gen_range(ceiling / 2..=ceiling))
}

/// Reads each reference that `sent_urls` does not hold for `day` once, and marks the ones the fetcher would still drop
/// when `day` ends. So each day that a block references an image, either a job goes out or the stored copy is younger
/// than the refresh interval, which the `images-v4` lifecycle allows for.
pub async fn mark_fresh<'a>(
    history: &dyn FetchHistory,
    sent_urls: &moka::sync::Cache<(String, String), ()>,
    references: impl IntoIterator<Item = &'a String>,
    day: &str,
    deadline: tokio::time::Instant,
) {
    let Some(day_end_ms) = day_end_ms(day) else {
        return;
    };
    let unsent: Vec<String> = {
        let mut seen = HashSet::new();
        references
            .into_iter()
            .filter(|reference| {
                seen.insert(*reference)
                    && !sent_urls.contains_key(&(day.to_owned(), (*reference).clone()))
            })
            .cloned()
            .collect()
    };
    for reference in fresh_references(history, &unsent, day_end_ms, deadline).await {
        sent_urls.insert((day.to_owned(), reference), ());
    }
}

/// A reference that a read does not return by `deadline` is not fresh, so the fetcher decides its job.
async fn fresh_references(
    history: &dyn FetchHistory,
    references: &[String],
    drops_at_ms: i64,
    deadline: tokio::time::Instant,
) -> HashSet<String> {
    if references.is_empty() {
        return HashSet::new();
    }
    let started = Instant::now();
    let past_deadline =
        |references: usize| HistoryRead::unread(references, "the read ran past its deadline");
    let reads: Vec<_> = references
        .chunks(DYNAMODB_BATCH_GET_KEY_LIMIT)
        .map(|chunk| async move {
            if tokio::time::Instant::now() >= deadline {
                return past_deadline(chunk.len());
            }
            tokio::time::timeout_at(deadline, history.read(chunk, deadline))
                .await
                .unwrap_or_else(|_| past_deadline(chunk.len()))
        })
        .collect();
    let reads: Vec<HistoryRead> = stream::iter(reads)
        .buffer_unordered(READS_IN_FLIGHT)
        .collect()
        .await;
    histogram!("ai_research_v4_recorder_image_fetch_history_duration_seconds")
        .record(started.elapsed().as_secs_f64());

    let mut fresh = HashSet::new();
    let (mut due, mut invalid, mut unread) = (0, 0, 0);
    let mut first_error = None;
    for read in reads {
        invalid += read.invalid_rows;
        unread += read.unread_references;
        first_error = first_error.or(read.error);
        for (reference, entry) in read.entries {
            if entry.fetcher_drops(drops_at_ms) {
                fresh.insert(reference);
            } else {
                due += 1;
            }
        }
    }
    if let Some(error) = first_error {
        tracing::warn!(%error, references = unread, "image fetch history read failed: those jobs go out unchecked");
    }

    let absent = references
        .len()
        .saturating_sub(fresh.len() + due + invalid + unread);
    for (outcome, count) in [
        ("fresh", fresh.len()),
        ("due", due),
        ("absent", absent),
        ("invalid", invalid),
        ("error", unread),
    ] {
        counter!("ai_research_v4_recorder_image_fetch_history_total", "outcome" => outcome)
            .increment(count as u64);
    }
    fresh
}

#[cfg(test)]
mod tests {
    use serde::Deserialize;
    use serde_json::json;

    use super::*;

    const DAY: &str = "2026-10-26";

    #[derive(Deserialize)]
    struct DropRuleVector {
        cases: Vec<DropRuleCase>,
    }

    #[derive(Deserialize)]
    #[serde(rename_all = "camelCase")]
    struct DropRuleCase {
        name: String,
        next_fetch_in_ms: f64,
        stored_ago_ms: Option<f64>,
        dropped: bool,
    }

    fn drop_rule_cases() -> Vec<DropRuleCase> {
        let vector: DropRuleVector = serde_json::from_str(include_str!(
            "../../../../nodejs/src/ingestion/pipelines/sessionreplay/ai-research/image-fetch-v4/drop-rule-vector-v4.json"
        ))
        .unwrap();
        vector.cases
    }

    struct MemoryHistory {
        entries: HashMap<String, UrlHistory>,
        read: std::sync::Mutex<Vec<String>>,
    }

    #[async_trait]
    impl FetchHistory for MemoryHistory {
        async fn read(&self, references: &[String], _: tokio::time::Instant) -> HistoryRead {
            self.read.lock().unwrap().extend_from_slice(references);
            HistoryRead {
                entries: references
                    .iter()
                    .filter_map(|r| self.entries.get(r).map(|entry| (r.clone(), *entry)))
                    .collect(),
                ..HistoryRead::default()
            }
        }
    }

    enum Broken {
        Failing,
        Stalled,
    }

    #[async_trait]
    impl FetchHistory for Broken {
        async fn read(&self, references: &[String], _: tokio::time::Instant) -> HistoryRead {
            match self {
                Broken::Failing => HistoryRead::unread(references.len(), "AccessDeniedException"),
                Broken::Stalled => std::future::pending().await,
            }
        }
    }

    fn marked(sent_urls: &moka::sync::Cache<(String, String), ()>, reference: &str) -> bool {
        sent_urls.contains_key(&(DAY.to_owned(), reference.to_owned()))
    }

    #[tokio::test]
    async fn reads_each_cache_miss_once_and_marks_what_the_fetcher_drops_until_the_day_ends() {
        let day_end_ms = day_end_ms(DAY).unwrap() as f64;
        let cases = drop_rule_cases();
        let history = MemoryHistory {
            entries: cases
                .iter()
                .map(|case| {
                    let entry = UrlHistory {
                        next_fetch_at_ms: day_end_ms + case.next_fetch_in_ms,
                        stored_at_ms: case.stored_ago_ms.map(|ago_ms| day_end_ms - ago_ms),
                    };
                    (case.name.clone(), entry)
                })
                .collect(),
            read: Default::default(),
        };
        let sent_urls = crate::urls::sent_urls(100);
        sent_urls.insert((DAY.to_owned(), "sent".to_owned()), ());
        let mut references = vec!["sent".to_owned(), "unknown".to_owned()];
        references.extend(cases.iter().map(|case| case.name.clone()));
        references.push(cases[0].name.clone());

        mark_fresh(
            &history,
            &sent_urls,
            &references,
            DAY,
            tokio::time::Instant::now() + Duration::from_secs(5),
        )
        .await;

        let mut read = history.read.into_inner().unwrap();
        read.sort();
        let mut expected: Vec<String> = cases.iter().map(|case| case.name.clone()).collect();
        expected.push("unknown".to_owned());
        expected.sort();
        assert_eq!(read, expected);
        for case in &cases {
            assert_eq!(
                marked(&sent_urls, &case.name),
                case.dropped,
                "{}",
                case.name
            );
        }
        assert!(!marked(&sent_urls, "unknown"));
    }

    #[tokio::test(start_paused = true)]
    async fn marks_nothing_when_the_read_fails_or_stalls() {
        for history in [Broken::Failing, Broken::Stalled] {
            let references: Vec<String> = (0..2 * DYNAMODB_BATCH_GET_KEY_LIMIT)
                .map(|i| format!("r{i:03}"))
                .collect();
            let sent_urls = crate::urls::sent_urls(1_000);
            mark_fresh(
                &history,
                &sent_urls,
                &references,
                DAY,
                tokio::time::Instant::now() + Duration::from_secs(5),
            )
            .await;
            assert!(!references.iter().any(|r| marked(&sent_urls, r)));
        }
    }

    #[tokio::test]
    async fn sends_no_read_once_the_deadline_has_passed() {
        let history = MemoryHistory {
            entries: HashMap::new(),
            read: Default::default(),
        };
        let references = ["r".to_owned()];
        let sent_urls = crate::urls::sent_urls(100);
        mark_fresh(
            &history,
            &sent_urls,
            &references,
            DAY,
            tokio::time::Instant::now(),
        )
        .await;
        assert!(history.read.into_inner().unwrap().is_empty());
    }

    #[test]
    fn reads_only_url_entries_the_fetcher_accepts_for_their_key() {
        let reference = "imageurl:v4:7:2026-10:AAAAAAAAAAAAAAAAAAAAAA";
        let item = |key: &str, value: &Value| {
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
        let with = |field: &str, value: Value| {
            let mut entry = url_entry.clone();
            entry[field] = value;
            item(reference, &entry)
        };
        let without = |field: &str| {
            let mut entry = url_entry.clone();
            entry.as_object_mut().unwrap().remove(field);
            item(reference, &entry)
        };
        let mut without_expiry = item(reference, &url_entry);
        without_expiry.remove("expires_at");

        assert_eq!(
            url_history(&item(reference, &url_entry)),
            Some((
                reference.to_owned(),
                UrlHistory {
                    next_fetch_at_ms: 1_795_000_000_000.0,
                    stored_at_ms: Some(1_792_000_000_000.0),
                }
            ))
        );
        let robots = json!({"kind": "robots", "key": reference, "nextFetchAtMs": 1});
        for row in [
            item("imageurl:v4:7:2026-10:other", &url_entry),
            item(reference, &robots),
            without_expiry,
            without("outcome"),
            without("storageExpiresAtMs"),
            with("storedAtMs", Value::Null),
            with("cache", json!({"requestTimeMs": 1})),
            with(
                "cache",
                json!({"requestTimeMs": 1, "responseTimeMs": 2, "etag": null}),
            ),
            with("_bodyChunks", json!({"count": 1, "sha256": "0".repeat(64)})),
        ] {
            assert_eq!(url_history(&row), None);
        }
    }
}
