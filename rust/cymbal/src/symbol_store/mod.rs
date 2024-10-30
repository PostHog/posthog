use std::sync::Arc;

use axum::async_trait;
use caching::SymbolSetCache;

use ::sourcemap::SourceMap;
use reqwest::Url;
use sourcemap::SourcemapProvider;
use tokio::sync::Mutex;

use crate::error::Error;

pub mod caching;
pub mod saving;
pub mod sourcemap;

#[async_trait]
pub trait SymbolCatalog<Ref, Set>: Send + Sync + 'static {
    // TODO - this doesn't actually need to return an Arc, but it does for now, because I'd
    // need to re-write the cache to let it return &'s instead, and the Arc overhead is not
    // going to be per critical right now
    async fn lookup(&self, team_id: i32, r: Ref) -> Result<Arc<Set>, Error>;
}

#[async_trait]
pub trait Fetcher: Send + Sync + 'static {
    type Ref;
    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Vec<u8>, Error>;
}

pub trait Parser: Send + Sync + 'static {
    type Set;
    fn parse(&self, data: Vec<u8>) -> Result<Self::Set, Error>;
}

pub struct Catalog {
    pub cache: Mutex<SymbolSetCache>,
    pub sourcemap: SourcemapProvider,
}

impl Catalog {
    pub fn new(max_bytes: usize, sourcemap: SourcemapProvider) -> Self {
        let cache = Mutex::new(SymbolSetCache::new(max_bytes));
        Self { sourcemap, cache }
    }
}

#[async_trait]
impl SymbolCatalog<Url, SourceMap> for Catalog {
    async fn lookup(&self, team_id: i32, r: Url) -> Result<Arc<SourceMap>, Error> {
        let mut cache = self.cache.lock().await;
        let cache_key = format!("{}:{}", team_id, r);
        if let Some(set) = cache.get(&cache_key) {
            return Ok(set);
        }
        let fetched = self.sourcemap.fetch(team_id, r).await?;
        let bytes = fetched.len();
        let parsed = self.sourcemap.parse(fetched)?;
        let parsed = Arc::new(parsed);
        cache.insert(cache_key, parsed.clone(), bytes);
        Ok(parsed)
    }
}
