//! The wire shapes of the two topics, decoded as strictly as their
//! consumers read them: the ClickHouse Kafka table drops an unreadable row
//! without an error, so a payload it would lose is an error here.

use serde_json::Value;
use uuid::Uuid;

/// Mirrors `MERGE_EVENT_SCHEMA_VERSION` in the cohort stream processor.
pub const MERGE_EVENT_SCHEMA_VERSION: u64 = 1;

const DISTINCT_ID_ROW: &str = "distinct id row";
const MERGE_EVENT: &str = "merge event";

#[derive(Debug, thiserror::Error)]
pub enum DecodeError {
    #[error("{what} is not valid JSON: {source}")]
    Json {
        what: &'static str,
        #[source]
        source: serde_json::Error,
    },
    #[error("{what} without {field}")]
    MissingField {
        what: &'static str,
        field: &'static str,
    },
    #[error("distinct id row with is_deleted {value}, expected 0 or 1")]
    IsDeleted { value: Value },
    #[error("merge event with schema_version {value}, expected {MERGE_EVENT_SCHEMA_VERSION}")]
    SchemaVersion { value: Value },
    #[error("merge event with merged_at_ms {value}, expected a positive integer")]
    MergedAt { value: Value },
    #[error("person row with {field} {value}, expected 0 or 1")]
    PersonFlag { field: &'static str, value: Value },
    #[error("person row whose properties are not a JSON object")]
    Properties,
    #[error("merge event {old} -> {new} produced under key {actual:?}, expected {expected:?}")]
    Key {
        old: Uuid,
        new: Uuid,
        expected: String,
        actual: Option<String>,
    },
}

/// `person_id` on the wire is the person's uuid; `is_deleted` is the Kafka
/// table's `Int8`, 0 or 1.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DistinctIdRow {
    pub team_id: i64,
    pub distinct_id: String,
    pub person_uuid: Uuid,
    pub version: i64,
    pub is_deleted: bool,
}

impl DistinctIdRow {
    pub fn decode(payload: &[u8]) -> Result<Self, DecodeError> {
        let value: Value = serde_json::from_slice(payload).map_err(|source| DecodeError::Json {
            what: DISTINCT_ID_ROW,
            source,
        })?;
        let missing = |field: &'static str| DecodeError::MissingField {
            what: DISTINCT_ID_ROW,
            field,
        };
        let team_id = value["team_id"]
            .as_i64()
            .ok_or_else(|| missing("an integer team_id"))?;
        let distinct_id = value["distinct_id"]
            .as_str()
            .ok_or_else(|| missing("a distinct_id"))?
            .to_string();
        let person_uuid =
            parse_uuid(&value["person_id"]).ok_or_else(|| missing("a person uuid"))?;
        let version = value["version"]
            .as_i64()
            .ok_or_else(|| missing("an integer version"))?;
        let is_deleted = match value["is_deleted"].as_u64() {
            Some(0) => false,
            Some(1) => true,
            _ => {
                return Err(DecodeError::IsDeleted {
                    value: value["is_deleted"].clone(),
                })
            }
        };
        Ok(Self {
            team_id,
            distinct_id,
            person_uuid,
            version,
            is_deleted,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MergeEvent {
    pub team_id: i64,
    pub old_person_uuid: Uuid,
    pub new_person_uuid: Uuid,
    pub merged_at_ms: i64,
}

impl MergeEvent {
    /// Checks the record key too: the cohort stream processor keeps the old
    /// person's state on the worker the key selects, so a wrong key lands
    /// the merge on the wrong worker without a decode error.
    pub fn decode(key: Option<&[u8]>, payload: &[u8]) -> Result<Self, DecodeError> {
        let value: Value = serde_json::from_slice(payload).map_err(|source| DecodeError::Json {
            what: MERGE_EVENT,
            source,
        })?;
        let missing = |field: &'static str| DecodeError::MissingField {
            what: MERGE_EVENT,
            field,
        };
        // The cohort stream processor reads team_id as i32.
        let team_id = value["team_id"]
            .as_i64()
            .filter(|team_id| i32::try_from(*team_id).is_ok())
            .ok_or_else(|| missing("a team_id in i32 range"))?;
        let old_person_uuid =
            parse_uuid(&value["old_person_uuid"]).ok_or_else(|| missing("an old_person_uuid"))?;
        let new_person_uuid =
            parse_uuid(&value["new_person_uuid"]).ok_or_else(|| missing("a new_person_uuid"))?;
        if value["schema_version"].as_u64() != Some(MERGE_EVENT_SCHEMA_VERSION) {
            return Err(DecodeError::SchemaVersion {
                value: value["schema_version"].clone(),
            });
        }
        let merged_at_ms = match value["merged_at_ms"].as_i64() {
            Some(ms) if ms > 0 => ms,
            _ => {
                return Err(DecodeError::MergedAt {
                    value: value["merged_at_ms"].clone(),
                })
            }
        };
        let event = Self {
            team_id,
            old_person_uuid,
            new_person_uuid,
            merged_at_ms,
        };
        let expected = event.key();
        if key != Some(expected.as_bytes()) {
            return Err(DecodeError::Key {
                old: old_person_uuid,
                new: new_person_uuid,
                expected,
                actual: key.map(|key| String::from_utf8_lossy(key).into_owned()),
            });
        }
        Ok(event)
    }

    /// Node's key, `"{team_id}:{old_person_uuid}"`.
    pub fn key(&self) -> String {
        format!("{}:{}", self.team_id, self.old_person_uuid)
    }
}

pub(super) fn parse_uuid(value: &Value) -> Option<Uuid> {
    value.as_str().and_then(|s| Uuid::parse_str(s).ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    const UUID_1: &str = "00000000-0000-0000-0000-000000000001";
    const UUID_2: &str = "00000000-0000-0000-0000-000000000002";

    #[test]
    fn distinct_id_row_decode_decision_table() {
        let row = DistinctIdRow::decode(
            format!(r#"{{"person_id":"{UUID_1}","team_id":5,"distinct_id":"d","version":2,"is_deleted":1}}"#)
                .as_bytes(),
        )
        .expect("decodes");
        assert_eq!(
            row,
            DistinctIdRow {
                team_id: 5,
                distinct_id: "d".to_string(),
                person_uuid: Uuid::parse_str(UUID_1).unwrap(),
                version: 2,
                is_deleted: true,
            }
        );

        let error = |payload: &str| DistinctIdRow::decode(payload.as_bytes()).unwrap_err();
        assert!(matches!(error("not json"), DecodeError::Json { .. }));
        assert!(matches!(
            error(
                r#"{"person_id":"00000000-0000-0000-0000-000000000001","team_id":"5","distinct_id":"d","version":1,"is_deleted":0}"#
            ),
            DecodeError::MissingField {
                field: "an integer team_id",
                ..
            }
        ));
        assert!(matches!(
            error(r#"{"team_id":5,"distinct_id":"d","version":1,"is_deleted":0}"#),
            DecodeError::MissingField {
                field: "a person uuid",
                ..
            }
        ));
        assert!(matches!(
            error(
                r#"{"person_id":"not-a-uuid","team_id":5,"distinct_id":"d","version":1,"is_deleted":0}"#
            ),
            DecodeError::MissingField {
                field: "a person uuid",
                ..
            }
        ));
        assert!(matches!(
            error(
                r#"{"person_id":"00000000-0000-0000-0000-000000000001","team_id":5,"distinct_id":"d","version":1,"is_deleted":2}"#
            ),
            DecodeError::IsDeleted { .. }
        ));
        assert!(matches!(
            error(
                r#"{"person_id":"00000000-0000-0000-0000-000000000001","team_id":5,"distinct_id":"d","version":1,"is_deleted":true}"#
            ),
            DecodeError::IsDeleted { .. }
        ));
    }

    #[test]
    fn merge_event_decode_decision_table() {
        let payload = |schema_version: u64, merged_at_ms: i64| {
            format!(
                r#"{{"team_id":5,"old_person_uuid":"{UUID_1}","new_person_uuid":"{UUID_2}","merged_at_ms":{merged_at_ms},"schema_version":{schema_version}}}"#
            )
        };
        let key = format!("5:{UUID_1}");
        let event =
            MergeEvent::decode(Some(key.as_bytes()), payload(1, 10).as_bytes()).expect("decodes");
        assert_eq!(
            event,
            MergeEvent {
                team_id: 5,
                old_person_uuid: Uuid::parse_str(UUID_1).unwrap(),
                new_person_uuid: Uuid::parse_str(UUID_2).unwrap(),
                merged_at_ms: 10,
            }
        );
        assert_eq!(event.key(), key);

        let error = |key: Option<&[u8]>, payload: String| {
            MergeEvent::decode(key, payload.as_bytes()).unwrap_err()
        };
        assert!(matches!(
            error(Some(key.as_bytes()), payload(2, 10)),
            DecodeError::SchemaVersion { .. }
        ));
        assert!(matches!(
            error(Some(key.as_bytes()), payload(1, 0)),
            DecodeError::MergedAt { .. }
        ));
        assert!(matches!(
            error(None, payload(1, 10)),
            DecodeError::Key { actual: None, .. }
        ));
        assert!(matches!(
            error(Some(b"5:wrong".as_slice()), payload(1, 10)),
            DecodeError::Key {
                actual: Some(_),
                ..
            }
        ));
        assert!(matches!(
            error(
                Some(key.as_bytes()),
                format!(
                    r#"{{"team_id":5,"old_person_uuid":"{UUID_1}","merged_at_ms":10,"schema_version":1}}"#
                )
            ),
            DecodeError::MissingField {
                field: "a new_person_uuid",
                ..
            }
        ));
        assert!(matches!(
            error(
                Some(format!("4294967301:{UUID_1}").as_bytes()),
                format!(
                    r#"{{"team_id":4294967301,"old_person_uuid":"{UUID_1}","new_person_uuid":"{UUID_2}","merged_at_ms":10,"schema_version":1}}"#
                )
            ),
            DecodeError::MissingField {
                field: "a team_id in i32 range",
                ..
            }
        ));
    }
}
