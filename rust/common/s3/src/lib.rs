//! Common S3 client abstraction for PostHog Rust services
//!
//! This crate provides a simple wrapper around AWS S3 operations
//! that enables testing with mocks and consistent error handling across services.

use async_trait::async_trait;
use aws_sdk_s3::primitives::ByteStream;
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
        S3Error::OperationFailed(format_with_source_chain(&err))
    }
}

/// Walk an error's source chain and join each layer with ": ".
///
/// AWS SDK errors implement `Display` tersely (e.g. `SdkError`'s top-level message is
/// "service error" / "dispatch failure"). The actionable detail — HTTP status, error code,
/// signature/permission failure — only lives in the `source()` chain. Without walking
/// it, every `OperationFailed` collapses to the same uninformative string.
fn format_with_source_chain(err: &dyn std::error::Error) -> String {
    let mut msg = err.to_string();
    let mut src = err.source();
    while let Some(e) = src {
        msg.push_str(": ");
        msg.push_str(&e.to_string());
        src = e.source();
    }
    msg
}

fn op_failed(prefix: &str, err: &dyn std::error::Error) -> S3Error {
    S3Error::OperationFailed(format!("{prefix}: {}", format_with_source_chain(err)))
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

    /// Put a UTF-8 string as an object in S3
    async fn put_string(&self, bucket: &str, key: &str, value: &str) -> Result<(), S3Error>;

    /// Delete an object from S3 (idempotent — does not error if key is missing)
    async fn delete(&self, bucket: &str, key: &str) -> Result<(), S3Error>;
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
                let svc_err = e.into_service_error();
                if matches!(
                    svc_err,
                    aws_sdk_s3::operation::get_object::GetObjectError::NoSuchKey(_)
                ) {
                    S3Error::NotFound(key.to_string())
                } else {
                    op_failed("Failed to get object from S3", &svc_err)
                }
            })?;

        let body_bytes = get_object_output
            .body
            .collect()
            .await
            .map_err(|e| op_failed("Failed to read S3 object body", &e))?;

        let body_str = String::from_utf8(body_bytes.to_vec())
            .map_err(|e| S3Error::ParseError(format!("S3 object body is not valid UTF-8: {e}")))?;
        Ok(body_str)
    }

    async fn put_string(&self, bucket: &str, key: &str, value: &str) -> Result<(), S3Error> {
        self.client
            .put_object()
            .bucket(bucket)
            .key(key)
            .body(ByteStream::from(value.to_owned().into_bytes()))
            .send()
            .await
            .map_err(|e| op_failed("Failed to put object to S3", &e))?;
        Ok(())
    }

    async fn delete(&self, bucket: &str, key: &str) -> Result<(), S3Error> {
        self.client
            .delete_object()
            .bucket(bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| op_failed("Failed to delete object from S3", &e))?;
        Ok(())
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

    #[test]
    fn test_format_with_source_chain_single_layer() {
        let err = anyhow::anyhow!("top");
        assert_eq!(format_with_source_chain(err.as_ref()), "top");
    }

    #[test]
    fn test_format_with_source_chain_walks_full_chain() {
        // anyhow's `.context()` wraps the previous error as `source`, so the outermost
        // context becomes the head of the chain — the same shape AWS SDK errors produce.
        let err = anyhow::anyhow!("AccessDenied: User is not authorized")
            .context("PutObjectError")
            .context("service error");
        assert_eq!(
            format_with_source_chain(err.as_ref()),
            "service error: PutObjectError: AccessDenied: User is not authorized"
        );
    }
}
