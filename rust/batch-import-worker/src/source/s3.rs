use anyhow::Error;
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
            let output = cmd.send().await?;
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

    async fn size(&self, key: &str) -> Result<usize, Error> {
        let head = self
            .client
            .head_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await?;

        let Some(size) = head.content_length else {
            return Err(Error::msg(format!("No content length for key {}", key)));
        };

        Ok(size as usize)
    }

    async fn get_chunk(&self, key: &str, offset: usize, size: usize) -> Result<Vec<u8>, Error> {
        let get = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .range(format!("bytes={}-{}", offset, offset + size - 1))
            .send()
            .await?;

        let data = get.body.collect().await?;

        Ok(data.to_vec())
    }
}
