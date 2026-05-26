use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{utils::add_raw_to_junk, CommonFrameMetadata, Frame, IntoFrame};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawDartFrame {
    pub filename: Option<String>,
    pub function: Option<String>,
    pub lineno: Option<u32>,
    pub colno: Option<u32>,
    pub abs_path: String,
    pub package: Option<String>,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawDartFrame {
    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();
        if let Some(filename) = &self.filename {
            hasher.update(filename.as_bytes());
        }
        if let Some(package) = &self.package {
            hasher.update(package.as_bytes());
        }
        hasher.update(self.function.clone().unwrap_or_default().as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        hasher.update(self.colno.unwrap_or_default().to_be_bytes());
        format!("{:x}", hasher.finalize())
    }
}

impl IntoFrame for &RawDartFrame {
    fn into_frame(self) -> Frame {
        let raw = self;
        let mut f = Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone().unwrap_or_default(),
            line: raw.lineno,
            column: raw.colno,
            source: Some(raw.abs_path.clone()),
            in_app: raw.meta.in_app,
            resolved_name: Some(raw.function.clone().unwrap_or_default()), // Assuming no obfuscation for now
            lang: "dart".to_string(),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            release: None,
            synthetic: raw.meta.synthetic,
            context: None,
            suspicious: false,
            module: None,
            code_variables: None,
        };

        add_raw_to_junk(&mut f, raw);
        f
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IntoFrame;

    fn make_raw() -> RawDartFrame {
        RawDartFrame {
            filename: Some("main.dart".to_string()),
            function: Some("MyWidget.build".to_string()),
            lineno: Some(10),
            colno: Some(5),
            abs_path: "package:myapp/main.dart".to_string(),
            package: Some("myapp".to_string()),
            meta: CommonFrameMetadata {
                in_app: true,
                synthetic: false,
            },
        }
    }

    #[test]
    fn into_frame_fields_dart() {
        let raw = make_raw();
        let frame = (&raw).into_frame();

        assert_eq!(frame.mangled_name, "MyWidget.build");
        assert_eq!(frame.resolved_name, Some("MyWidget.build".to_string()));
        assert_eq!(frame.lang, "dart");
        assert!(frame.resolved);
        assert!(frame.resolve_failure.is_none());
        assert_eq!(frame.line, Some(10));
        assert_eq!(frame.column, Some(5));
        // abs_path is used as source
        assert_eq!(frame.source, Some("package:myapp/main.dart".to_string()));
        assert!(frame.in_app);
        assert!(frame.context.is_none()); // Dart has no context
    }

    #[test]
    fn into_frame_junk_drawer_dart() {
        let raw = make_raw();
        let frame = (&raw).into_frame();
        // raw frame is stored in junk drawer
        let junk = frame
            .junk_drawer
            .as_ref()
            .expect("junk_drawer should be set");
        assert!(junk.get("raw_frame").is_some());
    }

    #[test]
    fn into_frame_missing_function_dart() {
        let raw = RawDartFrame {
            filename: None,
            function: None,
            lineno: None,
            colno: None,
            abs_path: "package:myapp/foo.dart".to_string(),
            package: None,
            meta: CommonFrameMetadata::default(),
        };
        let frame = (&raw).into_frame();
        assert_eq!(frame.mangled_name, ""); // unwrap_or_default gives empty string
        assert_eq!(frame.source, Some("package:myapp/foo.dart".to_string()));
    }

    #[test]
    fn frame_id_stable_dart() {
        let raw = make_raw();
        assert_eq!(raw.frame_id(), raw.frame_id());
    }
}
