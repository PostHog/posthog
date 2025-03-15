mod constants;
mod hash;
mod manager;
mod metrics;
mod salt_cache;

pub use constants::*;
pub use hash::{do_hash, HashError};
pub use manager::{
    CookielessConfig, CookielessManager, CookielessManagerError, HashParams,
};
pub use salt_cache::{is_calendar_date_valid, SaltCache, SaltCacheError};

#[cfg(feature = "examples")]
pub mod examples;
