//! Shared symbolication kernel: the symbol-resolution stack and the domain
//! pieces both run modes depend on (see `crate::modes`). Nothing here may
//! depend on processing-only modules (the pipeline, Kafka/Redis, rules), so
//! this subtree can later be lifted into its own `cymbal-core` crate.

pub mod analytics;
pub mod config;
pub mod error;
pub mod ids;
pub mod metric_consts;
pub mod resolver;
pub mod sanitize;
pub mod shutdown;
pub mod symbolication;
pub mod types;
