use std::sync::Arc;

use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    error::{AppleError, FrameError, ResolveError, UnhandledError},
    frames::Frame,
    langs::{utils::add_raw_to_junk, CommonFrameMetadata},
    symbol_store::{
        apple::{AppleRef, ParsedAppleSymbols},
        chunk_id::OrChunkId,
        SymbolCatalog,
    },
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AppleDebugImage {
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
    pub async fn resolve<C>(
        &self,
        team_id: i32,
        catalog: &C,
        debug_images: &[AppleDebugImage],
    ) -> Result<Frame, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<AppleRef>, ParsedAppleSymbols>,
    {
        tracing::info!("[apple-debug] resolve() called: instruction_addr={:?}, image_addr={:?}, image_uuid={:?}, module={:?}, debug_images_count={}",
            self.instruction_addr, self.image_addr, self.image_uuid, self.module, debug_images.len());
        match self.resolve_impl(team_id, catalog, debug_images).await {
            Ok(frame) => {
                tracing::info!("[apple-debug] resolve() SUCCESS: resolved_name={:?}, source={:?}, line={:?}",
                    frame.resolved_name, frame.source, frame.line);
                Ok(frame)
            }
            Err(ResolveError::ResolutionError(FrameError::Apple(e))) => {
                tracing::warn!("[apple-debug] resolve() Apple error: {:?}", e);
                Ok(self.handle_resolution_error(e))
            }
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => {
                tracing::warn!("[apple-debug] resolve() MissingChunkIdData: {}", chunk_id);
                Ok(self.handle_resolution_error(AppleError::MissingDsym(chunk_id)))
            }
            Err(ResolveError::ResolutionError(e)) => {
                unreachable!("Should not have received error {:?}", e)
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
        debug_images: &[AppleDebugImage],
    ) -> Result<Frame, ResolveError>
    where
        C: SymbolCatalog<OrChunkId<AppleRef>, ParsedAppleSymbols>,
    {
        let instruction_addr = self
            .instruction_addr
            .as_ref()
            .ok_or(AppleError::InvalidAddress("missing instruction_addr".into()))?;

        let instruction_addr = parse_hex_address(instruction_addr)?;
        tracing::info!("[apple-debug] resolve_impl: parsed instruction_addr=0x{:x}", instruction_addr);

        let debug_image = self.find_debug_image(instruction_addr, debug_images)?;
        tracing::info!("[apple-debug] resolve_impl: matched debug_image debug_id={}, image_addr={}", debug_image.debug_id, debug_image.image_addr);

        let relative_addr = self.calculate_relative_addr(instruction_addr, debug_image)?;
        tracing::info!("[apple-debug] resolve_impl: relative_addr=0x{:x}", relative_addr);

        tracing::info!("[apple-debug] resolve_impl: looking up symbols for chunk_id={}", debug_image.debug_id);
        let symbols: Arc<ParsedAppleSymbols> = catalog
            .lookup(
                team_id,
                OrChunkId::chunk_id(debug_image.debug_id.clone()),
            )
            .await?;
        tracing::info!("[apple-debug] resolve_impl: symbols loaded successfully");

        let symbol_info = symbols
            .lookup(relative_addr)?
            .ok_or(AppleError::SymbolNotFound(relative_addr))?;
        tracing::info!("[apple-debug] resolve_impl: found symbol={}, file={:?}, line={}", symbol_info.symbol, symbol_info.filename, symbol_info.line);

        Ok(self.build_resolved_frame(&symbol_info, debug_image))
    }

    fn find_debug_image<'a>(
        &self,
        instruction_addr: u64,
        debug_images: &'a [AppleDebugImage],
    ) -> Result<&'a AppleDebugImage, AppleError> {
        let frame_image_addr = self
            .image_addr
            .as_ref()
            .and_then(|addr| parse_hex_address(addr).ok());

        for image in debug_images {
            let image_base = parse_hex_address(&image.image_addr).ok();
            let image_size = image.image_size.unwrap_or(u64::MAX);

            if let (Some(frame_addr), Some(base)) = (frame_image_addr, image_base) {
                if frame_addr == base {
                    return Ok(image);
                }
            }

            if let Some(base) = image_base {
                if instruction_addr >= base && instruction_addr < base.saturating_add(image_size) {
                    return Ok(image);
                }
            }
        }

        Err(AppleError::NoMatchingDebugImage)
    }

    fn calculate_relative_addr(
        &self,
        instruction_addr: u64,
        debug_image: &AppleDebugImage,
    ) -> Result<u64, AppleError> {
        let image_addr = parse_hex_address(&debug_image.image_addr)?;

        // Calculate the offset from the runtime load address
        // The symcache already contains addresses relative to the binary's VM base,
        // so we just need the offset from where it was loaded
        Ok(instruction_addr - image_addr)
    }

    fn build_resolved_frame(
        &self,
        symbol_info: &crate::symbol_store::apple::SymbolInfo,
        _debug_image: &AppleDebugImage,
    ) -> Frame {
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: symbol_info.symbol.clone(),
            line: if symbol_info.line > 0 {
                Some(symbol_info.line)
            } else {
                None
            },
            column: None,
            source: if symbol_info.filename.is_empty() {
                None
            } else {
                Some(symbol_info.filename.clone())
            },
            in_app: self.meta.in_app,
            resolved_name: Some(symbol_info.symbol.clone()),
            lang: "apple".to_string(),
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
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: self.function.clone().unwrap_or_default(),
            line: self.lineno,
            column: self.colno,
            source: self.filename.clone(),
            in_app: self.meta.in_app,
            resolved_name: self.function.clone(),
            lang: "apple".to_string(),
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

        add_raw_to_junk(&mut f, self);
        f
    }

    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();

        if let Some(instruction_addr) = &self.instruction_addr {
            hasher.update(instruction_addr.as_bytes());
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

fn parse_hex_address(s: &str) -> Result<u64, AppleError> {
    let s = s.trim().trim_start_matches("0x").trim_start_matches("0X");
    u64::from_str_radix(s, 16).map_err(|_| AppleError::InvalidAddress(s.to_string()))
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
            lang: "apple".to_string(),
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
    fn test_calculate_relative_addr_with_vmaddr() {
        let frame = RawAppleFrame {
            instruction_addr: Some("0x100004000".to_string()),
            symbol_addr: None,
            image_addr: Some("0x100000000".to_string()),
            image_uuid: None,
            module: None,
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        };

        let debug_image = AppleDebugImage {
            debug_id: "test-uuid".to_string(),
            image_addr: "0x100000000".to_string(),
            image_vmaddr: Some("0x100000000".to_string()),
            image_size: Some(0x10000),
            code_file: None,
            image_type: None,
            arch: None,
        };

        let result = frame.calculate_relative_addr(0x100004000, &debug_image).unwrap();
        assert_eq!(result, 0x4000);
    }

    #[test]
    fn test_calculate_relative_addr_default_vmaddr() {
        let frame = RawAppleFrame {
            instruction_addr: Some("0x100004000".to_string()),
            symbol_addr: None,
            image_addr: Some("0x100000000".to_string()),
            image_uuid: None,
            module: None,
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        };

        let debug_image = AppleDebugImage {
            debug_id: "test-uuid".to_string(),
            image_addr: "0x100000000".to_string(),
            image_vmaddr: None,
            image_size: Some(0x10000),
            code_file: None,
            image_type: None,
            arch: None,
        };

        let result = frame.calculate_relative_addr(0x100004000, &debug_image).unwrap();
        assert_eq!(result, 0x4000);
    }

    #[test]
    fn test_find_debug_image_by_image_addr() {
        let frame = RawAppleFrame {
            instruction_addr: Some("0x100004000".to_string()),
            symbol_addr: None,
            image_addr: Some("0x100000000".to_string()),
            image_uuid: None,
            module: None,
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        };

        let debug_images = vec![
            AppleDebugImage {
                debug_id: "other-uuid".to_string(),
                image_addr: "0x200000000".to_string(),
                image_vmaddr: None,
                image_size: Some(0x10000),
                code_file: None,
                image_type: None,
                arch: None,
            },
            AppleDebugImage {
                debug_id: "matching-uuid".to_string(),
                image_addr: "0x100000000".to_string(),
                image_vmaddr: None,
                image_size: Some(0x10000),
                code_file: None,
                image_type: None,
                arch: None,
            },
        ];

        let result = frame.find_debug_image(0x100004000, &debug_images).unwrap();
        assert_eq!(result.debug_id, "matching-uuid");
    }

    #[test]
    fn test_find_debug_image_by_address_range() {
        let frame = RawAppleFrame {
            instruction_addr: Some("0x100004000".to_string()),
            symbol_addr: None,
            image_addr: None, // No image_addr on frame
            image_uuid: None,
            module: None,
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        };

        let debug_images = vec![AppleDebugImage {
            debug_id: "range-match".to_string(),
            image_addr: "0x100000000".to_string(),
            image_vmaddr: None,
            image_size: Some(0x10000),
            code_file: None,
            image_type: None,
            arch: None,
        }];

        let result = frame.find_debug_image(0x100004000, &debug_images).unwrap();
        assert_eq!(result.debug_id, "range-match");
    }

    #[test]
    fn test_find_debug_image_no_match() {
        let frame = RawAppleFrame {
            instruction_addr: Some("0x300000000".to_string()),
            symbol_addr: None,
            image_addr: None,
            image_uuid: None,
            module: None,
            function: None,
            filename: None,
            lineno: None,
            colno: None,
            meta: CommonFrameMetadata::default(),
        };

        let debug_images = vec![AppleDebugImage {
            debug_id: "some-uuid".to_string(),
            image_addr: "0x100000000".to_string(),
            image_vmaddr: None,
            image_size: Some(0x10000),
            code_file: None,
            image_type: None,
            arch: None,
        }];

        let result = frame.find_debug_image(0x300000000, &debug_images);
        assert!(matches!(result, Err(AppleError::NoMatchingDebugImage)));
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_apple_symbolication(db: sqlx::PgPool) {
        use std::sync::Arc;
        use chrono::Utc;
        use mockall::predicate;
        use uuid::Uuid;

        use crate::{
            config::Config,
            frames::RawFrame,
            symbol_store::{
                apple::AppleProvider, chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider,
                proguard::ProguardProvider, saving::SymbolSetRecord, sourcemap::SourcemapProvider,
                Catalog, MockS3Client,
            },
        };

        let team_id = 1;
        let mut config = Config::init_with_defaults().unwrap();
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
            .returning(|_, _| Ok(Some(get_dsym_bytes())));

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

        let catalog = Catalog::new(smp, hmp, pgp, apple);

        // Create a frame with instruction_addr pointing to inner_function
        // From dwarfdump output: inner_function is at 0x0000000100000328
        let raw_frame = RawAppleFrame {
            instruction_addr: Some("0x100000328".to_string()),
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

        let debug_images = vec![AppleDebugImage {
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
            .resolve(team_id, &catalog, &debug_images)
            .await
            .unwrap()
            .pop()
            .unwrap();

        assert!(resolved.resolved);
        assert_eq!(resolved.resolved_name, Some("inner_function".to_string()));
        assert!(resolved.source.is_some());
        assert!(resolved
            .source
            .as_ref()
            .unwrap()
            .contains("test_binary.c"));
        assert!(resolved.line.is_some());
    }

    fn get_dsym_bytes() -> Vec<u8> {
        use posthog_symbol_data::write_symbol_data;
        
        const DSYM_ZIP: &[u8] = include_bytes!("../../tests/static/apple/test_binary.dSYM.zip");
        write_symbol_data(posthog_symbol_data::AppleDsym {
            data: DSYM_ZIP.to_vec(),
        })
        .unwrap()
    }
}
