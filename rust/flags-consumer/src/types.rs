use serde::Deserialize;
use uuid::Uuid;

use crate::utils::mock::Mock;

/// Raw message from the `clickhouse_person` Kafka topic.
///
/// The `properties` field arrives as a JSON-encoded string (stringified by the
/// Plugin Server), not as a nested object. We deserialize it as a raw `String`
/// and parse it into `serde_json::Value` during classification.
#[derive(Debug, Clone, Deserialize)]
pub struct PersonMessage {
    pub id: Uuid,
    pub team_id: i32,
    pub properties: String,
    pub version: i64,
    #[serde(default)]
    pub is_deleted: i32,
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

/// Internal event after deserialization and classification.
///
/// String fields that are read-only after construction use `Box<str>` instead
/// of `String` to save 8 bytes per instance (no capacity field) and to signal
/// immutability.
#[derive(Debug, Clone)]
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

/// Classify a raw person message into a `CdcEvent`.
///
/// Parses the stringified `properties` JSON. Falls back to `{}` on parse
/// failure so a single malformed properties blob doesn't block the pipeline.
pub fn classify_person_message(msg: PersonMessage) -> CdcEvent {
    if msg.is_deleted != 0 {
        CdcEvent::PersonDeletion {
            team_id: msg.team_id,
            person_uuid: msg.id,
            version: msg.version,
        }
    } else {
        let properties = serde_json::from_str(&msg.properties).unwrap_or_default();
        CdcEvent::PersonUpdate {
            team_id: msg.team_id,
            person_uuid: msg.id,
            properties,
            version: msg.version,
        }
    }
}

/// Classify a raw distinct-ID message into a `CdcEvent`.
pub fn classify_distinct_id_message(msg: DistinctIdMessage) -> CdcEvent {
    let distinct_id = msg.distinct_id.into_boxed_str();
    if msg.is_deleted != 0 {
        CdcEvent::DistinctIdDeletion {
            team_id: msg.team_id,
            person_uuid: msg.person_id,
            distinct_id,
            version: msg.version,
        }
    } else {
        CdcEvent::DistinctIdAssignment {
            team_id: msg.team_id,
            person_uuid: msg.person_id,
            distinct_id,
            version: msg.version,
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
        let event = classify_person_message(msg);
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
        let event = classify_person_message(msg);
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
        let event = classify_person_message(msg);
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
        let event = classify_distinct_id_message(msg);
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
        let event = classify_distinct_id_message(msg);
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
