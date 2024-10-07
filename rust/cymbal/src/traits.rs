use axum::async_trait;

use crate::{
    error::Error,
    types::frames::{Frame, RawFrame},
};

#[async_trait]
pub trait Resolver {
    // Resolvers work on a per-frame basis, so we can be clever about the order
    // in which we resolve them. We also force any resolver to handle all frame
    // types
    async fn resolve(&self, raw: RawFrame) -> Result<Frame, Error>;
}

#[async_trait]
pub trait SymbolStore {
    async fn fetch(&self, r: SymbolSetRef) -> Result<Vec<u8>, Error>;
}

pub struct SymbolSetRef {
    team_id: i32,
    id: String,
}
