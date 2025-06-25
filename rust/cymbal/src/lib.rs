use error::EventError;

use serde_json::Value;
use tracing::warn;

use uuid::Uuid;

pub mod app_context;
pub mod assignment_rules;
pub mod config;
pub mod error;
pub mod fingerprinting;
pub mod frames;
pub mod issue_resolution;
pub mod langs;
pub mod metric_consts;
pub mod pipeline;
pub mod posthog_utils;
pub mod symbol_store;
pub mod teams;
pub mod types;

pub fn recursively_sanitize_properties(
    id: Uuid,
    value: &mut Value,
    depth: usize,
) -> Result<(), EventError> {
    if depth > 64 {
        // We don't want to recurse too deeply, in case we have a circular reference or something.
        return Err(EventError::InvalidProperties(
            id,
            "Recursion limit exceeded".to_string(),
        ));
    }
    match value {
        Value::Object(map) => {
            for (_, v) in map.iter_mut() {
                recursively_sanitize_properties(id, v, depth + 1)?;
            }
        }
        Value::Array(arr) => {
            for v in arr.iter_mut() {
                recursively_sanitize_properties(id, v, depth + 1)?;
            }
        }
        Value::String(s) => {
            if needs_sanitization(s) {
                warn!("Sanitizing null bytes from string in event {}", id);
                *s = sanitize_string(s.clone());
            }
        }
        _ => {}
    }
    Ok(())
}

// Postgres doesn't like nulls (u0000) in strings, so we replace them with uFFFD.
pub fn sanitize_string(s: String) -> String {
    s.replace('\u{0000}', "\u{FFFD}")
}

pub fn needs_sanitization(s: &str) -> bool {
    s.contains('\u{0000}')
}

struct WithIndices<T> {
    indices: Vec<usize>,
    inner: T,
}
