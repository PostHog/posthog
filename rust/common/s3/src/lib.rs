//! Common S3 client abstraction for PostHog Rust services
//!
//! This crate provides a simple wrapper around AWS S3 operations
//! that enables testing with mocks and consistent error handling across services.

use async_trait::async_trait;
use aws_sdk_s3::Client as AwsS3SdkClient;
use thiserror::Error;

#[cfg(feature = "mock-client")]
use mockall::automock;

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
#[cfg_attr(feature = "mock-client", automock)]
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

#[cfg(test)]
mod tests {
    use super::*;

    // Integration tests in tests/integration_tests.rs verify real S3/MinIO functionality
    // Unit tests here use the auto-generated MockS3Client from #[automock]

    #[tokio::test]
    async fn test_s3_error_from_utf8_error() {
        let utf8_error = String::from_utf8(vec![0, 159, 146, 150]).unwrap_err();
        let s3_error = S3Error::from(utf8_error);
        assert!(matches!(s3_error, S3Error::ParseError(_)));
    }
}
