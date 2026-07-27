//! Observability surface: health/readiness probes, Prometheus metrics, and the canonical log.

pub mod canonical_log;
pub mod health;
pub mod metrics;
pub mod store_stats;
pub mod tokio_monitor;
