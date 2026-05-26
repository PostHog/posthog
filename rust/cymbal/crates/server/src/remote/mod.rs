//! Remote stage transport, endpoint selection, and per-endpoint health state.
//!
//! Split across submodules along the runtime/transport boundaries used by the
//! connection manager:
//!
//! - [`client`] — the per-call gRPC client wrapper and the connection options
//!   it depends on.
//! - [`circuit`] — per-endpoint circuit breaker state machine and the jittered
//!   retry-after helper used by the dispatcher.
//! - [`load`] — observed `StageLoad` cache, capacity translation, and the
//!   `cymbal_remote_endpoint_*` metric writers.
//! - [`connection`] — the [`RemoteStageConnectionManager`] itself: DNS
//!   resolution, channel cache, refresh loop, circuit/load integration, and
//!   candidate selection.

mod circuit;
mod client;
mod connection;
mod load;

pub use client::{
    RemoteStageClient, RemoteStageConfig, RemoteStageConnectionOptions, RemoteStageItem,
};
pub use connection::{
    resolve_headless_service, RemoteStageConnectionError, RemoteStageConnectionManager,
    RemoteStageTarget,
};

pub(crate) use circuit::jittered_retry_after_ms;
