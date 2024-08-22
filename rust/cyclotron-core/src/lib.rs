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

#[doc(hidden)]
pub mod test_support {
    pub use crate::manager::Shard;
}
