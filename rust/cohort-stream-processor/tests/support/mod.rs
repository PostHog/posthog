#![allow(dead_code)]

use std::time::{Duration, Instant};

use cohort_stream_processor::partitions::COHORT_PARTITION_COUNT;
use futures::{Stream, StreamExt};
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::{KafkaError, KafkaResult, RDKafkaErrorCode};
use rdkafka::message::Message;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use uuid::Uuid;

pub fn bootstrap_servers() -> String {
    std::env::var("KAFKA_HOSTS").unwrap_or_else(|_| "localhost:9092".to_string())
}

pub async fn recv<S, T>(stream: &mut S) -> KafkaResult<T>
where
    S: Stream<Item = KafkaResult<T>> + Unpin,
{
    loop {
        match stream.next().await.expect("Kafka consumer stream ended") {
            // With a single broker, librdkafka reports `AllBrokersDown` after a dropped connection.
            // It can also report `AllBrokersDown` alone, because it suppresses a repeated transport error.
            Err(
                error @ KafkaError::MessageConsumption(
                    RDKafkaErrorCode::BrokerTransportFailure | RDKafkaErrorCode::AllBrokersDown,
                ),
            ) => {
                eprintln!("Kafka test reader is waiting for transport recovery: {error}");
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            result => return result,
        }
    }
}

/// Read up to `expected` messages (all partitions from the beginning). Assigned explicitly — no group
/// join, no commit — so committed offsets the test asserts on are never perturbed.
pub async fn consume_all(topic: &str, expected: usize, deadline: Duration) -> Vec<(i32, Vec<u8>)> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", format!("scan-verifier-{}", Uuid::new_v4()))
        .set("enable.auto.commit", "false")
        .create()
        .expect("create scan verifier");
    let mut tpl = TopicPartitionList::new();
    for partition in 0..COHORT_PARTITION_COUNT as i32 {
        tpl.add_partition_offset(topic, partition, Offset::Beginning)
            .expect("add partition to scan TPL");
    }
    consumer.assign(&tpl).expect("assign scan verifier");

    let mut messages = Vec::new();
    let start = Instant::now();
    while messages.len() < expected && start.elapsed() < deadline {
        match tokio::time::timeout(Duration::from_secs(2), recv(&mut consumer.stream())).await {
            Ok(Ok(message)) => {
                if let Some(payload) = message.payload() {
                    messages.push((message.partition(), payload.to_vec()));
                }
            }
            Ok(Err(err)) => panic!("scan verifier recv error: {err}"),
            Err(_) => {}
        }
    }
    messages
}
