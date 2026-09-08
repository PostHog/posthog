//! Sends the label maps of a metric series once per window instead of on every
//! row. The metrics2 ClickHouse chain builds its series and attribute rollups
//! from rows with `has_labels = true`, so one labelled row per series per
//! window is enough; every other row only needs the fingerprint and the value.
//!
//! The decision runs on the request path against a local cache and never
//! awaits. Redis only shares the set of recently labelled series between pods:
//! new series are pushed from a background task, and the cache is pulled from
//! Redis at startup and on an interval. Every Redis failure is ignored, which
//! can only make labels go out more often, never less.

use std::collections::BTreeMap;
use std::hash::Hasher;
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use common_redis::{Client, CustomRedisError, PipelineCommand};
use dashmap::DashMap;
use metrics::{counter, gauge};
use siphasher::sip::SipHasher13;
use tokio::sync::mpsc;
use tracing::{debug, info, warn};

use capture_logs::metric_record::KafkaMetricRow;

const REDIS_KEY_PREFIX: &str = "capture-logs:metric-series-labels";
/// Members are spread over hour buckets so keys expire on their own and no
/// prune command is needed.
const REDIS_BUCKET_SECS: i64 = 3600;
/// Members written by another pod just before a pull started can carry a score
/// below the pull's `since` because of clock skew. The next pull starts this
/// much earlier; members already in the cache are a no-op.
const PULL_OVERLAP_SECS: i64 = 60;
const WRITER_CHANNEL_CAPACITY: usize = 10_000;
const WRITER_BATCH_SIZE: usize = 500;
const WRITER_FLUSH_INTERVAL: Duration = Duration::from_secs(1);
const PRUNE_INTERVAL: Duration = Duration::from_secs(300);

pub type Clock = Arc<dyn Fn() -> i64 + Send + Sync>;

/// Gate key and the unix second its labels went out.
type SeenSeries = (u64, i64);

pub struct SeriesLabelGate {
    cache: DashMap<u64, i64>,
    tx: Option<mpsc::Sender<SeenSeries>>,
    window_secs: i64,
    enabled: bool,
    clock: Clock,
}

impl SeriesLabelGate {
    /// Gate backed by Redis. The receiver goes to [`spawn_redis_writer`].
    pub fn new(window: Duration, enabled: bool) -> (Arc<Self>, mpsc::Receiver<SeenSeries>) {
        let (tx, rx) = mpsc::channel(WRITER_CHANNEL_CAPACITY);
        let gate = Self::build(window, enabled, Some(tx), Arc::new(unix_now));
        (Arc::new(gate), rx)
    }

    /// Gate with the local cache only. Used when `REDIS_URL` is unset.
    pub fn local_only(window: Duration, enabled: bool) -> Arc<Self> {
        Arc::new(Self::build(window, enabled, None, Arc::new(unix_now)))
    }

    fn build(
        window: Duration,
        enabled: bool,
        tx: Option<mpsc::Sender<SeenSeries>>,
        clock: Clock,
    ) -> Self {
        Self {
            cache: DashMap::new(),
            tx,
            window_secs: window.as_secs() as i64,
            enabled,
            clock,
        }
    }

    /// Decide per row whether it carries the series labels. The first row for a
    /// series in the window keeps them; later rows get empty label maps and
    /// `has_labels = false`. Synchronous: never waits on Redis.
    pub fn apply(&self, token: &str, rows: &mut [KafkaMetricRow]) {
        let now = (self.clock)();
        let mut sent = 0u64;
        let mut skipped = 0u64;
        let mut queue_full = 0u64;

        for row in rows.iter_mut() {
            let key = gate_key(token, row.series_fingerprint);
            if self.seen_within_window(key, now) {
                skipped += 1;
                if self.enabled {
                    strip_labels(row);
                }
                continue;
            }

            self.cache.insert(key, now);
            sent += 1;
            if let Some(tx) = &self.tx {
                if tx.try_send((key, now)).is_err() {
                    queue_full += 1;
                }
            }
        }

        counter!("capture_metrics_series_labels_sent").increment(sent);
        counter!("capture_metrics_series_labels_skipped").increment(skipped);
        if queue_full > 0 {
            counter!("capture_metrics_series_redis_queue_full").increment(queue_full);
        }
    }

    fn seen_within_window(&self, key: u64, now: i64) -> bool {
        self.cache
            .get(&key)
            .is_some_and(|last| now - *last < self.window_secs)
    }

    /// Read every series labelled by any pod in the current window. Runs once
    /// before the service accepts traffic; a failure leaves the cache empty.
    pub async fn seed_from_redis(&self, client: &dyn Client, timeout: Duration) {
        let now = (self.clock)();
        match self
            .pull_from_redis(client, now - self.window_secs, timeout)
            .await
        {
            Ok(merged) => info!("Seeded series label cache with {merged} series from Redis"),
            Err(e) => warn!("Could not seed series label cache from Redis, starting empty: {e}"),
        }
    }

    /// Merge the series with a score at or after `since` into the cache. A
    /// series this pod already knows keeps its exact local timestamp; a series
    /// another pod labelled is recorded as seen now. Returns how many were new.
    pub async fn pull_from_redis(
        &self,
        client: &dyn Client,
        since: i64,
        timeout: Duration,
    ) -> Result<usize, PullError> {
        let now = (self.clock)();
        let read = async {
            let mut members = Vec::new();
            for key in bucket_keys(since.max(now - self.window_secs), now) {
                members.extend(
                    client
                        .zrangebyscore(key, since.to_string(), "+inf".to_string())
                        .await?,
                );
            }
            Ok::<_, CustomRedisError>(members)
        };
        let members = tokio::time::timeout(timeout, read)
            .await
            .map_err(|_| PullError::Timeout)??;

        let mut merged = 0usize;
        for member in members {
            let Ok(key) = member.parse::<u64>() else {
                continue;
            };
            if let dashmap::Entry::Vacant(slot) = self.cache.entry(key) {
                slot.insert(now - seed_jitter(key, self.window_secs));
                merged += 1;
            }
        }
        counter!("capture_metrics_series_redis_pulled").increment(merged as u64);
        Ok(merged)
    }

    /// Repeat [`Self::pull_from_redis`] every `interval`, each time reading only
    /// members added since the previous pull (with an overlap for clock skew).
    pub fn spawn_redis_puller(
        self: &Arc<Self>,
        client: Arc<dyn Client>,
        interval: Duration,
        timeout: Duration,
    ) {
        let gate = Arc::clone(self);
        tokio::spawn(async move {
            let mut since = (gate.clock)() - PULL_OVERLAP_SECS;
            let mut ticker = tokio::time::interval(interval);
            ticker.tick().await;
            loop {
                ticker.tick().await;
                let started = (gate.clock)();
                match gate.pull_from_redis(client.as_ref(), since, timeout).await {
                    Ok(merged) => {
                        debug!("Pulled {merged} new series from Redis");
                        since = started - PULL_OVERLAP_SECS;
                    }
                    Err(e) => {
                        counter!("capture_metrics_series_redis_pull_failed").increment(1);
                        debug!("Series label pull from Redis failed: {e}");
                    }
                }
            }
        });
    }

    /// Drop cache entries older than the window so memory tracks the number of
    /// active series, not the number ever seen.
    pub fn spawn_pruner(self: &Arc<Self>) {
        let gate = Arc::clone(self);
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(PRUNE_INTERVAL);
            ticker.tick().await;
            loop {
                ticker.tick().await;
                let now = (gate.clock)();
                gate.cache.retain(|_, last| now - *last < gate.window_secs);
                gauge!("capture_metrics_series_cache_size").set(gate.cache.len() as f64);
            }
        });
    }

    #[cfg(test)]
    fn cache_len(&self) -> usize {
        self.cache.len()
    }

    #[cfg(test)]
    fn seen_at(&self, key: u64) -> Option<i64> {
        self.cache.get(&key).map(|v| *v)
    }
}

/// Batch newly labelled series into `ZADD` pipelines. One flush per
/// [`WRITER_BATCH_SIZE`] series or per [`WRITER_FLUSH_INTERVAL`], whichever
/// comes first. Failures are counted and dropped; the next pull from another
/// pod, or this pod's own cache, covers the gap.
pub fn spawn_redis_writer(
    client: Arc<dyn Client>,
    mut rx: mpsc::Receiver<SeenSeries>,
    timeout: Duration,
    window: Duration,
) {
    let ttl_secs = window.as_secs() + REDIS_BUCKET_SECS as u64;
    tokio::spawn(async move {
        let mut batch: Vec<SeenSeries> = Vec::with_capacity(WRITER_BATCH_SIZE);
        loop {
            let Some(first) = rx.recv().await else {
                return;
            };
            batch.push(first);

            let flush_at = tokio::time::sleep(WRITER_FLUSH_INTERVAL);
            tokio::pin!(flush_at);
            while batch.len() < WRITER_BATCH_SIZE {
                tokio::select! {
                    item = rx.recv() => match item {
                        Some(item) => batch.push(item),
                        None => break,
                    },
                    _ = &mut flush_at => break,
                }
            }

            let commands = zadd_commands(&batch, ttl_secs);
            let pushed = batch.len() as u64;
            batch.clear();
            match tokio::time::timeout(timeout, client.execute_pipeline(commands)).await {
                Ok(Ok(_)) => {
                    counter!("capture_metrics_series_redis_pushed").increment(pushed);
                }
                Ok(Err(e)) => {
                    counter!("capture_metrics_series_redis_push_failed").increment(pushed);
                    debug!("Series label push to Redis failed: {e}");
                }
                Err(_) => {
                    counter!("capture_metrics_series_redis_push_failed").increment(pushed);
                    debug!("Series label push to Redis timed out");
                }
            }
        }
    });
}

/// A pulled series gets a timestamp that is a little in the past, so that
/// series seeded together do not all expire in the same second. Without this,
/// every pod relabels every seeded series at the same moment one window after
/// startup. The offset is derived from the key so all pods pick the same one.
fn seed_jitter(key: u64, window_secs: i64) -> i64 {
    let spread = (window_secs / 4).max(1);
    (key % spread as u64) as i64
}

/// One ZADD per bucket carrying every member, plus one EXPIRE per bucket.
fn zadd_commands(batch: &[SeenSeries], ttl_secs: u64) -> Vec<PipelineCommand> {
    let mut by_bucket: BTreeMap<String, Vec<(i64, String)>> = BTreeMap::new();
    for (key, seen_at) in batch {
        by_bucket
            .entry(bucket_key(*seen_at))
            .or_default()
            .push((*seen_at, key.to_string()));
    }
    let mut commands = Vec::with_capacity(by_bucket.len() * 2);
    for (bucket, members) in by_bucket {
        commands.push(PipelineCommand::ZAdd {
            key: bucket.clone(),
            members,
        });
        commands.push(PipelineCommand::Expire {
            key: bucket,
            seconds: ttl_secs,
        });
    }
    commands
}

#[derive(Debug, thiserror::Error)]
pub enum PullError {
    #[error("redis error: {0}")]
    Redis(#[from] CustomRedisError),
    #[error("timed out")]
    Timeout,
}

/// `series_fingerprint` is computed without the token, and ClickHouse tables
/// are per team, so two teams with identical series must not share a gate
/// entry. The token is hashed in rather than stored, so no key reaches Redis.
fn gate_key(token: &str, series_fingerprint: i64) -> u64 {
    let mut hasher = SipHasher13::new();
    hasher.write(&(token.len() as u64).to_le_bytes());
    hasher.write(token.as_bytes());
    hasher.write(&series_fingerprint.to_le_bytes());
    hasher.finish()
}

fn strip_labels(row: &mut KafkaMetricRow) {
    row.has_labels = false;
    row.attributes.clear();
    row.resource_attributes.clear();
}

fn bucket_key(unix_secs: i64) -> String {
    format!(
        "{REDIS_KEY_PREFIX}:{}",
        unix_secs.div_euclid(REDIS_BUCKET_SECS)
    )
}

/// Bucket keys that can hold a member with a score in `[from, to]`.
fn bucket_keys(from: i64, to: i64) -> Vec<String> {
    let first = from.div_euclid(REDIS_BUCKET_SECS);
    let last = to.div_euclid(REDIS_BUCKET_SECS);
    (first..=last)
        .map(|bucket| format!("{REDIS_KEY_PREFIX}:{bucket}"))
        .collect()
}

fn unix_now() -> i64 {
    Utc::now().timestamp()
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::atomic::{AtomicI64, Ordering};

    use common_redis::{MockRedisClient, MockRedisValue};

    use super::*;

    const WINDOW: Duration = Duration::from_secs(1800);
    const START: i64 = 1_800_000_000;

    fn gate(
        enabled: bool,
        with_redis: bool,
    ) -> (
        SeriesLabelGate,
        Arc<AtomicI64>,
        Option<mpsc::Receiver<SeenSeries>>,
    ) {
        let now = Arc::new(AtomicI64::new(START));
        let clock_now = Arc::clone(&now);
        let clock: Clock = Arc::new(move || clock_now.load(Ordering::SeqCst));
        let (tx, rx) = if with_redis {
            let (tx, rx) = mpsc::channel(WRITER_CHANNEL_CAPACITY);
            (Some(tx), Some(rx))
        } else {
            (None, None)
        };
        (SeriesLabelGate::build(WINDOW, enabled, tx, clock), now, rx)
    }

    fn row(series_fingerprint: i64) -> KafkaMetricRow {
        KafkaMetricRow {
            uuid: String::new(),
            trace_id: String::new(),
            span_id: String::new(),
            trace_flags: 0,
            timestamp: Utc::now(),
            observed_timestamp: Utc::now(),
            service_name: "svc".into(),
            metric_name: "m".into(),
            metric_type: "gauge".into(),
            value: 1.0,
            count: 1,
            histogram_bounds: vec![],
            histogram_counts: vec![],
            unit: String::new(),
            aggregation_temporality: String::new(),
            is_monotonic: false,
            resource_attributes: HashMap::from([("service.name".into(), "\"svc\"".into())]),
            instrumentation_scope: String::new(),
            attributes: HashMap::from([("env".into(), "\"prod\"".into())]),
            series_fingerprint,
            has_labels: true,
            retention_days: None,
        }
    }

    fn assert_labelled(row: &KafkaMetricRow) {
        assert!(row.has_labels);
        assert!(!row.attributes.is_empty());
        assert!(!row.resource_attributes.is_empty());
    }

    fn assert_stripped(row: &KafkaMetricRow) {
        assert!(!row.has_labels);
        assert!(row.attributes.is_empty());
        assert!(row.resource_attributes.is_empty());
    }

    #[test]
    fn first_row_keeps_labels_and_later_rows_in_window_are_stripped() {
        let (gate, now, _) = gate(true, false);

        let mut rows = vec![row(7), row(7)];
        gate.apply("token-a", &mut rows);
        assert_labelled(&rows[0]);
        assert_stripped(&rows[1]);

        now.fetch_add(WINDOW.as_secs() as i64 - 1, Ordering::SeqCst);
        let mut rows = vec![row(7)];
        gate.apply("token-a", &mut rows);
        assert_stripped(&rows[0]);

        now.fetch_add(1, Ordering::SeqCst);
        let mut rows = vec![row(7)];
        gate.apply("token-a", &mut rows);
        assert_labelled(&rows[0]);
    }

    #[test]
    fn same_fingerprint_under_different_tokens_are_separate_series() {
        let (gate, _, _) = gate(true, false);

        let mut rows = vec![row(7)];
        gate.apply("token-a", &mut rows);
        let mut rows = vec![row(7)];
        gate.apply("token-b", &mut rows);
        assert_labelled(&rows[0]);
    }

    #[test]
    fn disabled_gate_tracks_series_but_leaves_rows_untouched() {
        let (gate, _, _) = gate(false, false);

        let mut rows = vec![row(7), row(7)];
        gate.apply("token-a", &mut rows);
        assert_labelled(&rows[0]);
        assert_labelled(&rows[1]);
        assert_eq!(gate.cache_len(), 1);
    }

    #[test]
    fn new_series_are_queued_for_redis_and_known_series_are_not() {
        let (gate, _, rx) = gate(true, true);
        let mut rx = rx.unwrap();

        let mut rows = vec![row(7), row(7), row(8)];
        gate.apply("token-a", &mut rows);

        let mut queued = Vec::new();
        while let Ok(item) = rx.try_recv() {
            queued.push(item);
        }
        assert_eq!(queued.len(), 2);
        assert!(queued.iter().all(|(_, seen_at)| *seen_at == START));
    }

    #[tokio::test]
    async fn pull_marks_other_pods_series_as_seen_without_overwriting_local_entries() {
        let (gate, now, _) = gate(true, false);
        let local_key = gate_key("token-a", 7);
        let remote_key = gate_key("token-a", 8);

        // The local series was labelled 20 minutes ago; the pull must not
        // reset it to now, or it would go out 20 minutes late.
        let mut rows = vec![row(7)];
        gate.apply("token-a", &mut rows);
        now.fetch_add(1200, Ordering::SeqCst);

        let mut client = MockRedisClient::new();
        for key in bucket_keys(START + 1200 - WINDOW.as_secs() as i64, START + 1200) {
            client = client.zrangebyscore_ret(&key, vec![]);
        }
        let client = client.zrangebyscore_ret(
            &bucket_key(START + 1200),
            vec![local_key.to_string(), remote_key.to_string(), "junk".into()],
        );

        let merged = gate
            .pull_from_redis(&client, START, Duration::from_secs(1))
            .await
            .unwrap();
        assert_eq!(merged, 1);

        // Seeded within the last quarter window, so it is seen but does not
        // expire in lockstep with the other seeded series.
        let seeded_at = gate.seen_at(remote_key).unwrap();
        let pulled_at = START + 1200;
        assert!(seeded_at <= pulled_at && seeded_at > pulled_at - WINDOW.as_secs() as i64 / 4);

        let mut rows = vec![row(8)];
        gate.apply("token-a", &mut rows);
        assert_stripped(&rows[0]);

        now.fetch_add(600, Ordering::SeqCst);
        let mut rows = vec![row(7)];
        gate.apply("token-a", &mut rows);
        assert_labelled(&rows[0]);
    }

    #[tokio::test]
    async fn pull_failure_leaves_cache_unchanged() {
        let (gate, _, _) = gate(true, false);
        let client = MockRedisClient::new();

        let result = gate
            .pull_from_redis(&client, START - 60, Duration::from_secs(1))
            .await;
        assert!(matches!(result, Err(PullError::Redis(_))));
        assert_eq!(gate.cache_len(), 0);
    }

    #[tokio::test]
    async fn writer_pushes_batches_as_zadd_with_bucket_expiry() {
        let (tx, rx) = mpsc::channel(WRITER_CHANNEL_CAPACITY);
        let client = MockRedisClient::new();
        let shared: Arc<dyn Client> = Arc::new(client.clone());
        spawn_redis_writer(shared, rx, Duration::from_millis(250), WINDOW);

        tx.send((42, START)).await.unwrap();
        tx.send((43, START + 5)).await.unwrap();

        // The writer flushes after WRITER_FLUSH_INTERVAL; poll instead of a fixed sleep.
        let deadline = tokio::time::Instant::now() + WRITER_FLUSH_INTERVAL * 5;
        while client.get_calls().is_empty() && tokio::time::Instant::now() < deadline {
            tokio::time::sleep(Duration::from_millis(50)).await;
        }

        let calls = client.get_calls();
        let zadds: Vec<_> = calls.iter().filter(|c| c.op == "pipeline_zadd").collect();
        assert_eq!(zadds.len(), 2);
        assert_eq!(zadds[0].key, format!("{}:42", bucket_key(START)));
        assert!(matches!(zadds[0].value, MockRedisValue::I64(START)));
        let expires: Vec<_> = calls.iter().filter(|c| c.op == "pipeline_expire").collect();
        assert_eq!(expires.len(), 1);
        assert_eq!(expires[0].key, bucket_key(START));
    }

    #[test]
    fn bucket_keys_cover_the_whole_range() {
        let from = 10 * REDIS_BUCKET_SECS - 1;
        let to = 11 * REDIS_BUCKET_SECS;
        assert_eq!(
            bucket_keys(from, to),
            vec![
                format!("{REDIS_KEY_PREFIX}:9"),
                format!("{REDIS_KEY_PREFIX}:10"),
                format!("{REDIS_KEY_PREFIX}:11"),
            ]
        );
    }
}
