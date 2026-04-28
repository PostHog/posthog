use aws_config::BehaviorVersion;
use aws_sdk_s3::config::Region;
use aws_sdk_s3::Client as AwsS3SdkClient;
use common_s3::{S3Client, S3Error, S3Impl};

const TEST_BUCKET: &str = "test-bucket";
const S3_ENDPOINT: &str = "http://127.0.0.1:19000"; // MinIO

async fn create_test_s3_client() -> (S3Impl, AwsS3SdkClient) {
    let config = aws_config::defaults(BehaviorVersion::latest())
        .endpoint_url(S3_ENDPOINT)
        .region(Region::new("us-east-1"))
        .credentials_provider(aws_sdk_s3::config::Credentials::new(
            "object_storage_root_user",
            "object_storage_root_password",
            None,
            None,
            "test",
        ))
        .load()
        .await;

    let aws_client = AwsS3SdkClient::new(&config);
    let s3_impl = S3Impl::new(aws_client.clone());
    (s3_impl, aws_client)
}

async fn ensure_bucket_exists(client: &AwsS3SdkClient) {
    // Try to create bucket, ignore if it already exists
    let _ = client.create_bucket().bucket(TEST_BUCKET).send().await;
}

#[tokio::test]
async fn test_s3_round_trip_get_string() {
    let (s3_client, aws_client) = create_test_s3_client().await;

    ensure_bucket_exists(&aws_client).await;

    let test_key = "test/round-trip-string.txt";
    let test_content = "Hello, S3! 🚀\nMultiline content works too.";

    // Put object using AWS client directly
    aws_client
        .put_object()
        .bucket(TEST_BUCKET)
        .key(test_key)
        .body(test_content.as_bytes().to_vec().into())
        .send()
        .await
        .expect("Failed to put test object");

    // Get object using our wrapper
    let result = s3_client.get_string(TEST_BUCKET, test_key).await;

    assert!(result.is_ok(), "Failed to get object: {:?}", result.err());
    assert_eq!(result.unwrap(), test_content);

    // Cleanup
    let _ = aws_client
        .delete_object()
        .bucket(TEST_BUCKET)
        .key(test_key)
        .send()
        .await;
}

#[tokio::test]
async fn test_s3_get_string_not_found() {
    let (s3_client, aws_client) = create_test_s3_client().await;

    ensure_bucket_exists(&aws_client).await;

    let nonexistent_key = "test/nonexistent-file.txt";

    let result = s3_client.get_string(TEST_BUCKET, nonexistent_key).await;

    assert!(result.is_err());
    assert!(matches!(result.unwrap_err(), S3Error::NotFound(_)));
}

#[tokio::test]
async fn test_s3_get_string_invalid_utf8() {
    let (s3_client, aws_client) = create_test_s3_client().await;

    ensure_bucket_exists(&aws_client).await;

    let test_key = "test/invalid-utf8.bin";
    let invalid_utf8_bytes = vec![0xFF, 0xFE, 0xFD]; // Invalid UTF-8 sequence

    // Put invalid UTF-8 content
    aws_client
        .put_object()
        .bucket(TEST_BUCKET)
        .key(test_key)
        .body(invalid_utf8_bytes.into())
        .send()
        .await
        .expect("Failed to put test object");

    // Try to get as string - should fail with ParseError
    let result = s3_client.get_string(TEST_BUCKET, test_key).await;

    assert!(result.is_err());
    assert!(matches!(result.unwrap_err(), S3Error::ParseError(_)));

    // Cleanup
    let _ = aws_client
        .delete_object()
        .bucket(TEST_BUCKET)
        .key(test_key)
        .send()
        .await;
}

#[tokio::test]
async fn test_s3_put_string_then_get_string() {
    let (s3_client, aws_client) = create_test_s3_client().await;
    ensure_bucket_exists(&aws_client).await;

    let test_key = "test/put-string-roundtrip.json";
    let test_content = r#"{"flags":[{"id":1,"key":"test-flag"}]}"#;

    // Put using our wrapper
    s3_client
        .put_string(TEST_BUCKET, test_key, test_content)
        .await
        .expect("Failed to put string");

    // Get using our wrapper
    let result = s3_client
        .get_string(TEST_BUCKET, test_key)
        .await
        .expect("Failed to get string");
    assert_eq!(result, test_content);

    // Cleanup
    let _ = s3_client.delete(TEST_BUCKET, test_key).await;
}

#[tokio::test]
async fn test_s3_delete_existing_key() {
    let (s3_client, aws_client) = create_test_s3_client().await;
    ensure_bucket_exists(&aws_client).await;

    let test_key = "test/delete-existing.txt";

    // Put an object first
    s3_client
        .put_string(TEST_BUCKET, test_key, "to be deleted")
        .await
        .expect("Failed to put string");

    // Delete it
    s3_client
        .delete(TEST_BUCKET, test_key)
        .await
        .expect("Failed to delete");

    // Verify it's gone
    let result = s3_client.get_string(TEST_BUCKET, test_key).await;
    assert!(matches!(result, Err(S3Error::NotFound(_))));
}

#[tokio::test]
async fn test_s3_delete_nonexistent_key_is_idempotent() {
    let (s3_client, aws_client) = create_test_s3_client().await;
    ensure_bucket_exists(&aws_client).await;

    let nonexistent_key = "test/never-existed.txt";

    // Delete should succeed even if key doesn't exist (S3 delete_object is idempotent)
    let result = s3_client.delete(TEST_BUCKET, nonexistent_key).await;
    assert!(result.is_ok(), "Delete of nonexistent key should succeed");
}
