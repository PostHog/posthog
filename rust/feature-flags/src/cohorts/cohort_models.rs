use crate::properties::property_models::PropertyFilter;
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct Cohort {
    pub id: i32,
    pub name: Option<String>,
    pub description: Option<String>,
    pub team_id: i32,
    pub deleted: bool,
    pub filters: Option<serde_json::Value>,
    pub query: Option<serde_json::Value>,
    pub version: Option<i32>,
    pub pending_version: Option<i32>,
    pub count: Option<i32>,
    pub is_calculating: bool,
    pub is_static: bool,
    pub errors_calculating: i32,
    pub groups: serde_json::Value,
    pub created_by_id: Option<i32>,
}

impl Cohort {
    /// Estimates the memory size of this cohort in bytes.
    ///
    /// This approximation accounts for the variable-size JSON fields (`filters`, `query`, `groups`)
    /// which can be arbitrarily large depending on cohort complexity. The estimate is used by the
    /// cache weigher to enforce memory-based eviction rather than count-based eviction.
    ///
    /// **Accuracy note**: This measures serialized JSON size, not actual heap allocations.
    /// `serde_json::Value` stores JSON in a tree structure with per-node overhead not counted here.
    /// Deeply nested structures may use 2-3x more memory than estimated. This is acceptable because:
    /// 1. The estimate is consistent and proportional to actual usage
    /// 2. It correctly identifies large cohorts as heavier than small ones
    /// 3. Operators can tune the cache limit based on observed memory usage
    pub fn estimated_size_bytes(&self) -> usize {
        // Base struct size (fixed-size fields like i32, bool, Option overhead)
        let base_size = std::mem::size_of::<Self>();

        // Variable-size string fields
        let name_size = self.name.as_ref().map_or(0, |s| s.len());
        let desc_size = self.description.as_ref().map_or(0, |s| s.len());

        // JSON fields - estimate size by traversing the structure without allocation
        let filters_size = self.filters.as_ref().map_or(0, estimate_json_size);
        let query_size = self.query.as_ref().map_or(0, estimate_json_size);
        let groups_size = estimate_json_size(&self.groups);

        base_size + name_size + desc_size + filters_size + query_size + groups_size
    }
}

/// Estimates the serialized size of a JSON value with minimal allocation.
///
/// This walks the JSON tree and estimates the byte length of the serialized form.
/// The estimate is close to `value.to_string().len()` but avoids the large allocation
/// of serializing the entire structure. Numbers still allocate a small temporary string
/// for simplicity, as they're typically only a few bytes.
fn estimate_json_size(value: &serde_json::Value) -> usize {
    match value {
        serde_json::Value::Null => 4, // "null"
        serde_json::Value::Bool(b) => {
            if *b {
                4
            } else {
                5
            }
        } // "true" or "false"
        serde_json::Value::Number(n) => {
            // For accuracy, just convert to string - numbers are small and this is fast
            n.to_string().len()
        }
        serde_json::Value::String(s) => s.len() + 2, // quotes + content (ignoring escapes)
        serde_json::Value::Array(arr) => {
            if arr.is_empty() {
                2 // "[]"
            } else {
                // "[" + elements + commas + "]"
                2 + arr.iter().map(estimate_json_size).sum::<usize>() + arr.len().saturating_sub(1)
            }
        }
        serde_json::Value::Object(map) => {
            if map.is_empty() {
                2 // "{}"
            } else {
                // "{" + entries + commas + "}"
                // Each entry serialized as "key":value
                2 + map
                    .iter()
                    .map(|(k, v)| {
                        k.len() + 3 + estimate_json_size(v) // key + 2 quotes + colon + value
                    })
                    .sum::<usize>()
                    + map.len().saturating_sub(1)
            }
        }
    }
}

pub type CohortId = i32;

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "UPPERCASE")]
pub enum CohortPropertyType {
    AND,
    OR,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CohortProperty {
    pub properties: InnerCohortProperty,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct InnerCohortProperty {
    #[serde(rename = "type")]
    pub prop_type: CohortPropertyType,
    pub values: Vec<CohortValues>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CohortValues {
    #[serde(rename = "type")]
    pub prop_type: String,
    pub values: Vec<PropertyFilter>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_cohort(
        filters: Option<serde_json::Value>,
        query: Option<serde_json::Value>,
        groups: serde_json::Value,
    ) -> Cohort {
        Cohort {
            id: 1,
            name: Some("Test Cohort".to_string()),
            description: Some("A test cohort".to_string()),
            team_id: 1,
            deleted: false,
            filters,
            query,
            version: Some(1),
            pending_version: None,
            count: Some(100),
            is_calculating: false,
            is_static: false,
            errors_calculating: 0,
            groups,
            created_by_id: Some(1),
        }
    }

    #[test]
    fn test_estimated_size_bytes_minimal_cohort() {
        let cohort = create_test_cohort(None, None, serde_json::json!({}));

        let size = cohort.estimated_size_bytes();

        // Should include at least the base struct size
        assert!(
            size >= std::mem::size_of::<Cohort>(),
            "Size should be at least the base struct size"
        );
    }

    #[test]
    fn test_estimated_size_bytes_with_large_filters() {
        let small_cohort = create_test_cohort(
            Some(serde_json::json!({"type": "AND", "values": []})),
            None,
            serde_json::json!({}),
        );

        let large_filters = serde_json::json!({
            "properties": {
                "type": "OR",
                "values": [
                    {"type": "OR", "values": [
                        {"key": "property_1", "type": "person", "value": ["value1", "value2", "value3", "value4", "value5"], "negation": false, "operator": "exact"},
                        {"key": "property_2", "type": "person", "value": ["value6", "value7", "value8", "value9", "value10"], "negation": false, "operator": "exact"}
                    ]},
                    {"type": "AND", "values": [
                        {"key": "property_3", "type": "person", "value": ["value11", "value12"], "negation": true, "operator": "is_not"}
                    ]}
                ]
            }
        });
        let large_cohort = create_test_cohort(Some(large_filters), None, serde_json::json!({}));

        let small_size = small_cohort.estimated_size_bytes();
        let large_size = large_cohort.estimated_size_bytes();

        assert!(
            large_size > small_size,
            "Large filter cohort ({large_size} bytes) should be larger than small filter cohort ({small_size} bytes)"
        );
    }

    #[test]
    fn test_estimated_size_bytes_includes_all_json_fields() {
        let base_cohort = create_test_cohort(None, None, serde_json::json!({}));

        let with_filters = create_test_cohort(
            Some(serde_json::json!({"key": "value", "nested": {"deep": "data"}})),
            None,
            serde_json::json!({}),
        );

        let with_query = create_test_cohort(
            None,
            Some(serde_json::json!({"query": "SELECT * FROM events WHERE large_query_here"})),
            serde_json::json!({}),
        );

        let with_groups = create_test_cohort(
            None,
            None,
            serde_json::json!({"group1": "value1", "group2": "value2", "group3": "value3"}),
        );

        let base_size = base_cohort.estimated_size_bytes();
        let filters_size = with_filters.estimated_size_bytes();
        let query_size = with_query.estimated_size_bytes();
        let groups_size = with_groups.estimated_size_bytes();

        // Each field should contribute to the size
        assert!(
            filters_size > base_size,
            "Adding filters should increase size"
        );
        assert!(query_size > base_size, "Adding query should increase size");
        assert!(
            groups_size > base_size,
            "Adding groups should increase size"
        );
    }

    #[test]
    fn test_estimate_json_size_accuracy() {
        // Test that estimate_json_size produces reasonable approximations
        // compared to actual serialization
        let test_cases = vec![
            serde_json::json!(null),
            serde_json::json!(true),
            serde_json::json!(false),
            serde_json::json!(42),
            serde_json::json!(-123),
            serde_json::json!(1.5),
            serde_json::json!("hello"),
            serde_json::json!([1, 2, 3]),
            serde_json::json!({"key": "value"}),
            serde_json::json!({
                "nested": {
                    "array": [1, 2, {"deep": true}],
                    "string": "test"
                }
            }),
        ];

        for value in test_cases {
            let estimated = estimate_json_size(&value);
            let actual = value.to_string().len();

            // Allow up to 20% deviation - the estimate doesn't need to be exact,
            // just proportional and reasonable
            let deviation = (estimated as f64 - actual as f64).abs() / actual as f64;
            assert!(
                deviation < 0.20,
                "Estimate {estimated} deviates too much from actual {actual} for {value}"
            );
        }
    }

    #[test]
    fn test_estimate_json_size_minimal_allocation() {
        // This test verifies the function works correctly. The "minimal allocation" property
        // is structural (only numbers allocate via to_string()) rather than something we can directly test.
        let large_value = serde_json::json!({
            "properties": {
                "type": "OR",
                "values": (0..100).map(|i| {
                    serde_json::json!({
                        "key": format!("property_{}", i),
                        "value": format!("value_{}", i)
                    })
                }).collect::<Vec<_>>()
            }
        });

        let size = estimate_json_size(&large_value);
        assert!(
            size > 1000,
            "Large JSON should have significant estimated size"
        );
    }
}
