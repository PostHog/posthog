use std::{path::Path, sync::Arc};

use axum::async_trait;

use crate::error::Error;

use super::SymbolProvider;

// Unimplemented sketch of how we might do s3/pg backed symbol set storing/lookup,
// for the sake of the django model being sketched out
struct InternalProvider<P> {
    provider: P,
}

impl<P> InternalProvider<P> {
    pub fn new(max_bytes: usize, provider: P) -> Self {
        Self { provider }
    }
}

#[async_trait]
impl<P> SymbolProvider for InternalProvider<P>
where
    P: SymbolProvider,
    P::Ref: ToString + Send,
{
    type Ref = P::Ref;
    type Set = P::Set;

    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Error> {
        todo!()
    }
}

pub trait ToVec {
    fn to_vec(&self) -> Vec<u8>;
}
