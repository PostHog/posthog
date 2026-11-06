use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use chrono::Utc;
use common_kafka::kafka_producer::{
    send_keyed_payloads_to_kafka_with_encoding, EnvelopeEncoding, KafkaContext,
};
use rdkafka::producer::FutureProducer;
use tonic::{Request, Response, Status};
use usage_ingestion_proto::usage_ingestion::v1::{
    usage_ingestion_server::UsageIngestion, BillingUsageRecord, IngestBillingUsageRequest,
    IngestBillingUsageResponse,
};
use uuid::Uuid;

use crate::counters::CounterAccumulator;
use crate::record::KafkaBillingUsageRecord;
use crate::resolver::{OrganizationResolver, ResolveError};

pub struct UsageIngestionService {
    producer: FutureProducer<KafkaContext>,
    resolver: Arc<dyn OrganizationResolver>,
    max_batch_size: usize,
    topic: String,
    counters: Option<Arc<CounterAccumulator>>,
}

impl UsageIngestionService {
    pub fn new(
        producer: FutureProducer<KafkaContext>,
        resolver: Arc<dyn OrganizationResolver>,
        max_batch_size: usize,
        topic: String,
        counters: Option<Arc<CounterAccumulator>>,
    ) -> Self {
        Self {
            producer,
            resolver,
            max_batch_size,
            topic,
            counters,
        }
    }

    async fn prepare(
        &self,
        record: BillingUsageRecord,
        resolved: &mut HashMap<i64, Result<Uuid, &'static str>>,
    ) -> Result<KafkaBillingUsageRecord, PrepareError> {
        if record.team_id <= 0 || record.team_id > i64::from(i32::MAX) {
            return Err(PrepareError::Rejected("invalid_team_id"));
        }
        // A rejection is memoized alongside a success, so a batch of 500 records from one
        // unmapped team costs one resolver call rather than 500 cache reads counted as hits.
        let organization_id = match resolved.get(&record.team_id) {
            Some(Ok(value)) => *value,
            Some(Err(reason)) => return Err(PrepareError::Rejected(reason)),
            None => match self.resolver.resolve(record.team_id).await {
                Ok(value) => {
                    resolved.insert(record.team_id, Ok(value));
                    value
                }
                Err(error) => {
                    let error = prepare_error(error);
                    if let PrepareError::Rejected(reason) = error {
                        resolved.insert(record.team_id, Err(reason));
                    }
                    return Err(error);
                }
            },
        };

        KafkaBillingUsageRecord::from_proto(record, organization_id, Utc::now())
            .map_err(|_| PrepareError::Rejected("invalid_record"))
    }

    /// Returns the records to produce and what was dropped on the way. A rejected record fails
    /// the same way however often it is re-sent, so keeping the batch alive is the difference
    /// between losing one team's usage and losing every team's usage that happened to share
    /// the batch with it.
    async fn prepare_batch(
        &self,
        records: Vec<BillingUsageRecord>,
    ) -> Result<(Vec<KafkaBillingUsageRecord>, Vec<Rejection>), Status> {
        // One resolver call per distinct team, not per record: a full batch from one
        // team would otherwise be 500 Redis reads and 500 queries on a cold cache.
        let mut resolved = HashMap::new();
        let mut prepared = Vec::with_capacity(records.len());
        let mut rejected = Vec::new();
        for record in records {
            let team_id = record.team_id;
            match self.prepare(record, &mut resolved).await {
                Ok(record) => prepared.push(record),
                Err(PrepareError::Rejected(reason)) => {
                    metrics::counter!("usage_ingestion_records_rejected_total", "reason" => reason)
                        .increment(1);
                    rejected.push(Rejection { team_id, reason });
                }
                Err(PrepareError::Unavailable(status)) => return Err(status),
            }
        }
        rejected.sort_unstable();
        rejected.dedup();
        Ok((prepared, rejected))
    }
}

/// Splits a failed record by what the producer should do about it. Anything a retry cannot
/// change is skipped; anything the service could not determine fails the whole batch, so the
/// producer sends it again.
#[derive(Debug)]
enum PrepareError {
    Rejected(&'static str),
    Unavailable(Status),
}

/// A team the service dropped records for, and why. Deduplicated per batch, so a team that
/// fails the same way twice reads as one lead.
#[derive(Debug, PartialEq, Eq, PartialOrd, Ord)]
struct Rejection {
    team_id: i64,
    reason: &'static str,
}

#[tonic::async_trait]
impl UsageIngestion for UsageIngestionService {
    async fn ingest_billing_usage(
        &self,
        request: Request<IngestBillingUsageRequest>,
    ) -> Result<Response<IngestBillingUsageResponse>, Status> {
        let records = request.into_inner().records;
        if records.is_empty() {
            return Err(Status::invalid_argument("records must not be empty"));
        }
        if records.len() > self.max_batch_size {
            return Err(Status::invalid_argument(
                "records exceeds the configured batch limit",
            ));
        }

        let (prepared, rejected) = self.prepare_batch(records).await?;
        if !rejected.is_empty() {
            tracing::warn!(
                rejected = ?rejected,
                "dropped usage records the service cannot accept"
            );
        }
        if prepared.is_empty() {
            return Ok(Response::new(IngestBillingUsageResponse::default()));
        }

        let accepted_record_ids = prepared
            .iter()
            .map(|record| record.record_id.clone())
            .collect::<Vec<_>>();
        // No key: nothing downstream reads per-team order, and a team key crowds one partition.
        let payloads = prepared.iter().map(|record| {
            serde_json::to_vec(record)
                .map(|payload| (None, payload))
                .map_err(|error| {
                    Status::internal(format!("failed to encode usage record: {error}"))
                })
        });
        let payloads = payloads.collect::<Result<Vec<_>, _>>()?;
        let producer_started_at = Instant::now();
        let results = send_keyed_payloads_to_kafka_with_encoding(
            &self.producer,
            &self.topic,
            EnvelopeEncoding::None,
            payloads,
        )
        .await;
        metrics::histogram!("usage_ingestion_kafka_delivery_seconds")
            .record(producer_started_at.elapsed().as_secs_f64());
        if results.iter().any(Result::is_err) {
            return Err(Status::unavailable(
                "Kafka did not confirm every usage record; retry with the same record IDs",
            ));
        }

        if let Some(counters) = &self.counters {
            metrics::histogram!("usage_ingestion_distinct_scopes_per_request")
                .record(CounterAccumulator::scope_count_for_records(&prepared) as f64);
            for record in &prepared {
                if let Err(error) = counters.add_record(record) {
                    metrics::counter!(
                        "usage_ingestion_redis_counter_rejected_deltas_total",
                        "reason" => error.reason()
                    )
                    .increment(1);
                    metrics::counter!("usage_ingestion_redis_counter_errors_total").increment(1);
                }
            }
        }

        Ok(Response::new(IngestBillingUsageResponse {
            accepted_record_ids,
        }))
    }
}

fn prepare_error(error: ResolveError) -> PrepareError {
    match error {
        ResolveError::InvalidTeamId => PrepareError::Rejected("invalid_team_id"),
        ResolveError::Missing => PrepareError::Rejected("organization_missing"),
        ResolveError::Database(error) => PrepareError::Unavailable(Status::unavailable(format!(
            "team organization lookup failed: {error}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use async_trait::async_trait;
    use common_liveness::SyncLivenessReporter;
    use rdkafka::ClientConfig;

    use super::*;

    const TEAM_ORGANIZATION: &str = "018f7c8e-4c08-7c5e-9bc0-15c9f5cc9f42";

    #[derive(Clone, Copy)]
    struct AlwaysHealthy;

    impl SyncLivenessReporter for AlwaysHealthy {
        fn report_healthy(&self) {}
        fn report_unhealthy(&self) {}
    }

    struct FixedResolver;

    #[async_trait]
    impl OrganizationResolver for FixedResolver {
        async fn resolve(&self, _team_id: i64) -> Result<Uuid, ResolveError> {
            Ok(Uuid::parse_str(TEAM_ORGANIZATION).unwrap())
        }
    }

    /// Resolves every team except `unmapped`, which stands in for a team whose organization
    /// row is gone. Counts its calls, so a test can pin how often a batch asks.
    #[derive(Default)]
    struct PartialResolver {
        unmapped: i64,
        calls: AtomicUsize,
    }

    #[async_trait]
    impl OrganizationResolver for PartialResolver {
        async fn resolve(&self, team_id: i64) -> Result<Uuid, ResolveError> {
            self.calls.fetch_add(1, Ordering::Relaxed);
            if team_id == self.unmapped {
                return Err(ResolveError::Missing);
            }
            Ok(Uuid::parse_str(TEAM_ORGANIZATION).unwrap())
        }
    }

    struct UnreachableResolver;

    #[async_trait]
    impl OrganizationResolver for UnreachableResolver {
        async fn resolve(&self, _team_id: i64) -> Result<Uuid, ResolveError> {
            Err(ResolveError::Database(sqlx::Error::PoolTimedOut))
        }
    }

    fn service_with(resolver: Arc<dyn OrganizationResolver>) -> UsageIngestionService {
        // prepare_batch() never produces, so the producer only has to exist.
        let producer = ClientConfig::new()
            .set("bootstrap.servers", "localhost:9092")
            .create_with_context(KafkaContext::new(AlwaysHealthy))
            .expect("failed to build the test producer");
        UsageIngestionService::new(producer, resolver, 500, "test-topic".to_string(), None)
    }

    fn service() -> UsageIngestionService {
        service_with(Arc::new(FixedResolver))
    }

    fn record() -> BillingUsageRecord {
        BillingUsageRecord {
            record_id: "018f7c8e-4c08-7c5e-9bc0-15c9f5cc9f44".to_string(),
            producer_id: "feature-flags".to_string(),
            team_id: 42,
            usage_key: "feature_flag_requests".to_string(),
            unit: "request".to_string(),
            quantity: 10,
            timestamp_ms: 1_718_409_600_000,
        }
    }

    fn record_for(team_id: i64) -> BillingUsageRecord {
        BillingUsageRecord {
            record_id: format!("018f7c8e-4c08-7c5e-9bc0-15c9f5cc9f{team_id:02}"),
            team_id,
            ..record()
        }
    }

    #[tokio::test]
    async fn the_resolved_organization_is_stamped_on_the_record() {
        let prepared = service()
            .prepare(record(), &mut HashMap::new())
            .await
            .expect("the record should be accepted");

        assert_eq!(
            prepared.organization_id,
            Uuid::parse_str(TEAM_ORGANIZATION).unwrap()
        );
    }

    #[tokio::test]
    async fn an_unattributable_team_does_not_discard_the_rest_of_the_batch() {
        let resolver = Arc::new(PartialResolver {
            unmapped: 11,
            ..Default::default()
        });
        let service = service_with(resolver.clone());

        let (prepared, rejected) = service
            .prepare_batch(vec![record_for(10), record_for(11), record_for(12)])
            .await
            .expect("a rejected record must not fail the batch");

        assert_eq!(
            prepared.iter().map(|r| r.team_id).collect::<Vec<_>>(),
            vec![10, 12]
        );
        assert_eq!(
            rejected,
            vec![Rejection {
                team_id: 11,
                reason: "organization_missing"
            }]
        );
    }

    #[tokio::test]
    async fn a_batch_asks_the_resolver_once_per_team_even_when_it_says_no() {
        let resolver = Arc::new(PartialResolver {
            unmapped: 11,
            ..Default::default()
        });
        let service = service_with(resolver.clone());
        let records = (0..4).map(|_| record_for(11)).collect();

        let (prepared, rejected) = service.prepare_batch(records).await.unwrap();

        assert!(prepared.is_empty());
        // One lead per team, and one lookup, however many of its records the batch held.
        assert_eq!(rejected.len(), 1);
        assert_eq!(resolver.calls.load(Ordering::Relaxed), 1);
    }

    #[tokio::test]
    async fn a_record_the_service_can_never_accept_is_skipped() {
        // Validation the record itself fails, rather than anything about its team.
        let unbillable = BillingUsageRecord {
            quantity: 0,
            ..record_for(10)
        };

        let (prepared, rejected) = service()
            .prepare_batch(vec![unbillable, record_for(12)])
            .await
            .expect("a rejected record must not fail the batch");

        assert_eq!(prepared.len(), 1);
        assert_eq!(
            rejected,
            vec![Rejection {
                team_id: 10,
                reason: "invalid_record"
            }]
        );
    }

    #[tokio::test]
    async fn a_lookup_that_could_not_be_answered_still_fails_the_batch() {
        // The producer has to retry this one, so it must not look like an accepted batch
        // that happened to drop records.
        let status = service_with(Arc::new(UnreachableResolver))
            .prepare_batch(vec![record_for(10)])
            .await
            .expect_err("an unavailable lookup must fail the batch");

        assert_eq!(status.code(), tonic::Code::Unavailable);
    }
}
