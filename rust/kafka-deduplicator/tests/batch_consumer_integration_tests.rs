use std::sync::Arc;
use std::time::Duration;

use kafka_deduplicator::kafka::{
    batch_consumer::*, batch_message::*, test_utils::TestRebalanceHandler,
};

use common_types::CapturedEvent;

use anyhow::Result;
use rdkafka::{
    config::ClientConfig,
    producer::{FutureProducer, FutureRecord},
    util::Timeout,
};
use time::OffsetDateTime;
use tokio::sync::mpsc::{unbounded_channel, UnboundedReceiver};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

const KAFKA_BROKERS: &str = "localhost:9092";
const TEST_TOPIC_BASE: &str = "kdedup-batch-consumer-integration-test";

/// Helper to create a BatchKafkaConsumer for integration smoke tests
#[allow(clippy::type_complexity)]
fn create_batch_kafka_consumer(
    topic: &str,
    group_id: &str,
    batch_size: usize,
    batch_timeout: Duration,
) -> Result<(
    BatchConsumer<CapturedEvent>,
    UnboundedReceiver<Batch<CapturedEvent>>,
    CancellationToken,
)> {
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000");

    // Create shutdown channel - return sender so test can control shutdown
    let shutdown_token = CancellationToken::new();

    let (chan_tx, chan_rx) = unbounded_channel();

    let consumer = BatchConsumer::<CapturedEvent>::new(
        &config,
        Arc::new(TestRebalanceHandler::default()),
        chan_tx,
        shutdown_token.clone(),
        topic,
        batch_size,
        batch_timeout,
        Duration::from_secs(1),
    )?;

    Ok((consumer, chan_rx, shutdown_token))
}

/// Helper to send test messages
async fn send_test_messages(
    topic: &str,
    messages: Vec<(String, String)>, // (key, value) pairs
) -> Result<()> {
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("message.timeout.ms", "5000")
        .create()?;

    for (key, value) in messages {
        let record = FutureRecord::to(topic).key(&key).payload(&value);

        producer
            .send(record, Timeout::After(Duration::from_secs(5)))
            .await
            .map_err(|(e, _)| anyhow::anyhow!("Failed to send message: {}", e))?;
    }

    // Give kafka some time to process the messages
    tokio::time::sleep(Duration::from_millis(100)).await;
    Ok(())
}

fn create_captured_event() -> CapturedEvent {
    let now = std::time::SystemTime::now();
    let now_offset_datetime = OffsetDateTime::from(now);
    let now_rfc3339 = chrono::DateTime::<chrono::Utc>::from(now).to_rfc3339();
    let distinct_id = Uuid::now_v7().to_string();
    let token = Uuid::now_v7().to_string();
    let event_name = "$pageview";
    let event_uuid = Uuid::now_v7();
    let data = format!(
        r#"{{"uuid": "{event_uuid}", "event": "{event_name}", "distinct_id": "{distinct_id}", "token": "{token}", "properties": {{}}}}"#,
    );

    // Create a mock KafkaMessage for testing
    CapturedEvent {
        uuid: event_uuid,
        distinct_id: distinct_id.to_string(),
        ip: "127.0.0.1".to_string(),
        now: now_rfc3339.clone(),
        token: token.to_string(),
        // serialized RawEvent
        data: data.to_string(),
        sent_at: Some(now_offset_datetime),
        is_cookieless_mode: false,
    }
}

// convenience to generate and serialize some simple CapturedEvent message payloads
fn generate_test_messages(count: usize) -> Vec<(String, String)> {
    (0..count)
        .map(|i| {
            let payload = create_captured_event();
            let serialized = serde_json::to_string(&payload).unwrap();
            (format!("key_{i}"), serialized)
        })
        .collect()
}

#[tokio::test]
async fn test_simple_batch_kafka_consumer() -> Result<()> {
    let test_topic = format!("{}-{}", TEST_TOPIC_BASE, uuid::Uuid::now_v7());
    let group_id = format!("test-group-{}", uuid::Uuid::now_v7());
    let batch_size = 3;
    let batch_timeout = Duration::from_millis(100);

    // Send test messages first
    let expected_msg_count = 9;
    let test_messages = generate_test_messages(expected_msg_count);

    send_test_messages(&test_topic, test_messages).await?;

    let (consumer, mut batch_rx, shutdown_token) =
        create_batch_kafka_consumer(&test_topic, &group_id, batch_size, batch_timeout)?;

    // Start consumption in background task
    let consumer_handle = tokio::spawn(async move { consumer.start_consumption().await });

    // this will cause the consumer.recv() loop below to exit
    //when the consumer's start_consumption loop breaks and
    // closes the batch submission channel
    let _shutdown_handle = tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(200)).await;
        shutdown_token.cancel();
    });

    tokio::time::sleep(Duration::from_millis(1)).await;

    let mut msgs_recv = 0;
    while let Some(batch_result) = batch_rx.recv().await {
        let (msgs, errs) = batch_result.unpack();
        if !errs.is_empty() {
            panic!("Errors in batch: {errs:?}");
        }
        assert!(
            msgs.len() <= 3,
            "Batch size should be at most 3, got: {}",
            msgs.len()
        );
        msgs_recv += msgs.len();
    }

    assert_eq!(
        msgs_recv, expected_msg_count,
        "Should have received all messages, got: {msgs_recv}",
    );

    // Wait for graceful shutdown
    let _ = consumer_handle.await;

    Ok(())
}
