use std::collections::HashMap;
use std::fmt::Display;
use std::io::{Cursor, Read};

use async_trait::async_trait;
use bytes::Bytes;
use serde::Deserialize;
use symbolic::debuginfo::Archive;
use symbolic::symcache::{SymCache, SymCacheConverter};
use symbolic_demangle::{Demangle, DemangleOptions};
use zip::ZipArchive;

use posthog_symbol_data::{
    read_symbol_data_with_byte_count_limited, AppleDsym, ElfDebugInfo, SymbolDataError,
};

use crate::{
    core::config::ResolverConfig,
    error::{NativeError, ResolveError, UnhandledError},
    metric_consts::SYMBOL_SET_DECOMPRESSED_BYTES,
    symbolication::symbol_store::{
        caching::Countable, record_size_limit_exceeded, Fetcher, ParsePermit, Parser,
    },
};

/// Manifest format for source files bundled in the symbol ZIP under `__source/`
#[derive(Deserialize)]
struct SourceManifest {
    #[allow(dead_code)]
    version: u32,
    /// Maps absolute DWARF source path → ZIP-relative path
    files: HashMap<String, String>,
}

/// Symbols parsed from an uploaded native debug-info bundle (dSYM, ELF, ...),
/// converted to a symcache for address lookup. The wire format is a ZIP with
/// the DWARF-bearing binary at the root plus an optional `__source/` bundle.
pub struct ParsedNativeSymbols {
    symcache_data: Vec<u8>,
    /// Source file contents indexed by DWARF absolute path.
    /// None if the bundle doesn't contain source files.
    sources: Option<HashMap<String, String>>,
    /// Decompressed byte count from the symbol_data container, used for cache memory accounting.
    decompressed_bytes: usize,
}

impl Countable for ParsedNativeSymbols {
    // Bundled sources are inflated out of the ZIP, so the parsed set can hold more memory than
    // the container it was parsed from.
    fn byte_count(&self) -> usize {
        let sources: usize = self
            .sources
            .iter()
            .flatten()
            .map(|(path, content)| path.len() + content.len())
            .sum();
        self.decompressed_bytes
            .max(self.symcache_data.len() + sources)
    }
}

// The zip crate inflates an entry until its compressed data ends and ignores the size in the
// entry header, so every read out of one ZIP is cut off at a shared remaining budget.
struct ExtractionBudget {
    max_bytes: usize,
    remaining: usize,
}

impl ExtractionBudget {
    fn new(max_bytes: usize) -> Self {
        Self {
            max_bytes,
            remaining: max_bytes,
        }
    }

    // A read that fails, for example on a CRC mismatch at the end of an entry, already inflated
    // its bytes, so they are charged before the error is returned.
    fn read(&mut self, entry: impl Read) -> Result<Vec<u8>, NativeError> {
        let mut data = Vec::new();
        let result = entry
            .take((self.remaining as u64).saturating_add(1))
            .read_to_end(&mut data);
        if data.len() > self.remaining {
            return Err(SymbolDataError::DecompressedTooLarge(self.max_bytes as u64).into());
        }
        self.remaining -= data.len();
        result.map_err(|e| NativeError::ParseError(e.to_string()))?;
        Ok(data)
    }

    fn read_optional(&mut self, entry: impl Read) -> Result<Option<Vec<u8>>, NativeError> {
        match self.read(entry) {
            Ok(data) => Ok(Some(data)),
            Err(e @ NativeError::DataError(_)) => Err(e),
            Err(_) => Ok(None),
        }
    }
}

impl ParsedNativeSymbols {
    /// Parses the result of a symbol_data container read. `kind` labels the metrics.
    pub fn from_container(
        container: Result<(Vec<u8>, usize), SymbolDataError>,
        source: &[u8],
        max_extracted_bytes: usize,
        kind: &'static str,
    ) -> Result<Self, NativeError> {
        let (zip_data, decompressed_bytes) = match container {
            Ok(container) => container,
            Err(e @ SymbolDataError::DecompressedTooLarge(_)) => {
                record_size_limit_exceeded(&e, kind, "container");
                return Err(e.into());
            }
            // Raw ZIP fallback for uploads from before the symbol_data container was introduced.
            // TODO(2026-09-24): Remove raw ZIP fallback once all old uploads have expired.
            Err(_) => (source.to_vec(), source.len()),
        };
        metrics::histogram!(SYMBOL_SET_DECOMPRESSED_BYTES, "kind" => kind)
            .record(decompressed_bytes as f64);
        Self::from_zip_data(zip_data, decompressed_bytes, max_extracted_bytes).inspect_err(|e| {
            if let NativeError::DataError(e) = e {
                record_size_limit_exceeded(e, kind, "extracted");
            }
        })
    }

    pub fn from_zip_data(
        zip_data: Vec<u8>,
        decompressed_bytes: usize,
        max_extracted_bytes: usize,
    ) -> Result<Self, NativeError> {
        let cursor = Cursor::new(zip_data);
        let mut archive =
            ZipArchive::new(cursor).map_err(|e| NativeError::ParseError(e.to_string()))?;
        let mut budget = ExtractionBudget::new(max_extracted_bytes);

        let dwarf_data = Self::extract_dwarf_from_zip(&mut archive, &mut budget)?;

        let symcache_data = Self::convert_to_symcache(&dwarf_data)?;

        // Try to load source files from the bundle (graceful — old bundles without source still work)
        let sources =
            Self::extract_sources_from_zip(&mut archive, &mut budget).unwrap_or_else(|e| {
                tracing::warn!("Dropping bundled sources from native symbol set: {e}");
                None
            });

        Ok(Self {
            symcache_data,
            sources,
            decompressed_bytes,
        })
    }

    /// Extract source files from a symbol ZIP that contains a `__source/manifest.json`.
    /// Returns None if no source manifest is found (backward compatible). Fails only when the
    /// sources exceed the extraction budget; an unreadable entry is skipped.
    fn extract_sources_from_zip(
        archive: &mut ZipArchive<Cursor<Vec<u8>>>,
        budget: &mut ExtractionBudget,
    ) -> Result<Option<HashMap<String, String>>, NativeError> {
        // Read and parse manifest
        let Ok(manifest_file) = archive.by_name("__source/manifest.json") else {
            return Ok(None);
        };
        let Some(manifest_data) = budget.read_optional(manifest_file)? else {
            return Ok(None);
        };
        let Ok(manifest) = serde_json::from_slice::<SourceManifest>(&manifest_data) else {
            return Ok(None);
        };

        let mut sources = HashMap::new();

        // Several manifest keys can name the same entry, and each one reads it again, so every
        // read is charged to the budget.
        for (dwarf_path, zip_path) in &manifest.files {
            let Ok(file) = archive.by_name(zip_path) else {
                continue;
            };
            if let Some(Ok(content)) = budget.read_optional(file)?.map(String::from_utf8) {
                sources.insert(dwarf_path.clone(), content);
            }
        }

        if sources.is_empty() {
            Ok(None)
        } else {
            Ok(Some(sources))
        }
    }

    /// Get the source content for a given DWARF absolute path.
    ///
    /// Uses a two-stage lookup to handle inlined cross-file frames under Swift WMO:
    ///
    /// 1. **Exact match** – fast path, works for physical-function frames where the
    ///    CU's own path matches the manifest key verbatim.
    ///
    /// 2. **Basename fallback** – when the embedding CU's line table records a
    ///    relative `include_directories` entry (e.g. `comp_dir="/"`,
    ///    `dir="PostHogExample"`) symcache resolves `full_path` as
    ///    `"/PostHogExample/Foo.swift"`, but the CLI built the manifest from the
    ///    callee CU's absolute path `"/Users/…/PostHogExample/Foo.swift"`.
    ///    The basename fallback matches by filename and is only applied when
    ///    there is exactly one candidate (no ambiguity).
    pub fn get_source(&self, dwarf_path: &str) -> Option<&str> {
        // 1. Exact match (fast path, works for physical-function frames)
        if let Some(text) = self.get_source_exact(dwarf_path) {
            return Some(text);
        }

        // 2. Basename fallback for inlined cross-file frames where the embedding
        //    CU's line table records a relative path but the manifest was built
        //    from the callee CU's absolute path (Swift WMO common case). Compares
        //    real file-name components, not string suffixes: "bar.c" must not
        //    match a bundled "/src/foobar.c".
        let sources = self.sources.as_ref()?;
        let basename = std::path::Path::new(dwarf_path).file_name()?;
        let mut candidates = sources
            .iter()
            .filter(|(k, _)| std::path::Path::new(k).file_name() == Some(basename));
        let first = candidates.next();
        // Only use the fallback if there is exactly one candidate (no ambiguity).
        if first.is_some() && candidates.next().is_none() {
            return first.map(|(_, v)| v.as_str());
        }

        None
    }

    /// Exact manifest-key lookup only, with no basename fallback. Used where
    /// the requested path comes from event input rather than the symcache
    /// (the symbol-miss context salvage), so fuzzy matching can't attach
    /// lines from a different file than the one named.
    pub fn get_source_exact(&self, dwarf_path: &str) -> Option<&str> {
        self.sources.as_ref()?.get(dwarf_path).map(|v| v.as_str())
    }

    fn extract_dwarf_from_zip(
        archive: &mut ZipArchive<Cursor<Vec<u8>>>,
        budget: &mut ExtractionBudget,
    ) -> Result<Vec<u8>, NativeError> {
        // New format: single DWARF binary stored as "dwarf" at root level
        if let Ok(file) = archive.by_name("dwarf") {
            return budget.read(file);
        }

        // Old format: full dSYM bundle with Contents/Resources/DWARF/<name>
        // TODO(2026-09-24): Remove this fallback once all old uploads have expired.
        for i in 0..archive.len() {
            let file = archive
                .by_index(i)
                .map_err(|e| NativeError::ParseError(e.to_string()))?;

            let name = file.name().to_string();

            if name.contains("/Contents/Resources/DWARF/") && !name.ends_with('/') {
                return budget.read(file);
            }
        }

        Err(NativeError::ParseError(
            "No DWARF file found in symbol bundle".to_string(),
        ))
    }

    fn convert_to_symcache(dwarf_data: &[u8]) -> Result<Vec<u8>, NativeError> {
        let archive =
            Archive::parse(dwarf_data).map_err(|e| NativeError::ParseError(e.to_string()))?;

        // For fat (universal) Mach-O binaries the archive contains multiple slices.
        // Crash reports from iOS/iPadOS devices are always arm64, so prefer that
        // architecture when building the symcache.  Falling back to the first slice
        // (the old behaviour) could pick x86_64 — the simulator architecture that
        // comes first in fat binaries built by Xcode — producing completely wrong
        // symbol names and line numbers for device crashes. ELF and PE archives
        // contain a single object, so the preference is a no-op for them.
        let obj = {
            let mut preferred: Option<_> = None;
            let mut fallback: Option<_> = None;
            for result in archive.objects() {
                match result {
                    Ok(o) => {
                        let arch_name = o.arch().name();
                        tracing::debug!("[symcache] candidate arch: {}", arch_name);
                        if arch_name.starts_with("arm64") {
                            preferred = Some(Ok(o));
                            break; // arm64 found — no need to look further
                        } else if fallback.is_none() {
                            fallback = Some(Ok(o));
                        }
                    }
                    Err(e) => {
                        if fallback.is_none() {
                            fallback = Some(Err(e));
                        }
                    }
                }
            }
            preferred
                .or(fallback)
                .ok_or_else(|| NativeError::ParseError("No objects in archive".to_string()))?
                .map_err(|e| NativeError::ParseError(e.to_string()))?
        };

        let mut converter = SymCacheConverter::new();
        converter
            .process_object(&obj)
            .map_err(|e| NativeError::ParseError(e.to_string()))?;

        let mut buffer = Vec::new();
        converter
            .serialize(&mut Cursor::new(&mut buffer))
            .map_err(|e| NativeError::ParseError(e.to_string()))?;

        Ok(buffer)
    }

    /// Look up all logical frames for an address, including inlined frames.
    ///
    /// The symcache iterator returns frames innermost-first:
    /// - index 0 is the deepest inlined function (the actual code running at `addr`)
    /// - last index is the outermost physical function that contains the address
    ///
    /// Returns an empty `Vec` when the address is not found in the symcache.
    pub fn lookup(&self, addr: u64) -> Result<Vec<SymbolInfo>, NativeError> {
        let symcache = SymCache::parse(&self.symcache_data)
            .map_err(|e| NativeError::ParseError(e.to_string()))?;

        let results = symcache
            .lookup(addr)
            .map(|result| {
                let raw_name = result.function().name_for_demangling();

                // Short name (no params/return type) for display as resolved_name
                let display_name = raw_name
                    .demangle(DemangleOptions::name_only())
                    .unwrap_or_else(|| raw_name.to_string());

                // Full demangled name for mangled_name (includes params and return type)
                let full_name = raw_name
                    .demangle(DemangleOptions::complete())
                    .unwrap_or_else(|| raw_name.to_string());

                let full_path = result.file().map(|f| f.full_path());
                let filename = full_path.as_ref().and_then(|path| extract_filename(path));

                SymbolInfo {
                    display_name,
                    full_name,
                    filename,
                    full_path,
                    line: result.line(),
                }
            })
            .collect();

        Ok(results)
    }
}

fn extract_filename(full_path: &str) -> Option<String> {
    use std::path::Path;
    Path::new(full_path)
        .file_name()
        .and_then(|s| s.to_str())
        .map(|s| s.to_string())
}

#[derive(Debug, Clone)]
pub struct SymbolInfo {
    /// Short demangled name (no params/return type) for display
    pub display_name: String,
    /// Full demangled name (with params and return type)
    pub full_name: String,
    pub filename: Option<String>,
    /// The full absolute path from DWARF debug info, used for source lookup
    pub full_path: Option<String>,
    pub line: u32,
}

/// Provider for native debug symbols looked up by debug_id. Accepts both
/// `ElfDebugInfo` bundles (uploaded via `posthog-cli debug-symbols upload`)
/// and `AppleDsym` bundles (uploaded via `posthog-cli dsym upload`), so
/// native frames from macOS binaries resolve against existing dSYM uploads.
pub struct NativeProvider {
    max_decompressed_bytes: usize,
    max_extracted_bytes: usize,
}

impl NativeProvider {
    pub fn new(config: &ResolverConfig) -> Self {
        Self {
            max_decompressed_bytes: config.symbol_set_max_decompressed_bytes.get(),
            max_extracted_bytes: config.symbol_set_max_extracted_bytes.get(),
        }
    }
}

#[derive(Debug, Clone)]
pub enum NativeRef {}

#[async_trait]
impl Fetcher for NativeProvider {
    type Ref = NativeRef;
    type Fetched = Bytes;
    type Err = ResolveError;

    async fn fetch(&self, _: i32, _: NativeRef) -> Result<Bytes, Self::Err> {
        unreachable!("NativeRef is impossible to construct, so cannot be passed")
    }
}

#[async_trait]
impl Parser for NativeProvider {
    type Source = Bytes;
    type Set = ParsedNativeSymbols;
    type Err = ResolveError;

    async fn parse(
        &self,
        source: Self::Source,
        permit: ParsePermit,
    ) -> Result<ParsedNativeSymbols, ResolveError> {
        // Debug-info parsing is the heaviest CPU work in the system: zstd
        // decompress, ZIP expansion, DWARF parse, and symcache conversion.
        // Always offload from the tokio runtime.
        let max_decompressed_bytes = self.max_decompressed_bytes;
        let max_extracted_bytes = self.max_extracted_bytes;
        tokio::task::spawn_blocking(move || -> Result<ParsedNativeSymbols, ResolveError> {
            let _permit = permit;
            // Slice selection invariant: CLI dSYM uploads are one single-arch
            // binary per UUID (fat binaries are thinned at upload), so a
            // chunk_id lookup always parses the slice it names. The arm64
            // preference inside the symcache conversion only kicks in for
            // legacy raw-zip fat uploads, which predate native frames.
            let container = read_symbol_data_with_byte_count_limited::<ElfDebugInfo>(
                &source,
                max_decompressed_bytes,
            )
            .map(|(elf, bytes)| (elf.data, bytes))
            .or_else(|e| match e {
                SymbolDataError::DecompressedTooLarge(_) => Err(e),
                _ => read_symbol_data_with_byte_count_limited::<AppleDsym>(
                    &source,
                    max_decompressed_bytes,
                )
                .map(|(dsym, bytes)| (dsym.data, bytes)),
            });
            ParsedNativeSymbols::from_container(container, &source, max_extracted_bytes, "native")
                .map_err(Into::into)
        })
        .await
        .map_err(|e| UnhandledError::Other(format!("native debug symbol parse task failed: {e}")))?
    }
}

impl Display for NativeRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "NativeRef")
    }
}

#[cfg(test)]
mod test {
    use std::collections::HashMap;

    use super::{NativeProvider, ParsedNativeSymbols};

    fn symbols_with(sources: &[(&str, &str)]) -> ParsedNativeSymbols {
        ParsedNativeSymbols {
            symcache_data: Vec::new(),
            sources: Some(
                sources
                    .iter()
                    .map(|(k, v)| (k.to_string(), v.to_string()))
                    .collect::<HashMap<_, _>>(),
            ),
            decompressed_bytes: 0,
        }
    }

    #[test]
    fn flutter_debug_symbols_resolve_dart_location_and_source() {
        use std::io::{Cursor, Write};

        use crate::langs::utils::get_context_lines;

        // The manifest must match the build path embedded in the fixture's DWARF.
        const SOURCE_PATH: &str =
            "/fixtures/flutter/native-symbolication-builds/sample/lib/main.dart";
        const SOURCE: &str = include_str!("../../../../tests/static/native/flutter_sample.dart");
        let artifacts: [(&[u8], u64); 2] = [
            (
                include_bytes!("../../../../tests/static/native/flutter_android_arm64.symbols.zst"),
                0x205217,
            ),
            (
                include_bytes!("../../../../tests/static/native/flutter_ios_arm64.symbols.zst"),
                0x14f1f7,
            ),
        ];

        for (compressed, address) in artifacts {
            let dwarf = zstd::decode_all(compressed).unwrap();
            for home_prefix in [b"/Users/".as_slice(), b"/home/".as_slice()] {
                assert!(
                    !dwarf
                        .windows(home_prefix.len())
                        .any(|bytes| bytes == home_prefix),
                    "fixture embeds an unredacted home directory"
                );
            }
            let manifest =
                serde_json::json!({"version": 1, "files": {SOURCE_PATH: "__source/main.dart"}})
                    .to_string();
            let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
            let options = zip::write::SimpleFileOptions::default();
            zip.start_file("dwarf", options).unwrap();
            zip.write_all(&dwarf).unwrap();
            zip.start_file("__source/manifest.json", options).unwrap();
            zip.write_all(manifest.as_bytes()).unwrap();
            zip.start_file("__source/main.dart", options).unwrap();
            zip.write_all(SOURCE.as_bytes()).unwrap();
            let data = zip.finish().unwrap().into_inner();
            let extracted_bytes = dwarf.len() + manifest.len() + SOURCE.len();

            // One byte short of the whole bundle: the sources are dropped and the symbols resolve.
            let without_sources =
                ParsedNativeSymbols::from_zip_data(data.clone(), data.len(), extracted_bytes - 1)
                    .unwrap();
            assert_eq!(without_sources.lookup(address).unwrap()[0].line, 7);
            assert_eq!(without_sources.get_source(SOURCE_PATH), None);

            let symbols =
                ParsedNativeSymbols::from_zip_data(data.clone(), data.len(), extracted_bytes)
                    .unwrap();
            let frame = symbols.lookup(address).unwrap().remove(0);
            assert_eq!(frame.display_name, "main");
            assert_eq!(frame.full_path.as_deref(), Some(SOURCE_PATH));
            assert_eq!(frame.line, 7);
            let context = get_context_lines(
                symbols
                    .get_source(frame.full_path.as_deref().unwrap())
                    .unwrap()
                    .lines(),
                (frame.line - 1) as usize,
                3,
            )
            .unwrap();
            assert_eq!(context.line.number, 7);
            assert!(context.line.line.contains("runApp("));
        }
    }

    #[tokio::test]
    async fn parse_fails_when_a_bundle_expands_past_its_size_limit() {
        use std::{
            io::{Cursor, Write},
            num::NonZeroUsize,
        };

        use posthog_symbol_data::{write_symbol_data, AppleDsym, ElfDebugInfo, SymbolDataError};

        use crate::{
            core::config::ResolverConfig,
            error::{AppleError, FrameError, NativeError, ResolveError},
            symbolication::symbol_store::{apple::AppleProvider, ParsePermit, Parser},
        };

        const LIMIT: usize = 1024;
        const EXTRACTED_LIMIT: usize = 2 * LIMIT;
        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.symbol_set_max_decompressed_bytes = NonZeroUsize::new(LIMIT).unwrap();
        config.symbol_set_max_extracted_bytes = NonZeroUsize::new(EXTRACTED_LIMIT).unwrap();

        let oversized_container = write_symbol_data(ElfDebugInfo {
            data: vec![0; 64 * LIMIT],
        })
        .unwrap();
        let oversized_dsym = write_symbol_data(AppleDsym {
            data: vec![0; 64 * LIMIT],
        })
        .unwrap();

        let oversized_entry = |name: &str| {
            let mut zip = zip::ZipWriter::new(Cursor::new(Vec::new()));
            zip.start_file(name, zip::write::SimpleFileOptions::default())
                .unwrap();
            zip.write_all(&vec![0; 64 * LIMIT]).unwrap();
            let zip_data = zip.finish().unwrap().into_inner();
            assert!(zip_data.len() <= LIMIT);
            write_symbol_data(ElfDebugInfo { data: zip_data }).unwrap()
        };

        let frame_error = |result: Result<ParsedNativeSymbols, ResolveError>| match result {
            Err(ResolveError::ResolutionError(e)) => e,
            Err(e) => panic!("{e:?}"),
            Ok(_) => panic!("parse succeeded"),
        };
        let too_large = |limit: usize| SymbolDataError::DecompressedTooLarge(limit as u64);

        let provider = NativeProvider::new(&config);
        for (source, expected_limit) in [
            (oversized_container, LIMIT),
            (oversized_dsym.clone(), LIMIT),
            (oversized_entry("dwarf"), EXTRACTED_LIMIT),
            (
                oversized_entry("App.dSYM/Contents/Resources/DWARF/App"),
                EXTRACTED_LIMIT,
            ),
        ] {
            assert_eq!(
                frame_error(provider.parse(source.into(), ParsePermit::none()).await),
                FrameError::Native(NativeError::DataError(too_large(expected_limit)))
            );
        }

        assert_eq!(
            frame_error(
                AppleProvider::new(&config)
                    .parse(oversized_dsym.into(), ParsePermit::none())
                    .await
            ),
            FrameError::Apple(AppleError::DataError(too_large(LIMIT)))
        );
    }

    #[test]
    fn extraction_budget_charges_bytes_from_a_failed_read() {
        use std::io::{Cursor, Read};

        use super::ExtractionBudget;

        struct FailsAtEnd(Cursor<Vec<u8>>);
        impl Read for FailsAtEnd {
            fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
                match self.0.read(buf)? {
                    0 => Err(std::io::Error::other("checksum mismatch")),
                    n => Ok(n),
                }
            }
        }

        let mut budget = ExtractionBudget::new(150);
        let entry = || FailsAtEnd(Cursor::new(vec![0; 100]));
        assert_eq!(budget.read_optional(entry()).unwrap(), None);
        assert!(budget.read_optional(entry()).is_err());
    }

    #[test]
    fn cache_counts_bundled_sources_past_the_container_size() {
        use super::Countable;

        let source = "x".repeat(1000);
        let symbols = symbols_with(&[("/src/main.c", &source)]);
        assert!(symbols.byte_count() >= source.len());
    }

    #[test]
    fn source_lookup_matches_file_name_components_not_suffixes() {
        let symbols = symbols_with(&[("/src/foobar.c", "foo"), ("/abs/path/Foo.swift", "swift")]);

        // Exact key always wins.
        assert_eq!(symbols.get_source("/src/foobar.c"), Some("foo"));
        assert_eq!(symbols.get_source_exact("/src/foobar.c"), Some("foo"));

        // The fallback compares real file-name components: a suffix of a
        // different file's name must not match.
        assert_eq!(symbols.get_source("bar.c"), None);
        // A relative spelling of the same file still matches.
        assert_eq!(symbols.get_source("sub/dir/Foo.swift"), Some("swift"));

        // The exact-only lookup never falls back.
        assert_eq!(symbols.get_source_exact("Foo.swift"), None);
        assert_eq!(symbols.get_source_exact("bar.c"), None);
    }

    #[test]
    fn source_fallback_requires_a_unique_candidate() {
        let symbols = symbols_with(&[("/a/util.c", "a"), ("/b/util.c", "b")]);
        assert_eq!(symbols.get_source("util.c"), None);
    }
}
