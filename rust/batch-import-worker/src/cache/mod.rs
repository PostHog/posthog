use anyhow::Error;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};

pub mod group_cache;
pub mod identify_cache;

pub use group_cache::{GroupCache, MemoryGroupCache};
pub use identify_cache::MemoryIdentifyCache;

/// Trait for caching user_id -> device_id mappings to determine when to inject $identify events
pub trait IdentifyCache: Send + Sync + std::fmt::Debug {
    fn has_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<bool, Error>;
    fn mark_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<(), Error>;
}

/// Mock implementation of IdentifyCache for testing
#[derive(Debug, Clone)]
pub struct MockIdentifyCache {
    seen_combinations: Arc<Mutex<HashSet<String>>>,
}

impl Default for MockIdentifyCache {
    fn default() -> Self {
        Self::new()
    }
}

impl MockIdentifyCache {
    pub fn new() -> Self {
        Self {
            seen_combinations: Arc::new(Mutex::new(HashSet::new())),
        }
    }

    fn make_key(team_id: i32, user_id: &str, device_id: &str) -> String {
        format!("{team_id}:{user_id}:{device_id}")
    }
}

impl IdentifyCache for MockIdentifyCache {
    fn has_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<bool, Error> {
        let key = Self::make_key(team_id, user_id, device_id);
        let seen = self.seen_combinations.lock().unwrap();
        Ok(seen.contains(&key))
    }

    fn mark_seen_user_device(
        &self,
        team_id: i32,
        user_id: &str,
        device_id: &str,
    ) -> Result<(), Error> {
        let key = Self::make_key(team_id, user_id, device_id);
        let mut seen = self.seen_combinations.lock().unwrap();
        seen.insert(key);
        Ok(())
    }
}

/// Mock implementation of GroupCache for testing
#[derive(Debug, Clone)]
pub struct MockGroupCache {
    seen_groups: Arc<Mutex<HashMap<String, u64>>>, // Key -> properties hash
}

impl Default for MockGroupCache {
    fn default() -> Self {
        Self::new()
    }
}

impl MockGroupCache {
    pub fn new() -> Self {
        Self {
            seen_groups: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    fn make_key(team_id: i32, group_type: &str, group_key: &str) -> String {
        format!("{team_id}:{group_type}:{group_key}")
    }

    fn hash_properties(properties: &HashMap<String, Value>) -> u64 {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};

        let mut hasher = DefaultHasher::new();

        // Sort keys to ensure consistent hashing
        let mut sorted_properties: Vec<_> = properties.iter().collect();
        sorted_properties.sort_by_key(|(k, _)| *k);

        for (key, value) in sorted_properties {
            key.hash(&mut hasher);
            value.to_string().hash(&mut hasher);
        }

        hasher.finish()
    }
}

impl GroupCache for MockGroupCache {
    fn has_group_changed(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        properties: &HashMap<String, Value>,
    ) -> Result<bool, Error> {
        let key = Self::make_key(team_id, group_type, group_key);
        let new_hash = Self::hash_properties(properties);

        let seen = self.seen_groups.lock().unwrap();
        match seen.get(&key) {
            Some(existing_hash) => Ok(*existing_hash != new_hash),
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

        let mut seen = self.seen_groups.lock().unwrap();
        seen.insert(key, hash);
        Ok(())
    }
}
