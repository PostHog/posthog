use anyhow::Error;
use async_trait::async_trait;

pub mod folder;

#[async_trait]
pub trait DataSource {
    type Output;
    async fn keys(&self) -> Result<Vec<String>, Error>;
    async fn size(&self, key: &str) -> Result<usize, Error>;
    // I take care here (and everywhere) to not treat offsets or sizes as inherently byte offsets
    // - for some data source/format combinations, the offset might be a record number or row count
    // or something.
    async fn get_chunk(&self, key: &str, offset: usize, size: usize)
        -> Result<Self::Output, Error>;
}
