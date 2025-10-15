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
    pub function: String,
    pub lineno: Option<u32>,
    pub colno: Option<u32>,
    pub module: String,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawDartFrame {
    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();
        if let Some(filename) = &self.filename {
            hasher.update(filename.as_bytes());
        }
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.colno.unwrap_or_default().to_be_bytes());
        hasher.update(self.module.as_bytes());
        format!("{:x}", hasher.finalize())
    }
}

impl From<&RawDartFrame> for Frame {
    fn from(raw: &RawDartFrame) -> Self {
        let source = raw
            .filename
            .as_ref()
            .map(|s| format!("{}:{}", raw.module, s))
            .unwrap_or_else(|| raw.module.clone());

        let mut f = Frame {
            raw_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno,
            column: raw.colno,
            source: Some(source),
            in_app: raw.meta.in_app,
            resolved_name: Some(raw.function.clone()), // dart function names already human-readable
            lang: "dart".to_string(),
            resolved: true,
            resolve_failure: None,
            junk_drawer: None,
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
        };

        add_raw_to_junk(&mut f, raw);
        f
    }
}
