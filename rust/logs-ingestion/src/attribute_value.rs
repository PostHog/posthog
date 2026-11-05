//! Capture stores attribute values JSON-encoded (`"error"` with quotes, `123`), so readers decode them first.

use crate::js::{json_parse, json_stringify, JsString, JsValue};

pub fn decode_log_attribute_value(value: &str) -> JsString {
    // `value.length >= 2` in UTF-16 units; both quotes are single units, so the byte check agrees.
    if value.len() >= 2 && value.starts_with('"') && value.ends_with('"') {
        let interior = &value[1..value.len() - 1];
        if !interior.contains('\\') && !interior.contains('"') {
            return JsString::from(interior);
        }
        if let Ok(JsValue::String(parsed)) = json_parse(value) {
            return parsed;
        }
    }
    JsString::from(value)
}

pub fn encode_log_attribute_value(value: &str) -> String {
    if json_parse(value).is_ok() {
        value.to_string()
    } else {
        json_stringify(&JsValue::string(value))
    }
}
