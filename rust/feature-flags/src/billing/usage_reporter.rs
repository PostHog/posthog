//! Mirrors flushed billing counts into the usage-ingestion service. Records are emitted only for a
//! chunk already credited to Redis, so a Redis retry cannot bill twice.
//!
//! `record_id` is a fresh UUID per emission, not derived from the aggregation key: a Redis outage
//! rebuckets and merges requeued entries, so one key legitimately carries different quantities
//! across flushes. ID reuse is scoped to the retry the gRPC client performs on one request.

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;

use common_metrics::inc;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tonic::transport::{Channel, Endpoint};
use usage_ingestion_proto::usage_ingestion::v1::{
    usage_ingestion_client::UsageIngestionClient, BillingUsageMode, BillingUsageRecord,
    IngestBillingUsageRequest,
};
use uuid::Uuid;

use crate::config::TeamIdCollection;
use crate::metrics::consts::{FLAGS_USAGE_RECORDS_FAILED, FLAGS_USAGE_RECORDS_SENT};

use super::AggregationKey;

const PRODUCER_ID: &str = "feature-flags";
const USAGE_KEY: &str = "feature_flag_requests";
const UNIT: &str = "requests";
const MAX_BATCH_SIZE: usize = 500;
/// Queued sends waiting on the sender task. A full queue drops rather than growing
/// unboundedly; the drop is counted, and Redis still holds the authoritative count.
const QUEUE_CAPACITY: usize = 64;

struct SenderState {
    queue: mpsc::Sender<Vec<BillingUsageRecord>>,
    task: JoinHandle<()>,
}

pub struct UsageReporter {
    teams: TeamIdCollection,
    state: Mutex<Option<SenderState>>,
}

impl UsageReporter {
    /// `None` when no URL is configured or no team is enabled, so the aggregator
    /// skips the work entirely.
    pub fn new(
        url: &str,
        teams: TeamIdCollection,
        timeout_ms: u64,
    ) -> Result<Option<Arc<Self>>, String> {
        if url.is_empty() || matches!(teams, TeamIdCollection::None) {
            return Ok(None);
        }
        let endpoint = Endpoint::from_shared(url.to_string())
            .map_err(|e| format!("invalid FLAGS_USAGE_INGESTION_URL: {e}"))?
            .timeout(std::time::Duration::from_millis(timeout_ms));
        let client = UsageIngestionClient::new(endpoint.connect_lazy());

        // One owned task drains the queue, so concurrency is bounded by construction and
        // `shutdown` has something to await. Spawning per flush chunk left thousands of
        // untracked tasks that a shutdown could not drain.
        let (queue, receiver) = mpsc::channel(QUEUE_CAPACITY);
        let task = tokio::spawn(run_sender(client, receiver));

        Ok(Some(Arc::new(Self {
            teams,
            state: Mutex::new(Some(SenderState { queue, task })),
        })))
    }

    /// `timestamp_ms` must be the reporter's own clock, never anything derived from a request.
    /// toDate of it is part of the storage sorting key, so a caller-controlled value would
    /// decide whether these records deduplicate.
    pub fn report(&self, entries: &[(AggregationKey, u64)], timestamp_ms: i64) {
        let records = build_records(entries, &self.teams, timestamp_ms);
        if records.is_empty() {
            return;
        }
        let dropped = records.len() as u64;
        let queued = match self.state.lock().unwrap().as_ref() {
            Some(state) => state.queue.try_send(records).is_ok(),
            None => false,
        };
        if !queued {
            inc(FLAGS_USAGE_RECORDS_FAILED, &[], dropped);
            tracing::warn!(
                records = dropped,
                "usage-ingestion send queue is full or closed; dropped usage records"
            );
        }
    }

    /// Closes the queue and awaits the sender so a graceful shutdown does not lose records
    /// the Redis flush already credited. Bounded by `timeout`.
    pub async fn shutdown(&self, timeout: std::time::Duration) {
        let state = self.state.lock().unwrap().take();
        let Some(SenderState { queue, task }) = state else {
            return;
        };
        // Dropping the only sender closes the channel, so the task drains its queue and returns.
        drop(queue);
        let abort = task.abort_handle();
        match tokio::time::timeout(timeout, task).await {
            Ok(_) => tracing::info!("UsageReporter: drained pending usage records"),
            Err(_) => {
                abort.abort();
                tracing::warn!(
                    timeout_ms = timeout.as_millis() as u64,
                    "UsageReporter: timed out draining usage records"
                );
            }
        }
    }
}

async fn run_sender(
    client: UsageIngestionClient<Channel>,
    mut receiver: mpsc::Receiver<Vec<BillingUsageRecord>>,
) {
    while let Some(records) = receiver.recv().await {
        for chunk in records.chunks(MAX_BATCH_SIZE) {
            let sent = chunk.len() as u64;
            let mut client = client.clone();
            match client
                .ingest_billing_usage(IngestBillingUsageRequest {
                    records: chunk.to_vec(),
                })
                .await
            {
                Ok(_) => inc(FLAGS_USAGE_RECORDS_SENT, &[], sent),
                Err(status) => {
                    inc(FLAGS_USAGE_RECORDS_FAILED, &[], sent);
                    tracing::warn!(
                        records = sent,
                        code = %status.code(),
                        "failed to report feature flag usage records"
                    );
                }
            }
        }
    }
}

fn build_records(
    entries: &[(AggregationKey, u64)],
    teams: &TeamIdCollection,
    timestamp_ms: i64,
) -> Vec<BillingUsageRecord> {
    entries
        .iter()
        .filter(|(key, count)| *count > 0 && teams.includes_team(key.team_id))
        .map(|(key, count)| BillingUsageRecord {
            record_id: Uuid::now_v7().to_string(),
            producer_id: PRODUCER_ID.to_string(),
            team_id: i64::from(key.team_id),
            usage_key: USAGE_KEY.to_string(),
            mode: BillingUsageMode::Delta as i32,
            unit: UNIT.to_string(),
            quantity: i64::try_from(*count).unwrap_or(i64::MAX),
            timestamp_ms,
            dimensions: dimensions_for(key),
        })
        .collect()
}

fn dimensions_for(key: &AggregationKey) -> HashMap<String, String> {
    let mut dimensions = HashMap::with_capacity(2);
    dimensions.insert(
        "request_type".to_string(),
        key.request_type.as_str().to_string(),
    );
    if let Some(library) = key.library {
        dimensions.insert("library".to_string(), library.as_str().to_string());
    }
    dimensions
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_request::FlagRequestType;
    use crate::handler::types::Library;

    fn key(team_id: i32, library: Option<Library>) -> AggregationKey {
        AggregationKey {
            team_id,
            request_type: FlagRequestType::Decide,
            library,
            bucket: 7,
        }
    }

    #[test]
    fn build_records_applies_the_team_filter() {
        let entries = vec![(key(1, None), 5), (key(2, None), 9)];
        let records = build_records(
            &entries,
            &TeamIdCollection::TeamIds(vec![2]),
            1_700_000_000_000,
        );

        assert_eq!(records.len(), 1);
        assert_eq!(records[0].team_id, 2);
        assert_eq!(records[0].quantity, 9);
    }

    #[test]
    fn build_records_skips_zero_counts() {
        let entries = vec![(key(1, None), 0)];
        assert!(build_records(&entries, &TeamIdCollection::All, 1).is_empty());
    }

    #[test]
    fn build_records_carries_the_aggregation_key_as_dimensions() {
        let entries = vec![(key(3, Some(Library::PosthogJs)), 2)];
        let records = build_records(&entries, &TeamIdCollection::All, 1_700_000_000_000);

        assert_eq!(records[0].dimensions.get("request_type").unwrap(), "decide");
        assert_eq!(records[0].dimensions.get("library").unwrap(), "posthog-js");
        assert_eq!(records[0].mode, BillingUsageMode::Delta as i32);
        assert_eq!(records[0].producer_id, PRODUCER_ID);
        assert_eq!(records[0].usage_key, USAGE_KEY);
    }

    #[test]
    fn build_records_gives_every_emission_its_own_id() {
        let entries = vec![(key(1, None), 1), (key(2, None), 1)];
        let records = build_records(&entries, &TeamIdCollection::All, 1);

        assert_ne!(records[0].record_id, records[1].record_id);
    }

    #[tokio::test]
    async fn shutdown_is_idempotent_and_closes_the_queue() {
        let reporter = UsageReporter::new("http://localhost:1", TeamIdCollection::All, 50)
            .unwrap()
            .unwrap();

        reporter
            .shutdown(std::time::Duration::from_millis(200))
            .await;
        // A second shutdown must not panic on the already-taken sender, and a late report must be
        // counted as dropped rather than queued onto a closed channel.
        reporter
            .shutdown(std::time::Duration::from_millis(200))
            .await;
        reporter.report(&[(key(1, None), 1)], 1);
    }

    #[tokio::test]
    async fn new_is_disabled_without_a_url_or_teams() {
        assert!(UsageReporter::new("", TeamIdCollection::All, 100)
            .unwrap()
            .is_none());
        assert!(
            UsageReporter::new("http://localhost:7143", TeamIdCollection::None, 100)
                .unwrap()
                .is_none()
        );
        assert!(
            UsageReporter::new("http://localhost:7143", TeamIdCollection::All, 100)
                .unwrap()
                .is_some()
        );
    }
}
