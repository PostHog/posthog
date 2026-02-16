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
        match self.resolve_impl(team_id, catalog, debug_images).await {
            Ok(frame) => Ok(frame),
            Err(ResolveError::ResolutionError(FrameError::Apple(e))) => {
                Ok(self.handle_resolution_error(e))
            }
            Err(ResolveError::ResolutionError(FrameError::MissingChunkIdData(chunk_id))) => {
                Ok(self.handle_resolution_error(AppleError::MissingDsym(chunk_id)))
            }
            Err(ResolveError::ResolutionError(e)) => {
                unreachable!("Should not have received error {:?}", e)
            }
            Err(ResolveError::UnhandledError(e)) => Err(e),
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

        let debug_image = self.find_debug_image(instruction_addr, debug_images)?;

        let relative_addr = self.calculate_relative_addr(instruction_addr, debug_image)?;

        let symbols: Arc<ParsedAppleSymbols> = catalog
            .lookup(
                team_id,
                OrChunkId::chunk_id(debug_image.debug_id.clone()),
            )
            .await?;

        let symbol_info = symbols
            .lookup(relative_addr)?
            .ok_or(AppleError::SymbolNotFound(relative_addr))?;

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

        let image_vmaddr = debug_image
            .image_vmaddr
            .as_ref()
            .and_then(|v| parse_hex_address(v).ok())
            .unwrap_or(0x100000000); // Default for arm64 Mach-O

        Ok(instruction_addr - image_addr + image_vmaddr)
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
