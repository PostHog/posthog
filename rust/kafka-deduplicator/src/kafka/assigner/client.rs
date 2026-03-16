use anyhow::{Context, Result};
use kafka_assigner_proto::kafka_assigner::v1 as proto;
use kafka_assigner_proto::kafka_assigner::v1::kafka_assigner_client::KafkaAssignerClient;
use tonic::transport::Channel;
use tonic::Streaming;
use tracing::info;

use crate::kafka::types::Partition;

/// Wrapper around the kafka-assigner gRPC client.
///
/// Handles registration and the two notification RPCs (PartitionReady, PartitionReleased).
pub struct AssignerGrpcClient {
    client: KafkaAssignerClient<Channel>,
    consumer_name: String,
    topic: String,
}

impl AssignerGrpcClient {
    pub async fn connect(endpoint: &str, consumer_name: String, topic: String) -> Result<Self> {
        let client = KafkaAssignerClient::connect(endpoint.to_string())
            .await
            .with_context(|| format!("Failed to connect to kafka-assigner at {endpoint}"))?;

        info!(
            endpoint = endpoint,
            consumer_name = consumer_name.as_str(),
            topic = topic.as_str(),
            "Connected to kafka-assigner"
        );

        Ok(Self {
            client,
            consumer_name,
            topic,
        })
    }

    /// Register with the assigner and receive the assignment command stream.
    ///
    /// The first message on the stream is always a snapshot of current assignments.
    /// The stream stays open for the lifetime of the consumer.
    pub async fn register(&mut self) -> Result<Streaming<proto::AssignmentCommand>> {
        let response = self
            .client
            .register(proto::RegisterRequest {
                consumer_name: self.consumer_name.clone(),
                topic: self.topic.clone(),
            })
            .await
            .context("register RPC failed")?;

        info!(
            consumer_name = self.consumer_name.as_str(),
            topic = self.topic.as_str(),
            "Registered with kafka-assigner"
        );

        Ok(response.into_inner())
    }

    /// Signal that a partition has finished warming and is ready to take ownership.
    pub async fn partition_ready(&mut self, partition: &Partition) -> Result<()> {
        self.client
            .partition_ready(proto::PartitionReadyRequest {
                consumer_name: self.consumer_name.clone(),
                partition: Some(partition_to_proto(partition)),
            })
            .await
            .with_context(|| {
                format!(
                    "partition_ready RPC failed for {}:{}",
                    partition.topic(),
                    partition.partition_number()
                )
            })?;

        info!(
            topic = partition.topic(),
            partition = partition.partition_number(),
            "Signaled partition ready to assigner"
        );

        Ok(())
    }

    /// Signal that a partition has been released after a handoff.
    pub async fn partition_released(&mut self, partition: &Partition) -> Result<()> {
        self.client
            .partition_released(proto::PartitionReleasedRequest {
                consumer_name: self.consumer_name.clone(),
                partition: Some(partition_to_proto(partition)),
            })
            .await
            .with_context(|| {
                format!(
                    "partition_released RPC failed for {}:{}",
                    partition.topic(),
                    partition.partition_number()
                )
            })?;

        info!(
            topic = partition.topic(),
            partition = partition.partition_number(),
            "Signaled partition released to assigner"
        );

        Ok(())
    }

    pub fn consumer_name(&self) -> &str {
        &self.consumer_name
    }
}

fn partition_to_proto(partition: &Partition) -> proto::TopicPartition {
    proto::TopicPartition {
        topic: partition.topic().to_string(),
        partition: partition.partition_number() as u32,
    }
}
