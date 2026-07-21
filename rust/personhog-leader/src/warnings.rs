use std::sync::Arc;

use metrics::counter;
use rdkafka::producer::{FutureProducer, FutureRecord};
use serde_json::{Map, Value};
use tracing::warn;

use common_ingestion_warnings::direct::build_direct_warning_payload;
use common_ingestion_warnings::registry::WarningType;
use common_ingestion_warnings::throttle::{ThrottleDecision, WarningThrottle};
use common_kafka::kafka_producer::KafkaContext;

/// An in-product ingestion warning about a person's property size —
/// emitted when admission trims an update to fit the Postgres constraint
/// or rejects one that cannot fit. Carries no property values, only
/// identifiers and sizes.
pub struct SizeViolationWarning {
    pub team_id: i64,
    /// The person's UUID — the pipeline convention for `personId` in
    /// warning details (row ids stay internal).
    pub person_uuid: String,
    pub message: String,
}

/// Produces ingestion warnings to Kafka so users see property size
/// violations in-product, with the payload built by the shared
/// ingestion-warnings crate so type and classification come from the
/// pipeline registry. Shares the leader's changelog producer (rdkafka
/// producers are topic-agnostic), so buffered warnings flush with it on
/// shutdown; emission is fire-and-forget and never blocks or fails the
/// update that triggered it.
///
/// Emission is throttled per `(team, type)` with the pipeline's default
/// budget (one per hour), matching the Node consumers' warning limiter:
/// one oversized person being hammered with updates yields one warning an
/// hour, not one per update. Cloning shares the throttle, so every handle
/// draws from the same budget.
#[derive(Clone)]
pub struct WarningsProducer {
    producer: FutureProducer<KafkaContext>,
    topic: String,
    throttle: Arc<WarningThrottle>,
}

impl WarningsProducer {
    pub fn new(producer: FutureProducer<KafkaContext>, topic: String) -> Self {
        Self::with_throttle(producer, topic, WarningThrottle::default())
    }

    /// Construct with an explicit throttle — tests use a larger burst so
    /// consecutive enforcement actions for one team all surface.
    pub fn with_throttle(
        producer: FutureProducer<KafkaContext>,
        topic: String,
        throttle: WarningThrottle,
    ) -> Self {
        Self {
            producer,
            topic,
            throttle: Arc::new(throttle),
        }
    }

    pub fn emit(&self, warning: &SizeViolationWarning) {
        let warning_type = WarningType::PersonPropertiesSizeViolation;
        match self
            .throttle
            .check(&warning.team_id.to_string(), warning_type)
        {
            ThrottleDecision::Emit => {}
            ThrottleDecision::Throttled => {
                counter!(
                    "personhog_leader_ingestion_warnings_suppressed_total",
                    "outcome" => "throttled"
                )
                .increment(1);
                return;
            }
            ThrottleDecision::CardinalityCapped => {
                counter!(
                    "personhog_leader_ingestion_warnings_suppressed_total",
                    "outcome" => "cardinality_capped"
                )
                .increment(1);
                return;
            }
        }

        let mut details = Map::new();
        details.insert(
            "personId".to_string(),
            Value::from(warning.person_uuid.clone()),
        );
        details.insert("teamId".to_string(), Value::from(warning.team_id));
        details.insert("message".to_string(), Value::from(warning.message.clone()));
        let payload = build_direct_warning_payload(
            warning.team_id,
            warning_type,
            "personhog-leader",
            details,
        );

        let payload_bytes = serde_json::to_vec(&payload).unwrap_or_default();
        let key = warning.team_id.to_string();
        let record = FutureRecord::to(&self.topic)
            .payload(&payload_bytes)
            .key(&key);

        match self.producer.send_result(record) {
            Ok(_future) => {
                counter!("personhog_leader_ingestion_warnings_emitted_total").increment(1);
            }
            Err((e, _)) => {
                warn!(error = %e, "failed to enqueue ingestion warning");
            }
        }
    }

    /// Evict fully refilled throttle keys, bounding memory. Called from the
    /// leader's periodic maintenance task.
    pub fn sweep_throttle(&self) {
        self.throttle.sweep();
    }
}
