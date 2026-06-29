use std::sync::Arc;

use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use symbolic::common::Name;
use symbolic::demangle::{Demangle, DemangleOptions};

use crate::{
    error::{AppleError, FrameError, ResolveError, UnhandledError},
    frames::{record_frame_resolution_failure, Frame},
    langs::native::{self, DebugImage},
    langs::utils::{add_raw_to_junk, get_context_lines},
    langs::CommonFrameMetadata,
    symbolication::symbol_store::{
        apple::AppleRef,
        chunk_id::OrChunkId,
        native::{ParsedNativeSymbols, SymbolInfo},
        SymbolCatalog,
    },
};

/// Known Apple system framework prefixes - frames from these modules are marked as not in_app
const APPLE_SYSTEM_MODULES: &[&str] = &[
    "Foundation",
    "UIKit",
    "CoreFoundation",
    "SwiftUI",
    "Combine",
    "CoreGraphics",
    "QuartzCore",
    "Security",
    "CFNetwork",
    "CoreData",
    "CoreLocation",
    "AVFoundation",
    "Metal",
    "MetalKit",
    "AppKit",
    "WebKit",
    "IOKit",
    "GraphicsServices",
    // Private/internal Apple frameworks
    "UpdateCycle",
    "UIKitCore",
    "UIKitServices",
    "UIFoundation",
    "FrontBoardServices",
    "BackBoardServices",
    "SpringBoardServices",
    "BaseBoard",
    "AttributeGraph",
    "SwiftUICore",
    // System libraries
    "libsystem_",
    "libdispatch",
    "libswift",
    "libobjc",
    "libxpc",
    "libdyld",
];

fn is_system_module(module: &Option<String>) -> bool {
    module.as_ref().is_some_and(|m| {
        APPLE_SYSTEM_MODULES
            .iter()
            .any(|prefix| m.starts_with(prefix))
    })
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawAppleFrame {
    pub instruction_addr: Option<String>,
    pub symbol_addr: Option<String>,
    pub image_addr: Option<String>,
    pub image_uuid: Option<String>,
    pub module: Option<String>,
    pub function: Option<String>,
    pub filename: Option<String>,
    pub lineno: Option<u32>,
    pub colno: Option<u32>,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawAppleFrame {
    pub async fn resolve_frame<C>(
        &self,
        team_id: i32,
        catalog: &C,
        debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<AppleRef>, ParsedNativeSymbols>,
    {
        tracing::debug!(
            "[apple-debug] resolve() called: instruction_addr={:?}, module={:?}, function={:?}, debug_images_count={}",
            self.instruction_addr, self.module, self.function, debug_images.len()
        );

        match self
            .resolve_impl(team_id, catalog, debug_images, context_lines)
            .await
        {
            Ok(frames) => {
                tracing::debug!(
                    "[apple-debug] resolve() SUCCESS: {} frame(s), first resolved_name={:?}",
                    frames.len(),
                    frames.first().and_then(|f| f.resolved_name.as_deref())
                );
                Ok(frames)
            }
            Err(ResolveError::ResolutionError(FrameError::Apple(e))) => {
                tracing::debug!("[apple-debug] resolve() Apple error: {:?}", e);
                Ok(vec![self.handle_resolution_error(e)])
            }
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => {
                tracing::debug!("[apple-debug] resolve() MissingChunkIdData: {}", chunk_id);
                Ok(vec![self.handle_resolution_error(AppleError::MissingDsym(
                    chunk_id,
                ))])
            }
            Err(ResolveError::ResolutionError(e)) => {
                tracing::warn!("Unexpected Apple symbol resolution error: {:?}", e);
                Ok(vec![self.handle_resolution_error(AppleError::ParseError(
                    e.to_string(),
                ))])
            }
            Err(ResolveError::UnhandledError(e)) => {
                tracing::error!("[apple-debug] resolve() unhandled error: {:?}", e);
                Err(e)
            }
        }
    }

    async fn resolve_impl<C>(
        &self,
        team_id: i32,
        catalog: &C,
        debug_images: &[DebugImage],
        context_lines: usize,
    ) -> Result<Vec<Frame>, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<AppleRef>, ParsedNativeSymbols>,
    {
        let instruction_addr = self
            .instruction_addr
            .as_ref()
            .ok_or(AppleError::InvalidAddress(
                "missing instruction_addr".into(),
            ))?;

        let instruction_addr =
            native::parse_hex_address(instruction_addr).map_err(AppleError::from)?;
        tracing::debug!(
            "[apple-debug] resolve_impl: parsed instruction_addr=0x{:x}",
            instruction_addr
        );

        let debug_image =
            native::find_debug_image(instruction_addr, self.image_addr.as_deref(), debug_images)
                .map_err(AppleError::from)?;
        tracing::debug!(
            "[apple-debug] resolve_impl: matched debug_image debug_id={}, image_addr={}",
            debug_image.debug_id,
            debug_image.image_addr
        );

        let relative_addr = native::calculate_relative_addr(instruction_addr, debug_image)
            .map_err(AppleError::from)?;

        // Subtract 1 from return-address frames so the lookup targets the call instruction
        // rather than the instruction after it, giving the correct source line.
        // This is safe for top (crash-site) frames too: addr-1 still falls within the
        // same function body, so the function and line resolve correctly.
        let lookup_addr = relative_addr.saturating_sub(1);
        tracing::debug!(
            "[apple-debug] resolve_impl: relative_addr=0x{:x}, lookup_addr=0x{:x}",
            relative_addr,
            lookup_addr
        );

        tracing::debug!(
            "[apple-debug] resolve_impl: looking up symbols for chunk_id={}",
            debug_image.debug_id
        );
        let symbols: Arc<ParsedNativeSymbols> = catalog
            .lookup(team_id, OrChunkId::chunk_id(debug_image.debug_id.clone()))
            .await?;
        tracing::debug!("[apple-debug] resolve_impl: symbols loaded successfully");

        let symbol_infos = symbols.lookup(lookup_addr).map_err(AppleError::from)?;
        if symbol_infos.is_empty() {
            return Err(AppleError::SymbolNotFound(lookup_addr).into());
        }
        tracing::debug!(
            "[apple-debug] resolve_impl: found {} logical frame(s) (including inlined)",
            symbol_infos.len()
        );

        // Build one resolved Frame per logical layer.
        //
        // The symcache returns layers innermost-first:
        //   [inlined_leaf, mid_inline, physical_function]
        //
        // We reverse to outermost-first so that when the caller flattens all
        // per-raw-frame Vecs, the overall stack stays in bottom-up order
        // (main first, crash site last).
        let frames: Vec<Frame> = symbol_infos
            .iter()
            .rev()
            .map(|info| {
                let mut frame = self.build_resolved_frame(info, debug_image);

                // Attach source context to every inlined layer independently.
                // Each layer has its own line number, and each gets a unique
                // FrameId via the /part suffix, so there is no risk of
                // clobbering another layer's context.
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

    fn build_resolved_frame(&self, symbol_info: &SymbolInfo, _debug_image: &DebugImage) -> Frame {
        // Override in_app to false for system frameworks or compiler-generated code
        let is_compiler_generated = symbol_info
            .filename
            .as_ref()
            .is_some_and(|f| f == "<compiler-generated>");
        let in_app = if is_system_module(&self.module) || is_compiler_generated {
            false
        } else {
            self.meta.in_app
        };

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
            in_app,
            resolved_name: Some(symbol_info.display_name.clone()),
            lang: lang_from_filename(symbol_info.filename.as_deref()).to_string(),
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

    fn handle_resolution_error(&self, err: AppleError) -> Frame {
        record_frame_resolution_failure("apple", err.metric_reason(), &err);

        // Demangle the raw function name if present
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

        // Override in_app to false for system frameworks or compiler-generated code
        let is_compiler_generated = self
            .filename
            .as_ref()
            .is_some_and(|f| f == "<compiler-generated>");
        let in_app = if is_system_module(&self.module) || is_compiler_generated {
            false
        } else {
            self.meta.in_app
        };

        // For unresolved frames without a filename, show "Module +image_addr" as source.
        // This is typically for Apple system frameworks (CoreFoundation, UIKitCore, etc.)
        // where we don't have dSYMs. Apple doesn't publicly distribute system symbols.
        //
        // Future work: To fully symbolicate system frames, we'd need to extract and host
        // Apple system symbols similar to Sentry's approach:
        // - Extract symbols from Xcode's iOS DeviceSupport or IPSW archives
        // - Host them in our symbol store
        // - See: https://github.com/getsentry/apple-system-symbols-upload
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
            in_app,
            resolved_name,
            lang: lang_from_filename(self.filename.as_deref()).to_string(),
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

    /// The uploaded dSYM this frame resolves against, identified by the matched
    /// debug image's `debug_id` (the chunk_id used at upload). None when no
    /// debug image matches the address, so there is no symbol set to link.
    pub fn symbol_set_ref(&self, debug_images: &[DebugImage]) -> Option<String> {
        native::launch_invariant_addr(
            self.instruction_addr.as_deref(),
            self.image_addr.as_deref(),
            debug_images,
        )
        .map(|(debug_id, _)| debug_id)
    }

    pub fn frame_id(&self, debug_images: &[DebugImage]) -> String {
        let mut hasher = Sha512::new();

        // Absolute instruction addresses are ASLR-slid per process launch, so hashing
        // them directly gives the same logical frame a different id every launch and
        // the frame record cache never hits. Hash the launch-invariant
        // (debug image, relative offset) identity instead whenever we can compute it.
        match native::launch_invariant_addr(
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

        if let Some(module) = &self.module {
            hasher.update(module.as_bytes());
        }

        if let Some(function) = &self.function {
            hasher.update(function.as_bytes());
        }

        if let Some(image_uuid) = &self.image_uuid {
            hasher.update(image_uuid.as_bytes());
        }

        format!("{:x}", hasher.finalize())
    }
}

/// Infer the programming language from a source filename for syntax highlighting.
/// Returns a markdown-compatible language identifier.
fn lang_from_filename(filename: Option<&str>) -> &'static str {
    match filename.and_then(|f| f.rsplit('.').next()) {
        Some("swift") => "swift",
        Some("m") => "objectivec",
        Some("mm") => "objectivecpp",
        Some("c") => "c",
        Some("cpp" | "cc" | "cxx") => "cpp",
        Some("h") => "c", // headers default to C
        _ => "swift",     // default for Apple platforms
    }
}

impl From<&RawAppleFrame> for Frame {
    fn from(raw: &RawAppleFrame) -> Self {
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone().unwrap_or_default(),
            line: raw.lineno,
            column: raw.colno,
            source: raw.filename.clone(),
            in_app: raw.meta.in_app,
            resolved_name: raw.function.clone(),
            lang: lang_from_filename(raw.filename.as_deref()).to_string(),
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

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_apple_symbolication(db: sqlx::PgPool) {
        use chrono::Utc;
        use mockall::predicate;
        use std::sync::Arc;
        use uuid::Uuid;

        use crate::{
            core::config::ResolverConfig,
            frames::RawFrame,
            symbolication::symbol_store::{
                apple::AppleProvider, chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider,
                native::NativeProvider, proguard::ProguardProvider, saving::SymbolSetRecord,
                sourcemap::SourcemapProvider, Catalog, MockS3Client,
            },
        };

        let team_id = 1;
        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();

        let chunk_id = Uuid::now_v7().to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref: chunk_id.clone(),
            storage_ptr: Some(chunk_id.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };

        record.save(&db).await.unwrap();

        let mut client = MockS3Client::default();

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(chunk_id.clone()),
            )
            .returning(|_, _| Ok(Some(bytes::Bytes::from(get_dsym_bytes()))));

        let client = Arc::new(client);

        let smp = SourcemapProvider::new(&config);
        let smp = ChunkIdFetcher::new(
            smp,
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let hmp = HermesMapProvider {};
        let hmp = ChunkIdFetcher::new(
            hmp,
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let pgp = ChunkIdFetcher::new(
            ProguardProvider {},
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let apple = ChunkIdFetcher::new(
            AppleProvider {},
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let native = ChunkIdFetcher::new(
            NativeProvider {},
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let catalog = Catalog::new(smp, hmp, pgp, apple, native);

        // Use 0x100000334 (line 7 of inner_function, "(void)x").
        // After the -1 call-site adjustment (0x334 - 1 = 0x333), the symcache
        // lookup still falls inside inner_function and resolves correctly.
        // Avoid using 0x100000328 (the very first instruction) because addr-1
        // would land before the function start.
        let raw_frame = RawAppleFrame {
            instruction_addr: Some("0x100000334".to_string()),
            symbol_addr: None,
            image_addr: Some("0x100000000".to_string()),
            image_uuid: Some(chunk_id.clone()),
            module: Some("test_binary".to_string()),
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        };

        let debug_images = vec![DebugImage {
            debug_id: chunk_id.clone(),
            image_addr: "0x100000000".to_string(),
            image_vmaddr: Some("0x100000000".to_string()),
            image_size: Some(0x10000),
            code_file: Some("test_binary".to_string()),
            image_type: Some("macho".to_string()),
            arch: Some("arm64".to_string()),
        }];

        let frame = RawFrame::Apple(raw_frame);
        let resolved = frame
            .resolve(team_id, &catalog, &debug_images, 15)
            .await
            .unwrap()
            .pop()
            .unwrap();

        assert!(resolved.resolved);
        assert_eq!(resolved.resolved_name, Some("inner_function".to_string()));
        assert!(resolved.source.is_some());
        assert!(resolved.source.as_ref().unwrap().contains("test_binary.c"));
        assert!(resolved.line.is_some());
    }

    fn get_dsym_bytes() -> Vec<u8> {
        use posthog_symbol_data::write_symbol_data;

        const DSYM_ZIP: &[u8] =
            include_bytes!("../../../../tests/static/apple/test_binary.dSYM.zip");
        write_symbol_data(posthog_symbol_data::AppleDsym {
            data: DSYM_ZIP.to_vec(),
        })
        .unwrap()
    }

    fn get_inline_dsym_bytes() -> Vec<u8> {
        use posthog_symbol_data::write_symbol_data;

        // This ZIP was built from test_binary_inline.c compiled with:
        //   -fdebug-prefix-map=$(srcdir)=/cymbal_tests/apple
        // so DWARF paths are stable across machines (always /cymbal_tests/apple/...).
        // The ZIP includes __source/manifest.json and the source file content,
        // enabling source-context tests without requiring the file to exist on disk.
        const DSYM_ZIP: &[u8] =
            include_bytes!("../../../../tests/static/apple/test_binary_inline.dSYM.zip");
        write_symbol_data(posthog_symbol_data::AppleDsym {
            data: DSYM_ZIP.to_vec(),
        })
        .unwrap()
    }

    /// Verify that a single raw frame at an address inside an inlined function expands
    /// into multiple resolved frames: one per logical layer (inlined + physical).
    ///
    /// Source layout of `test_binary_inline.c`:
    ///   inlined_leaf()    — always_inline, lines 4-8 (`volatile int x = 99` at line 6)
    ///   inner_function()  — calls inlined_leaf (line 12); inlined_leaf is inlined here
    ///   outer_function()  — calls inner_function (line 17); both get inlined here
    ///
    /// Address 0x10000034c is inside the body of inlined_leaf as inlined into
    /// outer_function (via inner_function). Lookup of 0x34c-1=0x34b resolves to
    /// three logical frames: inlined_leaf → inner_function → outer_function.
    ///
    /// The test ZIP includes source files with DWARF paths remapped to the stable
    /// prefix `/cymbal_tests/apple/`, so source context is verified end-to-end.
    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_apple_inlined_frame_expansion(db: sqlx::PgPool) {
        use chrono::Utc;
        use mockall::predicate;
        use std::sync::Arc;
        use uuid::Uuid;

        use crate::{
            core::config::ResolverConfig,
            frames::RawFrame,
            symbolication::symbol_store::{
                apple::AppleProvider, chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider,
                native::NativeProvider, proguard::ProguardProvider, saving::SymbolSetRecord,
                sourcemap::SourcemapProvider, Catalog, MockS3Client,
            },
        };

        let team_id = 1;
        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();

        let chunk_id = Uuid::now_v7().to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref: chunk_id.clone(),
            storage_ptr: Some(chunk_id.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };
        record.save(&db).await.unwrap();

        let mut client = MockS3Client::default();
        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(chunk_id.clone()),
            )
            .returning(|_, _| Ok(Some(bytes::Bytes::from(get_inline_dsym_bytes()))));
        let client = Arc::new(client);

        let catalog = Catalog::new(
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
        );

        // 0x10000034c is inside inlined_leaf as inlined into outer_function.
        // After the -1 call-site adjustment (0x34c - 1 = 0x34b), the symcache
        // should expand this into three logical frames:
        //   outermost (returned first from our Vec): outer_function
        //   middle:                                  inner_function
        //   innermost (returned last):               inlined_leaf
        let raw_frame = RawAppleFrame {
            instruction_addr: Some("0x10000034c".to_string()),
            symbol_addr: None,
            image_addr: Some("0x100000000".to_string()),
            image_uuid: Some(chunk_id.clone()),
            module: Some("test_binary_inline".to_string()),
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        };

        let debug_images = vec![DebugImage {
            debug_id: chunk_id.clone(),
            image_addr: "0x100000000".to_string(),
            image_vmaddr: Some("0x100000000".to_string()),
            image_size: Some(0x10000),
            code_file: Some("test_binary_inline".to_string()),
            image_type: Some("macho".to_string()),
            arch: Some("arm64".to_string()),
        }];

        let frames = RawFrame::Apple(raw_frame)
            .resolve(team_id, &catalog, &debug_images, 15)
            .await
            .unwrap();

        // Three logical frames from one physical address
        assert_eq!(
            frames.len(),
            3,
            "expected 3 frames (inlined expansion), got: {:#?}",
            frames
        );

        // All must be resolved
        assert!(frames.iter().all(|f| f.resolved));

        // Bottom-up order: outermost first, innermost last
        assert_eq!(frames[0].resolved_name, Some("outer_function".to_string()));
        assert_eq!(frames[1].resolved_name, Some("inner_function".to_string()));
        assert_eq!(frames[2].resolved_name, Some("inlined_leaf".to_string()));

        // Source file populated
        assert!(frames.iter().all(|f| f
            .source
            .as_ref()
            .is_some_and(|s| s.contains("test_binary_inline.c"))));

        // Source context populated for every frame — the ZIP includes source
        // files, so all three layers should have context lines.
        for (i, frame) in frames.iter().enumerate() {
            assert!(
                frame.context.is_some(),
                "frame[{i}] ({:?}) has no source context",
                frame.resolved_name
            );
        }

        // The innermost frame (inlined_leaf) should have the `volatile int x = 99` line.
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

    fn frame_at(instruction_addr: u64, image_addr: u64) -> RawAppleFrame {
        RawAppleFrame {
            instruction_addr: Some(format!("0x{instruction_addr:x}")),
            symbol_addr: None,
            image_addr: Some(format!("0x{image_addr:x}")),
            image_uuid: None,
            module: Some("MyApp".to_string()),
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        }
    }

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
    fn symbol_set_ref_is_matched_debug_id() {
        let frame = frame_at(0x100004000, 0x100000000);
        let images = [image_at("dsym-uuid-1", 0x100000000)];
        assert_eq!(
            frame.symbol_set_ref(&images),
            Some("dsym-uuid-1".to_string())
        );
        // No matching debug image -> no symbol set to link.
        assert_eq!(frame.symbol_set_ref(&[]), None);
    }

    #[test]
    fn test_frame_id_stable_across_aslr_slides() {
        // Same logical frame (same image, same relative offset) from two launches
        // with different ASLR slides must produce the same frame id.
        let launch_a = frame_at(0x100004000, 0x100000000);
        let launch_b = frame_at(0x104f04000, 0x104f00000);

        let id_a = launch_a.frame_id(&[image_at("uuid-build-1", 0x100000000)]);
        let id_b = launch_b.frame_id(&[image_at("uuid-build-1", 0x104f00000)]);

        assert_eq!(id_a, id_b);
    }

    #[test]
    fn test_frame_id_distinguishes_builds() {
        let launch_a = frame_at(0x100004000, 0x100000000);
        let launch_b = frame_at(0x100004000, 0x100000000);

        let id_a = launch_a.frame_id(&[image_at("uuid-build-1", 0x100000000)]);
        let id_b = launch_b.frame_id(&[image_at("uuid-build-2", 0x100000000)]);

        assert_ne!(id_a, id_b);
    }

    #[test]
    fn test_frame_id_distinguishes_call_sites_within_image() {
        let images = [image_at("uuid-build-1", 0x100000000)];

        let id_a = frame_at(0x100004000, 0x100000000).frame_id(&images);
        let id_b = frame_at(0x100004004, 0x100000000).frame_id(&images);

        assert_ne!(id_a, id_b);
    }

    #[test]
    fn test_frame_id_falls_back_to_absolute_addr_without_debug_image() {
        let launch_a = frame_at(0x100004000, 0x100000000);
        let launch_b = frame_at(0x104f04000, 0x104f00000);

        assert_ne!(launch_a.frame_id(&[]), launch_b.frame_id(&[]));
    }
}
