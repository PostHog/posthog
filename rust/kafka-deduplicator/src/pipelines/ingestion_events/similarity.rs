//! Similarity calculation for RawEvent.

use anyhow::Result;
use common_types::RawEvent;

use crate::pipelines::results::{EventSimilarity, SimilarityComparable};

impl SimilarityComparable for RawEvent {
    fn calculate_similarity(original: &Self, new: &Self) -> Result<EventSimilarity> {
        let mut different_fields = Vec::new();
        let mut matching_fields = 0u32;
        let total_fields = 5u32; // uuid, event, distinct_id, token, timestamp

        // Compare UUID
        if original.uuid == new.uuid {
            matching_fields += 1;
        } else {
            different_fields.push((
                "uuid".to_string(),
                format!("{:?}", original.uuid),
                format!("{:?}", new.uuid),
            ));
        }

        // Compare event name
        if original.event == new.event {
            matching_fields += 1;
        } else {
            different_fields.push((
                "event".to_string(),
                original.event.clone(),
                new.event.clone(),
            ));
        }

        // Compare distinct_id
        if original.distinct_id == new.distinct_id {
            matching_fields += 1;
        } else {
            different_fields.push((
                "distinct_id".to_string(),
                format!("{:?}", original.distinct_id),
                format!("{:?}", new.distinct_id),
            ));
        }

        // Compare token
        if original.token == new.token {
            matching_fields += 1;
        } else {
            different_fields.push((
                "token".to_string(),
                format!("{:?}", original.token),
                format!("{:?}", new.token),
            ));
        }

        // Compare timestamp
        if original.timestamp == new.timestamp {
            matching_fields += 1;
        } else {
            different_fields.push((
                "timestamp".to_string(),
                format!("{:?}", original.timestamp),
                format!("{:?}", new.timestamp),
            ));
        }

        // Compare properties
        let (properties_similarity, different_properties) =
            EventSimilarity::compare_properties(&original.properties, &new.properties);

        Ok(EventSimilarity::from_field_comparisons(
            matching_fields,
            total_fields,
            different_fields,
            properties_similarity,
            different_properties,
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::HashMap;
    use uuid::Uuid;

    #[test]
    fn test_event_similarity_identical() {
        let uuid = Uuid::new_v4();
        let event1 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user123")),
            token: Some("token123".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("key".to_string(), json!("value"));
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(uuid),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user123")),
            token: Some("token123".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("key".to_string(), json!("value"));
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        assert_eq!(similarity.different_field_count, 0);
        assert_eq!(similarity.different_property_count, 0);
        assert_eq!(similarity.properties_similarity, 1.0);
        assert_eq!(similarity.overall_score, 1.0);
    }

    #[test]
    fn test_event_similarity_only_uuid_differs() {
        let event1 = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user123")),
            token: Some("token123".to_string()),
            properties: HashMap::new(),
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "test_event".to_string(),
            distinct_id: Some(json!("user123")),
            token: Some("token123".to_string()),
            properties: HashMap::new(),
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        assert_eq!(similarity.different_field_count, 1);
        assert!(similarity
            .different_fields
            .iter()
            .any(|(field, _, _)| field == "uuid"));
        assert_eq!(similarity.properties_similarity, 1.0);
    }

    #[test]
    fn test_event_similarity_multiple_differences() {
        let event1 = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "page_view".to_string(),
            distinct_id: Some(json!("user123")),
            token: Some("token_a".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("url".to_string(), json!("/home"));
                props.insert("referrer".to_string(), json!("google"));
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let event2 = RawEvent {
            uuid: Some(Uuid::new_v4()),
            event: "page_view".to_string(),
            distinct_id: Some(json!("user123")),
            token: Some("token_a".to_string()),
            properties: {
                let mut props = HashMap::new();
                props.insert("url".to_string(), json!("/about"));
                props.insert("referrer".to_string(), json!("google"));
                props.insert("browser".to_string(), json!("chrome"));
                props
            },
            timestamp: Some("1234567890".to_string()),
            ..Default::default()
        };

        let similarity = EventSimilarity::calculate(&event1, &event2).unwrap();

        // UUID and properties differ
        assert!(similarity.different_field_count >= 1);
        assert_eq!(similarity.different_property_count, 2); // url differs, browser is new
        assert!(similarity.properties_similarity < 1.0);
        assert!(similarity.overall_score < 1.0);
    }
}
