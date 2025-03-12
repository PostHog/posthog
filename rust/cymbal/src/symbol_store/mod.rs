use std::sync::Arc;

use axum::async_trait;

use chunk_id::{ChunkId, WithChunkId};
use reqwest::Url;
use sourcemap::OwnedSourceMapCache;
use tracing::warn;

use crate::error::{ChunkIdError, Error};

pub mod caching;
pub mod chunk_id;
pub mod concurrency;
pub mod saving;
pub mod sourcemap;

mod s3;
#[cfg(test)]
pub use s3::MockS3Impl as S3Client;
#[cfg(not(test))]
pub use s3::S3Impl as S3Client;

#[async_trait]
pub trait SymbolCatalog<Ref, Set>: Send + Sync + 'static {
    // TODO - this doesn't actually need to return an Arc, but it does for now, because I'd
    // need to re-write the cache to let it return &'s instead, and the Arc overhead is not
    // going to be super critical right now
    async fn lookup(&self, team_id: i32, r: Ref) -> Result<Arc<Set>, Error>;
}

#[async_trait]
pub trait Fetcher: Send + Sync + 'static {
    type Ref;
    type Fetched;
    type Err;
    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Self::Fetched, Self::Err>;
}

#[async_trait]
pub trait Parser: Send + Sync + 'static {
    type Source;
    type Set;
    type Err;
    async fn parse(&self, data: Self::Source) -> Result<Self::Set, Self::Err>;
}

#[async_trait]
pub trait Provider: Send + Sync + 'static {
    type Ref;
    type Set;
    type Err;

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Self::Err>;
}

pub struct Catalog {
    // "source map provider"
    pub smp: Box<dyn Provider<Ref = Url, Set = OwnedSourceMapCache, Err = Error>>,
    pub chunk_id_smp:
        Box<dyn Provider<Ref = ChunkId, Set = OwnedSourceMapCache, Err = ChunkIdError>>,
}

impl Catalog {
    pub fn new(
        smp: impl Provider<Ref = Url, Set = OwnedSourceMapCache, Err = Error>,
        chunk_id_smp: impl Provider<Ref = ChunkId, Set = OwnedSourceMapCache, Err = ChunkIdError>,
    ) -> Self {
        Self {
            smp: Box::new(smp),
            chunk_id_smp: Box::new(chunk_id_smp),
        }
    }
}

#[async_trait]
impl SymbolCatalog<Url, OwnedSourceMapCache> for Catalog {
    async fn lookup(&self, team_id: i32, r: Url) -> Result<Arc<OwnedSourceMapCache>, Error> {
        self.smp.lookup(team_id, r).await
    }
}

#[async_trait]
impl SymbolCatalog<WithChunkId<Url>, OwnedSourceMapCache> for Catalog {
    async fn lookup(
        &self,
        team_id: i32,
        r: WithChunkId<Url>,
    ) -> Result<Arc<OwnedSourceMapCache>, Error> {
        match self.chunk_id_smp.lookup(team_id, r.chunk_id).await {
            Ok(s) => Ok(s),
            Err(ChunkIdError::Other(e)) => Err(e), // Anything not specifically a chunk id error we just return
            Err(e) => {
                // If we hit some chunk id error, we fall back to trying to fetch from the outside world
                warn!("Chunk ID lookup failed, falling back {:?}", e);
                self.lookup(team_id, r.inner).await
            }
        }
    }
}

#[async_trait]
impl<T> Provider for T
where
    T: Fetcher + Parser<Source = T::Fetched, Err = <T as Fetcher>::Err>,
    T::Ref: Send,
    T::Fetched: Send,
{
    type Ref = T::Ref;
    type Set = T::Set;
    type Err = <T as Fetcher>::Err;

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Self::Err> {
        let fetched = self.fetch(team_id, r).await?;
        let parsed = self.parse(fetched).await?;
        Ok(Arc::new(parsed))
    }
}
