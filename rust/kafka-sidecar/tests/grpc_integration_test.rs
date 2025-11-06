use anyhow::Result;
use kafka_sidecar::config::Config;
use kafka_sidecar::proto::kafka_producer::{
    kafka_producer_client::KafkaProducerClient, kafka_producer_server::KafkaProducerServer,
    ProduceRequest,
};
use kafka_sidecar::service::KafkaProducerService;
use rdkafka::{
    config::ClientConfig,
    consumer::{Consumer, StreamConsumer},
    message::Headers,
    Message,
};
use std::net::SocketAddr;
use std::time::Duration;
use tokio::time::timeout;
use tonic::transport::Server;
use tonic::Request;

const KAFKA_BROKERS: &str = "localhost:9092";
const TEST_TOPIC: &str = "kafka-sidecar-integration-test";

/// Helper to start the gRPC server on a random available port
async fn start_test_server() -> Result<(SocketAddr, tokio::task::JoinHandle<()>)> {
    let config = Config {
        grpc_port: 0, // Use port 0 to get a random available port
        metrics_port: 0,
        kafka_hosts: KAFKA_BROKERS.to_string(),
        kafka_producer_linger_ms: 0,
        kafka_producer_queue_mib: 256,
        kafka_message_timeout_ms: 30000,
        kafka_compression_codec: "snappy".to_string(),
        kafka_tls: false,
    };

    // Set up health registry
    let health_registry = health::HealthRegistry::new("liveness");
    let kafka_liveness = health_registry
        .register("kafka".to_string(), Duration::from_secs(30))
        .await;

    // Create Kafka producer
    let kafka_config = config.to_kafka_config();
    let producer =
        common_kafka::kafka_producer::create_kafka_producer(&kafka_config, kafka_liveness).await?;

    // Create gRPC service
    let kafka_service = KafkaProducerService::new(producer);

    // Bind to a random port
    let addr: SocketAddr = "127.0.0.1:0".parse()?;
    let listener = tokio::net::TcpListener::bind(addr).await?;
    let bound_addr = listener.local_addr()?;

    // Start server in background
    let server_handle = tokio::spawn(async move {
        Server::builder()
            .add_service(KafkaProducerServer::new(kafka_service))
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .expect("Server failed");
    });

    // Give server time to start
    tokio::time::sleep(Duration::from_millis(100)).await;

    Ok((bound_addr, server_handle))
}

/// Helper to create a Kafka consumer for verification
fn create_test_consumer(group_id: &str) -> Result<StreamConsumer> {
    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BROKERS)
        .set("group.id", group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest") // Read from beginning
        .set("session.timeout.ms", "6000")
        .set("heartbeat.interval.ms", "2000")
        .create()?;

    Ok(consumer)
}

#[tokio::test]
async fn test_grpc_produce_to_kafka() -> Result<()> {
    let test_topic = format!("{}-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-consumer-{}", uuid::Uuid::new_v4());

    // Start test server
    let (server_addr, _server_handle) = start_test_server().await?;

    // Connect to gRPC server
    let grpc_url = format!("http://{}", server_addr);
    let mut client = KafkaProducerClient::connect(grpc_url).await?;

    // Send a test message via gRPC
    let request = Request::new(ProduceRequest {
        value: b"test message value".to_vec(),
        key: Some(b"test-key".to_vec()),
        topic: test_topic.clone(),
        headers: vec![("header1".to_string(), "value1".to_string())]
            .into_iter()
            .collect(),
    });

    let response = client.produce(request).await?;
    let offset = response.into_inner().offset;

    // Verify message was produced (offset should be >= 0)
    assert!(offset >= 0, "Should receive valid offset from Kafka");

    // Create Kafka consumer after producing to ensure topic exists
    let consumer = create_test_consumer(&group_id)?;
    consumer.subscribe(&[&test_topic])?;

    // Consume and verify the message
    let message = timeout(Duration::from_secs(5), consumer.recv())
        .await?
        .map_err(|e| anyhow::anyhow!("Failed to receive message: {}", e))?;

    assert_eq!(
        message.payload(),
        Some(b"test message value".as_ref()),
        "Message payload should match"
    );
    assert_eq!(
        message.key(),
        Some(b"test-key".as_ref()),
        "Message key should match"
    );

    // Verify headers
    let headers = message.headers().expect("Should have headers");
    assert_eq!(headers.count(), 1, "Should have one header");
    let header = headers.get(0);
    assert_eq!(header.key, "header1");
    assert_eq!(header.value, Some(b"value1".as_ref()));

    Ok(())
}

#[tokio::test]
async fn test_grpc_produce_without_key() -> Result<()> {
    let test_topic = format!("{}-no-key-{}", TEST_TOPIC, uuid::Uuid::new_v4());
    let group_id = format!("test-consumer-no-key-{}", uuid::Uuid::new_v4());

    // Start test server
    let (server_addr, _server_handle) = start_test_server().await?;

    // Connect to gRPC server
    let grpc_url = format!("http://{}", server_addr);
    let mut client = KafkaProducerClient::connect(grpc_url).await?;

    // Send message without key
    let request = Request::new(ProduceRequest {
        value: b"keyless message".to_vec(),
        key: None,
        topic: test_topic.clone(),
        headers: Default::default(),
    });

    let response = client.produce(request).await?;
    let offset = response.into_inner().offset;

    assert!(offset >= 0, "Should receive valid offset");

    // Create Kafka consumer after producing to ensure topic exists
    let consumer = create_test_consumer(&group_id)?;
    consumer.subscribe(&[&test_topic])?;

    // Verify message
    let message = timeout(Duration::from_secs(5), consumer.recv())
        .await?
        .map_err(|e| anyhow::anyhow!("Failed to receive message: {}", e))?;

    assert_eq!(
        message.payload(),
        Some(b"keyless message".as_ref()),
        "Message payload should match"
    );
    assert_eq!(message.key(), None, "Message should have no key");

    Ok(())
}

#[tokio::test]
async fn test_grpc_produce_multiple_messages() -> Result<()> {
    let test_topic = format!("{}-multi-{}", TEST_TOPIC, uuid::Uuid::new_v4());

    // Start test server
    let (server_addr, _server_handle) = start_test_server().await?;

    // Connect to gRPC server
    let grpc_url = format!("http://{}", server_addr);
    let mut client = KafkaProducerClient::connect(grpc_url).await?;

    // Send multiple messages
    let message_count = 100;
    for i in 0..message_count {
        let request = Request::new(ProduceRequest {
            value: format!("message-{}", i).into_bytes(),
            key: Some(format!("key-{}", i).into_bytes()),
            topic: test_topic.clone(),
            headers: Default::default(),
        });

        let response = client.produce(request).await?;
        let offset = response.into_inner().offset;

        assert!(offset >= 0, "Should receive valid offset for message {}", i);
    }

    Ok(())
}

#[tokio::test]
async fn test_grpc_produce_concurrent_messages() -> Result<()> {
    let test_topic = format!("{}-concurrent-{}", TEST_TOPIC, uuid::Uuid::new_v4());

    // Start test server
    let (server_addr, _server_handle) = start_test_server().await?;

    // Connect to gRPC server
    let grpc_url = format!("http://{}", server_addr);

    // Send 1000 messages concurrently
    let message_count = 1000;
    let mut tasks = Vec::new();

    for i in 0..message_count {
        let grpc_url = grpc_url.clone();
        let test_topic = test_topic.clone();

        let task = tokio::spawn(async move {
            let mut client = KafkaProducerClient::connect(grpc_url)
                .await
                .expect("Failed to connect");

            let request = Request::new(ProduceRequest {
                value: format!("concurrent-message-{}", i).into_bytes(),
                key: Some(format!("key-{}", i).into_bytes()),
                topic: test_topic,
                headers: vec![("test".to_string(), "concurrent".to_string())]
                    .into_iter()
                    .collect(),
            });

            let response = client.produce(request).await.expect("Failed to produce");
            response.into_inner().offset
        });

        tasks.push(task);
    }

    // Wait for all tasks to complete
    let results = futures::future::join_all(tasks).await;

    // Verify all messages were produced successfully
    let mut success_count = 0;
    for result in results {
        match result {
            Ok(offset) => {
                assert!(offset >= 0, "Should receive valid offset");
                success_count += 1;
            }
            Err(e) => {
                panic!("Task failed: {}", e);
            }
        }
    }

    assert_eq!(
        success_count, message_count,
        "All {} messages should be produced successfully",
        message_count
    );

    Ok(())
}
