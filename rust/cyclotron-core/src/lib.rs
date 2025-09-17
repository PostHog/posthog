mod ops;

// We do this pattern (privately use a module, then re-export parts of it) so we can refactor/rename or generally futz around with the internals without breaking the public API

// Types
mod types;
pub use types::AggregatedDelete;
pub use types::Bytes;
pub use types::Job;
pub use types::JobInit;
pub use types::JobState;
pub use types::JobUpdate;

// Errors
mod error;
// Errors about some job operation - locks being lost, invalid states, flush deadlines exceeded etc
pub use error::JobError;
// Errors about the queue itself - full shards, timeouts, postgres/network errors
pub use error::QueueError;

// Manager
mod manager;
pub use manager::QueueManager;

// Worker
mod worker;
// A handle to a released job update, that can be awaited to block waiting for the flush to complete
pub use worker::FlushHandle;
pub use worker::Worker;

// Janitor
mod janitor;
pub use janitor::Janitor;

// Config
mod config;
pub use config::ManagerConfig;
pub use config::PoolConfig;
pub use config::WorkerConfig;

// The shard id is a fixed value that is set by the janitor when it starts up.
// Workers may use this value when reporting metrics. The `Worker` struct provides
// a method for fetching this value, that caches it appropriately such that it's safe
// to call frequently, while still being up-to-date (even though it should "never" change)
pub const SHARD_ID_KEY: &str = "shard_id";

// This isn't pub because, ideally, nothing using the core will ever need to know it.
const DEAD_LETTER_QUEUE: &str = "_cyclotron_dead_letter";

#[doc(hidden)]
pub mod test_support {
    pub use crate::manager::Shard;
}
