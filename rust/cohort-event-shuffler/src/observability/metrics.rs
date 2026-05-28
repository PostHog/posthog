//! Prometheus recorder setup. Application counters/histograms are registered by the
//! consumer/producer as they are built; this installs the global recorder and returns
//! the render handle consumed by `GET /metrics`.

use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};

/// Install the global Prometheus recorder. Call once at startup.
///
/// # Panics
/// Panics if a global metrics recorder has already been installed.
pub fn install_recorder() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("failed to install Prometheus recorder")
}
