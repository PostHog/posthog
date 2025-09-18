use anyhow::Error;
use moka::sync::Cache;
use serde_json::Value;
use std::collections::hash_map::DefaultHasher;
use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::time::Duration;

/// Memory-only implementation of GroupCache using moka for tracking group property changes
#[derive(Clone)]
pub struct MemoryGroupCache {
    cache: Cache<String, u64>, // Key -> properties hash
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

    /// Create hash of group properties for change detection
    fn hash_properties(properties: &HashMap<String, Value>) -> u64 {
        let mut hasher = DefaultHasher::new();

        // Sort keys to ensure consistent hashing regardless of insertion order
        let mut sorted_properties: Vec<_> = properties.iter().collect();
        sorted_properties.sort_by_key(|(k, _)| *k);

        for (key, value) in sorted_properties {
            key.hash(&mut hasher);
            // Hash the JSON representation to handle complex values consistently
            value.to_string().hash(&mut hasher);
        }

        hasher.finish()
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
    /// Returns true if this is the first time seeing the group or if properties changed
    fn has_group_changed(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        properties: &HashMap<String, Value>,
    ) -> Result<bool, Error>;

    /// Mark group properties as seen with current hash
    fn mark_group_seen(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        properties: &HashMap<String, Value>,
    ) -> Result<(), Error>;
}

impl GroupCache for MemoryGroupCache {
    fn has_group_changed(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        properties: &HashMap<String, Value>,
    ) -> Result<bool, Error> {
        let key = Self::make_key(team_id, group_type, group_key);
        let new_hash = Self::hash_properties(properties);

        match self.cache.get(&key) {
            Some(existing_hash) => Ok(existing_hash != new_hash),
            None => Ok(true), // First time seeing this group
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
        let hash = Self::hash_properties(properties);
        self.cache.insert(key, hash);
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

        // First time should be considered changed
        let result = cache
            .has_group_changed(1, "company", "acme-corp", &properties)
            .unwrap();
        assert!(result);
    }

    #[test]
    fn test_group_cache_no_change() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let properties = create_test_properties();

        // Mark as seen
        cache
            .mark_group_seen(1, "company", "acme-corp", &properties)
            .unwrap();

        // Same properties should not be considered changed
        let result = cache
            .has_group_changed(1, "company", "acme-corp", &properties)
            .unwrap();
        assert!(!result);
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

        // Modified properties should be considered changed
        let result = cache
            .has_group_changed(1, "company", "acme-corp", &modified_properties)
            .unwrap();
        assert!(result);
    }

    #[test]
    fn test_group_cache_team_isolation() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let properties = create_test_properties();

        // Mark for team 1
        cache
            .mark_group_seen(1, "company", "acme-corp", &properties)
            .unwrap();

        // Should not be changed for team 1
        let result1 = cache
            .has_group_changed(1, "company", "acme-corp", &properties)
            .unwrap();
        assert!(!result1);

        // Should be changed for team 2 (different team, first time)
        let result2 = cache
            .has_group_changed(2, "company", "acme-corp", &properties)
            .unwrap();
        assert!(result2);
    }

    #[test]
    fn test_group_cache_different_group_types() {
        let cache = MemoryGroupCache::new(100, Duration::from_secs(10));
        let properties = create_test_properties();

        // Mark company
        cache
            .mark_group_seen(1, "company", "acme-corp", &properties)
            .unwrap();

        // Same key but different type should be considered changed (first time)
        let result = cache
            .has_group_changed(1, "team", "acme-corp", &properties)
            .unwrap();
        assert!(result);
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

        // Same properties in different order should not be considered changed
        let result = cache
            .has_group_changed(1, "company", "test", &props2)
            .unwrap();
        assert!(!result);
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

        // Empty properties should not be considered changed
        let result1 = cache
            .has_group_changed(1, "company", "test", &empty_props)
            .unwrap();
        assert!(!result1);

        // Non-empty properties should be considered changed
        let result2 = cache
            .has_group_changed(1, "company", "test", &non_empty_props)
            .unwrap();
        assert!(result2);
    }

    #[test]
    fn test_group_cache_ttl_expiry() {
        let cache = MemoryGroupCache::new(100, Duration::from_millis(100));
        let properties = create_test_properties();

        // Mark as seen
        cache
            .mark_group_seen(1, "company", "acme-corp", &properties)
            .unwrap();

        // Should not be changed immediately
        let result1 = cache
            .has_group_changed(1, "company", "acme-corp", &properties)
            .unwrap();
        assert!(!result1);

        // Wait for TTL expiry
        thread::sleep(Duration::from_millis(150));

        // Should be considered changed after expiry (first time again)
        let result2 = cache
            .has_group_changed(1, "company", "acme-corp", &properties)
            .unwrap();
        assert!(result2);
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
            // Should be changed first time
            let result1 = cache
                .has_group_changed(1, group_type, group_key, &properties)
                .unwrap();
            assert!(result1);

            // Mark as seen
            cache
                .mark_group_seen(1, group_type, group_key, &properties)
                .unwrap();

            // Should not be changed second time
            let result2 = cache
                .has_group_changed(1, group_type, group_key, &properties)
                .unwrap();
            assert!(!result2);
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

        // Different array should be considered changed
        let result = cache
            .has_group_changed(1, "company", "test", &props2)
            .unwrap();
        assert!(result);
    }
}
