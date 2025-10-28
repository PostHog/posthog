use std::fmt::Display;

use axum::async_trait;
use posthog_symbol_data::{read_symbol_data, ProguardMapping};

use crate::{
    error::{ProguardError, ResolveError},
    symbol_store::{Fetcher, Parser},
};

pub struct FetchedMapping {
    inner: ProguardMapping,
}

pub struct ProguardProvider {}

// Enum it's impossible to construct, allowing us to type-brand an OrChunkID for proguard maps specifically.
// Chunk ID's aren't injected into proguard maps and java projects the way they are in e.g. JS projects,
// instead being derived from project metadata (name, version) available at both build and run time. The SDK tags
// each frame in a java exception with this derived chunk ID, and we use the normal chunk id layer etc to fetch
// it for us
#[derive(Debug, Clone)]
pub enum ProguardRef {}

#[async_trait]
impl Fetcher for ProguardProvider {
    type Ref = ProguardRef;
    type Fetched = Vec<u8>;
    type Err = ResolveError;

    async fn fetch(&self, _: i32, _: ProguardRef) -> Result<Vec<u8>, Self::Err> {
        unreachable!("ProguardRef is impossible to construct, so cannot be passed")
    }
}

#[async_trait]
impl Parser for ProguardProvider {
    type Source = Vec<u8>;
    type Set = FetchedMapping;
    type Err = ResolveError;

    async fn parse(&self, source: Self::Source) -> Result<FetchedMapping, ResolveError> {
        let map: ProguardMapping =
            read_symbol_data(source).map_err(|e| ProguardError::DataError(e))?;
        Ok(FetchedMapping::new(map)?)
    }
}

impl FetchedMapping {
    pub fn new(inner: ProguardMapping) -> Result<Self, ProguardError> {
        // Map construction is basically free, so we hold onto the underlying data
        // and re-construct it as needed
        let mapping = proguard::ProguardMapping::new(inner.content.as_bytes());
        if !mapping.is_valid() {
            return Err(ProguardError::InvalidMapping.into());
        }
        Ok(Self { inner })
    }
}

impl Display for ProguardRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "ProguardRef")
    }
}
