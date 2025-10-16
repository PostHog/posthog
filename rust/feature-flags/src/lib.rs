pub mod api;
pub mod billing_limiters;
pub mod cache;
pub mod cohorts;
pub mod config;
pub mod database;
pub mod database_pools;
pub mod db_monitor;
pub mod flags;
pub mod handler;
pub mod metrics;
pub mod properties;
pub mod router;
pub mod server;
pub mod site_apps;
pub mod team;

// Test modules don't need to be compiled with main binary
// #[cfg(test)]
// TODO: To use in integration tests, we need to compile with binary
// or make it a separate feature using cfg(feature = "integration-tests")
// and then use this feature only in tests.
// For now, ok to just include in binary
pub mod utils;
