//! JavaScript semantics that the Node consumer's output depends on.
//!
//! The Node consumer writes values that come from `JSON.parse`, `JSON.stringify`, JS object key
//! order, UTF-16 string lengths and `Date.parse`. Rust defaults differ on each of these, so the
//! port goes through this module wherever such a value reaches an output.

mod date;
mod json;
mod number;
pub(crate) mod object;
mod string;

pub use date::date_parse;
pub use json::{
    json_parse, json_parse_shape, json_stringify, json_stringify_into, quote_js_string, JsonError,
    JsonShape, MAX_BUILT_DEPTH,
};
pub use number::{number_to_string, write_number};
pub use object::{is_array_index, JsKey, JsObject};
pub use string::{utf16_len, utf16_slice_lossy, CharOrSurrogate, JsString};

#[derive(Debug, Clone, PartialEq)]
pub enum JsValue {
    Null,
    Bool(bool),
    Number(f64),
    String(JsString),
    Array(Vec<JsValue>),
    Object(JsObject),
}

impl JsValue {
    /// `typeof value === 'object' && value !== null`, which arrays also pass.
    pub fn is_object_like(&self) -> bool {
        matches!(self, JsValue::Array(_) | JsValue::Object(_))
    }

    pub fn as_js_string(&self) -> Option<&JsString> {
        match self {
            JsValue::String(s) => Some(s),
            _ => None,
        }
    }

    pub fn string(s: &str) -> JsValue {
        JsValue::String(JsString::from(s))
    }
}
