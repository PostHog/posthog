//! Shared test utilities for integration tests.
//!
//! This module provides common helpers for MinIO/S3 operations used across
//! multiple integration test files.

use aws_config::BehaviorVersion;
use aws_sdk_s3::config::Region;
use aws_sdk_s3::primitives::ByteStream;
use aws_sdk_s3::Client as AwsS3Client;
use chrono::{DateTime, Utc};
use kafka_deduplicator::checkpoint::CheckpointMetadata;

// MinIO configuration matching docker-compose.dev.yml
pub const MINIO_ENDPOINT: &str = "http://localhost:19000";
pub const MINIO_ACCESS_KEY: &str = "object_storage_root_user";
pub const MINIO_SECRET_KEY: &str = "object_storage_root_password";

/// Creates a MinIO S3 client configured for local testing.
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

/// Ensures a bucket exists, creating it if necessary.
pub async fn ensure_bucket_exists(client: &AwsS3Client, bucket: &str) {
    // Try to create bucket, ignore if it already exists
    let _ = client.create_bucket().bucket(bucket).send().await;
}

/// Deletes all objects in a bucket with the given prefix.
pub async fn cleanup_bucket(client: &AwsS3Client, bucket: &str, prefix: &str) {
    // List and delete all objects with the given prefix
    let list_result = client
        .list_objects_v2()
        .bucket(bucket)
        .prefix(prefix)
        .send()
        .await;

    if let Ok(response) = list_result {
        for object in response.contents() {
            if let Some(key) = object.key() {
                let _ = client.delete_object().bucket(bucket).key(key).send().await;
            }
        }
    }
}

/// Uploads a test checkpoint with the specified number of files to MinIO.
/// Returns the checkpoint metadata that was uploaded.
///
/// The checkpoint will have:
/// - `file_count` SST files (named 000001.sst, 000002.sst, etc.)
/// - A metadata.json file
///
/// All files are uploaded to: {s3_key_prefix}/{topic}/{partition}/{checkpoint_id}/
#[allow(dead_code)] // Used by checkpoint_integration_tests, not all test files
pub async fn upload_test_checkpoint(
    client: &AwsS3Client,
    bucket: &str,
    s3_key_prefix: &str,
    topic: &str,
    partition: i32,
    attempt_timestamp: DateTime<Utc>,
    file_count: usize,
) -> CheckpointMetadata {
    let mut metadata = CheckpointMetadata::new(
        topic.to_string(),
        partition,
        attempt_timestamp,
        12345, // placeholder sequence number
        100,   // placeholder consumer offset
        50,    // placeholder producer offset
    );

    let checkpoint_id = CheckpointMetadata::generate_id(attempt_timestamp);
    let remote_base_path = format!("{s3_key_prefix}/{topic}/{partition}/{checkpoint_id}");

    // Upload SST files
    for i in 1..=file_count {
        let filename = format!("{:06}.sst", i);
        let remote_key = format!("{remote_base_path}/{filename}");
        let file_content = format!("mock sst file content for {filename}");

        client
            .put_object()
            .bucket(bucket)
            .key(&remote_key)
            .body(ByteStream::from(file_content.into_bytes()))
            .send()
            .await
            .expect("Failed to upload test SST file");

        metadata.track_file(remote_key, format!("checksum_{i}"));
    }

    // Upload metadata.json
    let metadata_key = format!("{remote_base_path}/metadata.json");
    let metadata_json = metadata.to_json().expect("Failed to serialize metadata");

    client
        .put_object()
        .bucket(bucket)
        .key(&metadata_key)
        .body(ByteStream::from(metadata_json.into_bytes()))
        .send()
        .await
        .expect("Failed to upload metadata.json");

    metadata
}

/// Deletes a specific file from a checkpoint in MinIO.
#[allow(dead_code)] // Used by checkpoint_integration_tests, not all test files
pub async fn delete_checkpoint_file(client: &AwsS3Client, bucket: &str, file_key: &str) {
    client
        .delete_object()
        .bucket(bucket)
        .key(file_key)
        .send()
        .await
        .expect("Failed to delete checkpoint file");
}
