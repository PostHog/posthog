//! Remote `cymbal.resolution.v1` client integration.
//!
//! When `Config::remote_resolution_enabled` is set, the resolution stage
//! routes exception-level symbol resolution through the `cymbal-resolution`
//! service via a caller-owned endpoint pool instead of running
//! [`crate::symbolication::symbol::local::LocalSymbolResolver`] inline.
//!
//! There is intentionally no silent local fallback: if the pool cannot
//! satisfy a request, the stage surfaces an error for the batch instead of
//! falling back to local resolution. Running out of routable capacity is
//! reported as `UnhandledError::LoadShed`, which answers the caller with a
//! retryable status rather than an unhandled exception; every other failure
//! stays unhandled.

pub mod client;
pub mod config;
pub mod dns;
pub mod mux;
pub mod pool;
pub mod resolver;
pub mod subscription;

pub use config::RemoteResolutionConfig;
pub use pool::EndpointPool;
