use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::{Context, Frame},
    langs::CommonFrameMetadata,
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawCommonLispFrame {
    #[serde(rename = "abs_path")]
    pub path: Option<String>, // Absolute path to the file - unused for now
    pub filename: String,    // Path of the file the function is defined in
    pub function: String,    // Name of the function
    pub package: String,     // The package the symbol is in
    pub lambda_list: String, // The function's parameter list, as a printed lambda list
    pub code_variables: Option<serde_json::Value>,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawCommonLispFrame {
    pub fn frame_id(&self) -> String {
        // We don't have version info for Common Lisp frames, so we key on
        // package + function + lambda_list. Filename is intentionally excluded
        // so the id is stable across file relocations.
        let mut hasher = Sha512::new();
        hasher.update(self.package.as_bytes());
        hasher.update(self.function.as_bytes());
        hasher.update(self.lambda_list.as_bytes());
        format!("{:x}", hasher.finalize())
    }

    pub fn get_context(&self) -> Option<Context> {
        None
    }
}

impl From<&RawCommonLispFrame> for Frame {
    fn from(raw: &RawCommonLispFrame) -> Self {
        Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: None,
            column: None,
            source: Some(raw.filename.clone()),
            in_app: raw.meta.in_app,
            resolved_name: Some(raw.function.clone()),
            lang: "common-lisp".to_string(),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            context: raw.get_context(),
            release: None,
            synthetic: raw.meta.synthetic,
            suspicious: false,
            module: Some(raw.package.clone()),
            code_variables: raw.code_variables.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base_frame() -> RawCommonLispFrame {
        RawCommonLispFrame {
            path: Some("/home/user/project/src/foo.lisp".to_string()),
            filename: "src/foo.lisp".to_string(),
            function: "do-thing".to_string(),
            package: "MY-APP".to_string(),
            lambda_list: "(x &optional y)".to_string(),
            code_variables: None,
            // Note: mirrors the serde default (`default_in_app` returns true),
            // which does NOT match `CommonFrameMetadata::default()`'s derived
            // bool default of `false`.
            meta: CommonFrameMetadata {
                in_app: true,
                synthetic: false,
            },
        }
    }

    #[test]
    fn parses_raw_common_lisp_frame_from_json() {
        let json = r#"
        {
            "abs_path": "/home/user/project/src/foo.lisp",
            "filename": "src/foo.lisp",
            "function": "do-thing",
            "package": "MY-APP",
            "lambda_list": "(x &optional y)",
            "in_app": true
        }
        "#;
        let frame: RawCommonLispFrame = serde_json::from_str(json).unwrap();
        assert_eq!(frame.filename, "src/foo.lisp");
        assert_eq!(frame.function, "do-thing");
        assert_eq!(frame.package, "MY-APP");
        assert_eq!(frame.lambda_list, "(x &optional y)");
        assert_eq!(
            frame.path.as_deref(),
            Some("/home/user/project/src/foo.lisp")
        );
        assert!(frame.meta.in_app);
        assert!(!frame.meta.synthetic);
    }

    #[test]
    fn parses_frame_with_optional_fields_missing() {
        let json = r#"
        {
            "filename": "src/foo.lisp",
            "function": "do-thing",
            "package": "MY-APP",
            "lambda_list": "()"
        }
        "#;
        let frame: RawCommonLispFrame = serde_json::from_str(json).unwrap();
        assert!(frame.path.is_none());
        assert!(frame.code_variables.is_none());
        // in_app defaults to true, synthetic defaults to false
        assert!(frame.meta.in_app);
        assert!(!frame.meta.synthetic);
    }

    #[test]
    fn frame_conversion_maps_fields_correctly() {
        let raw = base_frame();
        let frame: Frame = (&raw).into();

        assert_eq!(frame.mangled_name, "do-thing");
        assert_eq!(frame.resolved_name.as_deref(), Some("do-thing"));
        assert_eq!(frame.source.as_deref(), Some("src/foo.lisp"));
        assert_eq!(frame.module.as_deref(), Some("MY-APP"));
        assert_eq!(frame.line, None);
        assert_eq!(frame.column, None);
        assert_eq!(frame.lang, "common-lisp");
        assert!(frame.resolved);
        assert!(frame.resolve_failure.is_none());
        assert!(frame.context.is_none());
        assert!(frame.in_app);
        assert!(!frame.synthetic);
        assert!(!frame.suspicious);
    }

    #[test]
    fn frame_conversion_respects_in_app_false() {
        let mut raw = base_frame();
        raw.meta.in_app = false;
        let frame: Frame = (&raw).into();
        assert!(!frame.in_app);
    }

    #[test]
    fn frame_conversion_respects_synthetic_true() {
        let mut raw = base_frame();
        raw.meta.synthetic = true;
        let frame: Frame = (&raw).into();
        assert!(frame.synthetic);
    }

    #[test]
    fn frame_id_is_stable_for_identical_frames() {
        let a = base_frame();
        let b = base_frame();
        assert_eq!(a.frame_id(), b.frame_id());
    }

    #[test]
    fn frame_id_differs_when_package_differs() {
        let a = base_frame();
        let mut b = base_frame();
        b.package = "OTHER-APP".to_string();
        assert_ne!(a.frame_id(), b.frame_id());
    }

    #[test]
    fn frame_id_differs_when_function_differs() {
        let a = base_frame();
        let mut b = base_frame();
        b.function = "other-thing".to_string();
        assert_ne!(a.frame_id(), b.frame_id());
    }

    #[test]
    fn frame_id_differs_when_lambda_list_differs() {
        let a = base_frame();
        let mut b = base_frame();
        b.lambda_list = "(x y z)".to_string();
        assert_ne!(a.frame_id(), b.frame_id());
    }

    #[test]
    fn frame_id_ignores_filename() {
        // Intentional: frame_id should be stable across file relocations,
        // since CL frames have no version info to key on.
        let a = base_frame();
        let mut b = base_frame();
        b.filename = "src/moved.lisp".to_string();
        assert_eq!(a.frame_id(), b.frame_id());
    }

    #[test]
    fn get_context_returns_none() {
        // CL frames do not carry source context yet.
        let raw = base_frame();
        assert!(raw.get_context().is_none());
    }
}
