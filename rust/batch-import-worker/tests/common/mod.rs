//! Shared test utilities for the batch-import integration tests.
//!
//! Each integration test file is its own crate and pulls this in via `mod
//! common;`, so a helper used by only some of them looks "dead" to the others —
//! hence the crate-wide allow below.
#![allow(dead_code)]

pub mod harness;
pub mod mock_export;

use std::io::Write;

use aws_config::BehaviorVersion;
use aws_sdk_s3::config::Region;
use aws_sdk_s3::Client as AwsS3Client;
use flate2::write::GzEncoder;
use flate2::Compression;

/// Gzip-compress `data` with default compression (single member).
pub fn gzip_bytes(data: &[u8]) -> Vec<u8> {
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(data).unwrap();
    encoder.finish().unwrap()
}

pub const SEAWEEDFS_ENDPOINT: &str = "http://localhost:8333";
pub const SEAWEEDFS_BUCKET: &str = "posthog";

/// An `object_store` client for the dev-stack SeaweedFS (S3 API on :8333).
/// SeaweedFS dev runs in open-access mode; any credentials are accepted.
pub fn seaweedfs_store() -> std::sync::Arc<dyn object_store::ObjectStore> {
    let store = object_store::aws::AmazonS3Builder::new()
        .with_bucket_name(SEAWEEDFS_BUCKET)
        .with_endpoint(SEAWEEDFS_ENDPOINT)
        .with_region("us-east-1")
        .with_allow_http(true)
        .with_virtual_hosted_style_request(false)
        .with_access_key_id("any")
        .with_secret_access_key("any")
        .build()
        .expect("failed to build SeaweedFS object_store");
    std::sync::Arc::new(store)
}

/// Probe SeaweedFS: a head on a missing key returns NotFound when reachable, and
/// a transport error when the dev stack isn't running. Unreachable is a silent
/// skip locally (developer convenience) but a hard failure in CI, where the dev
/// compose stack (including SeaweedFS) is always booted - a down store must
/// produce a red build, never a silently-skipped green one.
pub async fn seaweedfs_reachable(store: &std::sync::Arc<dyn object_store::ObjectStore>) -> bool {
    use object_store::ObjectStoreExt;
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

/// An `aws_sdk_s3` client for the same dev-stack SeaweedFS, for sources that
/// consume the AWS SDK rather than `object_store` (e.g. `GzipS3Source`).
pub async fn seaweedfs_sdk_client() -> AwsS3Client {
    let config = aws_config::defaults(BehaviorVersion::latest())
        .endpoint_url(SEAWEEDFS_ENDPOINT)
        .region(Region::new("us-east-1"))
        .credentials_provider(aws_sdk_s3::config::Credentials::new(
            "any", "any", None, None, "test",
        ))
        .load()
        .await;

    let s3_config = aws_sdk_s3::config::Builder::from(&config)
        .force_path_style(true)
        .build();

    AwsS3Client::from_conf(s3_config)
}

pub const MINIO_ENDPOINT: &str = "http://localhost:19000";
pub const MINIO_ACCESS_KEY: &str = "object_storage_root_user";
pub const MINIO_SECRET_KEY: &str = "object_storage_root_password";

pub async fn create_minio_client() -> AwsS3Client {
    let config = aws_config::defaults(BehaviorVersion::latest())
        .endpoint_url(MINIO_ENDPOINT)
        .region(Region::new("us-east-1"))
        .credentials_provider(aws_sdk_s3::config::Credentials::new(
            MINIO_ACCESS_KEY,
            MINIO_SECRET_KEY,
            None,
            None,
            "test",
        ))
        .load()
        .await;

    let s3_config = aws_sdk_s3::config::Builder::from(&config)
        .force_path_style(true)
        .build();

    AwsS3Client::from_conf(s3_config)
}

pub async fn ensure_bucket_exists(client: &AwsS3Client, bucket: &str) {
    drop(client.create_bucket().bucket(bucket).send().await);
}

pub async fn cleanup_bucket(client: &AwsS3Client, bucket: &str, prefix: &str) {
    let list_result = client
        .list_objects_v2()
        .bucket(bucket)
        .prefix(prefix)
        .send()
        .await;

    if let Ok(response) = list_result {
        for object in response.contents() {
            if let Some(key) = object.key() {
                drop(client.delete_object().bucket(bucket).key(key).send().await);
            }
        }
    }
}
