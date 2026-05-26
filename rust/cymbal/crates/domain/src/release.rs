use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct ReleaseRecord {
    pub id: Uuid,
    pub team_id: i32,
    pub hash_id: String,
    pub created_at: DateTime<Utc>,
    pub version: String,
    pub project: String,
    pub metadata: Option<Value>,
}

// The info, as written to clickhouse at the exception level.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReleaseInfo {
    version: String,
    project: String,
    timestamp: DateTime<Utc>,
    #[serde(skip_serializing_if = "Option::is_none")]
    metadata: Option<Value>,
}

impl ReleaseRecord {
    pub fn collect_to_map<'a, I>(iter: I) -> HashMap<String, ReleaseInfo>
    where
        I: Iterator<Item = &'a Self>,
    {
        iter.fold(HashMap::new(), |mut map, record| {
            if !map.contains_key(&record.hash_id) {
                map.insert(
                    record.hash_id.clone(),
                    ReleaseInfo {
                        project: record.project.clone(),
                        version: record.version.clone(),
                        timestamp: record.created_at,
                        metadata: record.metadata.clone(),
                    },
                );
            }
            map
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn release_record(hash_id: &str, version: &str) -> ReleaseRecord {
        ReleaseRecord {
            id: Uuid::nil(),
            team_id: 1,
            hash_id: hash_id.to_string(),
            created_at: DateTime::parse_from_rfc3339("2025-01-02T03:04:05Z")
                .unwrap()
                .with_timezone(&Utc),
            version: version.to_string(),
            project: "web".to_string(),
            metadata: Some(serde_json::json!({ "commit": "abc123" })),
        }
    }

    #[test]
    fn collect_to_map_keeps_first_release_for_each_hash() {
        let first = release_record("same-hash", "1.0.0");
        let duplicate = release_record("same-hash", "2.0.0");
        let other = release_record("other-hash", "3.0.0");

        let map = ReleaseRecord::collect_to_map([&first, &duplicate, &other].into_iter());

        assert_eq!(map.len(), 2);
        assert_eq!(
            serde_json::to_value(&map["same-hash"]).unwrap()["version"],
            "1.0.0"
        );
        assert_eq!(
            serde_json::to_value(&map["other-hash"]).unwrap()["version"],
            "3.0.0"
        );
    }

    #[test]
    fn release_info_serializes_clickhouse_shape() {
        let release = release_record("release-hash", "1.0.0");
        let map = ReleaseRecord::collect_to_map([&release].into_iter());

        let value = serde_json::to_value(&map["release-hash"]).unwrap();

        assert_eq!(value["version"], "1.0.0");
        assert_eq!(value["project"], "web");
        assert_eq!(
            value["timestamp"],
            serde_json::to_value(release.created_at).unwrap()
        );
        assert_eq!(value["metadata"], serde_json::json!({ "commit": "abc123" }));
    }
}
