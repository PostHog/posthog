/// Estimates the serialized size of a JSON value with minimal allocation.
///
/// Walks the JSON tree and approximates the byte length of the serialized
/// form. Close to `value.to_string().len()` but avoids the large allocation
/// of serializing the entire structure. Numbers still allocate a small
/// temporary string for accuracy, as they're typically only a few bytes.
pub fn estimate_json_size(value: &serde_json::Value) -> usize {
    match value {
        serde_json::Value::Null => 4, // "null"
        serde_json::Value::Bool(b) => {
            if *b {
                4
            } else {
                5
            }
        } // "true" or "false"
        serde_json::Value::Number(n) => n.to_string().len(),
        serde_json::Value::String(s) => s.len() + 2, // quotes + content (ignoring escapes)
        serde_json::Value::Array(arr) => {
            if arr.is_empty() {
                2 // "[]"
            } else {
                2 + arr.iter().map(estimate_json_size).sum::<usize>() + arr.len().saturating_sub(1)
            }
        }
        serde_json::Value::Object(map) => {
            if map.is_empty() {
                2 // "{}"
            } else {
                2 + map
                    .iter()
                    .map(|(k, v)| k.len() + 3 + estimate_json_size(v))
                    .sum::<usize>()
                    + map.len().saturating_sub(1)
            }
        }
    }
}
