use std::sync::Arc;

use crate::symbol_store::Catalog;

// Will make requests to internal cluster endpoints to resolve symbols in batch
pub struct RemoteSymbolResolver {
    catalog: Arc<Catalog>,
}

impl RemoteSymbolResolver {
    pub fn new(catalog: Arc<Catalog>) -> Self {
        Self { catalog }
    }
}
