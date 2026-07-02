//! Dependency-free integration test for the fail-fast staging disk guard wired
//! into the date range export source. It proves that when the staging directory
//! is already over the configured byte budget, preparing a key returns an error
//! carrying an actionable user-facing message (so the job pauses cleanly instead
//! of the pod being evicted under disk pressure). A limit of 0 leaves the guard
//! disabled and downloads proceed normally.

use std::collections::HashMap;
use std::path::Path;

use batch_import_worker::extractor::ExtractorType;
use batch_import_worker::source::date_range_export::{AuthConfig, DateRangeExportSource};
use batch_import_worker::source::DataSource;
use chrono::{TimeZone, Utc};
use httpmock::MockServer;
use tempfile::TempDir;

fn build_source(base_url: String, staging: &Path, staging_max_bytes: u64) -> DateRangeExportSource {
    let start = Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap();
    let end = Utc.with_ymd_and_hms(2023, 1, 1, 1, 0, 0).unwrap();
    DateRangeExportSource::builder(
        base_url,
        start,
        end,
        3600,
        ExtractorType::PlainGzip.create_extractor(),
        staging.to_path_buf(),
    )
    .with_auth(AuthConfig::None)
    .with_date_format("%Y-%m-%dT%H:%M:%SZ".to_string())
    .with_headers(HashMap::new())
    .with_staging_max_bytes(staging_max_bytes)
    .build()
    .unwrap()
}

#[tokio::test]
async fn test_prepare_key_pauses_when_staging_over_budget() {
    let server = MockServer::start();
    let _mock = server.mock(|when, then| {
        when.method(httpmock::Method::GET).path("/export");
        then.status(200).body(vec![0u8; 1024]);
    });

    let staging = TempDir::new().unwrap();
    // Pre-fill staging well above the 1 KiB limit (simulates leftover from prior
    // work / a sibling part). The guard measures the whole staging tree.
    std::fs::write(staging.path().join("preexisting.bin"), vec![0u8; 64 * 1024]).unwrap();

    let source = build_source(server.url("/export"), staging.path(), 1024);
    source.prepare_for_job().await.unwrap();
    let keys = source.keys().await.unwrap();
    let key = &keys[0];

    let err = source
        .prepare_key(key)
        .await
        .expect_err("prepare_key must fail when staging is over budget");
    // The error chain carries the actionable UserError so the job pauses with it.
    let chain = format!("{err:#}");
    assert!(
        chain.contains("Staging disk limit exceeded"),
        "expected user-facing staging-limit message, got: {chain}"
    );
}

#[tokio::test]
async fn test_prepare_key_succeeds_when_guard_disabled() {
    let server = MockServer::start();
    let _mock = server.mock(|when, then| {
        when.method(httpmock::Method::GET).path("/export");
        then.status(200).body(vec![0u8; 1024]);
    });

    let staging = TempDir::new().unwrap();
    std::fs::write(staging.path().join("preexisting.bin"), vec![0u8; 64 * 1024]).unwrap();

    // max_bytes == 0 disables the guard: the same over-budget staging is fine.
    let source = build_source(server.url("/export"), staging.path(), 0);
    source.prepare_for_job().await.unwrap();
    let keys = source.keys().await.unwrap();
    let key = &keys[0];

    source
        .prepare_key(key)
        .await
        .expect("prepare_key must succeed when the guard is disabled");
}
