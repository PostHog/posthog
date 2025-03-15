mod hash;
mod metrics;
mod salt_cache;

pub use hash::{do_hash, HashError};
pub use salt_cache::{SaltCache, SaltCacheError, is_calendar_date_valid};

#[cfg(feature = "examples")]
pub mod examples;
