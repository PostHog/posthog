//! Typed, data-only workflow definitions. Version 2 is executed by the native
//! runner, shared by mounted views and the headless broker.
mod host_error;
pub use host_error::{FailureKind, HostError};
#[cfg(all(feature = "runner", not(target_family = "wasm")))]
pub mod expressions;
pub mod pattern;
#[cfg(all(feature = "runner", not(target_family = "wasm")))]
pub mod runner;
pub mod schedules;

#[cfg(all(feature = "runner", not(target_family = "wasm")))]
mod definition;
#[cfg(all(feature = "runner", not(target_family = "wasm")))]
pub use definition::*;
#[cfg(all(feature = "runner", not(target_family = "wasm")))]
pub mod catalog;
