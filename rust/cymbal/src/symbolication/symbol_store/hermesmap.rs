use async_trait::async_trait;
use bytes::Bytes;
use posthog_symbol_data::{read_symbol_data_with_byte_count, HermesMap};

use crate::{
    error::{HermesError, ResolveError, UnhandledError},
    langs::hermes::HermesRef,
    metric_consts::SYMBOL_SET_DECOMPRESSED_BYTES,
    symbolication::symbol_store::{caching::Countable, Fetcher, Parser},
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
    type Fetched = Bytes;
    type Err = ResolveError;

    async fn fetch(&self, _: i32, _: HermesRef) -> Result<Bytes, Self::Err> {
        unreachable!("HermesRef is impossible to construct, so cannot be passed")
    }
}

#[async_trait]
impl Parser for HermesMapProvider {
    type Source = Bytes;
    type Set = ParsedHermesMap;
    type Err = ResolveError;

    async fn parse(&self, source: Bytes) -> Result<ParsedHermesMap, Self::Err> {
        // zstd decompress + Hermes sourcemap parse are both CPU-bound; offload from the
        // tokio runtime so a large bundle doesn't block other in-flight requests.
        tokio::task::spawn_blocking(move || -> Result<ParsedHermesMap, ResolveError> {
            let (map, decompressed_bytes): (HermesMap, usize) =
                read_symbol_data_with_byte_count(&source).map_err(HermesError::DataError)?;
            metrics::histogram!(SYMBOL_SET_DECOMPRESSED_BYTES, "kind" => "hermes")
                .record(decompressed_bytes as f64);
            Ok(ParsedHermesMap::parse(map, decompressed_bytes)?)
        })
        .await
        .map_err(|e| UnhandledError::Other(format!("hermes map parse task failed: {e}")))?
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
