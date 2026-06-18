use serde::de::DeserializeOwned;
use serde::Deserialize;
use uuid::Uuid;

use crate::types::CdcEvent;
use crate::utils::mock::Mock;

/// A Kafka message that can be deserialized, filtered, and classified into a [`CdcEvent`].
///
/// Adding a new topic requires a new struct + impl of this trait.
pub trait KafkaMessage: DeserializeOwned + Send {
    /// Prometheus metrics label for this topic.
    const SOURCE: &'static str;

    fn team_id(&self) -> i32;

    /// Classify into a [`CdcEvent`], consuming the raw message.
    fn classify(self) -> CdcEvent;
}

/// Raw message from the `clickhouse_person` Kafka topic.
///
/// `properties` is a JSON-encoded string (the Plugin Server stringifies it).
/// Parsed into `serde_json::Value` in `classify()`, only for non-deletion messages.
#[derive(Debug, Clone, Deserialize)]
pub struct PersonMessage {
    pub id: Uuid,
    pub team_id: i32,
    pub properties: String,
    pub version: i64,
    #[serde(default)]
    pub is_deleted: i32,
}

impl KafkaMessage for PersonMessage {
    const SOURCE: &'static str = "person";

    fn team_id(&self) -> i32 {
        self.team_id
    }

    fn classify(self) -> CdcEvent {
        if self.is_deleted != 0 {
            CdcEvent::PersonDeletion {
                team_id: self.team_id,
                person_uuid: self.id,
                version: self.version,
            }
        } else {
            let properties = serde_json::from_str(&self.properties).unwrap_or_default();
            CdcEvent::PersonUpdate {
                team_id: self.team_id,
                person_uuid: self.id,
                properties,
                version: self.version,
            }
        }
    }
}

/// Raw message from the `clickhouse_person_distinct_id` Kafka topic.
#[derive(Debug, Clone, Deserialize)]
pub struct DistinctIdMessage {
    pub person_id: Uuid,
    pub team_id: i32,
    pub distinct_id: String,
    pub version: i64,
    #[serde(default)]
    pub is_deleted: i32,
}

impl KafkaMessage for DistinctIdMessage {
    const SOURCE: &'static str = "distinct_id";

    fn team_id(&self) -> i32 {
        self.team_id
    }

    fn classify(self) -> CdcEvent {
        let distinct_id = self.distinct_id.into_boxed_str();
        if self.is_deleted != 0 {
            CdcEvent::DistinctIdDeletion {
                team_id: self.team_id,
                person_uuid: self.person_id,
                distinct_id,
                version: self.version,
            }
        } else {
            CdcEvent::DistinctIdAssignment {
                team_id: self.team_id,
                person_uuid: self.person_id,
                distinct_id,
                version: self.version,
            }
        }
    }
}

// Mock implementations
impl Mock for PersonMessage {
    fn mock() -> Self {
        Self {
            id: Uuid::nil(),
            team_id: 1,
            properties: r#"{"email":"test@example.com"}"#.to_string(),
            version: 1,
            is_deleted: 0,
        }
    }
}

impl Mock for DistinctIdMessage {
    fn mock() -> Self {
        Self {
            person_id: Uuid::nil(),
            team_id: 1,
            distinct_id: "test_distinct_id".to_string(),
            version: 1,
            is_deleted: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mock;

    #[test]
    fn test_person_message_deserialize() {
        let json = r#"{
            "id": "00000000-0000-0000-0000-000000000001",
            "team_id": 42,
            "properties": "{\"email\":\"user@test.com\"}",
            "version": 5,
            "is_deleted": 0
        }"#;
        let msg: PersonMessage = serde_json::from_str(json).unwrap();
        assert_eq!(msg.team_id, 42);
        assert_eq!(msg.version, 5);
        assert_eq!(msg.is_deleted, 0);
    }

    #[test]
    fn test_person_message_deserialize_missing_is_deleted() {
        let json = r#"{
            "id": "00000000-0000-0000-0000-000000000001",
            "team_id": 42,
            "properties": "{}",
            "version": 5
        }"#;
        let msg: PersonMessage = serde_json::from_str(json).unwrap();
        assert_eq!(msg.is_deleted, 0);
    }

    #[test]
    fn test_distinct_id_message_deserialize() {
        let json = r#"{
            "person_id": "00000000-0000-0000-0000-000000000002",
            "team_id": 42,
            "distinct_id": "user-abc",
            "version": 3,
            "is_deleted": 0
        }"#;
        let msg: DistinctIdMessage = serde_json::from_str(json).unwrap();
        assert_eq!(msg.distinct_id, "user-abc");
        assert_eq!(msg.version, 3);
    }

    #[test]
    fn test_classify_person_update() {
        let msg = mock!(PersonMessage, team_id: 42, version: 5);
        let event = msg.classify();
        match event {
            CdcEvent::PersonUpdate {
                team_id, version, ..
            } => {
                assert_eq!(team_id, 42);
                assert_eq!(version, 5);
            }
            _ => panic!("expected PersonUpdate"),
        }
    }

    #[test]
    fn test_classify_person_deletion() {
        let msg = mock!(PersonMessage, is_deleted: 1, version: 105);
        let event = msg.classify();
        match event {
            CdcEvent::PersonDeletion { version, .. } => {
                assert_eq!(version, 105);
            }
            _ => panic!("expected PersonDeletion"),
        }
    }

    #[test]
    fn test_classify_person_malformed_properties() {
        let msg = mock!(PersonMessage, properties: "not valid json".to_string());
        let event = msg.classify();
        match event {
            CdcEvent::PersonUpdate { properties, .. } => {
                assert_eq!(properties, serde_json::Value::Null);
            }
            _ => panic!("expected PersonUpdate"),
        }
    }

    #[test]
    fn test_classify_distinct_id_assignment() {
        let msg = mock!(DistinctIdMessage, distinct_id: "user-xyz".to_string(), version: 7);
        let event = msg.classify();
        match event {
            CdcEvent::DistinctIdAssignment {
                distinct_id,
                version,
                ..
            } => {
                assert_eq!(&*distinct_id, "user-xyz");
                assert_eq!(version, 7);
            }
            _ => panic!("expected DistinctIdAssignment"),
        }
    }

    #[test]
    fn test_classify_distinct_id_deletion() {
        let msg = mock!(DistinctIdMessage, is_deleted: 1, version: 3);
        let event = msg.classify();
        match event {
            CdcEvent::DistinctIdDeletion { version, .. } => {
                assert_eq!(version, 3);
            }
            _ => panic!("expected DistinctIdDeletion"),
        }
    }

    #[test]
    fn test_mock_person_message_defaults() {
        let msg = mock!(PersonMessage);
        assert_eq!(msg.team_id, 1);
        assert_eq!(msg.version, 1);
        assert_eq!(msg.is_deleted, 0);
        assert_eq!(msg.id, Uuid::nil());
    }

    #[test]
    fn test_mock_person_message_overrides() {
        let msg = mock!(PersonMessage, team_id: 99, version: 42);
        assert_eq!(msg.team_id, 99);
        assert_eq!(msg.version, 42);
        assert_eq!(msg.is_deleted, 0);
    }

    #[test]
    fn test_mock_distinct_id_message_defaults() {
        let msg = mock!(DistinctIdMessage);
        assert_eq!(msg.team_id, 1);
        assert_eq!(msg.distinct_id, "test_distinct_id");
    }
}
