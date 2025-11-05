use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{frames::Frame, langs::CommonFrameMetadata};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RawGoFrame {
    filename: String,
    function: String,
    lineno: u32,
    #[serde(flatten)]
    meta: CommonFrameMetadata,
}

impl RawGoFrame {
    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();
        hasher.update(self.filename.as_bytes());
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.to_be_bytes());
        format!("{:x}", hasher.finalize())
    }
}

impl From<&RawGoFrame> for Frame {
    fn from(frame: &RawGoFrame) -> Self {
        Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: frame.function.clone(),
            line: Some(frame.lineno),
            column: None,
            source: Some(frame.filename.clone()),
            in_app: frame.meta.in_app,
            resolved_name: Some(frame.function.clone()),
            lang: "go".to_string(),
            resolved: true,
            resolve_failure: None,
            synthetic: frame.meta.synthetic,
            junk_drawer: None,
            context: None,
            release: None,
            suspicious: false,
            module: None,
            exception_type: None,
        }
    }
}
