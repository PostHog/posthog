mod ops;

// We do this pattern (privately use a module, then re-export parts of it) so we can refactor/rename or generally futz around with the internals without breaking the public API

// Types
mod types;
pub use types::BulkInsertResult;
pub use types::Job;
pub use types::JobInit;
pub use types::JobState;
pub use types::JobUpdate;

// Errors
mod error;
pub use error::QueueError;

// Manager
mod manager;
pub use manager::QueueManager;

// Worker
mod worker;
pub use worker::Worker;

// Janitor operations are exposed directly for now (and only the janitor impl uses them)
pub use ops::janitor::delete_completed_jobs;
pub use ops::janitor::delete_failed_jobs;
pub use ops::janitor::delete_poison_pills;
pub use ops::janitor::reset_stalled_jobs;

// We also expose some handly meta operations
pub use ops::meta::count_total_waiting_jobs;

// Config
mod config;
pub use config::ManagerConfig;
pub use config::PoolConfig;

// Some data is shared between workers and janitors on a given shard, using
// the metadata table. These keys are reserved for that purpose

// The shard id is a fixed value that is set by the janitor when it starts up.
// Workers may use this value when reporting metrics. The `Worker` struct provides
// a method for fetching this value, that caches it appropriately such that it's safe
// to call frequently, while still being up-to-date (even though it should "never" change)
pub const SHARD_ID_KEY: &str = "shard_id";

#[doc(hidden)]
pub mod test_support {
    pub use crate::manager::Shard;
}
