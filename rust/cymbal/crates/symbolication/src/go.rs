use common_types::error_tracking::FrameId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{CommonFrameMetadata, Frame, IntoFrame};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RawGoFrame {
    filename: String,
    function: String,
    lineno: u32,
    #[serde(flatten)]
    meta: CommonFrameMetadata,
}

impl RawGoFrame {
    pub fn frame_id(&self) -> String {
        let mut hasher = Sha512::new();
        hasher.update(self.filename.as_bytes());
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.to_be_bytes());
        format!("{:x}", hasher.finalize())
    }
}

impl IntoFrame for &RawGoFrame {
    fn into_frame(self) -> Frame {
        let frame = self;
        Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: frame.function.clone(),
            line: Some(frame.lineno),
            column: None,
            source: Some(frame.filename.clone()),
            in_app: frame.meta.in_app,
            resolved_name: Some(frame.function.clone()),
            lang: "go".to_string(),
            resolved: true,
            resolve_failure: None,

            synthetic: frame.meta.synthetic,
            junk_drawer: None,
            context: None,
            release: None,
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

    fn make_raw() -> RawGoFrame {
        serde_json::from_value(serde_json::json!({
            "platform": "go",
            "filename": "main.go",
            "function": "main.run",
            "lineno": 55
        }))
        .unwrap()
    }

    #[test]
    fn into_frame_fields_go() {
        let raw = make_raw();
        let frame = (&raw).into_frame();

        assert_eq!(frame.mangled_name, "main.run");
        assert_eq!(frame.resolved_name, Some("main.run".to_string()));
        assert_eq!(frame.lang, "go");
        assert!(frame.resolved);
        assert!(frame.resolve_failure.is_none());
        assert_eq!(frame.line, Some(55));
        assert!(frame.column.is_none());
        assert_eq!(frame.source, Some("main.go".to_string()));
        assert!(frame.module.is_none());
        assert!(frame.context.is_none()); // Go frames have no context
    }

    #[test]
    fn frame_id_stable_go() {
        let raw = make_raw();
        assert_eq!(raw.frame_id(), raw.frame_id());
    }

    #[test]
    fn frame_id_changes_with_lineno_go() {
        let raw1 = make_raw();
        let raw2: RawGoFrame = serde_json::from_value(serde_json::json!({
            "platform": "go",
            "filename": "main.go",
            "function": "main.run",
            "lineno": 99
        }))
        .unwrap();
        assert_ne!(raw1.frame_id(), raw2.frame_id());
    }
}
