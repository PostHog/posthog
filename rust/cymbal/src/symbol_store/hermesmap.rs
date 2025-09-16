use axum::async_trait;
use posthog_symbol_data::{read_symbol_data, HermesMap};

use crate::{
    error::{HermesError, ResolveError},
    langs::hermes::HermesRef,
    symbol_store::{Fetcher, Parser},
};

pub struct ParsedHermesMap {
    pub map: sourcemap::SourceMapHermes,
}

pub struct HermesMapProvider {}

#[async_trait]
impl Fetcher for HermesMapProvider {
    type Ref = HermesRef;
    type Fetched = Vec<u8>;
    type Err = ResolveError;

    async fn fetch(&self, _: i32, _: HermesRef) -> Result<Vec<u8>, Self::Err> {
        unreachable!("HermesRef is impossible to construct, so cannot be passed")
    }
}

#[async_trait]
impl Parser for HermesMapProvider {
    type Source = Vec<u8>;
    type Set = ParsedHermesMap;
    type Err = ResolveError;

    async fn parse(&self, source: Vec<u8>) -> Result<ParsedHermesMap, Self::Err> {
        let map: HermesMap = read_symbol_data(source).map_err(HermesError::DataError)?;
        Ok(ParsedHermesMap::parse(map)?)
    }
}

impl ParsedHermesMap {
    pub fn parse(map: HermesMap) -> Result<ParsedHermesMap, HermesError> {
        Ok(ParsedHermesMap {
            map: sourcemap::SourceMapHermes::from_reader(map.sourcemap.as_bytes())
                .map_err(|e| HermesError::InvalidMap(e.to_string()))?,
        })
    }
}
