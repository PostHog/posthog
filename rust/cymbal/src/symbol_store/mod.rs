use std::sync::Arc;

use ::sourcemap::SourceMap;
use axum::async_trait;
use caching::{CacheInner, CachingProvider};
use reqwest::Url;
use sourcemap::SourcemapProvider;
use tokio::sync::Mutex;

use crate::error::Error;

pub mod caching;
pub mod sourcemap;

pub trait SymbolCatlog<Ref, Set>: Send + Sync + 'static {
    fn get(&self) -> &dyn SymbolProvider<Ref = Ref, Set = Set>;
}

#[async_trait]
pub trait SymbolProvider: Send + Sync + 'static {
    type Ref;
    type Set;
    // Symbol stores return an Arc, to allow them to cache (and evict) without any consent from callers
    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Error>;
}

pub struct Catalog {
    pub sourcemap: CachingProvider<SourcemapProvider>,
    pub cache: Arc<Mutex<CacheInner>>,
}

impl Catalog {
    pub fn new(max_bytes: usize, sourcemap: SourcemapProvider) -> Self {
        let cache = Arc::new(Mutex::new(CacheInner::new(max_bytes)));
        let sourcemap = CachingProvider::new(max_bytes, sourcemap, cache.clone());

        Self { sourcemap, cache }
    }
}

impl SymbolCatlog<Url, SourceMap> for Catalog {
    fn get(&self) -> &dyn SymbolProvider<Ref = Url, Set = SourceMap> {
        &self.sourcemap
    }
}
