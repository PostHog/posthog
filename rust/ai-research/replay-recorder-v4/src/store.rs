//! Object storage. Tests replace S3 at this boundary.

use async_trait::async_trait;

#[derive(Debug, thiserror::Error)]
#[error("object store write failed: {0}")]
pub struct StoreError(pub String);

#[async_trait]
pub trait BlobStore: Send + Sync {
    /// Writes an object that must not exist yet. The recorder names every object uniquely, so an existing one means
    /// the SDK retried this same write, and the first write stands.
    async fn put_new(&self, bucket: &str, key: &str, body: Vec<u8>) -> Result<(), StoreError>;
}

pub struct S3Store {
    client: aws_sdk_s3::Client,
}

impl S3Store {
    pub fn new(client: aws_sdk_s3::Client) -> Self {
        Self { client }
    }
}

#[async_trait]
impl BlobStore for S3Store {
    async fn put_new(&self, bucket: &str, key: &str, body: Vec<u8>) -> Result<(), StoreError> {
        let result = self
            .client
            .put_object()
            .bucket(bucket)
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
                    .is_some_and(|r| r.status().as_u16() == 412) =>
            {
                Ok(())
            }
            Err(error) => Err(StoreError(error.to_string())),
        }
    }
}
