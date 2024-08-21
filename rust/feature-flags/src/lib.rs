pub mod api;
pub mod config;
pub mod database;
pub mod flag_definitions;
pub mod flag_matching;
pub mod geo_ip;
pub mod property_matching;
pub mod redis;
pub mod router;
pub mod server;
pub mod team;
pub mod v0_endpoint;
pub mod v0_request;

// Test modules don't need to be compiled with main binary
// #[cfg(test)]
// TODO: To use in integration tests, we need to compile with binary
// or make it a separate feature using cfg(feature = "integration-tests")
// and then use this feature only in tests.
// For now, ok to just include in binary
pub mod test_utils;
