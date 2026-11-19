use std::fmt::Display;

use async_trait::async_trait;
use bytes::Bytes;

use posthog_symbol_data::{read_symbol_data_with_byte_count_limited, AppleDsym};

use crate::{
    core::config::ResolverConfig,
    error::{AppleError, ResolveError, UnhandledError},
    symbolication::symbol_store::{native::ParsedNativeSymbols, Fetcher, ParsePermit, Parser},
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
            )
            .map(|(dsym, bytes)| (dsym.data, bytes));
            // Map shared native parse errors onto AppleError so stored failure
            // reasons for apple symbol sets keep their existing shape.
            ParsedNativeSymbols::from_container(container, &source, max_extracted_bytes, "apple")
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
