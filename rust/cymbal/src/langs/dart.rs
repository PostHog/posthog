use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::Frame,
    langs::{utils::add_raw_to_junk, CommonFrameMetadata},
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawDartFrame {
    pub filename: Option<String>,
    pub function: Option<String>,
    pub lineno: Option<u32>,
    pub colno: Option<u32>,
    pub abs_path: String,
    pub package: Option<String>,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawDartFrame {
    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();
        if let Some(filename) = &self.filename {
            hasher.update(filename.as_bytes());
        }
        if let Some(package) = &self.package {
            hasher.update(package.as_bytes());
        }
        hasher.update(self.function.clone().unwrap_or_default().as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.colno.unwrap_or_default().to_be_bytes());
        format!("{:x}", hasher.finalize())
    }
}

impl From<&RawDartFrame> for Frame {
    fn from(raw: &RawDartFrame) -> Self {
        let mut f = Frame {
            raw_id: FrameId::placeholder(),
            mangled_name: raw.function.clone().unwrap_or_default(),
            line: raw.lineno,
            column: raw.colno,
            source: Some(raw.abs_path.clone()),
            in_app: raw.meta.in_app,
            resolved_name: Some(raw.function.clone().unwrap_or_default()), // Assuming no obfuscation for now
            lang: "dart".to_string(),
            resolved: true,
            resolve_failure: None,
            junk_drawer: None,
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: None,
        };

        add_raw_to_junk(&mut f, raw);
        f
    }
}
