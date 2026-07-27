//! Core of the realtime feature-flags streaming gateway (plan §2).
//!
//! The service is a stateless SSE version-beacon: it watches the two flag
//! HyperCaches in Redis (a per-tier ETag sweep for correctness plus a pub/sub
//! hint fast path) and pushes the current content version to subscribed clients,
//! who refetch through the existing flag endpoints only on a version mismatch.
//!
//! Milestone 3 landed the lib-only core — the domain state machine
//! ([`domain`]), the fanout registry ([`registry`]), the wire protocol
//! ([`protocol`]), and the validated config ([`config`]). Milestone 4 adds the
//! runnable service around it: dependency construction ([`server`]), the router
//! and probes ([`router`]), auth and admission ([`auth`]), the SSE handler
//! ([`api`]), the trigger tasks ([`trigger`]), and the metric surface
//! ([`metrics`]).

pub mod api;
pub mod auth;
pub mod config;
pub mod domain;
pub mod metrics;
pub mod protocol;
pub mod registry;
pub mod router;
pub mod server;
pub mod trigger;
