use std::sync::Arc;

use anyhow::{Context, Result};
use axum::{routing::get, Router};
use futures::future::ready;
use rdkafka::{config::ClientConfig, consumer::Consumer};
use serve_metrics::{serve, setup_metrics_routes};
use tokio::task::JoinHandle;
use tracing::{error, info};

use kafka_deduplicator::{
    config::Config,
    deduplication_processor::{DeduplicationConfig, DeduplicationProcessor},
    kafka::stateful_consumer::StatefulKafkaConsumer,
    processor_rebalance_handler::ProcessorRebalanceHandler,
    rocksdb::deduplication_store::DeduplicationStoreConfig,
};

pub async fn index() -> &'static str {
    "kafka deduplicator service"
}

fn start_server(config: &Config) -> JoinHandle<()> {
    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(|| ready("ok")));
    let router = setup_metrics_routes(router);

    let bind = config.bind_address();

    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    })
}

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt::init();

    info!("Starting Kafka Deduplicator service");

    // Load configuration using PostHog pattern
    let config = Config::init_with_defaults()
        .context("Failed to load configuration from environment")?;
    
    info!("Configuration loaded: {:?}", config);

    // Start HTTP server with metrics endpoint
    let server_handle = start_server(&config);
    info!("Started metrics server on {}", config.bind_address());

    // Create deduplication store config
    let store_config = DeduplicationStoreConfig {
        path: config.store_path_buf(),
        max_capacity: config.max_store_capacity,
    };

    // Create producer config for output topic using config values
    let mut producer_config = ClientConfig::new();
    producer_config
        .set("bootstrap.servers", &config.kafka_hosts)
        .set("message.timeout.ms", config.kafka_message_timeout_ms.to_string())
        .set("queue.buffering.max.messages", config.kafka_producer_queue_messages.to_string())
        .set("queue.buffering.max.ms", config.kafka_producer_linger_ms.to_string())
        .set("compression.type", &config.kafka_compression_codec);

    // Create deduplication processor
    let dedup_config = DeduplicationConfig {
        output_topic: config.output_topic.clone(),
        producer_config,
        store_config,
    };

    let processor = Arc::new(
        DeduplicationProcessor::new(dedup_config)
            .context("Failed to create deduplication processor")?,
    );

    // Create rebalance handler
    let rebalance_handler = Arc::new(ProcessorRebalanceHandler::new(processor.clone()));

    // Create consumer config using our consolidated config
    let consumer_config = ClientConfig::new()
        .set("bootstrap.servers", &config.kafka_hosts)
        .set("group.id", &config.kafka_consumer_group)
        .set("enable.auto.commit", config.kafka_consumer_auto_commit.to_string())
        .set("auto.offset.reset", &config.kafka_consumer_offset_reset)
        .set("session.timeout.ms", "30000")
        .set("heartbeat.interval.ms", "10000")
        .set("max.poll.interval.ms", "300000")
        .set("fetch.min.bytes", "1")
        .set("fetch.max.wait.ms", "500")
        .set("max.partition.fetch.bytes", "1048576") // 1MB
        .clone();

    // Create stateful Kafka consumer with our processor
    let kafka_consumer = StatefulKafkaConsumer::from_config(
        &consumer_config,
        rebalance_handler,
        (*processor).clone(),
        config.max_in_flight_messages,
    )
    .context("Failed to create Kafka consumer")?;

    // Subscribe to input topic
    kafka_consumer
        .inner_consumer()
        .subscribe(&[&config.kafka_consumer_topic])
        .context("Failed to subscribe to input topic")?;

    info!(
        "Starting consumption from topic '{}', publishing to '{:?}'",
        config.kafka_consumer_topic, config.output_topic
    );

    // Setup shutdown signal handling
    let shutdown_signal = async {
        tokio::signal::ctrl_c()
            .await
            .expect("Failed to listen for ctrl+c signal");

        info!("Received shutdown signal");
    };

    // Start consumption with graceful shutdown
    tokio::select! {
        result = kafka_consumer.start_consumption() => {
            match result {
                Ok(_) => info!("Consumer stopped normally"),
                Err(e) => error!("Consumer stopped with error: {}", e),
            }
        }
        _ = shutdown_signal => {
            info!("Shutting down gracefully...");

            // Log final statistics
            let stats = processor.get_store_stats().await;
            info!("Final store statistics: {} active stores", stats.len());
            for ((topic, partition), (memory, processed, duplicates)) in stats {
                info!(
                    "Store {}:{} - Memory: {} bytes, Processed: {}, Duplicates: {}",
                    topic, partition, memory, processed, duplicates
                );
            }
        }
    }

    // Clean up metrics server
    server_handle.abort();

    info!("Kafka Deduplicator service stopped");
    Ok(())
}