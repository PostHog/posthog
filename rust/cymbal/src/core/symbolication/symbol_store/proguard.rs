use std::fmt::Display;

use async_trait::async_trait;
use bytes::Bytes;
use posthog_symbol_data::{read_symbol_data_with_byte_count, ProguardMapping};

use crate::{
    error::{ProguardError, ResolveError, UnhandledError},
    metric_consts::SYMBOL_SET_DECOMPRESSED_BYTES,
    symbolication::symbol_store::{caching::Countable, Fetcher, Parser},
};

pub struct FetchedMapping {
    cache_bytes: Vec<u8>,
}

impl Countable for FetchedMapping {
    fn byte_count(&self) -> usize {
        self.cache_bytes.len()
    }
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
    type Fetched = Bytes;
    type Err = ResolveError;

    async fn fetch(&self, _: i32, _: ProguardRef) -> Result<Bytes, Self::Err> {
        unreachable!("ProguardRef is impossible to construct, so cannot be passed")
    }
}

#[async_trait]
impl Parser for ProguardProvider {
    type Source = Bytes;
    type Set = FetchedMapping;
    type Err = ResolveError;

    async fn parse(&self, source: Self::Source) -> Result<FetchedMapping, ResolveError> {
        // zstd decompress + ProguardCache::write are CPU-bound; offload from the tokio
        // runtime so a large mapping doesn't block other in-flight requests.
        tokio::task::spawn_blocking(move || -> Result<FetchedMapping, ResolveError> {
            let (map, decompressed_bytes): (ProguardMapping, usize) =
                read_symbol_data_with_byte_count(&source).map_err(ProguardError::DataError)?;
            metrics::histogram!(SYMBOL_SET_DECOMPRESSED_BYTES, "kind" => "proguard")
                .record(decompressed_bytes as f64);
            Ok(FetchedMapping::new(map, decompressed_bytes)?)
        })
        .await
        .map_err(|e| UnhandledError::Other(format!("proguard parse task failed: {e}")))?
    }
}

impl FetchedMapping {
    pub fn new(inner: ProguardMapping, _decompressed_bytes: usize) -> Result<Self, ProguardError> {
        let mapping = proguard::ProguardMapping::new(inner.content.as_bytes());
        if !mapping.is_valid() {
            return Err(ProguardError::InvalidMapping);
        }

        let mut cache_bytes = Vec::new();
        proguard::ProguardCache::write(&mapping, &mut cache_bytes)
            .map_err(|_| ProguardError::InvalidMapping)?;
        proguard::ProguardCache::parse(&cache_bytes).map_err(|_| ProguardError::InvalidMapping)?;

        Ok(Self { cache_bytes })
    }

    pub fn get_cache<'a>(&'a self) -> Result<proguard::ProguardCache<'a>, ProguardError> {
        proguard::ProguardCache::parse(&self.cache_bytes).map_err(|_| ProguardError::InvalidMapping)
    }

    pub fn remap_class(&self, class: &str) -> Result<Option<String>, ProguardError> {
        Ok(self
            .get_cache()?
            .remap_class(class)
            .map(ToString::to_string))
    }
}

impl Display for ProguardRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "ProguardRef")
    }
}

#[cfg(test)]
mod tests {
    use posthog_symbol_data::write_symbol_data;

    use super::*;

    const PROGUARD_MAP: &str =
        include_str!("../../../../tests/static/proguard/mapping_example.txt");

    #[test]
    fn fetched_mapping_uses_proguard_cache_for_lookups() {
        let source = write_symbol_data(ProguardMapping {
            content: PROGUARD_MAP.to_string(),
        })
        .unwrap();
        let (mapping, byte_count): (ProguardMapping, usize) =
            read_symbol_data_with_byte_count(&source).unwrap();
        let fetched = FetchedMapping::new(mapping, byte_count).unwrap();

        assert_eq!(
            fetched.remap_class("a1.c").unwrap(),
            Some("com.posthog.android.sample.MyCustomException3".to_string())
        );

        let cache = fetched.get_cache().unwrap();
        let frame = proguard::StackFrame::with_file("a1.d", "onClick", 14, "SourceFile");
        let remapped: Vec<_> = cache.remap_frame(&frame).collect();

        assert!(remapped.iter().any(|frame| {
            frame.class() == "com.posthog.android.sample.MyCustomException3"
                && frame.method() == "<init>"
        }));
    }
}
