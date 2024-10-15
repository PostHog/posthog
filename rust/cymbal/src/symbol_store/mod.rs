use std::{
    fmt::{Display, Formatter},
    sync::Arc,
};

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

// We provide this to allow for using these refs as primary keys in some arbitrary storage system,
// like s3 or a database. The result should be ~unique, per team.
impl Display for SymbolSetRef {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            SymbolSetRef::Js(url) => write!(f, "{}", url),
        }
    }
}
