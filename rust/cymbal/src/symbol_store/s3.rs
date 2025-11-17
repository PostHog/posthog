use aws_sdk_s3::{error::SdkError, primitives::ByteStream, Client as S3Client, Error as S3Error};
#[cfg(test)]
use mockall::automock;
use tracing::error;

use crate::{
    error::UnhandledError,
    metric_consts::{S3_FETCH, S3_PUT},
};

// We wrap the s3 client to allow us to use mocks for testing. We only expose the functionality
// we need.
#[allow(dead_code)]
pub struct S3Impl {
    inner: S3Client,
}

#[cfg_attr(test, automock)]
impl S3Impl {
    #[allow(dead_code)]
    pub fn new(inner: S3Client) -> Self {
        Self { inner }
    }

    #[allow(dead_code)]
    pub async fn get(&self, bucket: &str, key: &str) -> Result<Option<Vec<u8>>, UnhandledError> {
        let start = common_metrics::timing_guard(S3_FETCH, &[]);
        let res = self.inner.get_object().bucket(bucket).key(key).send().await;

        match res {
            Ok(res) => {
                let data = res.body.collect().await?;
                start.label("outcome", "success").fin();
                Ok(Some(data.to_vec()))
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

    #[allow(dead_code)]
    pub async fn put(&self, bucket: &str, key: &str, data: Vec<u8>) -> Result<(), UnhandledError> {
        let start = common_metrics::timing_guard(S3_PUT, &[]);
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

        start
            .label("outcome", if res.is_ok() { "success" } else { "failure" })
            .fin();
        res
    }

    // Simply assert we can do a ListBucket operation, returning an error if not. This is
    // useful during app startup to ensure the bucket is accessible.
    #[allow(dead_code)]
    pub async fn ping_bucket(&self, bucket: &str) -> Result<(), UnhandledError> {
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
