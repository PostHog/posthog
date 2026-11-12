use std::time::Duration;

use async_trait::async_trait;
use aws_sdk_s3::error::DisplayErrorContext;

use crate::batcher::{IndexStore, StoreError};

/// A file can hold up to the sink's byte target of rows, so the upload gets this long, retries included.
const PUT_TIMEOUT: Duration = Duration::from_secs(120);
const WATERMARK_PUT_TIMEOUT: Duration = Duration::from_secs(10);

pub struct S3Store {
    client: aws_sdk_s3::Client,
    bucket: String,
}

impl S3Store {
    pub fn new(client: aws_sdk_s3::Client, bucket: String) -> Self {
        Self { client, bucket }
    }
}

async fn within<T>(
    timeout: Duration,
    request: impl std::future::Future<Output = Result<T, StoreError>>,
) -> Result<T, StoreError> {
    tokio::time::timeout(timeout, request)
        .await
        .map_err(|_| StoreError(format!("timed out after {timeout:?}")))?
}

#[async_trait]
impl IndexStore for S3Store {
    async fn put_new(&self, key: &str, body: Vec<u8>) -> Result<(), StoreError> {
        within(PUT_TIMEOUT, async {
            let result = self
                .client
                .put_object()
                .bucket(&self.bucket)
                .key(key)
                .if_none_match("*")
                .body(body.into())
                .send()
                .await;
            match result {
                Ok(_) => Ok(()),
                // 412: the SDK retried this PUT after a first try that stored the object, so it is there.
                Err(error)
                    if error
                        .raw_response()
                        .is_some_and(|response| response.status().as_u16() == 412) =>
                {
                    Ok(())
                }
                Err(error) => Err(StoreError(DisplayErrorContext(error).to_string())),
            }
        })
        .await
    }

    async fn put_json(&self, key: &str, body: Vec<u8>) -> Result<(), StoreError> {
        within(WATERMARK_PUT_TIMEOUT, async {
            self.client
                .put_object()
                .bucket(&self.bucket)
                .key(key)
                .content_type("application/json")
                .body(body.into())
                .send()
                .await
                .map(|_| ())
                .map_err(|error| StoreError(DisplayErrorContext(error).to_string()))
        })
        .await
    }
}
