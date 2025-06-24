use anyhow::Error;
use async_trait::async_trait;

pub mod date_range_export;
pub mod folder;
pub mod s3;
pub mod url_list;

#[async_trait]
pub trait DataSource: Sync + Send {
    async fn keys(&self) -> Result<Vec<String>, Error>;
    async fn size(&self, key: &str) -> Result<Option<u64>, Error>;
    async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error>;

    // life cycle methods that support preparing and cleaning up resources for job/keys
    // no op by default
    async fn prepare_key(&self, _key: &str) -> Result<(), Error> {
        Ok(())
    }

    async fn cleanup_key(&self, _key: &str) -> Result<(), Error> {
        Ok(())
    }

    async fn prepare_for_job(&self) -> Result<(), Error> {
        Ok(())
    }
    async fn cleanup_after_job(&self) -> Result<(), Error> {
        Ok(())
    }
}
