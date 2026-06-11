use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::{Context, ContextLine, Frame},
    langs::CommonFrameMetadata,
};

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn get_context_orders_pre_context_adjacent_first() {
        // Ruby SDKs send pre_context ordered farthest -> adjacent to the context line.
        let frame = RawRubyFrame {
            path: None,
            context_line: Some("    raise \"boom\"".to_string()),
            filename: "application_service.rb".to_string(),
            function: "ApplicationService.call".to_string(),
            lineno: Some(4),
            pre_context: vec![
                "# frozen_string_literal: true".to_string(), // farthest (line 1)
                "".to_string(),                              // line 2
                "def self.call(**args)".to_string(),         // adjacent (line 3)
            ],
            post_context: vec![],
            meta: CommonFrameMetadata::default(),
        };

        let context = frame.get_context().unwrap();

        // The line adjacent to the context line is rendered first, with the
        // highest line number; the farthest line is rendered last.
        assert_eq!(context.before.len(), 3);
        assert_eq!(context.before[0].number, 3);
        assert_eq!(context.before[0].line, "def self.call(**args)");
        assert_eq!(context.before[2].number, 1);
        assert_eq!(context.before[2].line, "# frozen_string_literal: true");

        // Numbers strictly increase up to the context line.
        assert!(context.before[2].number < context.before[0].number);
        assert_eq!(context.before[0].number + 1, context.line.number);
    }
}

impl From<&RawRubyFrame> for Frame {
    fn from(raw: &RawRubyFrame) -> Self {
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
