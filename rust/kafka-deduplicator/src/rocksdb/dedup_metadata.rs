use anyhow::{anyhow, Result};
use serde::{Deserialize, Serialize};

use crate::event::EventData;

#[derive(Serialize, Deserialize, Debug)]
pub struct MetadataV1 {
    pub source: u8,
    pub team: u32,
    pub timestamp: u64,
}

/*
 * VersionedMetadata is a wrapper for the different versions of the metadata format.
 */
#[derive(Debug)]
pub enum VersionedMetadata {
    V1(MetadataV1),
}

impl VersionedMetadata {
    pub fn serialize_metadata(value: &Self) -> Vec<u8> {
        let mut buf = Vec::new();
        match value {
            VersionedMetadata::V1(v1) => {
                buf.push(1);
                buf.extend(bincode::serialize(v1).unwrap());
            }
        }
        buf
    }

    pub fn deserialize_metadata(bytes: &[u8]) -> Result<VersionedMetadata> {
        let (version, payload) = bytes.split_first().ok_or_else(|| anyhow!("empty value"))?;
        match version {
            1 => Ok(VersionedMetadata::V1(bincode::deserialize(payload)?)),
            _ => Err(anyhow::anyhow!("unknown version: {}", version)),
        }
    }
}

impl From<&EventData> for VersionedMetadata {
    fn from(event: &EventData) -> Self {
        VersionedMetadata::V1(MetadataV1 {
            source: event.source,
            team: event.team_id,
            timestamp: event.timestamp,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_event(source: u8, team_id: u32) -> EventData {
        EventData {
            timestamp: 1234567890,
            distinct_id: "test_user".to_string(),
            token: "test_token".to_string(),
            event_name: "test_event".to_string(),
            source,
            team_id,
        }
    }

    #[test]
    fn test_metadata_v1_serialization() {
        let metadata = MetadataV1 {
            source: 5,
            team: 12345,
            timestamp: 1234567890,
        };
        let versioned = VersionedMetadata::V1(metadata);

        let serialized = VersionedMetadata::serialize_metadata(&versioned);

        // Check that version byte is present
        assert_eq!(serialized[0], 1);
        assert!(serialized.len() > 1);
    }

    #[test]
    fn test_metadata_v1_deserialization() {
        let original_metadata = MetadataV1 {
            source: 3,
            team: 98765,
            timestamp: 1234567890,
        };
        let versioned = VersionedMetadata::V1(original_metadata);

        let serialized = VersionedMetadata::serialize_metadata(&versioned);
        let deserialized = VersionedMetadata::deserialize_metadata(&serialized).unwrap();

        match deserialized {
            VersionedMetadata::V1(metadata) => {
                assert_eq!(metadata.source, 3);
                assert_eq!(metadata.team, 98765);
            }
        }
    }

    #[test]
    fn test_metadata_roundtrip() {
        let test_cases = vec![
            (0, 0, 1234567890),
            (1, 1, 1234567890),
            (255, u32::MAX, 1234567890),
            (128, 123456, 1234567890),
        ];

        for (source, team, timestamp) in test_cases {
            let metadata = MetadataV1 {
                source,
                team,
                timestamp,
            };
            let versioned = VersionedMetadata::V1(metadata);

            let serialized = VersionedMetadata::serialize_metadata(&versioned);
            let deserialized = VersionedMetadata::deserialize_metadata(&serialized).unwrap();

            match deserialized {
                VersionedMetadata::V1(result) => {
                    assert_eq!(result.source, source);
                    assert_eq!(result.team, team);
                }
            }
        }
    }

    #[test]
    fn test_from_event_data() {
        let event = create_test_event(7, 54321);
        let metadata = VersionedMetadata::from(&event);

        match metadata {
            VersionedMetadata::V1(v1) => {
                assert_eq!(v1.source, 7);
                assert_eq!(v1.team, 54321);
            }
        }
    }

    #[test]
    fn test_deserialize_invalid_version() {
        let invalid_data = vec![99, 1, 2, 3]; // version 99 doesn't exist
        let result = VersionedMetadata::deserialize_metadata(&invalid_data);

        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("unknown version: 99"));
    }

    #[test]
    fn test_deserialize_empty_data() {
        let empty_data = vec![];
        let result = VersionedMetadata::deserialize_metadata(&empty_data);

        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("empty value"));
    }

    #[test]
    fn test_deserialize_corrupted_payload() {
        let corrupted_data = vec![1, 255, 255, 255]; // version 1 but invalid bincode
        let result = VersionedMetadata::deserialize_metadata(&corrupted_data);

        assert!(result.is_err());
    }
}
