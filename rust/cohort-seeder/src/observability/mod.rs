//! Observability layer (leaf): the health HTTP router and the Prometheus metric surface. Depends on
//! `lifecycle`/`axum`/the metrics exporter only, never on another seeder module; every layer above
//! draws its metric-name constants from here.

pub mod health;
pub mod metrics;
