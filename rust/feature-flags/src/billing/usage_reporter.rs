//! Mirrors flushed billing counts into the usage-ingestion service. Records are emitted only for a
//! chunk already credited to Redis, so a Redis retry cannot bill twice.
//!
//! `record_id` is a fresh UUID per emission, not derived from the aggregation key: a Redis outage
//! rebuckets and merges requeued entries, so one key legitimately carries different quantities
//! across flushes. A retry reuses the record it already built, which is what makes retrying safe:
//! the service deduplicates on `record_id`, including when Kafka took only part of the batch.

use std::sync::Arc;
use std::sync::Mutex;

use common_metrics::inc;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tonic::transport::{Channel, Endpoint};
use tonic::Code;
use usage_ingestion_proto::usage_ingestion::v1::{
    usage_ingestion_client::UsageIngestionClient, BillingUsageRecord, IngestBillingUsageRequest,
};
use uuid::Uuid;

use crate::config::TeamIdCollection;
use crate::flags::flag_request::FlagRequestType;
use crate::metrics::consts::{FLAGS_USAGE_RECORDS_FAILED, FLAGS_USAGE_RECORDS_SENT};

use super::AggregationKey;

const PRODUCER_ID: &str = "feature-flags";
const UNIT: &str = "requests";
const MAX_BATCH_SIZE: usize = 500;
/// Queued sends waiting on the sender task. A full queue drops rather than growing
/// unboundedly; the drop is counted, and Redis still holds the authoritative count.
const QUEUE_CAPACITY: usize = 64;
/// Attempts per chunk, including the first. The sender is one task, so a chunk that
/// keeps failing holds up the queue behind it — hence a small number and a short wait.
const SEND_ATTEMPTS: u32 = 3;
const RETRY_BACKOFF: std::time::Duration = std::time::Duration::from_millis(100);

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
        addr: &str,
        use_tls: bool,
        teams: TeamIdCollection,
        timeout_ms: u64,
    ) -> Result<Option<Arc<Self>>, String> {
        if addr.is_empty() || matches!(teams, TeamIdCollection::None) {
            return Ok(None);
        }
        // tonic is built here without its TLS feature, so an https endpoint fails at connect
        // time with nothing naming the cause. Refuse at startup instead.
        if use_tls {
            return Err("USAGE_INGESTION_TLS is not supported by the flags reporter".to_string());
        }
        let endpoint = Endpoint::from_shared(format!("http://{addr}"))
            .map_err(|e| format!("invalid USAGE_INGESTION_ADDR: {e}"))?
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
        let record_count = records.len() as u64;
        let queued = match self.state.lock().unwrap().as_ref() {
            Some(state) => state.queue.try_send(records).is_ok(),
            None => false,
        };
        if !queued {
            inc(FLAGS_USAGE_RECORDS_FAILED, &[], record_count);
            tracing::warn!(
                records = record_count,
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

/// A code the service returns for a condition that clears on its own: an unreachable
/// or draining pod, a timeout, a full queue. The rest, `invalid_argument` above all,
/// describe the records themselves and would fail the same way forever.
fn is_retryable(code: Code) -> bool {
    matches!(
        code,
        Code::Unavailable | Code::DeadlineExceeded | Code::ResourceExhausted | Code::Aborted
    )
}

async fn run_sender(
    client: UsageIngestionClient<Channel>,
    mut receiver: mpsc::Receiver<Vec<BillingUsageRecord>>,
) {
    while let Some(records) = receiver.recv().await {
        for chunk in records.chunks(MAX_BATCH_SIZE) {
            send_chunk(&client, chunk).await;
        }
    }
}

/// Retries the same records, never rebuilt ones, so the service's `record_id` dedup holds.
/// A bounded retry is the ceiling here: a crash still loses what the queue holds, and Redis
/// plus the nightly report stay authoritative for what a team owes.
async fn send_chunk(client: &UsageIngestionClient<Channel>, chunk: &[BillingUsageRecord]) {
    let count = chunk.len() as u64;
    let request = IngestBillingUsageRequest {
        records: chunk.to_vec(),
    };
    for attempt in 1..=SEND_ATTEMPTS {
        let mut client = client.clone();
        match client.ingest_billing_usage(request.clone()).await {
            Ok(_) => {
                inc(FLAGS_USAGE_RECORDS_SENT, &[], count);
                return;
            }
            Err(status) => {
                let retryable = is_retryable(status.code());
                if !retryable || attempt == SEND_ATTEMPTS {
                    inc(FLAGS_USAGE_RECORDS_FAILED, &[], count);
                    tracing::warn!(
                        records = count,
                        attempts = attempt,
                        code = %status.code(),
                        "failed to report feature flag usage records"
                    );
                    return;
                }
                tokio::time::sleep(RETRY_BACKOFF * attempt).await;
            }
        }
    }
}

/// The two billable request types are priced apart — the nightly report weighs one local
/// evaluation as ten decide requests — so they cannot share a key. The weighting itself stays
/// out of here: a producer reports what happened, and pricing is applied downstream.
fn usage_key(request_type: FlagRequestType) -> &'static str {
    match request_type {
        FlagRequestType::Decide => "feature_flag_requests",
        FlagRequestType::FlagDefinitions => "feature_flag_local_evaluation_requests",
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
            usage_key: usage_key(key.request_type).to_string(),
            unit: UNIT.to_string(),
            quantity: i64::try_from(*count).unwrap_or(i64::MAX),
            timestamp_ms,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::billing::usage_test_support::{serve, RecordingIngestion};
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
    fn build_records_keys_the_two_billable_request_types_apart() {
        // The report weighs one local evaluation as ten decide requests, so a shared key
        // would price them the same.
        let entries = vec![
            (key(1, None), 3),
            (
                AggregationKey {
                    request_type: FlagRequestType::FlagDefinitions,
                    ..key(1, None)
                },
                4,
            ),
        ];
        let records = build_records(&entries, &TeamIdCollection::All, 1);

        assert_eq!(
            records
                .iter()
                .map(|record| (record.usage_key.as_str(), record.quantity))
                .collect::<Vec<_>>(),
            vec![
                ("feature_flag_requests", 3),
                ("feature_flag_local_evaluation_requests", 4)
            ]
        );
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
    fn build_records_gives_every_emission_its_own_id() {
        let entries = vec![(key(1, None), 1), (key(2, None), 1)];
        let records = build_records(&entries, &TeamIdCollection::All, 1);

        assert_ne!(records[0].record_id, records[1].record_id);
    }

    #[tokio::test]
    async fn shutdown_is_idempotent_and_closes_the_queue() {
        let reporter = UsageReporter::new("127.0.0.1:1", false, TeamIdCollection::All, 50)
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
    async fn new_is_disabled_without_an_address_or_teams() {
        assert!(UsageReporter::new("", false, TeamIdCollection::All, 100)
            .unwrap()
            .is_none());
        assert!(
            UsageReporter::new("localhost:7143", false, TeamIdCollection::None, 100)
                .unwrap()
                .is_none()
        );
        assert!(
            UsageReporter::new("localhost:7143", false, TeamIdCollection::All, 100)
                .unwrap()
                .is_some()
        );
    }

    #[tokio::test]
    async fn new_refuses_tls_it_cannot_honor() {
        assert!(UsageReporter::new("localhost:7143", true, TeamIdCollection::All, 100).is_err());
    }

    async fn reporter_for(addr: std::net::SocketAddr) -> Arc<UsageReporter> {
        UsageReporter::new(&addr.to_string(), false, TeamIdCollection::All, 1_000)
            .unwrap()
            .unwrap()
    }

    /// `shutdown` is the drain, so it also stands in for a wait: it returns once the sender
    /// task has emptied the queue, which is what the aggregator's ordering promises.
    #[tokio::test]
    async fn a_queued_record_reaches_the_service_by_shutdown() {
        let service = RecordingIngestion::default();
        let reporter = reporter_for(serve(service.clone()).await).await;

        reporter.report(&[(key(7, None), 4)], 1_700_000_000_000);
        reporter.shutdown(std::time::Duration::from_secs(5)).await;

        let requests = service.requests();
        assert_eq!(requests.len(), 1);
        assert_eq!(requests[0].len(), 1);
        assert_eq!(requests[0][0].team_id, 7);
        assert_eq!(requests[0][0].quantity, 4);
        assert_eq!(requests[0][0].producer_id, PRODUCER_ID);
        assert_eq!(requests[0][0].usage_key, usage_key(FlagRequestType::Decide));
    }

    #[tokio::test]
    async fn retries_a_transient_failure_with_the_same_record_id() {
        let service = RecordingIngestion::default();
        service.fail_next(Code::Unavailable);
        let reporter = reporter_for(serve(service.clone()).await).await;

        reporter.report(&[(key(7, None), 1)], 1_700_000_000_000);
        reporter.shutdown(std::time::Duration::from_secs(5)).await;

        let requests = service.requests();
        assert_eq!(requests.len(), 2);
        // Reusing the ID is what makes the retry safe: the service deduplicates on it, so a
        // batch Kafka took only part of does not bill twice.
        assert_eq!(requests[0][0].record_id, requests[1][0].record_id);
    }

    #[tokio::test]
    async fn does_not_retry_a_rejected_batch() {
        let service = RecordingIngestion::default();
        // The records themselves are wrong, so every attempt fails the same way.
        service.fail_next(Code::InvalidArgument);
        let reporter = reporter_for(serve(service.clone()).await).await;

        reporter.report(&[(key(7, None), 1)], 1_700_000_000_000);
        reporter.shutdown(std::time::Duration::from_secs(5)).await;

        assert_eq!(service.requests().len(), 1);
    }
}
