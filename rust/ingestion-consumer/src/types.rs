pub mod proto {
    tonic::include_proto!("ingestion.v1");
}

pub use proto::ingestion_service_client::IngestionServiceClient;
pub use proto::{IngestBatchRequest, KafkaHeader, KafkaMessage};

impl KafkaMessage {
    pub fn get_header(&self, name: &str) -> Option<String> {
        self.headers
            .iter()
            .find(|h| h.key == name)
            .map(|h| String::from_utf8_lossy(&h.value).into_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_message(headers: Vec<(&str, &[u8])>) -> KafkaMessage {
        KafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset: 0,
            timestamp: None,
            key: None,
            value: None,
            headers: headers
                .into_iter()
                .map(|(k, v)| KafkaHeader {
                    key: k.to_string(),
                    value: v.to_vec(),
                })
                .collect(),
        }
    }

    #[test]
    fn test_get_header() {
        let msg = make_message(vec![
            ("token", b"phc_abc"),
            ("distinct_id", b"user-1"),
        ]);

        assert_eq!(msg.get_header("token"), Some("phc_abc".to_string()));
        assert_eq!(msg.get_header("distinct_id"), Some("user-1".to_string()));
        assert_eq!(msg.get_header("missing"), None);
    }

    #[test]
    fn test_null_key_and_value() {
        let msg = KafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset: 0,
            timestamp: None,
            key: None,
            value: None,
            headers: vec![],
        };

        assert!(msg.key.is_none());
        assert!(msg.value.is_none());
        assert!(msg.headers.is_empty());
    }
}
