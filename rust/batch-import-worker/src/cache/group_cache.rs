use anyhow::Error;
use moka::sync::Cache;
use serde_json::Value;
use std::collections::HashMap;
use std::time::Duration;

/// Represents changes to group properties
#[derive(Debug, Clone)]
pub struct GroupChanges {
    /// Properties to set (new or changed)
    pub set: HashMap<String, Value>,
    /// Properties to unset (deleted)
    pub unset: Vec<String>,
}

/// Memory-only implementation of GroupCache using moka for tracking group property changes
#[derive(Clone)]
pub struct MemoryGroupCache {
    cache: Cache<String, HashMap<String, Value>>, // Key -> properties
}

impl MemoryGroupCache {
    /// Create a new memory-only group cache
    pub fn new(max_capacity: u64, ttl: Duration) -> Self {
        let cache = Cache::builder()
            .time_to_live(ttl)
            .max_capacity(max_capacity)
            .build();

        Self { cache }
    }

    /// Create with default settings (50K entries, 2 hour TTL)
    /// Groups change less frequently than user-device combinations
    pub fn with_defaults() -> Self {
        Self::new(50_000, Duration::from_secs(2 * 60 * 60))
    }

    /// Generate cache key for group type and key combination
    fn make_key(team_id: i32, group_type: &str, group_key: &str) -> String {
        // URL encode group_type and group_key to prevent key format conflicts
        let encoded_group_type = urlencoding::encode(group_type);
        let encoded_group_key = urlencoding::encode(group_key);
        format!("group:{team_id}:{encoded_group_type}:{encoded_group_key}")
    }
}

impl std::fmt::Debug for MemoryGroupCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MemoryGroupCache")
            .field("cache", &"<moka cache>")
            .finish()
    }
}

/// Trait for group property change tracking
pub trait GroupCache: Send + Sync + std::fmt::Debug {
    /// Check if group properties have changed since last seen
    /// Returns Some(GroupChanges) if changes are needed, None if no changes
    fn get_group_changes(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        properties: &HashMap<String, Value>,
    ) -> Option<GroupChanges>;

    /// Mark group properties as seen with current properties
    fn mark_group_seen(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        properties: &HashMap<String, Value>,
    ) -> Result<(), Error>;
}

impl GroupCache for MemoryGroupCache {
    fn get_group_changes(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        properties: &HashMap<String, Value>,
    ) -> Option<GroupChanges> {
        let key = Self::make_key(team_id, group_type, group_key);

        match self.cache.get(&key) {
            Some(existing_properties) => {
                // Group exists in cache
                if properties.is_empty() {
                    // If passed properties are empty, ignore it
                    return None;
                }

                // Compute differences
                let mut set = HashMap::new();
                let mut unset = Vec::new();

                // Find new/changed properties
                for (key, value) in properties {
                    match existing_properties.get(key) {
                        Some(existing_value) => {
                            if existing_value != value {
                                set.insert(key.clone(), value.clone());
                            }
                        }
                        None => {
                            set.insert(key.clone(), value.clone());
                        }
                    }
                }

                // Find deleted properties
                for key in existing_properties.keys() {
                    if !properties.contains_key(key) {
                        unset.push(key.clone());
                    }
                }

                // Return changes if there are any
                if set.is_empty() && unset.is_empty() {
                    None
                } else {
                    Some(GroupChanges { set, unset })
                }
            }
            None => {
                // Group does not exist in cache
                if properties.is_empty() {
                    // If properties are empty, still return empty changes for first time
                    Some(GroupChanges {
                        set: HashMap::new(),
                        unset: Vec::new(),
                    })
                } else {
                    // Return all properties as new
                    Some(GroupChanges {
                        set: properties.clone(),
                        unset: Vec::new(),
                    })
                }
            }
        }
    }

    fn mark_group_seen(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        properties: &HashMap<String, Value>,
    ) -> Result<(), Error> {
        let key = Self::make_key(team_id, group_type, group_key);
        self.cache.insert(key, properties.clone());
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::thread;

    fn create_test_properties() -> HashMap<String, Value> {
        let mut props = HashMap::new();
        props.insert("company_name".to_string(), json!("Acme Corp"));
        props.insert("industry".to_string(), json!("Technology"));
        props.insert("size".to_string(), json!(250));
        props
    }

    fn create_modified_properties() -> HashMap<String, Value> {
        let mut props = HashMap::new();
        props.insert("company_name".to_string(), json!("Acme Corp"));
        props.insert("industry".to_string(), json!("Technology"));
        props.insert("size".to_string(), json!(300)); // Changed value
        props
    }

    #[test]
    fn test_group_cache_first_time_seen() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let properties = create_test_properties();

        // First time should return changes with all properties
        let result = cache.get_group_changes(1, "company", "acme-corp", &properties);
        assert!(result.is_some());
        let changes = result.unwrap();
        assert_eq!(changes.set.len(), 3); // All properties should be new
        assert_eq!(changes.unset.len(), 0); // No properties to unset
        assert!(changes.set.contains_key("company_name"));
        assert!(changes.set.contains_key("industry"));
        assert!(changes.set.contains_key("size"));
    }

    #[test]
    fn test_group_cache_no_change() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let properties = create_test_properties();

        // Mark as seen
        cache
            .mark_group_seen(1, "company", "acme-corp", &properties)
            .unwrap();

        // Same properties should not return changes
        let result = cache.get_group_changes(1, "company", "acme-corp", &properties);
        assert!(result.is_none());
    }

    #[test]
    fn test_group_cache_properties_changed() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let properties = create_test_properties();
        let modified_properties = create_modified_properties();

        // Mark original as seen
        cache
            .mark_group_seen(1, "company", "acme-corp", &properties)
            .unwrap();

        // Modified properties should return changes
        let result = cache.get_group_changes(1, "company", "acme-corp", &modified_properties);
        assert!(result.is_some());
        let changes = result.unwrap();
        assert_eq!(changes.set.len(), 1); // Only size changed
        assert_eq!(changes.unset.len(), 0); // No properties deleted
        assert_eq!(changes.set.get("size"), Some(&json!(300)));
    }

    #[test]
    fn test_group_cache_team_isolation() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let properties = create_test_properties();

        // Mark for team 1
        cache
            .mark_group_seen(1, "company", "acme-corp", &properties)
            .unwrap();

        // Should not return changes for team 1
        let result1 = cache.get_group_changes(1, "company", "acme-corp", &properties);
        assert!(result1.is_none());

        // Should return changes for team 2 (different team, first time)
        let result2 = cache.get_group_changes(2, "company", "acme-corp", &properties);
        assert!(result2.is_some());
        let changes = result2.unwrap();
        assert_eq!(changes.set.len(), 3); // All properties new for team 2
    }

    #[test]
    fn test_group_cache_different_group_types() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let properties = create_test_properties();

        // Mark company
        cache
            .mark_group_seen(1, "company", "acme-corp", &properties)
            .unwrap();

        // Same key but different type should return changes (first time)
        let result = cache.get_group_changes(1, "team", "acme-corp", &properties);
        assert!(result.is_some());
        let changes = result.unwrap();
        assert_eq!(changes.set.len(), 3); // All properties new for different type
    }

    #[test]
    fn test_group_cache_property_order_independence() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));

        // Create properties in different orders
        let mut props1 = HashMap::new();
        props1.insert("a".to_string(), json!("value1"));
        props1.insert("b".to_string(), json!("value2"));

        let mut props2 = HashMap::new();
        props2.insert("b".to_string(), json!("value2"));
        props2.insert("a".to_string(), json!("value1"));

        // Mark first version as seen
        cache
            .mark_group_seen(1, "company", "test", &props1)
            .unwrap();

        // Same properties in different order should not return changes
        let result = cache.get_group_changes(1, "company", "test", &props2);
        assert!(result.is_none());
    }

    #[test]
    fn test_group_cache_empty_properties() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let empty_props = HashMap::new();
        let non_empty_props = create_test_properties();

        // Mark empty properties as seen
        cache
            .mark_group_seen(1, "company", "test", &empty_props)
            .unwrap();

        // Empty properties should not return changes (ignored)
        let result1 = cache.get_group_changes(1, "company", "test", &empty_props);
        assert!(result1.is_none());

        // Non-empty properties should return changes
        let result2 = cache.get_group_changes(1, "company", "test", &non_empty_props);
        assert!(result2.is_some());
        let changes = result2.unwrap();
        assert_eq!(changes.set.len(), 3); // All properties new
    }

    #[test]
    fn test_group_cache_ttl_expiry() {
        let cache = MemoryGroupCache::new(100, Duration::from_millis(100));
        let properties = create_test_properties();

        // Mark as seen
        cache
            .mark_group_seen(1, "company", "acme-corp", &properties)
            .unwrap();

        // Should not return changes immediately
        let result1 = cache.get_group_changes(1, "company", "acme-corp", &properties);
        assert!(result1.is_none());

        // Wait for TTL expiry
        thread::sleep(Duration::from_millis(150));

        // Should return changes after expiry (first time again)
        let result2 = cache.get_group_changes(1, "company", "acme-corp", &properties);
        assert!(result2.is_some());
        let changes = result2.unwrap();
        assert_eq!(changes.set.len(), 3); // All properties new again
    }

    #[test]
    fn test_group_cache_special_characters() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let properties = create_test_properties();

        // Test with special characters that need URL encoding
        let test_cases = vec![
            ("company:type", "group@key"),
            ("team space", "group+plus"),
            ("公司", "组织456"),   // Unicode
            (":::", ":::"),        // Only colons
            ("type%20", "key%40"), // Already encoded characters
        ];

        for (group_type, group_key) in test_cases {
            // Should return changes first time
            let result1 = cache.get_group_changes(1, group_type, group_key, &properties);
            assert!(result1.is_some());
            let changes1 = result1.unwrap();
            assert_eq!(changes1.set.len(), 3);

            // Mark as seen
            cache
                .mark_group_seen(1, group_type, group_key, &properties)
                .unwrap();

            // Should not return changes second time
            let result2 = cache.get_group_changes(1, group_type, group_key, &properties);
            assert!(result2.is_none());
        }
    }

    #[test]
    fn test_group_cache_complex_values() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));

        let mut props1 = HashMap::new();
        props1.insert("array".to_string(), json!(["a", "b", "c"]));
        props1.insert("object".to_string(), json!({"nested": "value"}));
        props1.insert("number".to_string(), json!(123.45));
        props1.insert("boolean".to_string(), json!(true));

        let mut props2 = HashMap::new();
        props2.insert("array".to_string(), json!(["a", "b", "d"])); // Different array
        props2.insert("object".to_string(), json!({"nested": "value"}));
        props2.insert("number".to_string(), json!(123.45));
        props2.insert("boolean".to_string(), json!(true));

        // Mark first version as seen
        cache
            .mark_group_seen(1, "company", "test", &props1)
            .unwrap();

        // Different array should return changes
        let result = cache.get_group_changes(1, "company", "test", &props2);
        assert!(result.is_some());
        let changes = result.unwrap();
        assert_eq!(changes.set.len(), 1); // Only array changed
        assert!(changes.set.contains_key("array"));
    }

    #[test]
    fn test_group_cache_property_deletion() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));

        // Create properties with 3 fields
        let mut props1 = HashMap::new();
        props1.insert("a".to_string(), json!("value1"));
        props1.insert("b".to_string(), json!("value2"));
        props1.insert("c".to_string(), json!("value3"));

        // Create properties with only 2 fields (c deleted)
        let mut props2 = HashMap::new();
        props2.insert("a".to_string(), json!("value1"));
        props2.insert("b".to_string(), json!("value2"));

        // Mark first version as seen
        cache
            .mark_group_seen(1, "company", "test", &props1)
            .unwrap();

        // Should return changes with c in unset
        let result = cache.get_group_changes(1, "company", "test", &props2);
        assert!(result.is_some());
        let changes = result.unwrap();
        assert_eq!(changes.set.len(), 0); // No new/changed properties
        assert_eq!(changes.unset.len(), 1); // One property deleted
        assert!(changes.unset.contains(&"c".to_string()));
    }

    #[test]
    fn test_group_cache_property_addition_and_deletion() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));

        // Create properties with 2 fields
        let mut props1 = HashMap::new();
        props1.insert("a".to_string(), json!("value1"));
        props1.insert("b".to_string(), json!("value2"));

        // Create properties with different fields (b deleted, c added, a changed)
        let mut props2 = HashMap::new();
        props2.insert("a".to_string(), json!("value1_changed"));
        props2.insert("c".to_string(), json!("value3"));

        // Mark first version as seen
        cache
            .mark_group_seen(1, "company", "test", &props1)
            .unwrap();

        // Should return changes with both set and unset
        let result = cache.get_group_changes(1, "company", "test", &props2);
        assert!(result.is_some());
        let changes = result.unwrap();
        assert_eq!(changes.set.len(), 2); // a changed, c added
        assert_eq!(changes.unset.len(), 1); // b deleted
        assert_eq!(changes.set.get("a"), Some(&json!("value1_changed")));
        assert_eq!(changes.set.get("c"), Some(&json!("value3")));
        assert!(changes.unset.contains(&"b".to_string()));
    }
}
