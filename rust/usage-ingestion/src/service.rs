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

use crate::record::KafkaBillingUsageRecord;
use crate::resolver::{OrganizationResolver, ResolveError};

pub struct UsageIngestionService {
    producer: FutureProducer<KafkaContext>,
    resolver: Arc<dyn OrganizationResolver>,
    max_batch_size: usize,
    topic: String,
}

impl UsageIngestionService {
    pub fn new(
        producer: FutureProducer<KafkaContext>,
        resolver: Arc<dyn OrganizationResolver>,
        max_batch_size: usize,
        topic: String,
    ) -> Self {
        Self {
            producer,
            resolver,
            max_batch_size,
            topic,
        }
    }

    async fn prepare(
        &self,
        record: BillingUsageRecord,
        resolved: &mut HashMap<i64, Uuid>,
    ) -> Result<KafkaBillingUsageRecord, Status> {
        if record.team_id <= 0 || record.team_id > i64::from(i32::MAX) {
            return Err(Status::invalid_argument(
                "team_id must be a positive 32-bit integer",
            ));
        }
        let organization_id = match resolved.get(&record.team_id) {
            Some(value) => *value,
            None => {
                let value = self
                    .resolver
                    .resolve(record.team_id)
                    .await
                    .map_err(resolve_status)?;
                resolved.insert(record.team_id, value);
                value
            }
        };

        KafkaBillingUsageRecord::from_proto(record, organization_id, Utc::now())
            .map_err(|error| Status::invalid_argument(error.to_string()))
    }
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

        // One resolver call per distinct team, not per record: a full batch from one
        // team would otherwise be 500 Redis reads and 500 queries on a cold cache.
        let mut resolved = HashMap::new();
        let mut prepared = Vec::with_capacity(records.len());
        for record in records {
            prepared.push(self.prepare(record, &mut resolved).await?);
        }
        let accepted_record_ids = prepared
            .iter()
            .map(|record| record.record_id.clone())
            .collect::<Vec<_>>();
        // No key: nothing downstream reads per-team order, and a team key crowds one partition.
        let payloads = prepared.into_iter().map(|record| {
            serde_json::to_vec(&record)
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

        Ok(Response::new(IngestBillingUsageResponse {
            accepted_record_ids,
        }))
    }
}

fn resolve_status(error: ResolveError) -> Status {
    match error {
        ResolveError::InvalidTeamId => {
            Status::invalid_argument("team_id must be a positive 32-bit integer")
        }
        ResolveError::Missing => Status::not_found("team organization mapping was not found"),
        ResolveError::Database(error) => {
            Status::unavailable(format!("team organization lookup failed: {error}"))
        }
    }
}

#[cfg(test)]
mod tests {
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

    fn service() -> UsageIngestionService {
        // prepare() never produces, so the producer only has to exist.
        let producer = ClientConfig::new()
            .set("bootstrap.servers", "localhost:9092")
            .create_with_context(KafkaContext::new(AlwaysHealthy))
            .expect("failed to build the test producer");
        UsageIngestionService::new(
            producer,
            Arc::new(FixedResolver),
            500,
            "test-topic".to_string(),
        )
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
}
