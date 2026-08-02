use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::{Context, ContextLine, Frame},
    langs::CommonFrameMetadata,
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawPHPFrame {
    #[serde(rename = "abs_path")]
    pub path: Option<String>,
    pub context_line: Option<String>,
    pub filename: Option<String>,
    pub function: Option<String>,
    pub lineno: Option<u32>,
    #[serde(default)]
    pub pre_context: Vec<String>,
    #[serde(default)]
    pub post_context: Vec<String>,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawPHPFrame {
    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();
        self.context_line
            .as_ref()
            .inspect(|c| hasher.update(c.as_bytes()));
        self.filename
            .as_ref()
            .inspect(|f| hasher.update(f.as_bytes()));
        self.function
            .as_ref()
            .inspect(|f| hasher.update(f.as_bytes()));
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
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
            .rev()
            .enumerate()
            .map(|(i, line)| ContextLine::new_rel(lineno, -(i as i32) - 1, line.clone()))
            .collect();
        let after = self
            .post_context
            .iter()
            .enumerate()
            .map(|(i, line)| ContextLine::new_rel(lineno, (i as i32) + 1, line.clone()))
            .collect();
        Some(Context {
            before,
            line,
            after,
        })
    }

    fn mangled_name(&self) -> String {
        self.function
            .clone()
            .unwrap_or_else(|| "<unknown>".to_string())
    }
}

impl From<&RawPHPFrame> for Frame {
    fn from(raw: &RawPHPFrame) -> Self {
        Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.mangled_name(),
            line: raw.lineno,
            column: None,
            source: raw.filename.clone(),
            in_app: raw.meta.in_app,
            resolved_name: raw.function.clone(),
            lang: "php".to_string(),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            context: raw.get_context(),
            release: None,
            synthetic: raw.meta.synthetic,
            suspicious: false,
            module: None,
            code_variables: None,
        }
    }
}
