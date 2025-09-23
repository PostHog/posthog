use anyhow::Error;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};

pub mod group_cache;
pub mod identify_cache;

pub use group_cache::{GroupCache, GroupChanges, MemoryGroupCache};
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
    seen_groups: Arc<Mutex<HashMap<String, HashMap<String, Value>>>>, // Key -> properties
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
}

impl GroupCache for MockGroupCache {
    fn get_group_changes(
        &self,
        team_id: i32,
        group_type: &str,
        group_key: &str,
        properties: &HashMap<String, Value>,
    ) -> Option<GroupChanges> {
        let key = Self::make_key(team_id, group_type, group_key);

        let seen = self.seen_groups.lock().unwrap();
        match seen.get(&key) {
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

        let mut seen = self.seen_groups.lock().unwrap();
        seen.insert(key, properties.clone());
        Ok(())
    }
}
