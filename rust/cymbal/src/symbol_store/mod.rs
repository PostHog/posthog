use std::sync::Arc;

use axum::async_trait;

use chunk_id::OrChunkId;
use reqwest::Url;
use sourcemap::OwnedSourceMapCache;

use crate::{
    error::ResolveError,
    langs::hermes::HermesRef,
    symbol_store::{
        hermesmap::ParsedHermesMap,
        proguard::{FetchedMapping, ProguardRef},
    },
};

pub mod caching;
pub mod chunk_id;
pub mod concurrency;
pub mod hermesmap;
pub mod proguard;
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
    async fn lookup(&self, team_id: i32, r: Ref) -> Result<Arc<Set>, ResolveError>;
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
    pub smp: Box<dyn Provider<Ref = OrChunkId<Url>, Set = OwnedSourceMapCache, Err = ResolveError>>,
    // Hermes map provider
    pub hmp:
        Box<dyn Provider<Ref = OrChunkId<HermesRef>, Set = ParsedHermesMap, Err = ResolveError>>,
    // Proguard map provider
    pub pg:
        Box<dyn Provider<Ref = OrChunkId<ProguardRef>, Set = FetchedMapping, Err = ResolveError>>,
}

impl Catalog {
    pub fn new(
        smp: impl Provider<Ref = OrChunkId<Url>, Set = OwnedSourceMapCache, Err = ResolveError>,
        hmp: impl Provider<Ref = OrChunkId<HermesRef>, Set = ParsedHermesMap, Err = ResolveError>,
        pg: impl Provider<Ref = OrChunkId<ProguardRef>, Set = FetchedMapping, Err = ResolveError>,
    ) -> Self {
        Self {
            smp: Box::new(smp),
            hmp: Box::new(hmp),
            pg: Box::new(pg),
        }
    }
}

#[async_trait]
impl SymbolCatalog<Url, OwnedSourceMapCache> for Catalog {
    async fn lookup(&self, team_id: i32, r: Url) -> Result<Arc<OwnedSourceMapCache>, ResolveError> {
        let r = OrChunkId::inner(r);
        self.smp.lookup(team_id, r).await
    }
}

#[async_trait]
impl SymbolCatalog<OrChunkId<Url>, OwnedSourceMapCache> for Catalog {
    async fn lookup(
        &self,
        team_id: i32,
        r: OrChunkId<Url>,
    ) -> Result<Arc<OwnedSourceMapCache>, ResolveError> {
        self.smp.lookup(team_id, r).await
    }
}

#[async_trait]
impl SymbolCatalog<OrChunkId<HermesRef>, ParsedHermesMap> for Catalog {
    async fn lookup(
        &self,
        team_id: i32,
        r: OrChunkId<HermesRef>,
    ) -> Result<Arc<ParsedHermesMap>, ResolveError> {
        self.hmp.lookup(team_id, r).await
    }
}

#[async_trait]
impl SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping> for Catalog {
    async fn lookup(
        &self,
        team_id: i32,
        r: OrChunkId<ProguardRef>,
    ) -> Result<Arc<FetchedMapping>, ResolveError> {
        self.pg.lookup(team_id, r).await
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
