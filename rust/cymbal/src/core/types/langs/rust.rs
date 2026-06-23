use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{frames::Frame, langs::CommonFrameMetadata};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawRustFrame {
    pub function: Option<String>,
    pub filename: Option<String>,
    pub lineno: Option<u32>,
    pub colno: Option<u32>,
    pub module: Option<String>,
    #[serde(default)]
    pub resolved: bool,
    #[serde(flatten)]
    meta: CommonFrameMetadata,
}

impl RawRustFrame {
    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();

        self.filename
            .as_ref()
            .inspect(|f| hasher.update(f.as_bytes()));
        hasher.update(self.function.as_deref().unwrap_or_default().as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.colno.unwrap_or_default().to_be_bytes());
        hasher.update(b"rust");
        self.module
            .as_ref()
            .inspect(|m| hasher.update(m.as_bytes()));
        format!("{:x}", hasher.finalize())
    }
}

impl From<&RawRustFrame> for Frame {
    fn from(value: &RawRustFrame) -> Self {
        let function = value.function.clone().unwrap_or_default();

        Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: function,
            line: value.lineno,
            column: value.colno,
            source: value.filename.clone(),
            in_app: value.meta.in_app,
            resolved_name: value.function.clone(),
            lang: "rust".to_string(),
            resolved: value.resolved,
            resolve_failure: None,

            junk_drawer: None,
            context: None,
            release: None,
            synthetic: value.meta.synthetic,
            suspicious: false,
            module: value.module.clone(),
            code_variables: None,
        }
    }
}
