//! Generic cache system for PostHog services
//!
//! This crate provides a generic read-through cache implementation that can be used
//! across all PostHog services. It supports:
//!
//! - Generic key-value caching with Redis
//! - Configurable TTL and cache prefixes
//! - Optional negative caching with Moka
//! - Rich return types indicating cache source for observability
//! - Function-based fallback API (no trait implementations required)
//! - User-defined error types
//!
//! # Example
//!
//! ```rust,ignore
//! use common_cache::{ReadThroughCache, CacheConfig, CacheSource};
//!
//! let cache = ReadThroughCache::new(
//!     redis_reader,
//!     redis_writer,
//!     CacheConfig::with_ttl("my_data:", 300),
//!     None, // negative_cache
//! );
//!
//! let result = cache
//!     .get_or_load(&key, |key| async {
//!         load_from_source(key).await
//!     })
//!     .await?;
//!
//! match result.source {
//!     CacheSource::PositiveCache => println!("Cache hit!"),
//!     CacheSource::LoaderCacheMiss => println!("Cache miss, loaded from source"),
//!     CacheSource::NegativeCache => println!("Known to not exist"),
//!     _ => println!("Other source: {:?}", result.source),
//! }
//!
//! if let Some(value) = result.value {
//!     // Use the value
//! } else {
//!     // Item doesn't exist
//! }
//! ```

pub mod negative_cache;
pub mod read_through;
pub mod types;

pub use negative_cache::NegativeCache;
pub use read_through::ReadThroughCache;
pub use types::{CacheConfig, CacheResult, CacheSource};
