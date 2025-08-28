use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::{Context, ContextLine, Frame},
    langs::CommonFrameMetadata,
};

// Generic frame layout, meant for users hacking up their own implementations
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CustomFrame {
    pub lang: String,                 // The platform/language, e.g. "elixir"
    pub function: String,             // The name of the function
    pub filename: Option<String>,     // The path of the file the context line is in
    pub lineno: Option<u32>,          // The line number of the frame/function
    pub colno: Option<u32>,           // The column number of the frame/function
    pub module: Option<String>,       // Whatever language-specific "module" name the function is in
    pub context_line: Option<String>, // The line of code the exception came from

    // The lines of code before the context line
    // The first line prior to the context line is at index 0
    #[serde(default)]
    pub pre_context: Vec<String>,
    #[serde(default)]
    pub post_context: Vec<String>, // The lines of code after the context line
    #[serde(default)]
    pub resolved: bool, // Whether the frame has been resolved, or is minified/mangled
    #[serde(flatten)]
    meta: CommonFrameMetadata,
}

impl CustomFrame {
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
        hasher.update(self.lang.as_bytes());
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
            .map(|(i, line)| ContextLine::new(lineno - i as u32 - 1, line.clone()))
            .collect();
        let after = self
            .post_context
            .iter()
            .take(10)
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

impl From<&CustomFrame> for Frame {
    fn from(value: &CustomFrame) -> Self {
        Frame {
            raw_id: String::new(),
            mangled_name: value.function.clone(),
            line: value.lineno,
            column: value.colno,
            source: value.filename.clone(),
            in_app: value.meta.in_app,
            resolved_name: Some(value.function.clone()),
            lang: value.lang.clone(),
            resolved: value.resolved,
            resolve_failure: None,
            junk_drawer: None,
            context: value.get_context(),
            release: None,
            synthetic: value.meta.synthetic,
        }
    }
}
