//! Core of the realtime feature-flags streaming gateway (plan §2).
//!
//! Milestone 3 is lib-only: the domain state machine, the fanout registry, the
//! wire protocol, and the validated config. Server wiring, auth, the SSE
//! handler, and the trigger tasks land in Milestone 4.

pub mod config;
pub mod domain;
pub mod protocol;
pub mod registry;
