//! Observability surface: K8s health/readiness probes, Prometheus metrics (§8.1), and
//! the per-batch canonical log (§8.2).

pub mod canonical_log;
pub mod health;
pub mod metrics;
