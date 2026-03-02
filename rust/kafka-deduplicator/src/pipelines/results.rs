//! Shared result types for deduplication pipelines.
//!
//! This module contains types used to represent deduplication outcomes
//! and event similarity comparisons across different pipelines.

use std::collections::{HashMap, HashSet};

/// Field name for deduplication comparisons (dynamic string to support different event types)
pub type DedupFieldName = String;

/// An event enriched with its pre-computed deduplication key.
///
/// This struct pairs an event reference with its dedup key bytes to avoid
/// recomputing the key during batch processing.
pub struct EnrichedEvent<'a, E> {
    pub event: &'a E,
    pub dedup_key_bytes: Vec<u8>,
}

/// Type alias for property differences
pub type PropertyDifference = (String, Option<(String, String)>);

/// Trait for events that can calculate similarity with another event of the same type.
pub trait SimilarityComparable: Sized {
    fn calculate_similarity(original: &Self, new: &Self) -> anyhow::Result<EventSimilarity>;
}

/// Represents the similarity between two events
#[derive(Debug)]
pub struct EventSimilarity {
    /// Total similarity score (0.0 = completely different, 1.0 = identical)
    pub overall_score: f64,
    /// Number of top-level fields that differ (excluding properties)
    pub different_field_count: u32,
    /// List of field names that differ with their values (original -> new)
    pub different_fields: Vec<(DedupFieldName, String, String)>, // (field_name, original_value, new_value)
    /// Properties similarity score (0.0 = completely different, 1.0 = identical)
    pub properties_similarity: f64,
    /// Number of properties that differ
    pub different_property_count: u32,
    /// List of properties that differ with values for $ properties, just key names for others
    /// Format: (property_name, Option<(original_value, new_value)>)
    pub different_properties: Vec<PropertyDifference>,
}

impl std::fmt::Display for EventSimilarity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:.2}", self.overall_score)
    }
}

impl EventSimilarity {
    /// Calculate similarity between two events using the SimilarityComparable trait
    pub fn calculate<E: SimilarityComparable>(original: &E, new: &E) -> anyhow::Result<Self> {
        E::calculate_similarity(original, new)
    }

    /// Helper to build similarity result from field comparisons
    pub fn from_field_comparisons(
        matching_fields: u32,
        total_fields: u32,
        different_fields: Vec<(DedupFieldName, String, String)>,
        properties_similarity: f64,
        different_properties: Vec<PropertyDifference>,
    ) -> Self {
        let different_field_count = different_fields.len() as u32;
        let different_property_count = different_properties.len() as u32;

        // Calculate overall similarity score
        // Weight: 70% field similarity, 30% properties similarity
        let field_similarity = if total_fields > 0 {
            matching_fields as f64 / total_fields as f64
        } else {
            1.0
        };

        let overall_score = field_similarity * 0.7 + properties_similarity * 0.3;

        EventSimilarity {
            overall_score,
            different_field_count,
            different_fields,
            properties_similarity,
            different_property_count,
            different_properties,
        }
    }

    pub fn compare_properties(
        original: &HashMap<String, serde_json::Value>,
        new: &HashMap<String, serde_json::Value>,
    ) -> (f64, Vec<PropertyDifference>) {
        let mut different_properties = Vec::new();

        // Get all unique keys from both maps
        let all_keys: HashSet<&String> = original.keys().chain(new.keys()).collect();

        if all_keys.is_empty() {
            return (1.0, different_properties);
        }

        let mut matching = 0;
        for key in &all_keys {
            let original_val = original.get(*key);
            let new_val = new.get(*key);

            match (original_val, new_val) {
                (Some(v1), Some(v2)) if v1 == v2 => matching += 1,
                (original_opt, new_opt) => {
                    // For $ properties (PostHog system properties), include values
                    // For other properties, just record the key for privacy
                    let values = if key.starts_with('$') {
                        let orig_str = original_opt
                            .map(|v| v.to_string())
                            .unwrap_or_else(|| "<not set>".to_string());
                        let new_str = new_opt
                            .map(|v| v.to_string())
                            .unwrap_or_else(|| "<not set>".to_string());
                        Some((orig_str, new_str))
                    } else {
                        None
                    };

                    different_properties.push(((*key).to_string(), values));
                }
            }
        }

        let similarity = matching as f64 / all_keys.len() as f64;
        (similarity, different_properties)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_compare_properties_identical() {
        let mut props1 = HashMap::new();
        props1.insert("key".to_string(), json!("value"));
        props1.insert("$browser".to_string(), json!("Chrome"));

        let props2 = props1.clone();

        let (similarity, differences) = EventSimilarity::compare_properties(&props1, &props2);
        assert_eq!(similarity, 1.0);
        assert!(differences.is_empty());
    }

    #[test]
    fn test_compare_properties_different() {
        let mut props1 = HashMap::new();
        props1.insert("key".to_string(), json!("value1"));
        props1.insert("$browser".to_string(), json!("Chrome"));

        let mut props2 = HashMap::new();
        props2.insert("key".to_string(), json!("value2"));
        props2.insert("$browser".to_string(), json!("Firefox"));
        props2.insert("extra".to_string(), json!("data"));

        let (similarity, differences) = EventSimilarity::compare_properties(&props1, &props2);

        assert!(similarity < 1.0);
        assert_eq!(differences.len(), 3); // key, $browser, extra

        // $browser should have values, others should not
        let browser_diff = differences.iter().find(|(k, _)| k == "$browser");
        assert!(browser_diff.is_some());
        assert!(browser_diff.unwrap().1.is_some());

        let key_diff = differences.iter().find(|(k, _)| k == "key");
        assert!(key_diff.is_some());
        assert!(key_diff.unwrap().1.is_none()); // Non-$ property, no values
    }

    #[test]
    fn test_compare_properties_empty() {
        let props1: HashMap<String, serde_json::Value> = HashMap::new();
        let props2: HashMap<String, serde_json::Value> = HashMap::new();

        let (similarity, differences) = EventSimilarity::compare_properties(&props1, &props2);
        assert_eq!(similarity, 1.0);
        assert!(differences.is_empty());
    }

    #[test]
    fn test_from_field_comparisons() {
        let different_fields = vec![("uuid".to_string(), "a".to_string(), "b".to_string())];
        let different_properties = vec![("key".to_string(), None)];

        let similarity = EventSimilarity::from_field_comparisons(
            4, // matching_fields
            5, // total_fields
            different_fields,
            0.5, // properties_similarity
            different_properties,
        );

        assert_eq!(similarity.different_field_count, 1);
        assert_eq!(similarity.different_property_count, 1);
        // 4/5 * 0.7 + 0.5 * 0.3 = 0.56 + 0.15 = 0.71
        assert!((similarity.overall_score - 0.71).abs() < 0.001);
    }
}
