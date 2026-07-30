//! Metrics emitted while components are built must survive to the scrape
//! endpoint. `build_components` installs the global recorder, so ordering
//! inside it decides whether a startup metric is recorded or silently dropped
//! — and that is only observable through the real startup path, never from a
//! unit test with a local recorder.
//!
//! Keep this binary to a single test: installing the Prometheus recorder is a
//! once-per-process operation.

use std::time::Duration;

#[path = "common/utils.rs"]
mod test_utils;
use test_utils::{setup_tracing, ServerHandle, DEFAULT_CONFIG};

#[tokio::test]
async fn startup_gauge_reaches_the_scrape_endpoint() {
    setup_tracing();

    let mut config = DEFAULT_CONFIG.clone();
    config.export_prometheus = true;
    // Warnings asked for but no dedicated hosts: the emitter reports `0` with a
    // reason during `build_components`, which is precisely the window where the
    // gauge used to be dropped.
    config.capture_ingestion_warnings_enabled = true;
    config.capture_ingestion_warnings_kafka_hosts = String::new();

    let server = ServerHandle::for_config(config).await;

    let body = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .expect("http client")
        .get(format!("http://{}/metrics", server.addr))
        .send()
        .await
        .expect("scrape /metrics")
        .text()
        .await
        .expect("read scrape body");

    let line = body
        .lines()
        .find(|line| line.starts_with("ingestion_warnings_emitter_enabled{"))
        .unwrap_or_else(|| {
            panic!("emitter gauge missing from scrape output, startup metrics are being dropped")
        });

    assert!(
        line.contains(r#"reason="hosts_unset""#),
        "gauge must name the misconfiguration: {line}"
    );
    assert!(
        line.ends_with(" 0"),
        "an enabled-but-unbuildable emitter must report 0: {line}"
    );
    // Recorder-level labels only exist when the recorder is installed before
    // the emission, so their presence pins the ordering too.
    assert!(
        line.contains(r#"capture_mode="events""#) && line.contains(r#"role="capture-testing""#),
        "gauge must carry the recorder's global labels: {line}"
    );
}
