use async_trait::async_trait;
use bytes::Bytes;
use posthog_symbol_data::{read_symbol_data_with_byte_count, HermesMap};
use serde::Deserialize;

use crate::{
    error::{HermesError, ResolveError, UnhandledError},
    langs::hermes::HermesRef,
    metric_consts::SYMBOL_SET_DECOMPRESSED_BYTES,
    symbolication::symbol_store::{caching::Countable, Fetcher, Parser},
};

pub struct ParsedHermesMap {
    pub(crate) map: ParsedHermesSourceMap,
    /// Decompressed byte count from the symbol_data container, used for cache memory accounting.
    decompressed_bytes: usize,
}

pub(crate) enum ParsedHermesSourceMap {
    WithScopes(sourcemap::SourceMapHermes),
    LocationOnly(sourcemap::SourceMap),
}

impl ParsedHermesSourceMap {
    pub fn lookup_token(&self, line: u32, column: u32) -> Option<sourcemap::Token<'_>> {
        match self {
            Self::WithScopes(map) => map.lookup_token(line, column),
            Self::LocationOnly(map) => map.lookup_token(line, column),
        }
    }

    pub fn get_original_function_name(&self, bytecode_offset: u32) -> Option<&str> {
        match self {
            Self::WithScopes(map) => map.get_original_function_name(bytecode_offset),
            Self::LocationOnly(_) => None,
        }
    }
}

#[derive(Deserialize)]
struct HermesMapMetadata {
    #[serde(default, deserialize_with = "marker_present")]
    x_hermes_function_offsets: bool,
}

fn marker_present<'de, D>(deserializer: D) -> Result<bool, D::Error>
where
    D: serde::Deserializer<'de>,
{
    serde::de::IgnoredAny::deserialize(deserializer)?;
    Ok(true)
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
        let content = map.sourcemap;
        let decoded = sourcemap::decode_slice(content.as_bytes())
            .map_err(|e| HermesError::InvalidMap(e.to_string()))?;

        let map = match decoded {
            sourcemap::DecodedMap::Hermes(map) => ParsedHermesSourceMap::WithScopes(map),
            // The CLI also accepts this Hermes marker, but rust-sourcemap classifies
            // maps without Metro's scope metadata as regular source maps.
            sourcemap::DecodedMap::Regular(map) if has_hermes_function_offsets(&content)? => {
                ParsedHermesSourceMap::LocationOnly(map)
            }
            _ => {
                return Err(HermesError::InvalidMap(
                    sourcemap::Error::IncompatibleSourceMap.to_string(),
                ));
            }
        };

        Ok(ParsedHermesMap {
            map,
            decompressed_bytes,
        })
    }
}

fn has_hermes_function_offsets(content: &str) -> Result<bool, HermesError> {
    let content = match content.as_bytes().first() {
        Some(b')' | b']' | b'}' | b'\'') => content
            .split_once('\n')
            .map(|(_, content)| content)
            .unwrap_or_default(),
        _ => content,
    };
    let metadata: HermesMapMetadata =
        serde_json::from_str(content).map_err(|e| HermesError::InvalidMap(e.to_string()))?;
    Ok(metadata.x_hermes_function_offsets)
}

#[cfg(test)]
mod tests {
    use posthog_symbol_data::HermesMap;

    use super::{ParsedHermesMap, ParsedHermesSourceMap};

    const OFFSETS_ONLY_MAP: &str =
        include_str!("../../../../tests/static/hermes/hermes_example.map");

    #[test]
    fn parses_offsets_only_map_for_location_resolution() {
        let parsed = ParsedHermesMap::parse(
            HermesMap {
                sourcemap: OFFSETS_ONLY_MAP.to_string(),
            },
            OFFSETS_ONLY_MAP.len(),
        )
        .unwrap();

        assert!(matches!(parsed.map, ParsedHermesSourceMap::LocationOnly(_)));
        let token = parsed.map.lookup_token(0, 1000).unwrap();
        assert_eq!(
            token.get_source(),
            Some("./build/android/index.android.bundle")
        );
        assert_eq!(token.get_src_line(), 49);
        assert_eq!(token.get_src_col(), 26);
        assert_eq!(parsed.map.get_original_function_name(1000), None);
    }

    #[test]
    fn rejects_regular_map_without_hermes_marker() {
        let result = ParsedHermesMap::parse(
            HermesMap {
                sourcemap: r#"{"version":3,"sources":["index.js"],"names":[],"mappings":"AAAA"}"#
                    .to_string(),
            },
            0,
        );

        assert!(result.is_err());
    }
}
