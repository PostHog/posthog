use common_kafka::kafka_producer::KafkaContext;
use metrics::counter;
use prost::Message;
use rdkafka::producer::{FutureProducer, FutureRecord};
use tracing::error;

use personhog_proto::personhog::types::v1::Person;

/// Formats the Kafka message key for person state changelog messages.
/// The topic should be configured with `cleanup.policy=compact` so that
/// Kafka retains only the latest state per person.
pub fn changelog_message_key(team_id: i64, person_id: i64) -> String {
    format!("{team_id}:{person_id}")
}

/// Produce a person state changelog message to Kafka.
///
/// Encodes the `Person` proto as the message payload and uses
/// `{team_id}:{person_id}` as the key for compaction and partitioning.
/// Returns `Ok(())` on successful delivery, or an error string on failure.
pub async fn produce_person_changelog(
    producer: &FutureProducer<KafkaContext>,
    topic: &str,
    person: &Person,
) -> Result<(), String> {
    let key = changelog_message_key(person.team_id, person.id);
    let payload = person.encode_to_vec();

    let record = FutureRecord::to(topic).key(&key).payload(&payload);

    match producer.send_result(record) {
        Ok(delivery_future) => match delivery_future.await {
            Ok(Ok(_)) => {
                counter!("personhog_leader_kafka_produces_total").increment(1);
                Ok(())
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
