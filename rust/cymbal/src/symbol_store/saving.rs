use aws_sdk_s3::{primitives::ByteStream, Client as S3Client, Error as S3Error};
use axum::async_trait;

use crate::error::Error;

use super::Fetcher;

pub struct Saving<F> {
    inner: F,
    s3_client: S3Client,
    bucket: String,
    prefix: String,
}

impl<F> Saving<F> {
    fn add_prefix(&self, key: String) -> String {
        format!("{}/{}", self.prefix, key)
    }
}

impl<F> Saving<F>
where
    F: Fetcher,
    F::Ref: ToString,
{
    pub async fn get_key(&self, _team_id: i32, r: &F::Ref) -> Result<Option<String>, Error> {
        // TODO - this should hit PG to get the object key
        Ok(Some(self.add_prefix(r.to_string())))
    }

    pub async fn save(&self, _team_id: i32, r: &F::Ref, data: Vec<u8>) -> Result<String, Error> {
        // TODO - write a record to PG, and get back an opaque key
        let key = self.add_prefix(r.to_string());
        self.store_in_s3(key.clone(), data).await?;
        Ok(key)
    }

    pub async fn fetch_from_s3(&self, key: String) -> Result<Vec<u8>, Error> {
        let res = self
            .s3_client
            .get_object()
            .bucket(&self.bucket)
            .key(&key)
            .send()
            .await;

        if let Ok(res) = res {
            let data = res.body.collect().await?;
            return Ok(data.to_vec());
        }

        // Note that we're not handling the "object not found" case here, because if we
        // got a key from the DB, we should have the object in S3
        Err(S3Error::from(res.unwrap_err()).into())
    }

    pub async fn store_in_s3(&self, key: String, data: Vec<u8>) -> Result<(), Error> {
        // TODO - lifecycle stuff I guess? Idk
        self.s3_client
            .put_object()
            .bucket(&self.bucket)
            .key(&key)
            .body(ByteStream::from(data))
            .send()
            .await
            .map_err(|e| S3Error::from(e).into())
            .map(|_| ()) // We don't care about the result as long as it's success
    }
}

#[async_trait]
impl<F> Fetcher for Saving<F>
where
    F: Fetcher + Send + Sync + 'static,
    F::Ref: ToString + Send,
{
    type Ref = F::Ref;

    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Vec<u8>, Error> {
        if let Some(s3_key) = self.get_key(team_id, &r).await? {
            return self.fetch_from_s3(s3_key).await; // We have a record for this symbol set data, so grab it from s3
        }

        // We have no record, so we need to hit the underlying fetcher, and then save it to s3
        let data = self.inner.fetch(team_id, r).await?;

        self.save(team_id, &r, data).await?;

        let e: S3Error = res.unwrap_err().into(); // Safe - see above
    }
}
