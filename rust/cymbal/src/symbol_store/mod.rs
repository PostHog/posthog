use std::sync::Arc;

use axum::async_trait;

use ::sourcemap::SourceMap;
use reqwest::Url;

use crate::error::Error;

pub mod caching;
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
    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Self::Fetched, Error>;
}

#[async_trait]
pub trait Parser: Send + Sync + 'static {
    type Source;
    type Set;
    async fn parse(&self, data: Self::Source) -> Result<Self::Set, Error>;
}

#[async_trait]
pub trait Provider: Send + Sync + 'static {
    type Ref;
    type Set;

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Error>;
}

pub struct Catalog {
    // "source map provider"
    pub smp: Box<dyn Provider<Ref = Url, Set = SourceMap>>,
}

impl Catalog {
    pub fn new(smp: impl Provider<Ref = Url, Set = SourceMap>) -> Self {
        Self { smp: Box::new(smp) }
    }
}

#[async_trait]
impl SymbolCatalog<Url, SourceMap> for Catalog {
    async fn lookup(&self, team_id: i32, r: Url) -> Result<Arc<SourceMap>, Error> {
        self.smp.lookup(team_id, r).await
    }
}

#[async_trait]
impl<T> Provider for T
where
    T: Fetcher + Parser<Source = T::Fetched>,
    T::Ref: Send,
    T::Fetched: Send,
{
    type Ref = T::Ref;
    type Set = T::Set;

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Error> {
        let fetched = self.fetch(team_id, r).await?;
        let parsed = self.parse(fetched).await?;
        Ok(Arc::new(parsed))
    }
}
