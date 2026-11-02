//! Port of `nodejs/src/logs/log-body-parse.ts`: one `JSON.parse` of a log body, classified.

use crate::js::{json_parse, JsString, JsValue};

#[derive(Debug, Clone, PartialEq)]
pub enum LogBodyParseResult {
    Empty,
    InvalidJson { raw: String },
    JsonObjectOrArray { value: JsValue },
    JsonString { value: JsString },
    JsonPrimitive { parsed: JsValue },
}

pub fn parse_log_body_for_ingestion(body: Option<&str>) -> LogBodyParseResult {
    let Some(body) = body else {
        return LogBodyParseResult::Empty;
    };
    match json_parse(body) {
        Ok(value @ (JsValue::Object(_) | JsValue::Array(_))) => {
            LogBodyParseResult::JsonObjectOrArray { value }
        }
        Ok(JsValue::String(value)) => LogBodyParseResult::JsonString { value },
        Ok(parsed) => LogBodyParseResult::JsonPrimitive { parsed },
        Err(_) => LogBodyParseResult::InvalidJson {
            raw: body.to_string(),
        },
    }
}
