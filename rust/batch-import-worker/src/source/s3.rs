use crate::error::ToUserError;
use anyhow::{Context, Error};
use aws_sdk_s3::Client as S3Client;
use axum::async_trait;
use tracing::debug;

use super::DataSource;

pub struct S3Source {
    client: S3Client,
    bucket: String,
    prefix: String,
}

impl S3Source {
    pub fn new(client: S3Client, bucket: String, prefix: String) -> Self {
        Self {
            client,
            bucket,
            prefix,
        }
    }
}

// String matching hack to get around the fact that there didn't seem to be an easy way to import and handle the different error types with the aws sdk
fn extract_user_friendly_error(
    error: &dyn std::error::Error,
    bucket: &str,
    operation: &str,
) -> String {
    let error_string = format!("{error:?}");

    if error_string.contains("InvalidAccessKeyId") {
        "Invalid AWS Access Key ID - please check your credentials".to_string()
    } else if error_string.contains("SignatureDoesNotMatch") {
        "Invalid AWS Secret Access Key - please check your credentials".to_string()
    } else if error_string.contains("AccessDenied") {
        format!("Access denied to S3 bucket '{bucket}' - check your permissions",)
    } else if error_string.contains("NoSuchBucket") {
        format!("S3 bucket '{bucket}' does not exist or you don't have access to it",)
    } else if error_string.contains("InvalidBucketName") {
        format!("Invalid S3 bucket name '{bucket}'")
    } else if error_string.contains("NoSuchKey") {
        "The specified S3 object does not exist".to_string()
    } else if error_string.contains("timeout") || error_string.contains("Timeout") {
        format!(
            "S3 {operation} operation timed out - check your network connection and region settings",
        )
    } else if error_string.contains("dns") || error_string.contains("DNS") {
        "Failed to connect to S3 - check your endpoint URL and network connection".to_string()
    } else if error_string.contains("EndpointConnectionError") {
        "Failed to connect to S3 endpoint - check your endpoint URL and network connection"
            .to_string()
    } else {
        format!("S3 {operation} failed - check your credentials, bucket name, and permissions",)
    }
}

#[async_trait]
impl DataSource for S3Source {
    async fn keys(&self) -> Result<Vec<String>, Error> {
        debug!(
            "Listing keys in bucket {} with prefix {}",
            self.bucket, self.prefix
        );
        let mut keys = Vec::new();
        let mut continuation_token = None;
        loop {
            let mut cmd = self
                .client
                .list_objects_v2()
                .bucket(&self.bucket)
                .prefix(self.prefix.clone());
            if let Some(token) = continuation_token {
                cmd = cmd.continuation_token(token);
            }
            let output = cmd.send().await.or_else(|sdk_error| {
                let friendly_msg =
                    extract_user_friendly_error(&sdk_error, &self.bucket, "list objects");
                Err(sdk_error).user_error(friendly_msg)
            })?;

            debug!("Got response: {:?}", output);
            if let Some(contents) = output.contents {
                keys.extend(contents.iter().filter_map(|o| o.key.clone()));
            }
            match output.next_continuation_token {
                Some(token) => continuation_token = Some(token),
                None => break,
            }
        }
        Ok(keys)
    }

    async fn size(&self, key: &str) -> Result<Option<u64>, Error> {
        let head = self
            .client
            .head_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .or_else(|sdk_error| {
                let friendly_msg =
                    extract_user_friendly_error(&sdk_error, &self.bucket, "get object metadata");
                Err(sdk_error).user_error(friendly_msg)
            })?;

        let Some(size) = head.content_length else {
            return Err(Error::msg(format!("No content length for key {key}")));
        };

        Ok(Some(size as u64))
    }

    async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
        let range = format!("bytes={offset}-{}", offset + size - 1);
        let get = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .range(&range)
            .send()
            .await
            .or_else(|sdk_error| {
                let friendly_msg =
                    extract_user_friendly_error(&sdk_error, &self.bucket, "get object chunk");
                Err(sdk_error).user_error(friendly_msg)
            })?;

        let data = get.body.collect().await.with_context(|| {
            format!(
                "Failed to read body data from S3 object s3://{0}/{key}",
                self.bucket,
            )
        })?;

        Ok(data.to_vec())
    }
}
