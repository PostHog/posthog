//! Shared test utilities for integration tests.
//!
//! This module provides common helpers for MinIO/S3 operations used across
//! multiple integration test files.

use aws_config::BehaviorVersion;
use aws_sdk_s3::config::Region;
use aws_sdk_s3::Client as AwsS3Client;

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
