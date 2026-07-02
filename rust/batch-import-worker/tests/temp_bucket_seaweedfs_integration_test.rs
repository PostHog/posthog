//! SeaweedFS integration test for the temp-bucket staging backend: stage a compressed
//! part through the real decompress pipeline into a live S3-compatible store, then read it
//! back by byte range and clean it up.
//!
//! Requires SeaweedFS running at localhost:8333 with a `posthog` bucket (docker-compose.dev.yml).
//! Skips if unreachable. No MinIO dependency.

use std::sync::Arc;

use batch_import_worker::extractor::ExtractorType;
use batch_import_worker::staging::{open_plaintext_stream, StagingBackend, TempBucketBackend};
use flate2::write::GzEncoder;
use flate2::Compression;
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
/// transport error when the dev stack isn't running (in which case we skip).
async fn seaweedfs_reachable(store: &Arc<dyn ObjectStore>) -> bool {
    let probe = object_store::path::Path::from("__reachability_probe__");
    let result = tokio::time::timeout(std::time::Duration::from_secs(3), store.head(&probe)).await;
    matches!(
        result,
        Ok(Ok(_)) | Ok(Err(object_store::Error::NotFound { .. }))
    )
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
