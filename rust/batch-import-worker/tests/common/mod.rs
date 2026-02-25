//! Shared test utilities for MinIO/S3 integration tests.

use aws_config::BehaviorVersion;
use aws_sdk_s3::config::Region;
use aws_sdk_s3::Client as AwsS3Client;

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
