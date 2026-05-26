use common_types::error_tracking::{FrameId, RawFrameId};
use serde::{Deserialize, Serialize};

use crate::{
    apple::{AppleDebugImage, RawAppleFrame},
    custom::CustomFrame,
    dart::RawDartFrame,
    go::RawGoFrame,
    hermes::RawHermesFrame,
    java::RawJavaFrame,
    js::RawJSFrame,
    node::RawNodeFrame,
    php::RawPHPFrame,
    python::RawPythonFrame,
    ruby::RawRubyFrame,
    to_vec, Catalog, Frame, IntoFrame, UnhandledError, FRAME_RESOLVED,
    JS_PLATFORM_ALIAS_FRAME_RESOLVED, PER_FRAME_TIME,
};

// We consume a huge variety of differently shaped stack frames, which we have special-case
// transformation for, to produce a single, unified representation of a frame.
#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(tag = "platform")]
pub enum RawFrame {
    #[serde(rename = "python")]
    Python(RawPythonFrame),
    #[serde(rename = "ruby")]
    Ruby(RawRubyFrame),
    #[serde(rename = "web:javascript")]
    JavaScriptWeb(RawJSFrame),
    #[serde(rename = "node:javascript")]
    JavaScriptNode(RawNodeFrame),
    #[serde(rename = "go")]
    Go(RawGoFrame),
    #[serde(rename = "php")]
    Php(RawPHPFrame),
    #[serde(rename = "hermes")]
    Hermes(RawHermesFrame),
    #[serde(rename = "java")]
    Java(RawJavaFrame),
    #[serde(rename = "dart")]
    Dart(RawDartFrame),
    #[serde(rename = "apple")]
    Apple(RawAppleFrame),
    #[serde(rename = "custom")]
    Custom(CustomFrame),
    // Some SDK payloads still send the bare `platform: "javascript"` value.
    // Treat it as a JavaScript platform alias while preserving metric continuity.
    #[serde(rename = "javascript")]
    JavaScriptPlatformAlias(RawJSFrame),
}

impl RawFrame {
    pub async fn resolve(
        &self,
        team_id: i32,
        catalog: &Catalog,
        debug_images: &[AppleDebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        let frame_resolve_time = common_metrics::timing_guard(PER_FRAME_TIME, &[]);
        let (res, lang_tag) = match self {
            RawFrame::JavaScriptWeb(frame) => {
                (to_vec(frame.resolve(team_id, catalog).await), "javascript")
            }
            RawFrame::JavaScriptPlatformAlias(frame) => {
                metrics::counter!(JS_PLATFORM_ALIAS_FRAME_RESOLVED).increment(1);
                (to_vec(frame.resolve(team_id, catalog).await), "javascript")
            }
            RawFrame::JavaScriptNode(frame) => {
                (to_vec(frame.resolve(team_id, catalog).await), "javascript")
            }

            RawFrame::Dart(frame) => (to_vec(Ok(frame.into_frame())), "dart"),
            RawFrame::Apple(frame) => {
                (frame.resolve(team_id, catalog, debug_images).await, "apple")
            }
            RawFrame::Php(frame) => (to_vec(Ok(frame.into_frame())), "php"),
            RawFrame::Python(frame) => (to_vec(Ok(frame.into_frame())), "python"),
            RawFrame::Ruby(frame) => (to_vec(Ok(frame.into_frame())), "ruby"),
            RawFrame::Custom(frame) => (to_vec(Ok(frame.into_frame())), "custom"),
            RawFrame::Go(frame) => (to_vec(Ok(frame.into_frame())), "go"),
            RawFrame::Hermes(frame) => (to_vec(frame.resolve(team_id, catalog).await), "hermes"),
            RawFrame::Java(frame) => (frame.resolve(team_id, catalog).await, "java"),
        };

        // The raw id of the frame is set after it's resolved.
        let res = res.map(|mut fs| {
            fs.iter_mut()
                .enumerate()
                .for_each(|(index, f)| f.frame_id = self.frame_id(team_id, index));
            fs
        });

        if res.is_err() {
            frame_resolve_time.label("outcome", "failed")
        } else {
            frame_resolve_time.label("outcome", "success")
        }
        .label("lang", lang_tag)
        .fin();

        if let Ok(frames) = &res {
            for frame in frames {
                if frame.resolved {
                    metrics::counter!(FRAME_RESOLVED, "lang" => lang_tag).increment(1);
                }
                // Failure metrics are emitted by the language-specific `From` impls in
                // `langs/*.rs` at the moment of frame construction, where the typed error
                // is in scope (so we can call `metric_reason()` directly). This avoids
                // having to carry the typed error on the `Frame` struct just to recover
                // the metric label, which previously required a custom serializer plus
                // `skip_deserializing` and silently dropped failure reasons on PG round-trip.
            }
        }

        res
    }

    pub fn symbol_set_ref(&self) -> Option<String> {
        match self {
            RawFrame::JavaScriptWeb(frame) | RawFrame::JavaScriptPlatformAlias(frame) => {
                frame.symbol_set_ref()
            }
            RawFrame::JavaScriptNode(frame) => frame.chunk_id.clone(),
            RawFrame::Hermes(frame) => frame.symbol_set_ref(),
            RawFrame::Java(frame) => frame.symbol_set_ref(),
            // Frames with no symbol sets
            RawFrame::Python(_)
            | RawFrame::Php(_)
            | RawFrame::Ruby(_)
            | RawFrame::Go(_)
            | RawFrame::Dart(_)
            | RawFrame::Apple(_)
            | RawFrame::Custom(_) => None,
        }
    }

    pub fn raw_id(&self, team_id: i32) -> RawFrameId {
        let hash_id = match self {
            RawFrame::JavaScriptWeb(raw) | RawFrame::JavaScriptPlatformAlias(raw) => raw.frame_id(),
            RawFrame::JavaScriptNode(raw) => raw.frame_id(),
            RawFrame::Php(raw) => raw.frame_id(),
            RawFrame::Python(raw) => raw.frame_id(),
            RawFrame::Ruby(raw) => raw.frame_id(),
            RawFrame::Go(raw) => raw.frame_id(),
            RawFrame::Custom(raw) => raw.frame_id(),
            RawFrame::Hermes(raw) => raw.frame_id(),
            RawFrame::Java(raw) => raw.frame_id(),
            RawFrame::Dart(raw) => raw.frame_id(),
            RawFrame::Apple(raw) => raw.frame_id(),
        };

        RawFrameId::new(hash_id, team_id)
    }

    pub fn frame_id(&self, team_id: i32, index: usize) -> FrameId {
        self.raw_id(team_id).to_full(index as i32)
    }

    pub fn is_suspicious(&self) -> bool {
        match self {
            RawFrame::JavaScriptWeb(frame) => frame.is_suspicious(),
            _ => false,
        }
    }
}

#[cfg(test)]
mod test {
    use common_types::error_tracking::FrameId;
    use cymbal_domain::{Context, ContextLine, ReleaseRecord};

    use crate::RawFrame;

    #[test]
    fn frame_id_serialization_preserves_public_raw_id_shape() {
        let frame = crate::Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: "fn".to_string(),
            line: Some(1),
            column: Some(2),
            source: Some("app.js".to_string()),
            module: None,
            in_app: true,
            resolved_name: Some("resolved".to_string()),
            lang: "javascript".to_string(),
            resolved: true,
            resolve_failure: None,
            synthetic: false,
            suspicious: false,
            junk_drawer: None,
            code_variables: None,
            context: Some(Context {
                before: vec![ContextLine::new(1, "before")],
                line: ContextLine::new(2, "line"),
                after: vec![ContextLine::new(3, "after")],
            }),
            release: Some(ReleaseRecord {
                id: uuid::Uuid::nil(),
                team_id: 1,
                hash_id: "release".to_string(),
                created_at: chrono::Utc::now(),
                version: "1.0".to_string(),
                project: "web".to_string(),
                metadata: None,
            }),
        };

        let value = serde_json::to_value(frame).unwrap();

        assert_eq!(value["raw_id"], FrameId::placeholder().to_string());
        assert!(value.get("frame_id").is_none());
        assert!(value.get("context").is_none());
        assert!(value.get("release").is_none());
    }

    #[test]
    fn raw_frame_symbol_set_ref_prefers_chunk_id_display() {
        let raw: RawFrame = serde_json::from_value(serde_json::json!({
            "platform": "web:javascript",
            "filename": "https://example.com/app.js",
            "function": "a",
            "lineno": 1,
            "colno": 2,
            "chunkId": "chunk-1"
        }))
        .unwrap();

        assert_eq!(raw.symbol_set_ref(), Some("chunk-1".to_string()));
    }

    // The `platform: "javascript"` alias must deserialize as JavaScriptPlatformAlias,
    // not produce an error. SDKs that haven't migrated to the canonical platform tag
    // still emit this form.
    #[test]
    fn javascript_platform_alias_deserializes() {
        let raw: RawFrame = serde_json::from_value(serde_json::json!({
            "platform": "javascript",
            "filename": "https://cdn.example.com/app.min.js",
            "function": "e",
            "lineno": 1,
            "colno": 100
        }))
        .unwrap();

        assert!(
            matches!(raw, RawFrame::JavaScriptPlatformAlias(_)),
            "expected JavaScriptPlatformAlias variant"
        );
    }

    // JavaScriptPlatformAlias should report a symbol_set_ref when a chunkId is present,
    // matching the behaviour of the canonical web:javascript variant.
    #[test]
    fn javascript_platform_alias_symbol_set_ref() {
        let raw: RawFrame = serde_json::from_value(serde_json::json!({
            "platform": "javascript",
            "filename": "https://cdn.example.com/app.min.js",
            "function": "e",
            "lineno": 1,
            "colno": 100,
            "chunkId": "legacy-chunk"
        }))
        .unwrap();

        assert_eq!(raw.symbol_set_ref(), Some("legacy-chunk".to_string()));
    }

    // Non-JS language frames should NOT return a symbol_set_ref.
    #[test]
    fn symbol_set_ref_none_for_python_ruby_go_php_dart_custom() {
        let langs = [
            serde_json::json!({"platform":"python","filename":"a.py","function":"f","lineno":1}),
            serde_json::json!({"platform":"ruby","filename":"a.rb","function":"f","lineno":1}),
            serde_json::json!({"platform":"go","filename":"a.go","function":"f","lineno":1}),
            serde_json::json!({"platform":"php","function":"f"}),
            serde_json::json!({"platform":"dart","abs_path":"pkg/a.dart"}),
            serde_json::json!({"platform":"custom","lang":"elixir","function":"f"}),
        ];
        for v in &langs {
            let raw: RawFrame = serde_json::from_value(v.clone()).unwrap();
            assert!(
                raw.symbol_set_ref().is_none(),
                "expected no symbol_set_ref for {v}"
            );
        }
    }

    // raw_id must be stable: the same frame produces the same RawFrameId on every call.
    #[test]
    fn raw_id_stable_for_python_frame() {
        let raw: RawFrame = serde_json::from_value(serde_json::json!({
            "platform": "python",
            "filename": "views.py",
            "function": "index",
            "lineno": 42
        }))
        .unwrap();

        let id1 = raw.raw_id(1);
        let id2 = raw.raw_id(1);
        assert_eq!(id1, id2);
    }

    // Different team_ids must produce different raw_ids even for otherwise identical frames.
    #[test]
    fn raw_id_differs_by_team_id() {
        let raw: RawFrame = serde_json::from_value(serde_json::json!({
            "platform": "python",
            "filename": "views.py",
            "function": "index",
            "lineno": 42
        }))
        .unwrap();

        assert_ne!(raw.raw_id(1), raw.raw_id(2));
    }

    // Node frame with a chunk_id must report that chunk_id as the symbol_set_ref.
    #[test]
    fn node_frame_symbol_set_ref_from_chunk_id() {
        let raw: RawFrame = serde_json::from_value(serde_json::json!({
            "platform": "node:javascript",
            "filename": "dist/server.js",
            "function": "handleRequest",
            "chunkId": "server-chunk-abc"
        }))
        .unwrap();

        assert_eq!(raw.symbol_set_ref(), Some("server-chunk-abc".to_string()));
    }

    // Node frame without a chunk_id must return None.
    #[test]
    fn node_frame_no_symbol_set_ref_without_chunk_id() {
        let raw: RawFrame = serde_json::from_value(serde_json::json!({
            "platform": "node:javascript",
            "filename": "dist/server.js",
            "function": "handleRequest"
        }))
        .unwrap();

        assert!(raw.symbol_set_ref().is_none());
    }
}
