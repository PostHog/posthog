use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::Frame,
    langs::{utils::add_raw_to_junk, CommonFrameMetadata},
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawJavaFrame {
    pub filename: Option<String>, // The relative path of the file the context line is in
    pub function: String,         // The name of the function the exception came from
    pub lineno: Option<u32>,      // The line number of the context line
    pub module: String,           // The java-import style module name the function is in
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawJavaFrame {
    pub fn frame_id(&self) -> String {
        // We don't have version info for java frames, so we rely on
        // the module, function and line number to
        // uniquely identify a frame, with the intuition being that even
        // if two frames are from two different library versions, if the
        // files they're in are sufficiently similar we can consider
        // them to be the same frame
        let mut hasher = Sha512::new();
        if let Some(filename) = &self.filename {
            hasher.update(filename.as_bytes());
        }
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.module.as_bytes());
        format!("{:x}", hasher.finalize())
    }
}

impl From<&RawJavaFrame> for Frame {
    fn from(raw: &RawJavaFrame) -> Self {
        let mut f = Frame {
            raw_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno,
            column: None,
            source: raw.filename.clone(),
            in_app: raw.meta.in_app,
            resolved_name: Some(raw.function.clone()),
            lang: "java".to_string(),
            resolved: true,
            resolve_failure: None,
            junk_drawer: None,
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: Some(raw.module.clone()),
        };

        // Java frames will have a decent amount of processing, we're gonna want this
        // for debugging
        add_raw_to_junk(&mut f, raw);

        f
    }
}
