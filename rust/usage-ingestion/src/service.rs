use std::collections::HashMap;
use std::sync::Arc;

use chrono::Utc;
use common_kafka::kafka_producer::{
    send_keyed_payloads_to_kafka_with_encoding, EnvelopeEncoding, KafkaContext,
};
use rdkafka::producer::FutureProducer;
use tonic::{Request, Response, Status};
use usage_ingestion_proto::usage_ingestion::v1::{
    usage_ingestion_server::UsageIngestion, IngestUsageRecordsRequest, IngestUsageRecordsResponse,
    UsageRecord,
};
use uuid::Uuid;

use crate::record::KafkaUsageRecord;
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
        record: UsageRecord,
        resolved: &mut HashMap<i64, Uuid>,
    ) -> Result<KafkaUsageRecord, Status> {
        if record.team_id <= 0 || record.team_id > i64::from(i32::MAX) {
            return Err(Status::invalid_argument(
                "team_id must be a positive 32-bit integer",
            ));
        }
        let provided_organization = record
            .organization_id
            .as_deref()
            .map(Uuid::parse_str)
            .transpose()
            .map_err(|_| Status::invalid_argument("organization_id must be a UUID"))?;
        let organization_id = match provided_organization {
            Some(value) => value,
            None => match resolved.get(&record.team_id) {
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
            },
        };

        KafkaUsageRecord::from_proto(record, organization_id, Utc::now())
            .map_err(|error| Status::invalid_argument(error.to_string()))
    }
}

#[tonic::async_trait]
impl UsageIngestion for UsageIngestionService {
    async fn ingest(
        &self,
        request: Request<IngestUsageRecordsRequest>,
    ) -> Result<Response<IngestUsageRecordsResponse>, Status> {
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
        let payloads = prepared.into_iter().map(|record| {
            let key = Some(record.team_id.to_string());
            serde_json::to_vec(&record)
                .map(|payload| (key, payload))
                .map_err(|error| {
                    Status::internal(format!("failed to encode usage record: {error}"))
                })
        });
        let payloads = payloads.collect::<Result<Vec<_>, _>>()?;
        let results = send_keyed_payloads_to_kafka_with_encoding(
            &self.producer,
            &self.topic,
            EnvelopeEncoding::None,
            payloads,
        )
        .await;
        if results.iter().any(Result::is_err) {
            return Err(Status::unavailable(
                "Kafka did not confirm every usage record; retry with the same record IDs",
            ));
        }

        Ok(Response::new(IngestUsageRecordsResponse {
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
