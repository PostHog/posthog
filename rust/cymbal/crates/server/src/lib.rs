//! Cymbal gRPC server and pipeline orchestration crate.

// `tonic::Status` is roughly 176 bytes (it carries headers, metadata, source
// chain, etc.), so almost every `Result<_, tonic::Status>` in this crate trips
// `clippy::result_large_err`. Boxing every Status return would ripple through
// the entire server crate and its public traits without a measurable benefit:
// the `Err` path is rare, and tonic generates `Result<_, Status>` for us. We
// accept the size here rather than wrapping every public signature in
// `Box<Status>`.
#![allow(clippy::result_large_err)]

mod api;
mod codec;
pub mod config;
pub mod observability;
pub mod pipeline;
mod pipeline_routing;
pub mod registry;
pub mod remote;
mod remote_runner;
pub mod stage;

pub use pipeline::CymbalPipelineService;
