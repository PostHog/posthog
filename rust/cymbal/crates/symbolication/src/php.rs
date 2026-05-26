use common_types::error_tracking::FrameId;
use cymbal_domain::{Context, ContextLine};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{CommonFrameMetadata, Frame, IntoFrame};

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

impl IntoFrame for &RawPHPFrame {
    fn into_frame(self) -> Frame {
        let raw = self;
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IntoFrame;

    #[test]
    fn into_frame_fields_php_with_all_fields() {
        let raw = RawPHPFrame {
            path: Some("/var/www/app.php".to_string()),
            context_line: Some("  $x = doSomething();".to_string()),
            filename: Some("app/Service.php".to_string()),
            function: Some("doSomething".to_string()),
            lineno: Some(30),
            pre_context: vec!["function run() {".to_string()],
            post_context: vec!["return $x;".to_string()],
            meta: CommonFrameMetadata {
                in_app: true,
                synthetic: false,
            },
        };

        let frame = (&raw).into_frame();

        assert_eq!(frame.mangled_name, "doSomething");
        assert_eq!(frame.resolved_name, Some("doSomething".to_string()));
        assert_eq!(frame.lang, "php");
        assert!(frame.resolved);
        assert!(frame.resolve_failure.is_none());
        assert_eq!(frame.line, Some(30));
        assert_eq!(frame.source, Some("app/Service.php".to_string()));
    }

    #[test]
    fn into_frame_missing_function_php() {
        let raw = RawPHPFrame {
            path: None,
            context_line: None,
            filename: None,
            function: None, // missing function
            lineno: None,
            pre_context: vec![],
            post_context: vec![],
            meta: CommonFrameMetadata::default(),
        };

        let frame = (&raw).into_frame();

        // mangled_name falls back to "<unknown>"
        assert_eq!(frame.mangled_name, "<unknown>");
        assert!(frame.resolved_name.is_none());
        assert!(frame.source.is_none());
        assert!(frame.context.is_none());
    }

    #[test]
    fn frame_id_stable_php() {
        let raw = RawPHPFrame {
            path: None,
            context_line: Some("echo 'hi';".to_string()),
            filename: Some("index.php".to_string()),
            function: Some("greet".to_string()),
            lineno: Some(5),
            pre_context: vec![],
            post_context: vec![],
            meta: CommonFrameMetadata::default(),
        };
        assert_eq!(raw.frame_id(), raw.frame_id());
    }
}
