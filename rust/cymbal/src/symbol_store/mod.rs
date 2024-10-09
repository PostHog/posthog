use std::sync::Arc;

use axum::async_trait;
use reqwest::Url;

use crate::error::Error;

pub mod basic;
pub mod caching;

#[async_trait]
pub trait SymbolStore: Send + Sync + 'static {
    // Symbol stores return an Arc, to allow them to cache (and evict) without any consent from callers
    async fn fetch(&self, team_id: i32, r: SymbolSetRef) -> Result<Arc<Vec<u8>>, Error>;
}

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub enum SymbolSetRef {
    Js(Url),
}
