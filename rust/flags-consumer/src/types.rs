use serde::de::DeserializeOwned;
use serde::Deserialize;
use uuid::Uuid;

use crate::utils::mock::Mock;

/// A Kafka message that can be classified into a [`CdcEvent`].
///
/// Implemented by each raw message type (`PersonMessage`,
/// `DistinctIdMessage`). The generic consumer loop is parameterised over
/// this trait, so adding a new topic requires only a new struct + impl —
/// no changes to the consumer machinery.
///
/// The `DeserializeOwned + Send` super-traits are required by
/// `SingleTopicConsumer::json_recv`.
pub trait KafkaMessage: DeserializeOwned + Send {
    /// Label used in Prometheus metrics (e.g. `"person"`, `"distinct_id"`).
    /// Must be a `&'static str` to avoid allocation in the hot path.
    const SOURCE: &'static str;

    /// Extract the team_id for early filtering before classification.
    fn team_id(&self) -> i32;

    /// Classify the raw message into the internal [`CdcEvent`] enum.
    /// Consumes `self` — the raw message is not needed after classification.
    fn classify(self) -> CdcEvent;
}

/// Raw message from the `clickhouse_person` Kafka topic.
///
/// The `properties` field arrives as a JSON-encoded string (stringified by
/// the Plugin Server), not as a nested object. It's kept as `String` to
/// mirror the wire format faithfully. The inner JSON is parsed only in
/// `classify()`, and only for non-deletion messages.
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

/// Internal event after deserialization and classification.
///
/// Not `Clone` by design — events are moved through the pipeline (consumer →
/// channel → processor → storage) without copying. This prevents accidental
/// deep-cloning of `serde_json::Value` property trees.
///
/// String fields that are read-only after construction use `Box<str>` instead
/// of `String` to save 8 bytes per instance (no capacity field) and to signal
/// immutability.
#[derive(Debug)]
pub enum CdcEvent {
    PersonUpdate {
        team_id: i32,
        person_uuid: Uuid,
        properties: serde_json::Value,
        version: i64,
    },
    PersonDeletion {
        team_id: i32,
        person_uuid: Uuid,
        version: i64,
    },
    DistinctIdAssignment {
        team_id: i32,
        person_uuid: Uuid,
        distinct_id: Box<str>,
        version: i64,
    },
    DistinctIdDeletion {
        team_id: i32,
        person_uuid: Uuid,
        distinct_id: Box<str>,
        version: i64,
    },
}

impl CdcEvent {
    pub fn team_id(&self) -> i32 {
        match self {
            CdcEvent::PersonUpdate { team_id, .. }
            | CdcEvent::PersonDeletion { team_id, .. }
            | CdcEvent::DistinctIdAssignment { team_id, .. }
            | CdcEvent::DistinctIdDeletion { team_id, .. } => *team_id,
        }
    }

    pub fn operation_label(&self) -> &'static str {
        match self {
            CdcEvent::PersonUpdate { .. } => "person_upsert",
            CdcEvent::PersonDeletion { .. } => "person_delete",
            CdcEvent::DistinctIdAssignment { .. } => "did_assign",
            CdcEvent::DistinctIdDeletion { .. } => "did_delete",
        }
    }
}

// ---------------------------------------------------------------------------
// Mock implementations
// ---------------------------------------------------------------------------

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
