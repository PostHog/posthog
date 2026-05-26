use std::sync::Arc;

use async_trait::async_trait;
use reqwest::Url;

use crate::{
    apple::{AppleRef, ParsedAppleSymbols},
    chunk_id::OrChunkId,
    hermesmap::{HermesRef, ParsedHermesMap},
    proguard::{FetchedMapping, ProguardRef},
    sourcemap::OwnedSourceMapCache,
    Provider, ResolveError,
};

#[async_trait]
pub trait SymbolCatalog<Ref, Set>: Send + Sync + 'static {
    // TODO - this doesn't actually need to return an Arc, but it does for now, because I'd
    // need to re-write the cache to let it return &'s instead, and the Arc overhead is not
    // going to be super critical right now
    async fn lookup(&self, team_id: i32, r: Ref) -> Result<Arc<Set>, ResolveError>;
}

pub type SourcemapProviderStack =
    dyn Provider<Ref = OrChunkId<Url>, Set = OwnedSourceMapCache, Err = ResolveError>;
pub type HermesMapProviderStack =
    dyn Provider<Ref = OrChunkId<HermesRef>, Set = ParsedHermesMap, Err = ResolveError>;
pub type ProguardProviderStack =
    dyn Provider<Ref = OrChunkId<ProguardRef>, Set = FetchedMapping, Err = ResolveError>;
pub type AppleProviderStack =
    dyn Provider<Ref = OrChunkId<AppleRef>, Set = ParsedAppleSymbols, Err = ResolveError>;

pub struct Catalog {
    // "source map provider"
    pub smp: Box<SourcemapProviderStack>,
    // Hermes map provider
    pub hmp: Box<HermesMapProviderStack>,
    // Proguard map provider
    pub pg: Box<ProguardProviderStack>,
    // Apple dSYM provider
    pub apple: Box<AppleProviderStack>,
}

impl Catalog {
    pub fn new(
        smp: impl Provider<Ref = OrChunkId<Url>, Set = OwnedSourceMapCache, Err = ResolveError>,
        hmp: impl Provider<Ref = OrChunkId<HermesRef>, Set = ParsedHermesMap, Err = ResolveError>,
        pg: impl Provider<Ref = OrChunkId<ProguardRef>, Set = FetchedMapping, Err = ResolveError>,
        apple: impl Provider<Ref = OrChunkId<AppleRef>, Set = ParsedAppleSymbols, Err = ResolveError>,
    ) -> Self {
        Self {
            smp: Box::new(smp),
            hmp: Box::new(hmp),
            pg: Box::new(pg),
            apple: Box::new(apple),
        }
    }
}

#[async_trait]
impl SymbolCatalog<Url, OwnedSourceMapCache> for Catalog {
    async fn lookup(&self, team_id: i32, r: Url) -> Result<Arc<OwnedSourceMapCache>, ResolveError> {
        let r = OrChunkId::inner(r);
        self.smp.lookup(team_id, r).await
    }
}

#[async_trait]
impl SymbolCatalog<OrChunkId<Url>, OwnedSourceMapCache> for Catalog {
    async fn lookup(
        &self,
        team_id: i32,
        r: OrChunkId<Url>,
    ) -> Result<Arc<OwnedSourceMapCache>, ResolveError> {
        self.smp.lookup(team_id, r).await
    }
}

#[async_trait]
impl SymbolCatalog<OrChunkId<HermesRef>, ParsedHermesMap> for Catalog {
    async fn lookup(
        &self,
        team_id: i32,
        r: OrChunkId<HermesRef>,
    ) -> Result<Arc<ParsedHermesMap>, ResolveError> {
        self.hmp.lookup(team_id, r).await
    }
}

#[async_trait]
impl SymbolCatalog<OrChunkId<ProguardRef>, FetchedMapping> for Catalog {
    async fn lookup(
        &self,
        team_id: i32,
        r: OrChunkId<ProguardRef>,
    ) -> Result<Arc<FetchedMapping>, ResolveError> {
        self.pg.lookup(team_id, r).await
    }
}

#[async_trait]
impl SymbolCatalog<OrChunkId<AppleRef>, ParsedAppleSymbols> for Catalog {
    async fn lookup(
        &self,
        team_id: i32,
        r: OrChunkId<AppleRef>,
    ) -> Result<Arc<ParsedAppleSymbols>, ResolveError> {
        self.apple.lookup(team_id, r).await
    }
}
