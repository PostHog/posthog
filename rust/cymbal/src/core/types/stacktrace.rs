use serde::{Deserialize, Deserializer, Serialize, Serializer};

use crate::core::types::frames::{Frame, RawFrame};

// `remote = "Self"` makes the derived impls inherent methods, so the hand-written
// `Deserialize` below can default a missing tag and then delegate to the derived logic.
#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(tag = "type", rename_all = "lowercase", remote = "Self")]
pub enum Stacktrace {
    Raw { frames: Vec<RawFrame> },
    Resolved { frames: Vec<Frame> },
}

// SDKs from before the tag existed send a bare `{"frames": [...]}` — posthog-python
// only added `"type": "raw"` in 3.8.0. Treat an untagged stacktrace as raw so those
// exceptions still resolve into issues. Serialization always writes the tag.
impl<'de> Deserialize<'de> for Stacktrace {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let mut value = serde_json::Value::deserialize(deserializer)?;
        if let Some(object) = value.as_object_mut() {
            object
                .entry("type")
                .or_insert_with(|| serde_json::Value::String("raw".to_string()));
        }
        Self::deserialize(&value).map_err(serde::de::Error::custom)
    }
}

impl Serialize for Stacktrace {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        Self::serialize(self, serializer)
    }
}

#[cfg(test)]
mod test {
    use super::*;

    // The shape posthog-python < 3.8.0 emits: no "type" on the stacktrace and no
    // "platform" on the frames. Written fresh, not copied from captured data.
    const LEGACY_PYTHON_STACKTRACE: &str = r#"{
        "frames": [
            {
                "abs_path": "/app/example/service.py",
                "context_line": "    connect()",
                "filename": "example/service.py",
                "function": "start",
                "lineno": 12,
                "module": "example.service",
                "pre_context": [],
                "post_context": [],
                "in_app": true
            }
        ]
    }"#;

    #[test]
    fn parses_a_legacy_python_stacktrace_as_raw() {
        let stack: Stacktrace = serde_json::from_str(LEGACY_PYTHON_STACKTRACE).unwrap();
        let Stacktrace::Raw { frames } = stack else {
            panic!("expected a raw stacktrace");
        };
        assert!(matches!(frames.as_slice(), [RawFrame::Python(_)]));
    }

    #[test]
    fn writes_the_tags_back_on_serialization() {
        let stack: Stacktrace = serde_json::from_str(LEGACY_PYTHON_STACKTRACE).unwrap();
        let serialized = serde_json::to_value(&stack).unwrap();
        assert_eq!(serialized["type"], "raw");
        assert_eq!(serialized["frames"][0]["platform"], "python");
    }

    #[test]
    fn rejects_an_untagged_frame_with_no_python_markers() {
        let raw =
            r#"{"frames": [{"filename": "app.js", "function": "main", "lineno": 3, "colno": 7}]}"#;
        assert!(serde_json::from_str::<Stacktrace>(raw).is_err());
    }
}
