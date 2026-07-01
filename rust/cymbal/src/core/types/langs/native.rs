use std::sync::Arc;

use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use symbolic::common::Name;
use symbolic::demangle::{Demangle, DemangleOptions};

use crate::{
    error::{FrameError, NativeError, ResolveError, UnhandledError},
    frames::{record_frame_resolution_failure, Frame},
    langs::utils::{add_raw_to_junk, get_context_lines},
    langs::CommonFrameMetadata,
    symbolication::symbol_store::{
        chunk_id::OrChunkId,
        native::{NativeRef, ParsedNativeSymbols, SymbolInfo},
        SymbolCatalog,
    },
};

/// A loaded module (binary image) reported by an SDK alongside native stack
/// frames, used to map absolute instruction addresses onto an uploaded debug
/// symbol set. Sent as the event-level `$debug_images` property.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct DebugImage {
    pub debug_id: String,
    pub image_addr: String,
    #[serde(default)]
    pub image_vmaddr: Option<String>,
    #[serde(default)]
    pub image_size: Option<u64>,
    #[serde(default)]
    pub code_file: Option<String>,
    #[serde(default, rename = "type")]
    pub image_type: Option<String>,
    #[serde(default)]
    pub arch: Option<String>,
}

pub fn parse_hex_address(s: &str) -> Result<u64, NativeError> {
    let s = s.trim().trim_start_matches("0x").trim_start_matches("0X");
    u64::from_str_radix(s, 16).map_err(|_| NativeError::InvalidAddress(s.to_string()))
}

/// Find the debug image containing `instruction_addr`, preferring an exact
/// match on the frame's own `image_addr` and falling back to a range check
/// against each image's `[image_addr, image_addr + image_size)`.
pub fn find_debug_image<'a>(
    instruction_addr: u64,
    frame_image_addr: Option<&str>,
    debug_images: &'a [DebugImage],
) -> Result<&'a DebugImage, NativeError> {
    let frame_image_addr = frame_image_addr.and_then(|addr| parse_hex_address(addr).ok());

    for image in debug_images {
        let image_base = parse_hex_address(&image.image_addr).ok();

        if let (Some(frame_addr), Some(base)) = (frame_image_addr, image_base) {
            if frame_addr == base {
                return Ok(image);
            }
        }

        if let (Some(base), Some(size)) = (image_base, image.image_size) {
            if instruction_addr >= base && instruction_addr < base.saturating_add(size) {
                return Ok(image);
            }
        }
    }

    Err(NativeError::NoMatchingDebugImage)
}

/// Offset of `instruction_addr` from the image's runtime load address, i.e. the
/// address the symcache is keyed by.
///
/// `image_vmaddr` is intentionally NOT added here. `symbolic` rebases symcache
/// entries to the image's preferred base, and the SDK reports `image_addr` as
/// the *actual* load address (preferred base + ASLR slide), so
/// `instruction_addr - image_addr` already yields the symcache-relative address.
/// Adding `image_vmaddr` would double-count the preferred base and break every
/// image with a nonzero one — see
/// `test_native_symbolication_is_load_relative_with_nonzero_vmaddr`.
pub fn calculate_relative_addr(
    instruction_addr: u64,
    debug_image: &DebugImage,
) -> Result<u64, NativeError> {
    let image_addr = parse_hex_address(&debug_image.image_addr)?;

    if instruction_addr < image_addr {
        return Err(NativeError::InvalidAddress(format!(
            "instruction_addr 0x{:x} < image_addr 0x{:x}",
            instruction_addr, image_addr
        )));
    }

    Ok(instruction_addr - image_addr)
}

/// The launch-invariant identity of a frame: the debug image it belongs to and
/// the offset within it. Absolute instruction addresses are ASLR-slid per
/// process launch, so anything that needs a stable per-build frame identity
/// (e.g. frame-record caching) should prefer this over the raw address.
pub fn launch_invariant_addr(
    instruction_addr: Option<&str>,
    frame_image_addr: Option<&str>,
    debug_images: &[DebugImage],
) -> Option<(String, u64)> {
    let instruction_addr = parse_hex_address(instruction_addr?).ok()?;
    let debug_image = find_debug_image(instruction_addr, frame_image_addr, debug_images).ok()?;
    let relative_addr = calculate_relative_addr(instruction_addr, debug_image).ok()?;
    Some((debug_image.debug_id.clone(), relative_addr))
}

/// A native stack frame as sent by SDKs that capture raw instruction
/// addresses (e.g. posthog-rs). Resolution model: when `instruction_addr` is
/// present and a matching debug image was sent, the frame is symbolicated
/// server-side against the uploaded debug symbols; otherwise the client-side
/// enrichment fields (`function`/`filename`/`lineno`) pass through as-is.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawNativeFrame {
    pub instruction_addr: Option<String>,
    pub symbol_addr: Option<String>,
    pub image_addr: Option<String>,
    /// Display-language hint from the SDK (e.g. "rust"); the resolved
    /// filename extension wins when available.
    pub lang: Option<String>,
    pub module: Option<String>,
    pub function: Option<String>,
    pub filename: Option<String>,
    pub lineno: Option<u32>,
    pub colno: Option<u32>,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawNativeFrame {
    pub async fn resolve<C>(
        &self,
        team_id: i32,
        catalog: &C,
        debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<NativeRef>, ParsedNativeSymbols>,
    {
        // Frames without an instruction address (e.g. hand-built exception
        // lists) carry only client-side resolution and pass through as-is.
        let Some(instruction_addr) = self.instruction_addr.as_deref() else {
            return Ok(vec![self.into()]);
        };

        match self
            .resolve_impl(
                team_id,
                catalog,
                instruction_addr,
                debug_images,
                context_lines,
            )
            .await
        {
            Ok(frames) => Ok(frames),
            Err(ResolveError::ResolutionError(FrameError::Native(e))) => {
                Ok(vec![self.handle_resolution_error(e)])
            }
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => Ok(
                vec![self.handle_resolution_error(NativeError::MissingSymbolSet(chunk_id))],
            ),
            Err(ResolveError::ResolutionError(e)) => {
                tracing::warn!("Unexpected native symbol resolution error: {:?}", e);
                Ok(vec![self.handle_resolution_error(NativeError::ParseError(
                    e.to_string(),
                ))])
            }
            Err(ResolveError::UnhandledError(e)) => Err(e),
        }
    }

    async fn resolve_impl<C>(
        &self,
        team_id: i32,
        catalog: &C,
        instruction_addr: &str,
        debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<NativeRef>, ParsedNativeSymbols>,
    {
        let instruction_addr = parse_hex_address(instruction_addr)?;

        let debug_image =
            find_debug_image(instruction_addr, self.image_addr.as_deref(), debug_images)?;

        let relative_addr = calculate_relative_addr(instruction_addr, debug_image)?;

        // Subtract 1 from return-address frames so the lookup targets the call
        // instruction rather than the instruction after it, giving the correct
        // source line. Safe for top (crash-site) frames too: addr-1 still falls
        // within the same function body.
        let lookup_addr = relative_addr.saturating_sub(1);

        let symbols: Arc<ParsedNativeSymbols> = catalog
            .lookup(team_id, OrChunkId::chunk_id(debug_image.debug_id.clone()))
            .await?;

        let symbol_infos = symbols.lookup(lookup_addr)?;
        if symbol_infos.is_empty() {
            return Err(NativeError::SymbolNotFound(lookup_addr).into());
        }

        // Build one resolved Frame per logical layer. The symcache returns
        // layers innermost-first; reverse to outermost-first so the flattened
        // stack stays in bottom-up order (main first, crash site last).
        let frames: Vec<Frame> = symbol_infos
            .iter()
            .rev()
            .map(|info| {
                let mut frame = self.build_resolved_frame(info);

                // Attach source context to every inlined layer independently.
                if let Some(full_path) = &info.full_path {
                    if let Some(source_text) = symbols.get_source(full_path) {
                        // symcache line numbers are 1-based (0 = unknown)
                        let target_line = if info.line > 0 {
                            (info.line - 1) as usize
                        } else {
                            0
                        };
                        frame.context =
                            get_context_lines(source_text.lines(), target_line, context_lines);
                    }
                }

                frame
            })
            .collect();

        Ok(frames)
    }

    fn build_resolved_frame(&self, symbol_info: &SymbolInfo) -> Frame {
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: symbol_info.full_name.clone(),
            line: if symbol_info.line > 0 {
                Some(symbol_info.line)
            } else {
                None
            },
            column: None,
            source: symbol_info.filename.clone(),
            in_app: self.meta.in_app,
            resolved_name: Some(symbol_info.display_name.clone()),
            lang: self.lang_for(symbol_info.filename.as_deref()),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            release: None,
            synthetic: self.meta.synthetic,
            context: None,
            suspicious: false,
            module: self.module.clone(),
            code_variables: None,
        };

        add_raw_to_junk(&mut f, self);
        f
    }

    fn handle_resolution_error(&self, err: NativeError) -> Frame {
        record_frame_resolution_failure("native", err.metric_reason(), &err);

        // Demangle the raw function name if the SDK sent a mangled one
        let mangled = self.function.clone().unwrap_or_default();
        let resolved_name = if !mangled.is_empty() {
            let name = Name::from(mangled.as_str());
            Some(
                name.demangle(DemangleOptions::complete())
                    .unwrap_or_else(|| mangled.clone()),
            )
        } else {
            None
        };

        // For unresolved frames without a filename, show "module +image_addr"
        // as source (e.g. system libraries we have no debug symbols for).
        let source = self
            .filename
            .clone()
            .or_else(|| match (&self.module, &self.image_addr) {
                (Some(module), Some(addr)) => Some(format!("{} +{}", module, addr)),
                (Some(module), None) => Some(module.clone()),
                _ => None,
            });

        let mut frame = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: mangled,
            line: self.lineno,
            column: self.colno,
            source,
            in_app: self.meta.in_app,
            resolved_name,
            lang: self.lang_for(self.filename.as_deref()),
            resolved: false,
            resolve_failure: Some(err.to_string()),
            junk_drawer: None,
            release: None,
            synthetic: self.meta.synthetic,
            context: None,
            suspicious: false,
            module: self.module.clone(),
            code_variables: None,
        };

        add_raw_to_junk(&mut frame, self);
        frame
    }

    /// Display language: the resolved filename extension wins (a Rust binary's
    /// stack legitimately contains C/C++ frames from native dependencies),
    /// falling back to the SDK's hint.
    fn lang_for(&self, filename: Option<&str>) -> String {
        match filename.and_then(|f| f.rsplit('.').next()) {
            Some("rs") => "rust".to_string(),
            Some("go") => "go".to_string(),
            Some("c") => "c".to_string(),
            Some("cpp" | "cc" | "cxx" | "hpp" | "hh" | "hxx") => "cpp".to_string(),
            // `.h` is ambiguous across C/C++/Objective-C, so default to C.
            Some("h") => "c".to_string(),
            Some("swift") => "swift".to_string(),
            Some("m") => "objectivec".to_string(),
            _ => self.lang.clone().unwrap_or_else(|| "native".to_string()),
        }
    }

    /// The uploaded debug symbol set this frame resolves against, identified by
    /// the matched debug image's `debug_id` (the chunk_id used at upload). None
    /// when no debug image matches the address, so there is no symbol set to
    /// link — e.g. a JIT or otherwise unmapped frame.
    pub fn symbol_set_ref(&self, debug_images: &[DebugImage]) -> Option<String> {
        launch_invariant_addr(
            self.instruction_addr.as_deref(),
            self.image_addr.as_deref(),
            debug_images,
        )
        .map(|(debug_id, _)| debug_id)
    }

    pub fn frame_id(&self, debug_images: &[DebugImage]) -> String {
        let mut hasher = Sha512::new();

        // Prefer the launch-invariant (debug image, relative offset) identity
        // so the frame record cache survives ASLR across process launches.
        match launch_invariant_addr(
            self.instruction_addr.as_deref(),
            self.image_addr.as_deref(),
            debug_images,
        ) {
            Some((debug_id, relative_addr)) => {
                hasher.update(debug_id.as_bytes());
                hasher.update(format!("rel:0x{relative_addr:x}").as_bytes());
            }
            None => {
                if let Some(instruction_addr) = &self.instruction_addr {
                    hasher.update(instruction_addr.as_bytes());
                }
            }
        }

        // Client-side identity, which also covers address-less frames.
        self.function
            .as_ref()
            .inspect(|f| hasher.update(f.as_bytes()));
        self.filename
            .as_ref()
            .inspect(|f| hasher.update(f.as_bytes()));
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.colno.unwrap_or_default().to_be_bytes());
        self.module
            .as_ref()
            .inspect(|m| hasher.update(m.as_bytes()));
        hasher.update(b"native");

        format!("{:x}", hasher.finalize())
    }
}

impl From<&RawNativeFrame> for Frame {
    fn from(raw: &RawNativeFrame) -> Self {
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone().unwrap_or_default(),
            line: raw.lineno,
            column: raw.colno,
            source: raw.filename.clone(),
            in_app: raw.meta.in_app,
            resolved_name: raw.function.clone(),
            lang: raw.lang_for(raw.filename.as_deref()),
            resolved: raw.function.is_some(),
            resolve_failure: None,

            junk_drawer: None,
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: raw.module.clone(),
            code_variables: None,
        };

        // Store raw frame data in junk drawer for debugging/analysis
        add_raw_to_junk(&mut f, raw);
        f
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::core::symbolication::resolve::Resolve;

    fn image_at(debug_id: &str, image_addr: u64) -> DebugImage {
        DebugImage {
            debug_id: debug_id.to_string(),
            image_addr: format!("0x{image_addr:x}"),
            image_vmaddr: None,
            image_size: Some(0x10000),
            code_file: None,
            image_type: None,
            arch: None,
        }
    }

    #[test]
    fn test_parse_hex_address_with_0x_prefix() {
        assert_eq!(parse_hex_address("0x100000000").unwrap(), 0x100000000);
        assert_eq!(parse_hex_address("0X100000000").unwrap(), 0x100000000);
    }

    #[test]
    fn test_parse_hex_address_without_prefix() {
        assert_eq!(parse_hex_address("100000000").unwrap(), 0x100000000);
        assert_eq!(parse_hex_address("deadbeef").unwrap(), 0xdeadbeef);
    }

    #[test]
    fn test_parse_hex_address_with_whitespace() {
        assert_eq!(parse_hex_address("  0x100000000  ").unwrap(), 0x100000000);
    }

    #[test]
    fn test_parse_hex_address_invalid() {
        assert!(parse_hex_address("not_hex").is_err());
        assert!(parse_hex_address("0xGGGG").is_err());
    }

    #[test]
    fn test_calculate_relative_addr() {
        let result = calculate_relative_addr(0x100004000, &image_at("test-uuid", 0x100000000));
        assert_eq!(result.unwrap(), 0x4000);
    }

    #[test]
    fn test_calculate_relative_addr_below_image_base() {
        let result = calculate_relative_addr(0x100, &image_at("test-uuid", 0x100000000));
        assert!(matches!(result, Err(NativeError::InvalidAddress(_))));
    }

    #[test]
    fn test_find_debug_image_by_image_addr() {
        let debug_images = vec![
            image_at("other-uuid", 0x200000000),
            image_at("matching-uuid", 0x100000000),
        ];

        let result = find_debug_image(0x100004000, Some("0x100000000"), &debug_images).unwrap();
        assert_eq!(result.debug_id, "matching-uuid");
    }

    #[test]
    fn test_find_debug_image_by_address_range() {
        let debug_images = vec![image_at("range-match", 0x100000000)];

        let result = find_debug_image(0x100004000, None, &debug_images).unwrap();
        assert_eq!(result.debug_id, "range-match");
    }

    #[test]
    fn test_find_debug_image_no_match() {
        let debug_images = vec![image_at("some-uuid", 0x100000000)];

        let result = find_debug_image(0x300000000, None, &debug_images);
        assert!(matches!(result, Err(NativeError::NoMatchingDebugImage)));
    }

    #[test]
    fn test_launch_invariant_addr() {
        let images = [image_at("uuid-build-1", 0x104f00000)];
        let result = launch_invariant_addr(Some("0x104f04000"), Some("0x104f00000"), &images);
        assert_eq!(result, Some(("uuid-build-1".to_string(), 0x4000)));
    }

    #[test]
    fn test_launch_invariant_addr_without_matching_image() {
        let result = launch_invariant_addr(Some("0x104f04000"), None, &[]);
        assert_eq!(result, None);
    }

    #[test]
    fn test_native_frames_without_address_pass_through() {
        let frame = RawNativeFrame {
            instruction_addr: None,
            symbol_addr: None,
            image_addr: None,
            lang: Some("rust".to_string()),
            module: Some("checkout_service".to_string()),
            function: Some("checkout::submit".to_string()),
            filename: Some("src/checkout.rs".to_string()),
            lineno: Some(42),
            colno: None,
            meta: CommonFrameMetadata::default(),
        };

        let resolved: Frame = (&frame).into();
        assert!(resolved.resolved);
        assert_eq!(resolved.resolved_name.as_deref(), Some("checkout::submit"));
        assert_eq!(resolved.source.as_deref(), Some("src/checkout.rs"));
        assert_eq!(resolved.line, Some(42));
        assert_eq!(resolved.lang, "rust");
    }

    #[test]
    fn test_native_frame_id_stable_across_aslr_slides() {
        let frame_at = |instruction_addr: u64, image_addr: u64| RawNativeFrame {
            instruction_addr: Some(format!("0x{instruction_addr:x}")),
            symbol_addr: None,
            image_addr: Some(format!("0x{image_addr:x}")),
            lang: Some("rust".to_string()),
            module: Some("my_service".to_string()),
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        };

        let launch_a = frame_at(0x100004000, 0x100000000);
        let launch_b = frame_at(0x104f04000, 0x104f00000);

        let id_a = launch_a.frame_id(&[image_at("build-1", 0x100000000)]);
        let id_b = launch_b.frame_id(&[image_at("build-1", 0x104f00000)]);
        assert_eq!(id_a, id_b);

        // Without a matching image the absolute address is hashed, so the ids differ.
        assert_ne!(launch_a.frame_id(&[]), launch_b.frame_id(&[]));
    }

    /// Wrap a fixture ELF in the upload ZIP layout (binary as `dwarf` at the
    /// root, optional `__source/` bundle), mirroring what the CLI produces.
    fn zip_fixture(elf: &[u8], source: Option<(&str, &str)>) -> Vec<u8> {
        use std::io::{Cursor, Write};

        let mut buffer = Cursor::new(Vec::new());
        {
            let mut zip = zip::ZipWriter::new(&mut buffer);
            let options = zip::write::SimpleFileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            zip.start_file("dwarf", options).unwrap();
            zip.write_all(elf).unwrap();

            if let Some((dwarf_path, content)) = source {
                let manifest = serde_json::json!({
                    "version": 1,
                    "files": { dwarf_path: "__source/0" },
                });
                zip.start_file("__source/manifest.json", options).unwrap();
                zip.write_all(manifest.to_string().as_bytes()).unwrap();
                zip.start_file("__source/0", options).unwrap();
                zip.write_all(content.as_bytes()).unwrap();
            }

            zip.finish().unwrap();
        }

        posthog_symbol_data::write_symbol_data(posthog_symbol_data::ElfDebugInfo {
            data: buffer.into_inner(),
        })
        .unwrap()
    }

    /// Build a catalog whose native provider serves `data` for `chunk_id`.
    async fn catalog_for_chunk(
        db: &sqlx::PgPool,
        chunk_id: &str,
        data: Vec<u8>,
    ) -> crate::symbolication::symbol_store::Catalog {
        use chrono::Utc;
        use mockall::predicate;
        use std::sync::Arc;
        use uuid::Uuid;

        use crate::{
            core::config::ResolverConfig,
            symbolication::symbol_store::{
                apple::AppleProvider, chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider,
                native::NativeProvider, proguard::ProguardProvider, saving::SymbolSetRecord,
                sourcemap::SourcemapProvider, Catalog, MockS3Client,
            },
        };

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id: 1,
            set_ref: chunk_id.to_string(),
            storage_ptr: Some(chunk_id.to_string()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };
        record.save(db).await.unwrap();

        let mut client = MockS3Client::default();
        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(chunk_id.to_string()),
            )
            .returning(move |_, _| Ok(Some(bytes::Bytes::from(data.clone()))));
        let client = Arc::new(client);

        Catalog::new(
            ChunkIdFetcher::new(
                SourcemapProvider::new(&config),
                client.clone(),
                db.clone(),
                config.object_storage_bucket.clone(),
            ),
            ChunkIdFetcher::new(
                HermesMapProvider {},
                client.clone(),
                db.clone(),
                config.object_storage_bucket.clone(),
            ),
            ChunkIdFetcher::new(
                ProguardProvider {},
                client.clone(),
                db.clone(),
                config.object_storage_bucket.clone(),
            ),
            ChunkIdFetcher::new(
                AppleProvider {},
                client.clone(),
                db.clone(),
                config.object_storage_bucket.clone(),
            ),
            ChunkIdFetcher::new(
                NativeProvider {},
                client.clone(),
                db.clone(),
                config.object_storage_bucket.clone(),
            ),
        )
    }

    fn native_frame_at(instruction_addr: u64, image_addr: u64) -> RawNativeFrame {
        RawNativeFrame {
            instruction_addr: Some(format!("0x{instruction_addr:x}")),
            symbol_addr: None,
            image_addr: Some(format!("0x{image_addr:x}")),
            lang: Some("rust".to_string()),
            module: Some("test_binary".to_string()),
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        }
    }

    #[test]
    fn lang_for_maps_source_extensions() {
        // native_frame_at carries lang hint "rust"
        let frame = native_frame_at(0x1000, 0x1000);

        assert_eq!(frame.lang_for(Some("src/main.rs")), "rust");
        assert_eq!(frame.lang_for(Some("foo.c")), "c");
        assert_eq!(frame.lang_for(Some("foo.cpp")), "cpp");
        // C++ headers must not be mislabeled as C
        assert_eq!(frame.lang_for(Some("foo.hpp")), "cpp");
        assert_eq!(frame.lang_for(Some("foo.hh")), "cpp");
        assert_eq!(frame.lang_for(Some("foo.hxx")), "cpp");
        // Plain `.h` is ambiguous, so it stays C
        assert_eq!(frame.lang_for(Some("foo.h")), "c");
        // Unknown / extension-less falls back to the SDK-provided lang hint
        assert_eq!(frame.lang_for(Some("README")), "rust");
        assert_eq!(frame.lang_for(None), "rust");
    }

    fn debug_image_at(debug_id: &str, image_addr: u64) -> DebugImage {
        DebugImage {
            debug_id: debug_id.to_string(),
            image_addr: format!("0x{image_addr:x}"),
            image_vmaddr: None,
            image_size: Some(0x100000),
            code_file: Some("/app/test_binary".to_string()),
            image_type: Some("elf".to_string()),
            arch: Some("x86_64".to_string()),
        }
    }

    #[test]
    fn symbol_set_ref_is_matched_debug_id() {
        let frame = native_frame_at(0x1000_4000, 0x1000_0000);
        let images = [debug_image_at("rust-build-1", 0x1000_0000)];
        assert_eq!(
            frame.symbol_set_ref(&images),
            Some("rust-build-1".to_string())
        );
        // No matching debug image -> no symbol set to link.
        assert_eq!(frame.symbol_set_ref(&[]), None);
    }

    // Fixture facts (see tests/static/native/build.sh; constants extracted
    // from the symcache the same way cymbal builds it):
    //   test_binary_nopie:  debug_id 7561847b-1054-7eb3-7763-4415adfaa134,
    //                       load_address 0x1000000, inner_function at 0x14a0
    //   test_binary_pie:    debug_id 850c70a2-6592-a70c-3e49-c0e443794d23,
    //                       load_address 0x0, inner_function at 0x14a0
    //   test_binary_inline: debug_id 140ab543-c098-09dc-22b6-11f72e46d6fe,
    //                       lookup(0x1474) -> inlined_leaf / inner_function / outer_function
    //   test_rust_binary:   debug_id d1dea836-4ad3-daad-dd96-0e8626f766e1,
    //                       charge at 0x10640, lookup(0x10644) ->
    //                       core::hint::black_box inlined into charge

    /// Non-PIE ELF: the binary links at a fixed base (0x1000000) and loads
    /// there unchanged, so image_addr equals the link-time base.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_native_symbolication_elf_non_pie(db: sqlx::PgPool) {
        use crate::frames::RawFrame;

        const ELF: &[u8] = include_bytes!("../../../../tests/static/native/test_binary_nopie");
        let chunk_id = "7561847b-1054-7eb3-7763-4415adfaa134";
        let catalog = catalog_for_chunk(&db, chunk_id, zip_fixture(ELF, None)).await;

        let image_base = 0x1000000u64;
        // 0x14a8 is inside inner_function (entry 0x14a0); the -1 call-site
        // adjustment keeps the lookup inside the function body.
        let frame = RawFrame::Native(native_frame_at(image_base + 0x14a8, image_base));
        let debug_images = vec![debug_image_at(chunk_id, image_base)];

        let resolved = frame
            .resolve(1, &catalog, &debug_images, 15)
            .await
            .unwrap()
            .pop()
            .unwrap();

        assert!(resolved.resolved, "{:?}", resolved.resolve_failure);
        assert_eq!(resolved.resolved_name.as_deref(), Some("inner_function"));
        assert_eq!(resolved.source.as_deref(), Some("test_binary.c"));
        assert_eq!(resolved.lang, "c");
        assert!(resolved.line.is_some());
    }

    /// PIE ELF: links at base 0 and gets an ASLR slide at runtime; the
    /// relative address math must recover the link-time offset.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_native_symbolication_elf_pie_with_aslr_slide(db: sqlx::PgPool) {
        use crate::frames::RawFrame;

        const ELF: &[u8] = include_bytes!("../../../../tests/static/native/test_binary_pie");
        let chunk_id = "850c70a2-6592-a70c-3e49-c0e443794d23";
        let catalog = catalog_for_chunk(&db, chunk_id, zip_fixture(ELF, None)).await;

        let slide_base = 0x7f1234560000u64;
        let frame = RawFrame::Native(native_frame_at(slide_base + 0x14a8, slide_base));
        let debug_images = vec![debug_image_at(chunk_id, slide_base)];

        let resolved = frame
            .resolve(1, &catalog, &debug_images, 15)
            .await
            .unwrap()
            .pop()
            .unwrap();

        assert!(resolved.resolved, "{:?}", resolved.resolve_failure);
        assert_eq!(resolved.resolved_name.as_deref(), Some("inner_function"));
        assert_eq!(resolved.source.as_deref(), Some("test_binary.c"));
        assert!(resolved.line.is_some());
    }

    /// One raw frame at an address inside two levels of inlining expands into
    /// three logical frames (outermost first), each with source context from
    /// the bundled `__source/` files.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_native_inlined_frame_expansion_with_source(db: sqlx::PgPool) {
        use crate::frames::RawFrame;

        const ELF: &[u8] = include_bytes!("../../../../tests/static/native/test_binary_inline");
        const SOURCE: &str = include_str!("../../../../tests/static/native/test_binary_inline.c");
        let chunk_id = "140ab543-c098-09dc-22b6-11f72e46d6fe";
        let zip = zip_fixture(
            ELF,
            Some(("/cymbal_tests/native/test_binary_inline.c", SOURCE)),
        );
        let catalog = catalog_for_chunk(&db, chunk_id, zip).await;

        let slide_base = 0x7f0000000000u64;
        // 0x1475: after the -1 adjustment the lookup lands on 0x1474, inside
        // inlined_leaf as inlined (via inner_function) into outer_function.
        let frame = RawFrame::Native(native_frame_at(slide_base + 0x1475, slide_base));
        let debug_images = vec![debug_image_at(chunk_id, slide_base)];

        let frames = frame.resolve(1, &catalog, &debug_images, 15).await.unwrap();

        assert_eq!(
            frames.len(),
            3,
            "expected 3 frames (inlined expansion), got: {frames:#?}"
        );
        assert!(frames.iter().all(|f| f.resolved));

        // Outermost first, innermost last
        assert_eq!(frames[0].resolved_name, Some("outer_function".to_string()));
        assert_eq!(frames[1].resolved_name, Some("inner_function".to_string()));
        assert_eq!(frames[2].resolved_name, Some("inlined_leaf".to_string()));

        for (i, frame) in frames.iter().enumerate() {
            assert!(
                frame.context.is_some(),
                "frame[{i}] ({:?}) has no source context",
                frame.resolved_name
            );
        }

        let leaf_ctx = frames[2].context.as_ref().unwrap();
        let all_lines: Vec<&str> = leaf_ctx
            .before
            .iter()
            .chain(std::iter::once(&leaf_ctx.line))
            .chain(leaf_ctx.after.iter())
            .map(|l| l.line.as_str())
            .collect();
        assert!(
            all_lines.iter().any(|l| l.contains("volatile int x = 99")),
            "expected 'volatile int x = 99' in inlined_leaf context, got: {all_lines:?}"
        );
    }

    /// A rustc-built binary: mangled symbols demangle to rust paths, the
    /// resolved filename drives `lang`, and std inlining expands.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_native_rust_symbol_demangling(db: sqlx::PgPool) {
        use crate::frames::RawFrame;

        // Committed compressed: a rustc binary carries debug info for all of
        // std, so even with line-tables-only + LTO it is megabytes raw.
        const ELF_ZST: &[u8] =
            include_bytes!("../../../../tests/static/native/test_rust_binary.zst");
        let elf = zstd::decode_all(ELF_ZST).unwrap();
        let chunk_id = "d1dea836-4ad3-daad-dd96-0e8626f766e1";
        let catalog = catalog_for_chunk(&db, chunk_id, zip_fixture(&elf, None)).await;

        let slide_base = 0x7f0000000000u64;
        // 0x10645: after the -1 adjustment the lookup lands on 0x10644, inside
        // core::hint::black_box as inlined into checkout::payment::charge.
        let frame = RawFrame::Native(native_frame_at(slide_base + 0x10645, slide_base));
        let debug_images = vec![debug_image_at(chunk_id, slide_base)];

        let frames = frame.resolve(1, &catalog, &debug_images, 15).await.unwrap();

        assert_eq!(frames.len(), 2, "expected 2 frames, got: {frames:#?}");
        assert!(frames.iter().all(|f| f.resolved));

        // Outermost: our function, demangled from the rustc-mangled symbol
        assert_eq!(
            frames[0].resolved_name.as_deref(),
            Some("test_rust::checkout::payment::charge")
        );
        assert_eq!(frames[0].source.as_deref(), Some("test_rust.rs"));
        assert_eq!(frames[0].line, Some(9));
        assert_eq!(frames[0].lang, "rust");

        // Innermost: the std function inlined into it
        assert!(
            frames[1]
                .resolved_name
                .as_deref()
                .is_some_and(|n| n.contains("black_box")),
            "expected black_box, got {:?}",
            frames[1].resolved_name
        );
        assert_eq!(frames[1].lang, "rust");
    }

    /// Native frames resolve against `AppleDsym` containers too, so macOS
    /// binaries uploaded via `posthog-cli dsym upload` work without re-upload.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_native_resolves_apple_dsym_container(db: sqlx::PgPool) {
        use crate::frames::RawFrame;

        const DSYM_ZIP: &[u8] =
            include_bytes!("../../../../tests/static/apple/test_binary.dSYM.zip");
        let wrapped = posthog_symbol_data::write_symbol_data(posthog_symbol_data::AppleDsym {
            data: DSYM_ZIP.to_vec(),
        })
        .unwrap();

        let chunk_id = "f70b89dc-3eb9-d3aa-d6a0-3b0c87cb0c45";
        let catalog = catalog_for_chunk(&db, chunk_id, wrapped).await;

        // Same address facts as the apple test for this dSYM: 0x100000334 is
        // inside inner_function with the image loaded at 0x100000000.
        let frame = RawFrame::Native(native_frame_at(0x100000334, 0x100000000));
        let debug_images = vec![debug_image_at(chunk_id, 0x100000000)];

        let resolved = frame
            .resolve(1, &catalog, &debug_images, 15)
            .await
            .unwrap()
            .pop()
            .unwrap();

        assert!(resolved.resolved, "{:?}", resolved.resolve_failure);
        assert_eq!(resolved.resolved_name.as_deref(), Some("inner_function"));
    }

    /// Symbolication must be purely load-relative: `image_vmaddr` (the image's
    /// stated/preferred base) must NOT be added to the lookup address.
    ///
    /// `symbolic` rebases every symcache entry relative to the object's
    /// preferred base at conversion time, so the symcache is keyed by
    /// `svma - image_vmaddr`. The SDK already folds the preferred base into
    /// `image_addr` (it reports the *actual* runtime load address), so
    /// `instruction_addr - image_addr` recovers that same relative address and
    /// the `image_vmaddr` term cancels out. Re-adding it would push every
    /// lookup past the end of the symcache and break symbolication for all
    /// images with a nonzero preferred base — every macOS/iOS Mach-O binary and
    /// every non-PIE ELF.
    ///
    /// This exercises an ASLR-slid Mach-O image (nonzero `__TEXT` vmaddr *and* a
    /// nonzero slide, so `image_addr != image_vmaddr`) — the case no other test
    /// covers and the one a spurious `+ image_vmaddr` "fix" would silently break.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_native_symbolication_is_load_relative_with_nonzero_vmaddr(db: sqlx::PgPool) {
        use crate::frames::RawFrame;

        const DSYM_ZIP: &[u8] =
            include_bytes!("../../../../tests/static/apple/test_binary.dSYM.zip");
        let wrapped = posthog_symbol_data::write_symbol_data(posthog_symbol_data::AppleDsym {
            data: DSYM_ZIP.to_vec(),
        })
        .unwrap();

        let chunk_id = "f70b89dc-3eb9-d3aa-d6a0-3b0c87cb0c45";
        let catalog = catalog_for_chunk(&db, chunk_id, wrapped).await;

        // __TEXT preferred base 0x100000000, inner_function at relative 0x334.
        // Simulate an ASLR slide: the image actually loaded 0x1000000 higher, so
        // the SDK reports image_addr = actual base and image_vmaddr = stated base.
        let preferred_base = 0x100000000u64;
        let actual_base = preferred_base + 0x1000000;

        let frame = RawFrame::Native(native_frame_at(actual_base + 0x334, actual_base));
        let mut image = debug_image_at(chunk_id, actual_base);
        image.image_vmaddr = Some(format!("0x{preferred_base:x}"));
        let debug_images = vec![image];

        let resolved = frame
            .resolve(1, &catalog, &debug_images, 15)
            .await
            .unwrap()
            .pop()
            .unwrap();

        assert!(resolved.resolved, "{:?}", resolved.resolve_failure);
        assert_eq!(resolved.resolved_name.as_deref(), Some("inner_function"));
    }

    /// A Go-built binary: Go function naming, non-PIE link base, and
    /// mid-stack inline expansion (transform inlined into process).
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_native_go_symbolication_with_inline(db: sqlx::PgPool) {
        use crate::frames::RawFrame;

        const ELF_ZST: &[u8] = include_bytes!("../../../../tests/static/native/test_go_binary.zst");
        let elf = zstd::decode_all(ELF_ZST).unwrap();
        let chunk_id = "ebfd4909-422d-83e9-9d6b-eb2083ab3189";
        let catalog = catalog_for_chunk(&db, chunk_id, zip_fixture(&elf, None)).await;

        // Go links non-PIE at 0x400000 on linux/amd64 by default, so the
        // runtime image base equals the link-time base. 0x7e7a2 is inside
        // main.transform as inlined into main.process; the -1 adjustment
        // lands the lookup on 0x7e7a1.
        let image_base = 0x400000u64;
        let mut raw = native_frame_at(image_base + 0x7e7a2, image_base);
        raw.lang = Some("go".to_string());
        let frame = RawFrame::Native(raw);
        let debug_images = vec![debug_image_at(chunk_id, image_base)];

        let frames = frame.resolve(1, &catalog, &debug_images, 15).await.unwrap();

        assert_eq!(frames.len(), 2, "expected 2 frames, got: {frames:#?}");
        assert!(frames.iter().all(|f| f.resolved));

        // Outermost first: the physical function, then the inlined callee
        assert_eq!(frames[0].resolved_name.as_deref(), Some("main.process"));
        assert_eq!(frames[0].source.as_deref(), Some("test_go.go"));
        assert_eq!(frames[0].line, Some(10));
        assert_eq!(frames[0].lang, "go");

        assert_eq!(frames[1].resolved_name.as_deref(), Some("main.transform"));
        assert_eq!(frames[1].source.as_deref(), Some("test_go.go"));
        assert_eq!(frames[1].line, Some(16));
        assert_eq!(frames[1].lang, "go");
    }

    /// Missing symbol set: the frame falls back to client-side enrichment and
    /// records the failure reason instead of erroring the event.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_native_missing_symbol_set_falls_back(db: sqlx::PgPool) {
        use crate::frames::RawFrame;

        const ELF: &[u8] = include_bytes!("../../../../tests/static/native/test_binary_pie");
        let catalog = catalog_for_chunk(
            &db,
            "850c70a2-6592-a70c-3e49-c0e443794d23",
            zip_fixture(ELF, None),
        )
        .await;

        let base = 0x7f0000000000u64;
        let mut raw = native_frame_at(base + 0x14a8, base);
        raw.function = Some("client::resolved::name".to_string());
        raw.filename = Some("src/lib.rs".to_string());
        raw.lineno = Some(7);
        let frame = RawFrame::Native(raw);
        // The frame's image points at a debug_id that was never uploaded
        let debug_images = vec![debug_image_at("not-uploaded-debug-id", base)];

        let resolved = frame
            .resolve(1, &catalog, &debug_images, 15)
            .await
            .unwrap()
            .pop()
            .unwrap();

        assert!(!resolved.resolved);
        assert!(resolved.resolve_failure.is_some());
        assert_eq!(
            resolved.resolved_name.as_deref(),
            Some("client::resolved::name")
        );
        assert_eq!(resolved.source.as_deref(), Some("src/lib.rs"));
        assert_eq!(resolved.line, Some(7));
        assert_eq!(resolved.lang, "rust");
    }
}
