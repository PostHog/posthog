use std::time::Duration;

use common_kafka::kafka_producer::KafkaContext;
use lifecycle::Handle;
use metrics::{counter, histogram};
use prost::Message;
use rdkafka::producer::{FutureProducer, FutureRecord, Producer};
use tracing::error;

use personhog_proto::personhog::types::v1::Person;

/// Formats the Kafka message key for person state changelog messages.
/// The topic must include `compact` in its `cleanup.policy` so Kafka
/// retains the latest state per person. Deployed config is
/// `compact,delete`, where retention bounds even the latest record —
/// acceptable because nothing reads records older than the writer's
/// committed offset, which retention outruns by design.
pub fn changelog_message_key(team_id: i64, person_id: i64) -> String {
    format!("{team_id}:{person_id}")
}

/// Produce a person state changelog message to Kafka.
///
/// Encodes the `Person` proto as the message payload and uses
/// `{team_id}:{person_id}` as the key for compaction. The message is
/// produced to an explicit partition — the person's routing partition —
/// rather than relying on the producer's key partitioner. Warming rebuilds
/// one routing partition's cache by consuming the same-numbered Kafka
/// partition, so the two numbering schemes must agree; producing explicitly
/// makes that alignment structural instead of depending on the partitioner
/// config matching the router's murmur2 (librdkafka's default partitioner
/// is CRC32-based and routes keys differently). A partition-count mismatch
/// fails loudly at produce time instead of silently mis-sharding.
/// Returns the record's changelog offset on successful delivery — the
/// dirty index records it so an evicted entry can be recovered from the
/// changelog later — or an error string on failure.
///
/// The handoff protocol relies on "handler returned Ok == message durable in Kafka."
/// That requires the delivery future to be awaited before returning (done here) and
/// `acks=all` on the producer. We rely on librdkafka's default (`acks=-1`) for the
/// latter; if that default ever changes, the drain-inflight step in
/// `coordination::LeaderHandoffHandler::drain_partition_inflight` becomes unsafe.
pub async fn produce_person_changelog(
    producer: &FutureProducer<KafkaContext>,
    topic: &str,
    partition: u32,
    person: &Person,
) -> Result<i64, String> {
    let key = changelog_message_key(person.team_id, person.id);
    let payload = person.encode_to_vec();
    // Recorded before the send so a payload rejected by the broker
    // (message.max.bytes) still shows up in the distribution.
    histogram!("personhog_leader_kafka_produce_bytes").record(payload.len() as f64);

    let record = FutureRecord::to(topic)
        .partition(partition as i32)
        .key(&key)
        .payload(&payload);

    // Time-to-durable for the changelog append: every acked write waits
    // on this, so it is the broker's direct contribution to write latency.
    let start = std::time::Instant::now();
    match producer.send_result(record) {
        Ok(delivery_future) => match delivery_future.await {
            Ok(Ok((_, offset))) => {
                counter!("personhog_leader_kafka_produces_total").increment(1);
                histogram!("personhog_leader_kafka_produce_duration_ms")
                    .record(start.elapsed().as_secs_f64() * 1000.0);
                Ok(offset)
            }
            Ok(Err((kafka_err, _))) => {
                counter!("personhog_leader_kafka_produce_errors_total").increment(1);
                error!(error = %kafka_err, "kafka delivery failed");
                Err(format!("kafka delivery failed: {kafka_err}"))
            }
            Err(_cancelled) => {
                counter!("personhog_leader_kafka_produce_errors_total").increment(1);
                error!("kafka produce cancelled (timeout)");
                Err("kafka produce cancelled (timeout)".to_string())
            }
        },
        Err((kafka_err, _)) => {
            counter!("personhog_leader_kafka_produce_errors_total").increment(1);
            error!(error = %kafka_err, "kafka send_result failed");
            Err(format!("kafka enqueue failed: {kafka_err}"))
        }
    }
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
