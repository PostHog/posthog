use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::{Context, ContextLine, Frame},
    langs::CommonFrameMetadata,
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawPythonFrame {
    #[serde(rename = "abs_path")]
    pub path: Option<String>, // Absolute path to the file - unused for now
    pub context_line: Option<String>, // The line of code the exception came from
    pub filename: String,             // The relative path of the file the context line is in
    pub function: String,             // The name of the function the exception came from
    pub lineno: Option<u32>,          // The line number of the context line
    pub module: Option<String>,       // The python-import style module name the function is in
    #[serde(default)]
    pub pre_context: Vec<String>, // The lines of code before the context line
    #[serde(default)]
    pub post_context: Vec<String>, // The lines of code after the context line
    pub code_variables: Option<serde_json::Value>,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawPythonFrame {
    pub fn frame_id(&self) -> String {
        // We don't have version info for python frames, so we rely on
        // the module, function, line number and surrounding context to
        // uniquely identify a frame, with the intuition being that even
        // if two frames are from two different library versions, if the
        // files they're in are sufficiently similar we can consider
        // them to be the same frame
        let mut hasher = Sha512::new();
        self.context_line
            .as_ref()
            .inspect(|c| hasher.update(c.as_bytes()));
        hasher.update(self.filename.as_bytes());
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        self.module
            .as_ref()
            .inspect(|m| hasher.update(m.as_bytes()));
        self.pre_context
            .iter()
            .chain(self.post_context.iter())
            .for_each(|line| {
                hasher.update(line.as_bytes());
            });
        format!("{:x}", hasher.finalize())
    }

    pub fn get_context(&self) -> Option<Context> {
        let context_line = self.context_line.as_ref()?;
        let lineno = self.lineno?;

        let line = ContextLine::new(lineno, context_line);

        let before = self
            .pre_context
            .iter()
            .enumerate()
            .map(|(i, line)| ContextLine::new(lineno - i as u32 - 1, line.clone()))
            .collect();
        let after = self
            .post_context
            .iter()
            .enumerate()
            .map(|(i, line)| ContextLine::new(lineno + i as u32 + 1, line.clone()))
            .collect();
        Some(Context {
            before,
            line,
            after,
        })
    }
}

impl From<&RawPythonFrame> for Frame {
    fn from(raw: &RawPythonFrame) -> Self {
        Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno,
            column: None,
            source: Some(raw.filename.clone()),
            in_app: raw.meta.in_app,
            resolved_name: Some(raw.function.clone()),
            lang: "python".to_string(),
            resolved: true,
            resolve_failure: None,
            junk_drawer: None,
            context: raw.get_context(),
            release: None,
            synthetic: raw.meta.synthetic,
            suspicious: false,
            module: raw.module.clone(),
            exception_type: None,
            code_variables: raw.code_variables.clone(),
        }
    }
}
