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
            .rev() // pre_context arrives in file order, newest line last
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

#[cfg(test)]
mod test {
    use super::*;

    fn frame(lineno: u32, pre_context: &[&str], post_context: &[&str]) -> RawRubyFrame {
        RawRubyFrame {
            path: None,
            context_line: Some(format!("line {lineno}")),
            filename: "app.rb".to_string(),
            function: "call".to_string(),
            lineno: Some(lineno),
            pre_context: pre_context.iter().map(|s| s.to_string()).collect(),
            post_context: post_context.iter().map(|s| s.to_string()).collect(),
            meta: CommonFrameMetadata::default(),
        }
    }

    #[test]
    fn test_get_context_pairs_lines_with_numbers() {
        // pre/post_context arrive in file order; before is emitted
        // nearest-line-first and the frontend sorts by line number
        type Case = (u32, &'static [&'static str], &'static [(u32, &'static str)]);
        let cases: &[Case] = &[
            (
                10,
                &["line 7", "line 8", "line 9"],
                &[(9, "line 9"), (8, "line 8"), (7, "line 7")],
            ),
            // SDK omitted context lines entirely
            (10, &[], &[]),
            // more pre-context lines than lines above lineno: offsets saturate at 0
            (2, &["a", "b", "c"], &[(1, "c"), (0, "b"), (0, "a")]),
        ];

        for (lineno, pre, expected_before) in cases {
            let context = frame(*lineno, pre, &["next 1", "next 2"])
                .get_context()
                .unwrap();

            assert_eq!(
                context.line,
                ContextLine::new(*lineno, format!("line {lineno}"))
            );
            let expected: Vec<ContextLine> = expected_before
                .iter()
                .map(|(number, line)| ContextLine::new(*number, *line))
                .collect();
            assert_eq!(context.before, expected);
            assert_eq!(
                context.after,
                vec![
                    ContextLine::new(lineno + 1, "next 1"),
                    ContextLine::new(lineno + 2, "next 2"),
                ]
            );
        }
    }
}
