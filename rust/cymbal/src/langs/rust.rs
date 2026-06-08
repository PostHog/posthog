use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::{Context, ContextLine, Frame},
    langs::CommonFrameMetadata,
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawRustFrame {
    pub function: String,
    pub filename: Option<String>,
    pub lineno: Option<u32>,
    pub colno: Option<u32>,
    pub module: Option<String>,
    pub context_line: Option<String>,
    #[serde(default)]
    pub pre_context: Vec<String>,
    #[serde(default)]
    pub post_context: Vec<String>,
    #[serde(default)]
    pub resolved: bool,
    #[serde(flatten)]
    meta: CommonFrameMetadata,
}

impl RawRustFrame {
    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();

        self.context_line
            .as_ref()
            .inspect(|c| hasher.update(c.as_bytes()));
        self.filename
            .as_ref()
            .inspect(|f| hasher.update(f.as_bytes()));
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.colno.unwrap_or_default().to_be_bytes());
        hasher.update(b"rust");
        hasher.update(self.resolved.to_string().as_bytes());
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
            .take(10)
            .enumerate()
            .map(|(i, line)| ContextLine::new_rel(lineno, -(i as i32) - 1, line.clone()))
            .collect();
        let after = self
            .post_context
            .iter()
            .take(10)
            .enumerate()
            .map(|(i, line)| ContextLine::new_rel(lineno, i as i32 + 1, line.clone()))
            .collect();
        Some(Context {
            before,
            line,
            after,
        })
    }
}

impl From<&RawRustFrame> for Frame {
    fn from(value: &RawRustFrame) -> Self {
        Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: value.function.clone(),
            line: value.lineno,
            column: value.colno,
            source: value.filename.clone(),
            in_app: value.meta.in_app,
            resolved_name: Some(value.function.clone()),
            lang: "rust".to_string(),
            resolved: value.resolved,
            resolve_failure: None,

            junk_drawer: None,
            context: value.get_context(),
            release: None,
            synthetic: value.meta.synthetic,
            suspicious: false,
            module: value.module.clone(),
            code_variables: None,
        }
    }
}
