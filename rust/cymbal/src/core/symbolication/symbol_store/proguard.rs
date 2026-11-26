use std::{collections::BTreeMap, fmt::Display};

use async_trait::async_trait;
use bytes::Bytes;
use posthog_symbol_data::{
    read_symbol_data_with_byte_count_limited, JvmBundle, ProguardMapping, SymbolDataError,
};

use crate::{
    core::config::ResolverConfig,
    error::{ProguardError, ResolveError, UnhandledError},
    metric_consts::SYMBOL_SET_DECOMPRESSED_BYTES,
    symbolication::symbol_store::{
        caching::Countable, record_size_limit_exceeded, Fetcher, ParsePermit, Parser,
    },
};

/// A JVM symbol set: a ProGuard mapping, the build's source files, or both. A set uploaded by
/// `posthog-cli proguard upload` holds only a mapping. A set uploaded by `posthog-cli jvm upload`
/// holds the sources of an unobfuscated build and no mapping.
pub struct FetchedMapping {
    cache_bytes: Option<Vec<u8>>,
    sources: BTreeMap<String, String>,
}

// Memory that one source entry holds beyond the bytes of its key and contents: the two `String`
// headers, its share of a B-tree node, and allocator rounding. B-tree nodes are often only half
// full, so this is about twice the 48 bytes of the headers. Without it, a bundle of many empty
// files reports almost no bytes, and the cache keeps far more sets than its budget allows.
const SOURCE_ENTRY_OVERHEAD_BYTES: usize = 128;

impl Countable for FetchedMapping {
    fn byte_count(&self) -> usize {
        let cache = self.cache_bytes.as_ref().map_or(0, Vec::capacity);
        let sources: usize = self
            .sources
            .iter()
            .map(|(key, content)| key.capacity() + content.capacity() + SOURCE_ENTRY_OVERHEAD_BYTES)
            .sum();
        std::mem::size_of::<Self>() + cache + sources
    }
}

pub struct ProguardProvider {
    max_decompressed_bytes: usize,
}

impl ProguardProvider {
    pub fn new(config: &ResolverConfig) -> Self {
        Self {
            max_decompressed_bytes: config.symbol_set_max_decompressed_bytes.get(),
        }
    }
}

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

    async fn parse(
        &self,
        source: Self::Source,
        permit: ParsePermit,
    ) -> Result<FetchedMapping, ResolveError> {
        // zstd decompress + ProguardCache::write are CPU-bound; offload from the tokio
        // runtime so a large mapping doesn't block other in-flight requests.
        let max_decompressed_bytes = self.max_decompressed_bytes;
        tokio::task::spawn_blocking(move || -> Result<FetchedMapping, ResolveError> {
            let _permit = permit;
            let mapping = read_symbol_data_with_byte_count_limited::<ProguardMapping>(
                &source,
                max_decompressed_bytes,
            );
            // A JVM symbol set is one of two container types under the same ref. The type tag
            // decides, so only a type mismatch falls through to the second type.
            if let Err(SymbolDataError::InvalidDataType(..)) = mapping {
                let (bundle, decompressed_bytes): (JvmBundle, usize) =
                    read_symbol_data_with_byte_count_limited(&source, max_decompressed_bytes)
                        .inspect_err(|e| record_size_limit_exceeded(e, "jvm", "container"))
                        .map_err(ProguardError::DataError)?;
                metrics::histogram!(SYMBOL_SET_DECOMPRESSED_BYTES, "kind" => "jvm")
                    .record(decompressed_bytes as f64);
                return Ok(FetchedMapping::from_bundle(bundle)?);
            }
            let (map, decompressed_bytes) = mapping
                .inspect_err(|e| record_size_limit_exceeded(e, "proguard", "container"))
                .map_err(ProguardError::DataError)?;
            metrics::histogram!(SYMBOL_SET_DECOMPRESSED_BYTES, "kind" => "proguard")
                .record(decompressed_bytes as f64);
            Ok(FetchedMapping::new(map, decompressed_bytes)?)
        })
        .await
        .map_err(|e| UnhandledError::Other(format!("proguard parse task failed: {e}")))?
    }
}

fn build_cache(content: &str) -> Result<Vec<u8>, ProguardError> {
    let mapping = proguard::ProguardMapping::new(content.as_bytes());
    if !mapping.is_valid() {
        return Err(ProguardError::InvalidMapping);
    }

    let mut cache_bytes = Vec::new();
    proguard::ProguardCache::write(&mapping, &mut cache_bytes)
        .map_err(|_| ProguardError::InvalidMapping)?;
    // The writer grows the Vec by doubling, so capacity can be up to twice the length.
    // The cache counts `len()`, so drop the spare capacity to keep the count accurate.
    cache_bytes.shrink_to_fit();
    proguard::ProguardCache::parse(&cache_bytes).map_err(|_| ProguardError::InvalidMapping)?;
    Ok(cache_bytes)
}

impl FetchedMapping {
    pub fn new(inner: ProguardMapping, _decompressed_bytes: usize) -> Result<Self, ProguardError> {
        Ok(Self {
            cache_bytes: Some(build_cache(&inner.content)?),
            sources: BTreeMap::new(),
        })
    }

    pub fn from_bundle(bundle: JvmBundle) -> Result<Self, ProguardError> {
        Ok(Self {
            cache_bytes: bundle.mapping.as_deref().map(build_cache).transpose()?,
            sources: bundle.sources,
        })
    }

    pub fn get_cache<'a>(&'a self) -> Result<Option<proguard::ProguardCache<'a>>, ProguardError> {
        self.cache_bytes
            .as_deref()
            .map(|bytes| {
                proguard::ProguardCache::parse(bytes).map_err(|_| ProguardError::InvalidMapping)
            })
            .transpose()
    }

    pub fn remap_class(&self, class: &str) -> Result<Option<String>, ProguardError> {
        match self.get_cache()? {
            Some(cache) => Ok(cache.remap_class(class).map(ToString::to_string)),
            // Without a mapping the build was not obfuscated, so every class keeps its name.
            None => Ok(Some(class.to_string())),
        }
    }

    pub fn source(&self, key: &str) -> Option<&str> {
        self.sources.get(key).map(String::as_str)
    }
}

impl Display for ProguardRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "ProguardRef")
    }
}

#[cfg(test)]
mod tests {
    use posthog_symbol_data::{read_symbol_data_with_byte_count, write_symbol_data};

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

        let cache = fetched.get_cache().unwrap().unwrap();
        let frame = proguard::StackFrame::with_file("a1.d", "onClick", 14, "SourceFile");
        let remapped: Vec<_> = cache.remap_frame(&frame).collect();

        assert!(remapped.iter().any(|frame| {
            frame.class() == "com.posthog.android.sample.MyCustomException3"
                && frame.method() == "<init>"
        }));
    }

    #[test]
    fn empty_source_files_still_count_against_the_cache_budget() {
        let sources: BTreeMap<String, String> = (0..1000)
            .map(|i| (format!("{i:06}"), String::new()))
            .collect();
        let fetched = FetchedMapping::from_bundle(JvmBundle {
            mapping: None,
            sources,
        })
        .unwrap();

        assert!(fetched.byte_count() >= 1000 * SOURCE_ENTRY_OVERHEAD_BYTES);
    }
}
