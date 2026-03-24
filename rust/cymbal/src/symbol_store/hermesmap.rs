use async_trait::async_trait;
use posthog_symbol_data::{read_symbol_data_with_byte_count, HermesMap};

use crate::{
    error::{HermesError, ResolveError},
    langs::hermes::HermesRef,
    symbol_store::{caching::Countable, Fetcher, Parser},
};

pub struct ParsedHermesMap {
    pub map: sourcemap::SourceMapHermes,
    /// Decompressed byte count from the symbol_data container, used for cache memory accounting.
    decompressed_bytes: usize,
}

impl Countable for ParsedHermesMap {
    fn byte_count(&self) -> usize {
        self.decompressed_bytes
    }
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
        let (map, decompressed_bytes): (HermesMap, usize) =
            read_symbol_data_with_byte_count(source).map_err(HermesError::DataError)?;
        Ok(ParsedHermesMap::parse(map, decompressed_bytes)?)
    }
}

impl ParsedHermesMap {
    pub fn parse(
        map: HermesMap,
        decompressed_bytes: usize,
    ) -> Result<ParsedHermesMap, HermesError> {
        Ok(ParsedHermesMap {
            map: sourcemap::SourceMapHermes::from_reader(map.sourcemap.as_bytes())
                .map_err(|e| HermesError::InvalidMap(e.to_string()))?,
            decompressed_bytes,
        })
    }
}
