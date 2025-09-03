use anyhow::Error;
use std::collections::HashSet;
use std::sync::{Arc, Mutex};

pub mod memory;

pub use memory::MemoryIdentifyCache;

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
