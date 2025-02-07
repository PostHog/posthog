use anyhow::Error;
use aws_sdk_s3::Client as S3Client;
use axum::async_trait;

use super::DataSource;

pub struct S3Source {
    pub client: S3Client,
    pub bucket: String,
    pub prefix: String,
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
        let list = self
            .client
            .list_objects()
            .bucket(&self.bucket)
            .prefix(self.prefix.clone())
            .send()
            .await?;

        Ok(list
            .contents
            .unwrap_or_default()
            .iter()
            .filter_map(|o| o.key.clone())
            .collect())
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
