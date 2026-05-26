use common_types::error_tracking::FrameId;
use cymbal_domain::{Context, ContextLine};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{CommonFrameMetadata, Frame, IntoFrame};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawRubyFrame {
    #[serde(rename = "abs_path")]
    pub path: Option<String>,
    pub context_line: Option<String>,
    pub filename: String,
    pub function: String,
    pub lineno: Option<u32>,
    #[serde(default)]
    pub pre_context: Vec<String>,
    #[serde(default)]
    pub post_context: Vec<String>,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawRubyFrame {
    pub fn frame_id(&self) -> String {
        // We don't have version info for ruby frames, so we rely on
        // the filename, function, line number and surrounding context to
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

impl IntoFrame for &RawRubyFrame {
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
            lang: "ruby".to_string(),
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IntoFrame;

    fn make_raw() -> RawRubyFrame {
        RawRubyFrame {
            path: Some("/app/controllers/users.rb".to_string()),
            context_line: Some("  User.create(params)".to_string()),
            filename: "controllers/users.rb".to_string(),
            function: "create".to_string(),
            lineno: Some(15),
            pre_context: vec!["def create".to_string()],
            post_context: vec!["end".to_string()],
            meta: CommonFrameMetadata {
                in_app: true,
                synthetic: false,
            },
        }
    }

    #[test]
    fn into_frame_fields_ruby() {
        let raw = make_raw();
        let frame = (&raw).into_frame();

        assert_eq!(frame.mangled_name, "create");
        assert_eq!(frame.resolved_name, Some("create".to_string()));
        assert_eq!(frame.lang, "ruby");
        assert!(frame.resolved);
        assert!(frame.resolve_failure.is_none());
        assert_eq!(frame.line, Some(15));
        assert!(frame.column.is_none());
        assert_eq!(frame.source, Some("controllers/users.rb".to_string()));
        assert!(frame.module.is_none()); // Ruby frames have no module
        assert!(frame.in_app);
    }

    #[test]
    fn into_frame_context_ruby() {
        let raw = make_raw();
        let frame = (&raw).into_frame();
        let ctx = frame.context.as_ref().expect("context should be present");
        assert_eq!(ctx.line.line, "  User.create(params)");
        assert_eq!(ctx.line.number, 15);
    }

    #[test]
    fn frame_id_stable_ruby() {
        let raw = make_raw();
        assert_eq!(raw.frame_id(), raw.frame_id());
    }
}
