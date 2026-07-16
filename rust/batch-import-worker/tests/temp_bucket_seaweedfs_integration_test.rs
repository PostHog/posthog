//! SeaweedFS integration test for the temp-bucket staging backend: stage a compressed
//! part through the real decompress pipeline into a live S3-compatible store, then read it
//! back by byte range and clean it up.
//!
//! Requires SeaweedFS running at localhost:8333 with a `posthog` bucket (docker-compose.dev.yml).
//! Skips if unreachable. No MinIO dependency.

use std::collections::HashMap;
use std::sync::Arc;

use batch_import_worker::extractor::ExtractorType;
use batch_import_worker::source::date_range_export::{AuthConfig, DateRangeExportSource};
use batch_import_worker::source::{DataSource, RemoteStaging};
use batch_import_worker::staging::{open_plaintext_stream, StagingBackend, TempBucketBackend};
use chrono::{TimeZone, Utc};
use flate2::write::GzEncoder;
use flate2::Compression;
use httpmock::MockServer;
use object_store::aws::AmazonS3Builder;
use object_store::{ObjectStore, ObjectStoreExt};
use std::io::Write;
use uuid::Uuid;

const SEAWEEDFS_ENDPOINT: &str = "http://localhost:8333";
const TEST_BUCKET: &str = "posthog";

fn seaweedfs_store() -> Arc<dyn ObjectStore> {
    let store = AmazonS3Builder::new()
        .with_bucket_name(TEST_BUCKET)
        .with_endpoint(SEAWEEDFS_ENDPOINT)
        .with_region("us-east-1")
        .with_allow_http(true)
        .with_virtual_hosted_style_request(false)
        // SeaweedFS dev runs in open-access mode; any credentials are accepted.
        .with_access_key_id("any")
        .with_secret_access_key("any")
        .build()
        .expect("failed to build SeaweedFS object_store");
    Arc::new(store)
}

fn gzip(data: &[u8]) -> Vec<u8> {
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(data).unwrap();
    encoder.finish().unwrap()
}

/// Probe SeaweedFS: a head on a missing key returns NotFound when reachable, and a
/// transport error when the dev stack isn't running. Unreachable is a silent skip
/// locally (developer convenience) but a hard failure in CI, where the dev compose
/// stack (including SeaweedFS) is always booted — a down store must produce a red
/// build, never a silently-skipped green one.
async fn seaweedfs_reachable(store: &Arc<dyn ObjectStore>) -> bool {
    let probe = object_store::path::Path::from("__reachability_probe__");
    let result = tokio::time::timeout(std::time::Duration::from_secs(3), store.head(&probe)).await;
    let reachable = matches!(
        result,
        Ok(Ok(_)) | Ok(Err(object_store::Error::NotFound { .. }))
    );
    if !reachable && std::env::var("CI").is_ok() {
        panic!("SeaweedFS unreachable at {SEAWEEDFS_ENDPOINT} in CI — the dev stack must be up");
    }
    reachable
}

#[tokio::test]
async fn test_temp_bucket_seaweedfs_round_trip() {
    let store = seaweedfs_store();

    if !seaweedfs_reachable(&store).await {
        eprintln!("SeaweedFS unreachable at {SEAWEEDFS_ENDPOINT}, skipping test");
        return;
    }

    // Unique job id so repeated runs don't collide, and so we can prove prefix cleanup.
    let job_id = format!("job-{}", Uuid::now_v7());
    let backend = TempBucketBackend::new(Arc::clone(&store), "batch-import-staging/", job_id);

    // Body without a trailing newline: exercises the pipeline's appended-newline path.
    let raw_dir = tempfile::TempDir::new().unwrap();
    let raw_path = raw_dir.path().join("part.raw");
    std::fs::write(&raw_path, gzip(b"{\"a\":1}\n{\"b\":2}\n{\"c\":3}")).unwrap();

    let size = backend
        .stage_part(
            "2024-01-01:00",
            open_plaintext_stream(raw_path, ExtractorType::PlainGzip, 0),
        )
        .await
        .unwrap();
    let expected = b"{\"a\":1}\n{\"b\":2}\n{\"c\":3}\n";
    assert_eq!(size, expected.len() as u64);

    // Full read, mid-slice, and overrun-EOF all behave against a real store.
    assert_eq!(backend.size("2024-01-01:00").await.unwrap(), Some(size));
    assert_eq!(
        backend.read("2024-01-01:00", 0, size + 10).await.unwrap(),
        expected
    );
    assert_eq!(
        backend.read("2024-01-01:00", 8, 7).await.unwrap(),
        b"{\"b\":2}"
    );
    assert!(backend
        .read("2024-01-01:00", size, 10)
        .await
        .unwrap()
        .is_empty());

    // cleanup_key removes it; a second delete is a no-op.
    backend.cleanup_key("2024-01-01:00").await.unwrap();
    assert_eq!(backend.size("2024-01-01:00").await.unwrap(), None);
    backend.cleanup_key("2024-01-01:00").await.unwrap();

    // cleanup_job leaves nothing under the job prefix.
    stage_and_assert_swept(&backend).await;
}

async fn stage_and_assert_swept(backend: &TempBucketBackend) {
    let stream = open_plaintext_stream_from_bytes(b"x\ny\nz\n");
    backend.stage_part("k", stream).await.unwrap();
    assert_eq!(backend.size("k").await.unwrap(), Some(6));
    backend.cleanup_job().await.unwrap();
    assert_eq!(backend.size("k").await.unwrap(), None);
}

fn open_plaintext_stream_from_bytes(data: &[u8]) -> batch_import_worker::staging::PlaintextStream {
    batch_import_worker::staging::PlaintextStream::from_chunks(vec![bytes::Bytes::copy_from_slice(
        data,
    )])
}

/// End-to-end remote staging through a real source: a DateRangeExportSource in
/// temp-bucket mode downloads from an httpmock origin, ingests via the pipeline into
/// live SeaweedFS, serves ranged reads back, resumes without re-download, and sweeps
/// its job prefix on cleanup.
/// A data-error pause must quarantine the staged plaintext (the exact bytes the
/// failing offset points into) rather than delete it: the resume re-downloads a
/// clean copy from the origin, while support can still read the failing bytes
/// from the quarantine location. Terminal cleanup sweeps quarantine with the
/// rest of the job prefix.
#[tokio::test]
async fn test_data_error_pause_quarantines_staged_part_and_resume_redownloads() {
    let store = seaweedfs_store();
    if !seaweedfs_reachable(&store).await {
        eprintln!("SeaweedFS unreachable at {SEAWEEDFS_ENDPOINT}, skipping test");
        return;
    }

    let body = b"{\"event\":\"a\"}\nnot valid json\n{\"event\":\"c\"}";
    let server = MockServer::start();
    let mock = server.mock(|when, then| {
        when.method(httpmock::Method::GET).path("/export");
        then.status(200).body(gzip(body));
    });

    let job_id = format!("job-{}", Uuid::now_v7());
    let build = |staging: &std::path::Path| {
        DateRangeExportSource::builder(
            server.url("/export"),
            Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap(),
            Utc.with_ymd_and_hms(2023, 1, 1, 1, 0, 0).unwrap(),
            3600,
            ExtractorType::PlainGzip.create_extractor(),
            staging.to_path_buf(),
        )
        .with_auth(AuthConfig::None)
        .with_date_format("%Y-%m-%dT%H:%M:%SZ".to_string())
        .with_headers(HashMap::new())
        .with_remote_staging(Some(RemoteStaging {
            backend: Arc::new(TempBucketBackend::new(
                Arc::clone(&store),
                "batch-import-staging/",
                job_id.clone(),
            )),
            extractor_type: ExtractorType::PlainGzip,
            max_plaintext_bytes: 0,
        }))
        .build()
        .unwrap()
    };

    // Stage the part and read a chunk, like a job that then hits the bad line.
    let staging = tempfile::TempDir::new().unwrap();
    let source = build(staging.path());
    source.prepare_for_job().await.unwrap();
    let key = source.keys().await.unwrap().remove(0);
    source.prepare_key(&key).await.unwrap();
    assert!(!source.get_chunk(&key, 0, 14).await.unwrap().is_empty());
    assert_eq!(mock.hits(), 1);

    // The data-error pause path.
    source.cleanup_after_data_error().await.unwrap();

    // Support can read the exact staged bytes that failed to parse (the
    // pipeline appends the trailing newline, matching what the offsets index).
    let quarantine_path = object_store::path::Path::from(format!(
        "batch-import-staging/{job_id}/quarantine/{}.data",
        key.replace([':', '/'], "_")
    ));
    let quarantined = store
        .get(&quarantine_path)
        .await
        .expect("staged part must be quarantined, not deleted")
        .bytes()
        .await
        .unwrap();
    let mut expected = body.to_vec();
    expected.push(b'\n');
    assert_eq!(quarantined.as_ref(), expected.as_slice());

    // The resume cannot attach to the stale copy: a fresh source re-downloads.
    let staging_b = tempfile::TempDir::new().unwrap();
    let resumed = build(staging_b.path());
    resumed.prepare_for_job().await.unwrap();
    resumed.prepare_key(&key).await.unwrap();
    assert_eq!(mock.hits(), 2, "resume after a data error must re-download");

    // Terminal cleanup sweeps the quarantined evidence with the job prefix.
    resumed.cleanup_after_job().await.unwrap();
    assert!(
        store.get(&quarantine_path).await.is_err(),
        "cleanup_after_job must sweep quarantine"
    );
}

#[tokio::test]
async fn test_remote_staged_source_round_trip_on_seaweedfs() {
    let store = seaweedfs_store();
    if !seaweedfs_reachable(&store).await {
        eprintln!("SeaweedFS unreachable at {SEAWEEDFS_ENDPOINT}, skipping test");
        return;
    }

    let body = b"{\"event\":\"a\"}\n{\"event\":\"b\"}\n{\"event\":\"c\"}";
    let server = MockServer::start();
    let mock = server.mock(|when, then| {
        when.method(httpmock::Method::GET).path("/export");
        then.status(200).body(gzip(body));
    });

    // Unique job id so repeated runs don't collide.
    let job_id = format!("job-{}", Uuid::now_v7());
    let build = |staging: &std::path::Path| {
        DateRangeExportSource::builder(
            server.url("/export"),
            Utc.with_ymd_and_hms(2023, 1, 1, 0, 0, 0).unwrap(),
            Utc.with_ymd_and_hms(2023, 1, 1, 1, 0, 0).unwrap(),
            3600,
            ExtractorType::PlainGzip.create_extractor(),
            staging.to_path_buf(),
        )
        .with_auth(AuthConfig::None)
        .with_date_format("%Y-%m-%dT%H:%M:%SZ".to_string())
        .with_headers(HashMap::new())
        .with_remote_staging(Some(RemoteStaging {
            backend: Arc::new(TempBucketBackend::new(
                Arc::clone(&store),
                "batch-import-staging/",
                job_id.clone(),
            )),
            extractor_type: ExtractorType::PlainGzip,
            max_plaintext_bytes: 0,
        }))
        .build()
        .unwrap()
    };

    // The pipeline appends the missing trailing newline.
    let expected = b"{\"event\":\"a\"}\n{\"event\":\"b\"}\n{\"event\":\"c\"}\n";

    let staging = tempfile::TempDir::new().unwrap();
    let source = build(staging.path());
    source.prepare_for_job().await.unwrap();
    let key = source.keys().await.unwrap().remove(0);

    source.prepare_key(&key).await.unwrap();
    assert_eq!(mock.hits(), 1);
    assert_eq!(
        source.size(&key).await.unwrap(),
        Some(expected.len() as u64)
    );

    // Ranged reads reconstruct the body across record-misaligned boundaries.
    let mut out = Vec::new();
    let mut offset = 0u64;
    loop {
        let chunk = source.get_chunk(&key, offset, 7).await.unwrap();
        if chunk.is_empty() {
            break;
        }
        offset += chunk.len() as u64;
        out.extend_from_slice(&chunk);
    }
    assert_eq!(out, expected);

    // A fresh source (cold process) attaches via head without re-downloading.
    let staging_b = tempfile::TempDir::new().unwrap();
    let resumed = build(staging_b.path());
    resumed.prepare_for_job().await.unwrap();
    resumed.prepare_key(&key).await.unwrap();
    assert_eq!(mock.hits(), 1, "resume must not re-hit the origin");
    assert_eq!(
        resumed.get_chunk(&key, 14, 14).await.unwrap(),
        &expected[14..28]
    );

    // Job cleanup sweeps the staged object.
    resumed.cleanup_after_job().await.unwrap();
    let fresh = build(tempfile::TempDir::new().unwrap().path());
    assert_eq!(fresh.size(&key).await.unwrap(), None);
}
