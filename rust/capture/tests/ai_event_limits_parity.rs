//! The limits file lives outside this workspace, so point the test at it with `AI_EVENT_LIMITS_JSON`.
//! Otherwise it walks up from the manifest dir looking for the file.

use std::path::PathBuf;

use capture::ai_event_limits::{
    AI_MAX_EVENT_BYTES_CEILING, AI_MAX_EVENT_BYTES_DEFAULT, AI_MAX_EVENT_BYTES_OVERRIDES,
};

const RELATIVE_PATH: &str = "products/ai_observability/shared/crosslang/ai_event_limits.json";

fn limits_json() -> PathBuf {
    if let Ok(path) = std::env::var("AI_EVENT_LIMITS_JSON") {
        let path = PathBuf::from(path);
        if path.is_file() {
            return path;
        }
        panic!(
            "AI_EVENT_LIMITS_JSON is set to {}, which is not a file",
            path.display()
        );
    }
    let mut current = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    loop {
        let candidate = current.join(RELATIVE_PATH);
        if candidate.is_file() {
            return candidate;
        }
        if !current.pop() {
            panic!("Could not locate {RELATIVE_PATH} - set AI_EVENT_LIMITS_JSON");
        }
    }
}

#[test]
fn mirror_matches_the_shared_json() {
    let raw = std::fs::read_to_string(limits_json()).expect("the limits file is readable");
    let limits: serde_json::Value = serde_json::from_str(&raw).expect("the limits file is json");

    let from_file = serde_json::json!({
        "max_event_bytes_default": limits["max_event_bytes_default"],
        "max_event_bytes_overrides": limits["max_event_bytes_overrides"],
        "max_event_bytes_ceiling": limits["max_event_bytes_ceiling"],
    });
    let from_mirror = serde_json::json!({
        "max_event_bytes_default": AI_MAX_EVENT_BYTES_DEFAULT,
        "max_event_bytes_overrides": AI_MAX_EVENT_BYTES_OVERRIDES,
        "max_event_bytes_ceiling": AI_MAX_EVENT_BYTES_CEILING,
    });

    assert_eq!(
        from_file, from_mirror,
        "src/ai_event_limits.rs has drifted from {RELATIVE_PATH}. Edit the json first, then the mirror."
    );
}
