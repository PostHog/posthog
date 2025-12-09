use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::Frame,
    langs::{utils::add_raw_to_junk, CommonFrameMetadata},
};

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
