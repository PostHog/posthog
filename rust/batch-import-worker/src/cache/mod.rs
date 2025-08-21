use std::fmt::Debug;

use anyhow::Error;
use async_trait::async_trait;

/// Cache for tracking Amplitude user_id -> device_id mappings to determine
/// when to inject $identify events (first time only per user-device pair)
#[async_trait]
pub trait AmplitudeIdentifyCache: Debug + Send + Sync {
    /// Check if we've already seen this user_id + device_id combination
    async fn has_seen_user_device(&self, team_id: i32, user_id: &str, device_id: &str) -> Result<bool, Error>;

    /// Mark that we've seen this user_id + device_id combination
    async fn mark_seen_user_device(&self, team_id: i32, user_id: &str, device_id: &str) -> Result<(), Error>;

    /// Get cache statistics for monitoring
    async fn stats(&self) -> Result<CacheStats, Error>;
}

/// Statistics about the cache for monitoring purposes
#[derive(Debug, Clone)]
pub struct CacheStats {
    pub total_entries: u64,
    pub cache_hits: u64,
    pub cache_misses: u64,
}

/// Key for identifying a unique user-device pair within a team
#[derive(Debug, Clone, Hash, PartialEq, Eq)]
pub struct UserDeviceKey {
    pub team_id: i32,
    pub user_id: String,
    pub device_id: String,
}

impl UserDeviceKey {
    pub fn new(team_id: i32, user_id: String, device_id: String) -> Self {
        Self {
            team_id,
            user_id,
            device_id,
        }
    }
}

pub mod memory;
pub mod redis;

pub use memory::MemoryAmplitudeIdentifyCache;
pub use redis::RedisAmplitudeIdentifyCache;
