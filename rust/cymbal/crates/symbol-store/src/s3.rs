use async_trait::async_trait;
use aws_sdk_s3::{error::SdkError, primitives::ByteStream, Client as S3Client, Error as S3Error};
use bytes::Bytes;
#[cfg(any(test, feature = "test-utils"))]
use mockall::automock;
use tracing::error;

use crate::SymbolStoreError;

const S3_FETCH: &str = "cymbal_s3_fetch";
const S3_FETCHED_BYTES: &str = "cymbal_s3_fetched_bytes";
const S3_PUT: &str = "cymbal_s3_put";
const S3_PUT_BYTES: &str = "cymbal_s3_put_bytes";

#[cfg_attr(any(test, feature = "test-utils"), automock)]
#[async_trait]
pub trait BlobClient: Send + Sync {
    async fn get(&self, bucket: &str, key: &str) -> Result<Option<Bytes>, SymbolStoreError>;
    async fn put(&self, bucket: &str, key: &str, data: Bytes) -> Result<(), SymbolStoreError>;
    async fn delete(&self, bucket: &str, key: &str) -> Result<(), SymbolStoreError>;
    async fn ping_bucket(&self, bucket: &str) -> Result<(), SymbolStoreError>;
}

// We wrap the s3 client to allow us to use mocks for testing. We only expose the functionality
// we need.
pub struct S3Impl {
    inner: S3Client,
}

impl S3Impl {
    pub fn new(inner: S3Client) -> Self {
        Self { inner }
    }
}

#[async_trait]
impl BlobClient for S3Impl {
    async fn get(&self, bucket: &str, key: &str) -> Result<Option<Bytes>, SymbolStoreError> {
        let start = common_metrics::timing_guard(S3_FETCH, &[]);
        let res = self.inner.get_object().bucket(bucket).key(key).send().await;

        match res {
            Ok(res) => {
                // Record the Content-Length advertised by S3 before we collect the body.
                // This is where a future size-cap check would short-circuit.
                if let Some(len) = res.content_length() {
                    if len >= 0 {
                        metrics::histogram!(S3_FETCHED_BYTES).record(len as f64);
                    }
                }
                let data = res.body.collect().await?;
                start.label("outcome", "success").fin();
                Ok(Some(data.into_bytes()))
            }
            // If this is a file not found error, return None
            Err(SdkError::ServiceError(err)) if err.err().is_no_such_key() => {
                start.label("outcome", "not_found").fin();
                Ok(None)
            }
            Err(err) => {
                // If we simply failed to talk to s3, return an error
                start.label("outcome", "failure").fin();
                error!("Failed to fetch object {} from S3: {:?}", key, err);
                Err(S3Error::from(err).into())
            }
        }
    }

    async fn put(&self, bucket: &str, key: &str, data: Bytes) -> Result<(), SymbolStoreError> {
        let start = common_metrics::timing_guard(S3_PUT, &[]);
        let data_len = data.len();
        let res = self
            .inner
            .put_object()
            .bucket(bucket)
            .key(key)
            .body(ByteStream::from(data))
            .send()
            .await
            .map_err(|e| S3Error::from(e).into())
            .map(|_| ()); // We don't care about the result as long as it's success

        // Record body size only on success, mirroring `S3_FETCHED_BYTES` which reads from
        // the GET response. Failed PUTs (auth errors, S3 unavailable, etc.) shouldn't be
        // counted toward the size distribution.
        if res.is_ok() {
            metrics::histogram!(S3_PUT_BYTES).record(data_len as f64);
        }

        start
            .label("outcome", if res.is_ok() { "success" } else { "failure" })
            .fin();
        res
    }

    async fn delete(&self, bucket: &str, key: &str) -> Result<(), SymbolStoreError> {
        self.inner
            .delete_object()
            .bucket(bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| S3Error::from(e).into())
            .map(|_| ())
    }

    // Simply assert we can do a ListBucket operation, returning an error if not. This is
    // useful during app startup to ensure the bucket is accessible.
    async fn ping_bucket(&self, bucket: &str) -> Result<(), SymbolStoreError> {
        let res = self
            .inner
            .list_objects_v2()
            .bucket(bucket)
            .prefix("")
            .send()
            .await;

        if let Err(e) = res {
            Err(S3Error::from(e).into())
        } else {
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::MockBlobClient;
    use mockall::predicate;

    #[tokio::test]
    async fn mock_blob_client_get_returns_some_bytes() {
        let mut client = MockBlobClient::default();
        client
            .expect_get()
            .with(predicate::eq("bucket"), predicate::eq("key"))
            .returning(|_, _| Ok(Some(Bytes::from_static(b"hello"))));

        let result = client.get("bucket", "key").await.unwrap();
        assert_eq!(result, Some(Bytes::from_static(b"hello")));
    }

    #[tokio::test]
    async fn mock_blob_client_get_returns_none_for_missing_key() {
        let mut client = MockBlobClient::default();
        client.expect_get().returning(|_, _| Ok(None));

        let result = client.get("bucket", "missing-key").await.unwrap();
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn mock_blob_client_put_returns_ok() {
        let mut client = MockBlobClient::default();
        client
            .expect_put()
            .with(
                predicate::eq("bucket"),
                predicate::eq("key"),
                predicate::eq(Bytes::from_static(b"data")),
            )
            .returning(|_, _, _| Ok(()));

        client
            .put("bucket", "key", Bytes::from_static(b"data"))
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn mock_blob_client_delete_returns_ok() {
        let mut client = MockBlobClient::default();
        client
            .expect_delete()
            .with(predicate::eq("bucket"), predicate::eq("key"))
            .returning(|_, _| Ok(()));

        client.delete("bucket", "key").await.unwrap();
    }

    // Verify that calling put twice with different keys invokes the mock twice.
    #[tokio::test]
    async fn mock_blob_client_put_is_called_once_per_key() {
        let mut client = MockBlobClient::default();
        client.expect_put().times(2).returning(|_, _, _| Ok(()));

        client
            .put("bucket", "key1", Bytes::from_static(b"a"))
            .await
            .unwrap();
        client
            .put("bucket", "key2", Bytes::from_static(b"b"))
            .await
            .unwrap();
    }
}
