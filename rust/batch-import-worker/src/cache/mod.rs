/// Statistics about the cache for monitoring purposes
#[derive(Debug, Clone)]
pub struct CacheStats {
    pub total_entries: u64,
    pub cache_hits: u64,
    pub cache_misses: u64,
}

pub mod redis;

pub use redis::IdentifyCache;
