use crate::{
    error::Error,
    symbol_store::SymbolStore,
    types::frames::{Frame, RawFrame},
};
use axum::async_trait;
use sourcemap::SourceMap;

#[async_trait]
pub trait Resolver {
    // Resolvers work on a per-frame basis, so we can be clever about the order
    // in which we resolve them. We also force any resolver to handle all frame
    // types
    async fn resolve(&self, raw: RawFrame, team_id: i32) -> Result<Frame, Error>;
}

pub struct ResolverImpl {
    pub store: Box<dyn SymbolStore>,
}

#[async_trait]
impl Resolver for ResolverImpl {
    async fn resolve(&self, raw: RawFrame, team_id: i32) -> Result<Frame, Error> {
        let source_ref = raw.source_ref()?;
        let source = self.store.fetch(team_id, source_ref).await?;

        // Since we only support js right now, this is all we do. Everything from here
        // is js specific
        let RawFrame::JavaScript(raw) = raw;
        let sm = SourceMap::from_reader(source.as_slice())?;
        let token = sm
            .lookup_token(raw.line, raw.column)
            .ok_or_else(|| Error::LookupFailed(String::from("Token not found")))?;
        Ok((raw, token).into())
    }
}

impl ResolverImpl {
    pub fn new(store: Box<dyn SymbolStore>) -> Self {
        Self { store }
    }
}
