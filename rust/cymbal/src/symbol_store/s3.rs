use aws_sdk_s3::{primitives::ByteStream, Client as S3Client, Error as S3Error};
#[cfg(test)]
use mockall::automock;

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
    pub async fn get(&self, bucket: &str, key: &str) -> Result<Vec<u8>, UnhandledError> {
        let start = common_metrics::timing_guard(S3_FETCH, &[]);
        let res = self.inner.get_object().bucket(bucket).key(key).send().await;

        if let Ok(res) = res {
            let data = res.body.collect().await?;
            start.label("outcome", "success").fin();
            return Ok(data.to_vec());
        }
        start.label("outcome", "failure").fin();

        // Note that we're not handling the "object not found" case here, because if we
        // got a key from the DB, we should have the object in S3
        Err(S3Error::from(res.unwrap_err()).into())
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
}
