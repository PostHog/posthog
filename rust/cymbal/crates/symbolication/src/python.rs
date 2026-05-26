use common_types::error_tracking::FrameId;
use cymbal_domain::{Context, ContextLine};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{CommonFrameMetadata, Frame, IntoFrame};

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
}

impl IntoFrame for &RawPythonFrame {
    fn into_frame(self) -> Frame {
        let raw = self;
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
            code_variables: raw.code_variables.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IntoFrame;

    fn make_raw() -> RawPythonFrame {
        RawPythonFrame {
            path: Some("/abs/path/app.py".to_string()),
            context_line: Some("  x = 1 + 2".to_string()),
            filename: "app.py".to_string(),
            function: "my_func".to_string(),
            lineno: Some(42),
            module: Some("myapp.views".to_string()),
            pre_context: vec!["def my_func():".to_string()],
            post_context: vec!["return x".to_string()],
            code_variables: Some(serde_json::json!({"x": "3"})),
            meta: CommonFrameMetadata {
                in_app: true,
                synthetic: false,
            },
        }
    }

    #[test]
    fn into_frame_fields_python() {
        let raw = make_raw();
        let frame = (&raw).into_frame();

        assert_eq!(frame.mangled_name, "my_func");
        assert_eq!(frame.resolved_name, Some("my_func".to_string()));
        assert_eq!(frame.lang, "python");
        assert!(frame.resolved);
        assert!(frame.resolve_failure.is_none());
        assert_eq!(frame.line, Some(42));
        assert!(frame.column.is_none());
        assert_eq!(frame.source, Some("app.py".to_string()));
        assert_eq!(frame.module, Some("myapp.views".to_string()));
        assert!(frame.in_app);
        assert!(!frame.synthetic);
        assert!(frame.code_variables.is_some());
    }

    #[test]
    fn into_frame_context_python() {
        let raw = make_raw();
        let frame = (&raw).into_frame();
        let ctx = frame.context.as_ref().expect("context should be present");
        assert_eq!(ctx.line.line, "  x = 1 + 2");
        assert_eq!(ctx.line.number, 42);
        assert_eq!(ctx.before.len(), 1);
        assert_eq!(ctx.after.len(), 1);
    }

    #[test]
    fn frame_id_stable_python() {
        let raw = make_raw();
        let id1 = raw.frame_id();
        let id2 = raw.frame_id();
        assert_eq!(id1, id2);
    }

    #[test]
    fn frame_id_changes_with_different_inputs_python() {
        let raw1 = make_raw();
        let mut raw2 = make_raw();
        raw2.lineno = Some(99);
        assert_ne!(raw1.frame_id(), raw2.frame_id());
    }
}
