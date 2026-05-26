use std::sync::Arc;

use async_trait::async_trait;

pub mod apple;
pub mod caching;
pub mod catalog;
pub mod chunk_id;
pub mod concurrency;
pub mod config;
pub mod dart_minified_names;
pub mod error;
pub mod hermesmap;
pub mod metric_consts;
pub mod proguard;
pub mod refs;
pub mod s3;
pub mod saving;
pub mod sourcemap;

pub use caching::{Caching, Countable, SymbolSetCache};
pub use catalog::{Catalog, SymbolCatalog};
pub use concurrency::AtMostOne;
pub use config::SymbolStoreConfig;
pub use dart_minified_names::parse_dart_minified_names;
pub use error::{
    AppleError, FrameError, HermesError, JsResolveErr, ProguardError, ResolveError,
    SymbolStoreError, UnhandledError,
};
pub use refs::{OrChunkId, SymbolSetCacheKey, SymbolSetKey};
#[cfg(any(test, feature = "test-utils"))]
pub use s3::MockBlobClient;
pub use s3::{BlobClient, S3Impl};

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
