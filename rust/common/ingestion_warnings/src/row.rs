//! Direct-row transport for services that know the `team_id`; same
//! fire-and-forget contract as [`crate::WarningEmitter`]. The throttle key
//! is `team_id` plus a caller-chosen scope, so one offending entity
//! re-presenting the same condition warns once per period while a
//! different entity warns at once. Scopes are far more numerous than
//! capture's tokens, so a caller sizes the throttle's tracked-key cap for
//! its own cardinality instead of taking the default.

use std::hash::{DefaultHasher, Hash, Hasher};
use std::time::Duration;

use common_kafka::kafka_producer::ThreadedKafkaContext;
use metrics::{counter, gauge};
use rdkafka::error::KafkaError;
use rdkafka::producer::{BaseRecord, Producer, ThreadedProducer};
use rdkafka::types::RDKafkaErrorCode;
use tracing::warn;

use crate::registry::WarningType;
use crate::serializer::Warning;
use crate::throttle::WarningThrottle;
use crate::{
    WarningDelivery, WarningSource, INGESTION_WARNINGS_THROTTLE_KEYS, INGESTION_WARNINGS_TOTAL,
};

pub trait RowWarningEmitter: Send + Sync {
    fn emit(&self, team_id: i64, scope: &str, source: WarningSource, warning: Warning);

    fn flush(&self, timeout: Duration);
}

pub struct KafkaRowWarningEmitter {
    producer: ThreadedProducer<ThreadedKafkaContext<WarningDelivery>>,
    topic: String,
    throttle: WarningThrottle,
}

impl KafkaRowWarningEmitter {
    pub fn new(
        producer: ThreadedProducer<ThreadedKafkaContext<WarningDelivery>>,
        topic: impl Into<String>,
    ) -> Self {
        Self::with_throttle(producer, topic, WarningThrottle::default())
    }

    pub fn with_throttle(
        producer: ThreadedProducer<ThreadedKafkaContext<WarningDelivery>>,
        topic: impl Into<String>,
        throttle: WarningThrottle,
    ) -> Self {
        Self {
            producer,
            topic: topic.into(),
            throttle,
        }
    }

    pub fn sweep_throttle(&self) {
        self.throttle.sweep();
        gauge!(INGESTION_WARNINGS_THROTTLE_KEYS).set(self.throttle.tracked_keys() as f64);
    }
}

/// The scope is caller data of unbounded length (a distinct id, say), and
/// the throttle retains every key for the period, so the key carries a
/// fixed-width digest of it instead.
pub fn throttle_key(team_id: i64, scope: &str) -> String {
    let mut hasher = DefaultHasher::new();
    scope.hash(&mut hasher);
    format!("{team_id}:{:016x}", hasher.finish())
}

fn count(warning: WarningType, source: WarningSource, outcome: &'static str) {
    counter!(
        INGESTION_WARNINGS_TOTAL,
        "type" => warning.as_str(),
        "source" => source.service,
        "path" => source.path,
        "outcome" => outcome,
    )
    .increment(1);
}

impl RowWarningEmitter for KafkaRowWarningEmitter {
    fn emit(&self, team_id: i64, scope: &str, source: WarningSource, warning: Warning) {
        let warning_type = warning.warning_type();
        if let Some(outcome) = self
            .throttle
            .check(&throttle_key(team_id, scope), warning_type)
            .drop_outcome()
        {
            count(warning_type, source, outcome);
            return;
        }

        let payload = match serde_json::to_vec(&warning.into_row(team_id, source)) {
            Ok(payload) => payload,
            Err(err) => {
                count(warning_type, source, "serialize_error");
                warn!(warning_type = warning_type.as_str(), source = source.service, error = %err,
                    "failed to serialize ingestion warning row");
                return;
            }
        };

        let key = team_id.to_string();
        let record = BaseRecord::with_opaque_to(
            &self.topic,
            Box::new(WarningDelivery {
                warning: warning_type,
                source,
            }),
        )
        .key(&key)
        .payload(&payload);

        match self.producer.send(record) {
            Ok(()) => count(warning_type, source, "emitted"),
            Err((KafkaError::MessageProduction(RDKafkaErrorCode::QueueFull), _record)) => {
                count(warning_type, source, "queue_full");
            }
            Err((err, _record)) => {
                count(warning_type, source, "enqueue_error");
                warn!(warning_type = warning_type.as_str(), source = source.service, error = %err,
                    "failed to enqueue ingestion warning row");
            }
        }
    }

    fn flush(&self, timeout: Duration) {
        drop(self.producer.flush(timeout));
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU32;
    use std::time::Instant;

    use common_kafka::config::KafkaConfig;
    use common_kafka::kafka_producer::create_threaded_kafka_producer_no_ping;
    use common_liveness::SyncLivenessReporter;
    use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};

    use super::*;
    use crate::observe_delivery;
    use crate::throttle::DEFAULT_THROTTLE_PERIOD;

    #[derive(Clone, Copy)]
    struct AlwaysHealthy;

    impl SyncLivenessReporter for AlwaysHealthy {
        fn report_healthy(&self) {}
        fn report_unhealthy(&self) {}
    }

    const SOURCE: WarningSource = WarningSource {
        service: "personhog-test",
        path: "row_test",
        pipeline_step: "personhog_test_step",
    };

    fn unreachable_producer(
        queue_messages: u32,
    ) -> ThreadedProducer<ThreadedKafkaContext<WarningDelivery>> {
        let config = KafkaConfig {
            kafka_hosts: "192.0.2.1:9092".to_string(),
            kafka_message_timeout_ms: 500,
            kafka_producer_linger_ms: 5,
            kafka_producer_queue_messages: queue_messages,
            kafka_producer_retries: Some(0),
            ..Default::default()
        };
        create_threaded_kafka_producer_no_ping(&config, AlwaysHealthy, observe_delivery)
            .expect("client config is valid, so creation cannot fail without a broker round-trip")
    }

    fn outcomes(snapshotter: &Snapshotter) -> Vec<(String, u64)> {
        let mut totals: std::collections::BTreeMap<String, u64> = Default::default();
        for (ckey, _, _, value) in snapshotter.snapshot().into_vec() {
            if ckey.key().name() != INGESTION_WARNINGS_TOTAL {
                continue;
            }
            let outcome = ckey
                .key()
                .labels()
                .find(|l| l.key() == "outcome")
                .map(|l| l.value().to_string())
                .expect("outcome label");
            let n = match value {
                DebugValue::Counter(n) => n,
                other => panic!("expected a counter, got {other:?}"),
            };
            *totals.entry(outcome).or_default() += n;
        }
        totals.into_iter().collect()
    }

    fn warning() -> Warning {
        Warning::new(WarningType::CannotMergeAlreadyIdentified).with_detail("distinctId", "u1")
    }

    #[test]
    fn emit_is_fire_and_forget_and_throttles_per_team_scope_and_type() {
        let emitter = KafkaRowWarningEmitter::new(unreachable_producer(100), "warnings");
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();

        let start = Instant::now();
        metrics::with_local_recorder(&recorder, || {
            emitter.emit(7, "did-a", SOURCE, warning());
            emitter.emit(7, "did-a", SOURCE, warning());
            emitter.emit(7, "did-b", SOURCE, warning());
            emitter.emit(8, "did-a", SOURCE, warning());
            emitter.emit(
                7,
                "did-a",
                SOURCE,
                Warning::new(WarningType::MergeSettledFailure),
            );
        });
        assert!(
            start.elapsed() < Duration::from_millis(500),
            "emit must never wait on the broker"
        );

        assert_eq!(
            outcomes(&snapshotter),
            vec![("emitted".to_string(), 4), ("throttled".to_string(), 1)],
            "only the repeat of the same team, scope and type is throttled"
        );
    }

    #[test]
    fn a_type_budget_caps_the_pod_across_teams() {
        let throttle =
            WarningThrottle::default().with_type_budget(DEFAULT_THROTTLE_PERIOD, NonZeroU32::MIN);
        let emitter =
            KafkaRowWarningEmitter::with_throttle(unreachable_producer(100), "warnings", throttle);
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();

        metrics::with_local_recorder(&recorder, || {
            for team in [1, 2, 3] {
                emitter.emit(team, "did", SOURCE, warning());
            }
        });

        assert_eq!(
            outcomes(&snapshotter),
            vec![
                ("emitted".to_string(), 1),
                ("type_budget_exhausted".to_string(), 2)
            ]
        );
    }

    #[test]
    fn a_full_local_queue_drops_the_row_and_counts_it() {
        let emitter = KafkaRowWarningEmitter::new(unreachable_producer(1), "warnings");
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();

        metrics::with_local_recorder(&recorder, || {
            emitter.emit(1, "a", SOURCE, warning());
            emitter.emit(2, "a", SOURCE, warning());
        });

        assert_eq!(
            outcomes(&snapshotter),
            vec![("emitted".to_string(), 1), ("queue_full".to_string(), 1)]
        );
    }

    #[test]
    fn the_throttle_key_is_fixed_width_whatever_the_scope_length() {
        let huge = "x".repeat(1 << 20);
        let key = throttle_key(7, &huge);
        assert_eq!(key.len(), throttle_key(7, "did").len());
        assert_ne!(key, throttle_key(7, &format!("{huge}y")));
        assert_ne!(key, throttle_key(8, &huge));
        assert_eq!(key, throttle_key(7, &huge));
    }
}
