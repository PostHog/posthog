// jemalloc is only the global allocator off msvc — see
// `common_alloc::DefaultAllocator`.
#[cfg(not(target_env = "msvc"))]
pub mod alloc_stats;
pub mod aperture;
pub mod config;
pub mod consumer;
pub mod debug_recorder;
pub mod discovery;
pub mod dispatcher;
pub mod kafka_config;
pub mod kafka_stats;
pub mod order_sentinel;
pub mod routing;
pub mod stash;
pub mod transport;
pub mod types;
pub mod worker_registry;
