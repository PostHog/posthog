use common_kafka::kafka_producer::KafkaProduceError;
use tonic::{Code, Status};

/// Convert Kafka producer errors to gRPC status codes
pub fn kafka_error_to_status(error: KafkaProduceError) -> Status {
    match error {
        // Serialization errors are client errors (invalid input)
        KafkaProduceError::SerializationError { error } => {
            Status::new(Code::InvalidArgument, format!("Invalid message format: {}", error))
        }
        // Kafka produce errors need more nuanced handling
        KafkaProduceError::KafkaProduceError { error } => {
            if let Some(code) = error.rdkafka_error_code() {
                use rdkafka::error::RDKafkaErrorCode;
                match code {
                    // Message too large - resource exhausted
                    RDKafkaErrorCode::MessageSizeTooLarge => {
                        Status::new(Code::ResourceExhausted, "Message size exceeds limit")
                    }
                    // Retriable errors - unavailable
                    RDKafkaErrorCode::QueueFull
                    | RDKafkaErrorCode::RequestTimedOut
                    | RDKafkaErrorCode::BrokerNotAvailable
                    | RDKafkaErrorCode::NotEnoughReplicas
                    | RDKafkaErrorCode::NotEnoughReplicasAfterAppend => {
                        Status::new(Code::Unavailable, format!("Kafka temporarily unavailable: {}", error))
                    }
                    // Other errors are internal
                    _ => Status::new(Code::Internal, format!("Kafka error: {}", error)),
                }
            } else {
                Status::new(Code::Internal, format!("Kafka error: {}", error))
            }
        }
        // Timeout/cancellation - unavailable
        KafkaProduceError::KafkaProduceCanceled => {
            Status::new(Code::Unavailable, "Kafka produce timeout")
        }
    }
}
