use std::collections::HashMap;
use std::fmt::Display;
use std::io::{Cursor, Read};

use async_trait::async_trait;
use bytes::Bytes;
use serde::Deserialize;
use symbolic::debuginfo::Archive;
use symbolic::demangle::{Demangle, DemangleOptions};
use symbolic::symcache::{SymCache, SymCacheConverter};
use zip::ZipArchive;

use posthog_symbol_data::{read_symbol_data_with_byte_count, AppleDsym, ElfDebugInfo};

use crate::{
    error::{NativeError, ResolveError, UnhandledError},
    metric_consts::SYMBOL_SET_DECOMPRESSED_BYTES,
    symbolication::symbol_store::{caching::Countable, Fetcher, Parser},
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
    fn byte_count(&self) -> usize {
        self.decompressed_bytes
    }
}

impl ParsedNativeSymbols {
    pub fn from_zip_data(
        zip_data: Vec<u8>,
        decompressed_bytes: usize,
    ) -> Result<Self, NativeError> {
        let cursor = Cursor::new(zip_data);
        let mut archive =
            ZipArchive::new(cursor).map_err(|e| NativeError::ParseError(e.to_string()))?;

        let dwarf_data = Self::extract_dwarf_from_zip(&mut archive)?;

        let symcache_data = Self::convert_to_symcache(&dwarf_data)?;

        // Try to load source files from the bundle (graceful — old bundles without source still work)
        let sources = Self::extract_sources_from_zip(&mut archive);

        Ok(Self {
            symcache_data,
            sources,
            decompressed_bytes,
        })
    }

    /// Extract source files from a symbol ZIP that contains a `__source/manifest.json`.
    /// Returns None if no source manifest is found (backward compatible).
    fn extract_sources_from_zip(
        archive: &mut ZipArchive<Cursor<Vec<u8>>>,
    ) -> Option<HashMap<String, String>> {
        // Read and parse manifest
        let manifest: SourceManifest = {
            let mut manifest_file = archive.by_name("__source/manifest.json").ok()?;
            let mut manifest_data = Vec::new();
            manifest_file.read_to_end(&mut manifest_data).ok()?;
            serde_json::from_slice(&manifest_data).ok()?
        };

        let mut sources = HashMap::new();

        for (dwarf_path, zip_path) in &manifest.files {
            if let Ok(mut file) = archive.by_name(zip_path) {
                let mut content = String::new();
                if file.read_to_string(&mut content).is_ok() {
                    sources.insert(dwarf_path.clone(), content);
                }
            }
        }

        if sources.is_empty() {
            None
        } else {
            Some(sources)
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
        let sources = self.sources.as_ref()?;

        // 1. Exact match (fast path, works for physical-function frames)
        if let Some(text) = sources.get(dwarf_path) {
            return Some(text.as_str());
        }

        // 2. Basename fallback for inlined cross-file frames where the embedding
        //    CU's line table records a relative path but the manifest was built
        //    from the callee CU's absolute path (Swift WMO common case).
        let basename = std::path::Path::new(dwarf_path).file_name()?.to_str()?;
        let mut candidates = sources.iter().filter(|(k, _)| k.ends_with(basename));
        let first = candidates.next();
        // Only use the fallback if there is exactly one candidate (no ambiguity).
        if first.is_some() && candidates.next().is_none() {
            return first.map(|(_, v)| v.as_str());
        }

        None
    }

    fn extract_dwarf_from_zip(
        archive: &mut ZipArchive<Cursor<Vec<u8>>>,
    ) -> Result<Vec<u8>, NativeError> {
        // New format: single DWARF binary stored as "dwarf" at root level
        if let Ok(mut file) = archive.by_name("dwarf") {
            let mut data = Vec::new();
            file.read_to_end(&mut data)
                .map_err(|e| NativeError::ParseError(e.to_string()))?;
            return Ok(data);
        }

        // Old format: full dSYM bundle with Contents/Resources/DWARF/<name>
        // TODO(2026-09-24): Remove this fallback once all old uploads have expired.
        for i in 0..archive.len() {
            let mut file = archive
                .by_index(i)
                .map_err(|e| NativeError::ParseError(e.to_string()))?;

            let name = file.name().to_string();

            if name.contains("/Contents/Resources/DWARF/") && !name.ends_with('/') {
                let mut data = Vec::new();
                file.read_to_end(&mut data)
                    .map_err(|e| NativeError::ParseError(e.to_string()))?;
                return Ok(data);
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
pub struct NativeProvider {}

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

    async fn parse(&self, source: Self::Source) -> Result<ParsedNativeSymbols, ResolveError> {
        // Debug-info parsing is the heaviest CPU work in the system: zstd
        // decompress, ZIP expansion, DWARF parse, and symcache conversion.
        // Always offload from the tokio runtime.
        tokio::task::spawn_blocking(move || -> Result<ParsedNativeSymbols, ResolveError> {
            // Slice selection invariant: CLI dSYM uploads are one single-arch
            // binary per UUID (fat binaries are thinned at upload), so a
            // chunk_id lookup always parses the slice it names. The arm64
            // preference inside the symcache conversion only kicks in for
            // legacy raw-zip fat uploads, which predate native frames.
            let (zip_data, decompressed_bytes) =
                match read_symbol_data_with_byte_count::<ElfDebugInfo>(&source) {
                    Ok((elf, bytes)) => (elf.data, bytes),
                    Err(_) => match read_symbol_data_with_byte_count::<AppleDsym>(&source) {
                        Ok((dsym, bytes)) => (dsym.data, bytes),
                        // Raw ZIP fallback for dSYMs uploaded before the
                        // symbol_data container was introduced.
                        Err(_) => {
                            let len = source.len();
                            (source.to_vec(), len)
                        }
                    },
                };
            metrics::histogram!(SYMBOL_SET_DECOMPRESSED_BYTES, "kind" => "native")
                .record(decompressed_bytes as f64);
            ParsedNativeSymbols::from_zip_data(zip_data, decompressed_bytes).map_err(Into::into)
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
