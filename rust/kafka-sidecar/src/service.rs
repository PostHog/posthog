use crate::error::kafka_error_to_status;
use crate::proto::kafka_producer::kafka_producer_server::KafkaProducer;
use crate::proto::kafka_producer::{ProduceRequest, ProduceResponse};
use metrics::counter;
use rdkafka::message::OwnedHeaders;
use rdkafka::producer::FutureProducer;
use tonic::{Request, Response, Status};
use tracing::{debug, error};

pub struct KafkaProducerService {
    producer: FutureProducer<common_kafka::kafka_producer::KafkaContext>,
}

impl KafkaProducerService {
    pub fn new(producer: FutureProducer<common_kafka::kafka_producer::KafkaContext>) -> Self {
        Self { producer }
    }
}

#[tonic::async_trait]
impl KafkaProducer for KafkaProducerService {
    async fn produce(
        &self,
        request: Request<ProduceRequest>,
    ) -> Result<Response<ProduceResponse>, Status> {
        let req = request.into_inner();

        let topic = &req.topic;
        counter!("kafka_producer_messages_queued_counter", "topic_name" => topic.clone())
            .increment(1);

        debug!(
            topic = %topic,
            value_size = req.value.len(),
            has_key = req.key.is_some(),
            headers_count = req.headers.len(),
            "Producing message"
        );

        // Convert headers to Kafka format
        let mut kafka_headers = OwnedHeaders::new();
        for (key, value) in &req.headers {
            kafka_headers = kafka_headers.insert(rdkafka::message::Header {
                key,
                value: Some(value.as_bytes()),
            });
        }

        // Build Kafka record
        let mut record = rdkafka::producer::FutureRecord::to(topic)
            .payload(&req.value)
            .headers(kafka_headers);

        if let Some(key) = &req.key {
            record = record.key(key);
        }

        // Add timestamp (current time in milliseconds)
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .ok();

        if let Some(ts) = timestamp {
            record = record.timestamp(ts);
        }

        // Send to Kafka
        match self.producer.send_result(record) {
            Ok(delivery_future) => {
                // Wait for acknowledgment
                match delivery_future.await {
                    Ok(Ok((partition, offset))) => {
                        counter!("kafka_producer_messages_written_counter", "topic_name" => topic.clone()).increment(1);
                        debug!(
                            topic = %topic,
                            partition = partition,
                            offset = offset,
                            "Message produced successfully"
                        );

                        Ok(Response::new(ProduceResponse { offset }))
                    }
                    Ok(Err((kafka_error, _))) => {
                        counter!("kafka_producer_messages_failed_counter", "topic_name" => topic.clone()).increment(1);
                        error!(
                            topic = %topic,
                            error = %kafka_error,
                            "Failed to produce message"
                        );

                        // Convert to appropriate gRPC status
                        let produce_error =
                            common_kafka::kafka_producer::KafkaProduceError::KafkaProduceError {
                                error: kafka_error,
                            };
                        Err(kafka_error_to_status(produce_error))
                    }
                    Err(_) => {
                        counter!("kafka_producer_messages_failed_counter", "topic_name" => topic.clone()).increment(1);
                        error!(topic = %topic, "Kafka produce canceled/timed out");
                        Err(Status::unavailable("Kafka produce timeout"))
                    }
                }
            }
            Err((kafka_error, _)) => {
                counter!("kafka_producer_messages_failed_counter", "topic_name" => topic.clone())
                    .increment(1);
                error!(
                    topic = %topic,
                    error = %kafka_error,
                    "Failed to queue message for Kafka"
                );

                let produce_error =
                    common_kafka::kafka_producer::KafkaProduceError::KafkaProduceError {
                        error: kafka_error,
                    };
                Err(kafka_error_to_status(produce_error))
            }
        }
    }
}
