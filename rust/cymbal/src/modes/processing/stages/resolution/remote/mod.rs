//! Remote `cymbal.resolution.v1` client integration.
//!
//! The processing resolution stage routes exception-level work through the
//! `cymbal-resolution` service via a caller-owned endpoint pool.

pub mod client;
pub mod config;
pub mod dns;
pub mod mux;
pub mod pool;
pub mod resolver;
pub mod subscription;

pub use config::RemoteResolutionConfig;
pub use pool::EndpointPool;
