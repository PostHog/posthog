use std::fmt::Display;

use async_trait::async_trait;
use bytes::Bytes;

use posthog_symbol_data::{read_symbol_data_with_byte_count_limited, AppleDsym, SymbolDataError};

use crate::{
    core::config::ResolverConfig,
    error::{AppleError, NativeError, ResolveError, UnhandledError},
    metric_consts::SYMBOL_SET_DECOMPRESSED_BYTES,
    symbolication::symbol_store::{
        native::ParsedNativeSymbols, record_size_limit_exceeded, Fetcher, ParsePermit, Parser,
    },
};

pub struct AppleProvider {
    max_decompressed_bytes: usize,
    max_extracted_bytes: usize,
}

impl AppleProvider {
    pub fn new(config: &ResolverConfig) -> Self {
        Self {
            max_decompressed_bytes: config.symbol_set_max_decompressed_bytes.get(),
            max_extracted_bytes: config.symbol_set_max_extracted_bytes.get(),
        }
    }
}

#[derive(Debug, Clone)]
pub enum AppleRef {}

#[async_trait]
impl Fetcher for AppleProvider {
    type Ref = AppleRef;
    type Fetched = Bytes;
    type Err = ResolveError;

    async fn fetch(&self, _: i32, _: AppleRef) -> Result<Bytes, Self::Err> {
        unreachable!("AppleRef is impossible to construct, so cannot be passed")
    }
}

#[async_trait]
impl Parser for AppleProvider {
    type Source = Bytes;
    type Set = ParsedNativeSymbols;
    type Err = ResolveError;

    async fn parse(
        &self,
        source: Self::Source,
        permit: ParsePermit,
    ) -> Result<ParsedNativeSymbols, ResolveError> {
        // dSYM parsing is the heaviest CPU work in the system: zstd decompress, ZIP
        // expansion, DWARF parse, and symcache conversion. Always offload from the tokio
        // runtime.
        let max_decompressed_bytes = self.max_decompressed_bytes;
        let max_extracted_bytes = self.max_extracted_bytes;
        tokio::task::spawn_blocking(move || -> Result<ParsedNativeSymbols, ResolveError> {
            let _permit = permit;
            // Try to unwrap symbol_data container first (new format),
            // fall back to raw ZIP for backward compatibility with existing uploads.
            // TODO(2026-09-24): Remove raw ZIP fallback once all old uploads have expired.
            let container = read_symbol_data_with_byte_count_limited::<AppleDsym>(
                &source,
                max_decompressed_bytes,
            );
            let (zip_data, decompressed_bytes) = match container {
                Ok((dsym, bytes)) => (dsym.data, bytes),
                Err(e @ SymbolDataError::DecompressedTooLarge(_)) => {
                    record_size_limit_exceeded(&e, "apple");
                    return Err(AppleError::DataError(e).into());
                }
                Err(_) => {
                    let len = source.len();
                    (source.to_vec(), len)
                }
            };
            metrics::histogram!(SYMBOL_SET_DECOMPRESSED_BYTES, "kind" => "apple")
                .record(decompressed_bytes as f64);
            // Map shared native parse errors onto AppleError so stored failure
            // reasons for apple symbol sets keep their existing shape.
            ParsedNativeSymbols::from_zip_data(zip_data, decompressed_bytes, max_extracted_bytes)
                .inspect_err(|e| {
                    if let NativeError::DataError(e) = e {
                        record_size_limit_exceeded(e, "apple");
                    }
                })
                .map_err(|e| AppleError::from(e).into())
        })
        .await
        .map_err(|e| UnhandledError::Other(format!("apple dSYM parse task failed: {e}")))?
    }
}

impl Display for AppleRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "AppleRef")
    }
}
