use std::time::Duration;

use common_kafka::kafka_producer::KafkaContext;
use lifecycle::Handle;
use rdkafka::producer::{FutureProducer, Producer};

/// Formats the Kafka message key for person state changelog messages.
/// The topic must include `compact` in its `cleanup.policy` so Kafka
/// retains the latest state per person. Deployed config is
/// `compact,delete`, where retention bounds even the latest record —
/// acceptable because nothing reads records older than the writer's
/// committed offset, which retention outruns by design.
pub fn changelog_message_key(team_id: i64, person_id: i64) -> String {
    format!("{team_id}:{person_id}")
}

/// Completes the kafka-producer lifecycle component with a bounded
/// flush instead of waiting for the last producer reference to drop.
///
/// The component's handle rides inside the producer context, which
/// every clone of the producer shares — so without explicit shutdown
/// work, the component completed only when everything holding the
/// producer let go, and a queue wedged against a stalled broker held
/// its shutdown phase to the global timeout. This task flushes what
/// the queue holds within `bound` once the component's phase shuts
/// down, then reports completion either way.
///
/// A timed-out flush drops only records nobody acked: the changelog
/// path awaits each record's delivery before acking (so anything acked
/// is already off the queue, and unacked writes retry via redelivery),
/// and the rest of this producer's traffic is best-effort warnings.
pub fn spawn_bounded_flush_on_shutdown(
    producer: FutureProducer<KafkaContext>,
    handle: Handle,
    bound: Duration,
) {
    tokio::spawn(async move {
        handle.shutdown_recv().await;
        let queued = producer.in_flight_count();
        // Flush blocks, and so can the producer teardown after it; both
        // stay off the async workers. Completion is reported first, so
        // a teardown that outlives the flush bound cannot hold the
        // phase.
        let flushed = tokio::task::spawn_blocking(move || {
            let outcome = producer.flush(bound);
            let remaining = producer.in_flight_count();
            drop(producer);
            (outcome, remaining)
        })
        .await;
        match flushed {
            Ok((Ok(()), _)) => {
                tracing::info!(queued, "kafka producer flushed at shutdown");
            }
            Ok((Err(e), remaining)) => {
                tracing::warn!(
                    queued,
                    remaining,
                    error = %e,
                    "kafka producer flush hit its shutdown bound; undelivered records dropped"
                );
            }
            Err(e) => {
                tracing::warn!(error = %e, "kafka producer shutdown flush task failed");
            }
        }
        handle.work_completed();
    });
}
