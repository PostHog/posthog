//! Common S3 client abstraction for PostHog Rust services
//!
//! This crate provides a simple wrapper around AWS S3 operations
//! that enables testing with mocks and consistent error handling across services.
//!
//! Follows the common-redis pattern: trait-based design with manual mock implementation
//! that's always available for testing.

use async_trait::async_trait;
use aws_sdk_s3::Client as AwsS3SdkClient;
use std::collections::HashMap;
use thiserror::Error;

#[derive(Error, Debug, Clone, PartialEq, Eq)]
pub enum S3Error {
    #[error("Object not found: {0}")]
    NotFound(String),
    #[error("S3 operation failed: {0}")]
    OperationFailed(String),
    #[error("Parse error: {0}")]
    ParseError(String),
}

impl From<aws_sdk_s3::Error> for S3Error {
    fn from(err: aws_sdk_s3::Error) -> Self {
        S3Error::OperationFailed(err.to_string())
    }
}

impl From<std::string::FromUtf8Error> for S3Error {
    fn from(err: std::string::FromUtf8Error) -> Self {
        S3Error::ParseError(err.to_string())
    }
}

/// S3 client trait that both real and mock implementations use
#[async_trait]
pub trait S3Client: Send + Sync {
    /// Get an object from S3 as a UTF-8 string
    async fn get_string(&self, bucket: &str, key: &str) -> Result<String, S3Error>;
}

/// Real S3 client implementation
pub struct S3Impl {
    client: AwsS3SdkClient,
}

impl S3Impl {
    pub fn new(client: AwsS3SdkClient) -> Self {
        Self { client }
    }
}

#[async_trait]
impl S3Client for S3Impl {
    /// Get an object from S3 as a UTF-8 string
    async fn get_string(&self, bucket: &str, key: &str) -> Result<String, S3Error> {
        let get_object_output = self
            .client
            .get_object()
            .bucket(bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| {
                let error_message = format!("Failed to get object from S3: {e}");
                if let aws_sdk_s3::operation::get_object::GetObjectError::NoSuchKey(_) =
                    e.into_service_error()
                {
                    S3Error::NotFound(key.to_string())
                } else {
                    S3Error::OperationFailed(error_message)
                }
            })?;

        let body_bytes =
            get_object_output.body.collect().await.map_err(|e| {
                S3Error::OperationFailed(format!("Failed to read S3 object body: {e}"))
            })?;

        // Convert directly from AggregatedBytes to String without intermediate Vec<u8>
        let body_str = String::from_utf8(body_bytes.to_vec())
            .map_err(|e| S3Error::ParseError(format!("S3 object body is not valid UTF-8: {e}")))?;
        Ok(body_str)
    }
}

/// Mock S3 client for testing - always available, no conditional compilation needed
#[derive(Clone, Default)]
pub struct MockS3Client {
    get_string_responses: HashMap<String, Result<String, S3Error>>,
}

impl MockS3Client {
    pub fn new() -> Self {
        Self::default()
    }

    /// Set up a response for get_string() - takes bucket and key as separate parameters for easier testing
    pub fn get_string_ret(
        mut self,
        bucket: &str,
        key: &str,
        response: Result<String, S3Error>,
    ) -> Self {
        let cache_key = format!("{bucket}:{key}");
        self.get_string_responses.insert(cache_key, response);
        self
    }
}

#[async_trait]
impl S3Client for MockS3Client {
    async fn get_string(&self, bucket: &str, key: &str) -> Result<String, S3Error> {
        let cache_key = format!("{bucket}:{key}");
        match self.get_string_responses.get(&cache_key) {
            Some(response) => response.clone(),
            None => Err(S3Error::NotFound(key.to_string())),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_mock_s3_client_get_string_success() {
        let client = MockS3Client::new().get_string_ret(
            "test-bucket",
            "test-key",
            Ok("test-content".to_string()),
        );

        let result = client.get_string("test-bucket", "test-key").await;
        assert_eq!(result.unwrap(), "test-content");
    }

    #[tokio::test]
    async fn test_mock_s3_client_get_string_not_found() {
        let client = MockS3Client::new().get_string_ret(
            "test-bucket",
            "test-key",
            Err(S3Error::NotFound("test-key".to_string())),
        );

        let result = client.get_string("test-bucket", "test-key").await;
        assert!(matches!(result, Err(S3Error::NotFound(_))));
    }

    #[tokio::test]
    async fn test_mock_s3_client_default_not_found() {
        let client = MockS3Client::new();

        // Should return NotFound for any key not explicitly configured
        let result = client.get_string("test-bucket", "nonexistent-key").await;
        assert!(matches!(result, Err(S3Error::NotFound(_))));
    }

    #[tokio::test]
    async fn test_s3_error_from_utf8_error() {
        let utf8_error = String::from_utf8(vec![0, 159, 146, 150]).unwrap_err();
        let s3_error = S3Error::from(utf8_error);
        assert!(matches!(s3_error, S3Error::ParseError(_)));
    }
}
