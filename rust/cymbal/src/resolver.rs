use crate::{
    error::Error,
    traits::{Resolver, SymbolStore},
    types::frames::{Frame, RawFrame},
};
use axum::async_trait;
use sourcemap::SourceMap;

pub struct ResolverImpl {
    pub store: Box<dyn SymbolStore>,
}

#[async_trait]
impl Resolver for ResolverImpl {
    async fn resolve(&self, raw: RawFrame, team_id: i32) -> Result<Frame, Error> {
        let source_ref = raw.source_ref(team_id);
        let source = self.store.fetch(source_ref).await?;

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
