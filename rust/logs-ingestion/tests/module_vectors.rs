//! Replays the per-function vectors that the Node code recorded in
//! `nodejs/src/logs/parity/fixtures/modules`.

mod common;

use common::{cases, get, string};
use logs_ingestion::attribute_value::{decode_log_attribute_value, encode_log_attribute_value};
use logs_ingestion::body_parse::{parse_log_body_for_ingestion, LogBodyParseResult};
use logs_ingestion::js::{date_parse, JsObject, JsValue};

#[test]
fn date_parse_matches_v8() {
    let cases = cases("date_parse");
    assert!(!cases.is_empty());
    for (input, output) in cases {
        let text = match &input {
            JsValue::Null => String::new(),
            other => string(other),
        };
        let expected = match output {
            JsValue::Number(n) => Some(n),
            _ => None,
        };
        assert_eq!(date_parse(&text), expected, "Date.parse({text:?})");
    }
}

#[test]
fn attribute_value_codec_matches_node() {
    let cases = cases("attribute_value");
    assert!(cases.len() > 100);
    for (input, output) in cases {
        let input = string(&input);
        assert_eq!(
            decode_log_attribute_value(&input),
            *get(&output, "decoded").as_js_string().unwrap(),
            "decode {input:?}"
        );
        assert_eq!(
            encode_log_attribute_value(&input),
            string(get(&output, "encoded")),
            "encode {input:?}"
        );
    }
}

fn body_parse_to_js(result: LogBodyParseResult) -> JsValue {
    let mut o = JsObject::new();
    match result {
        LogBodyParseResult::Empty => o.insert_str("kind", JsValue::string("empty")),
        LogBodyParseResult::InvalidJson { raw } => {
            o.insert_str("kind", JsValue::string("invalid_json"));
            o.insert_str("raw", JsValue::string(&raw));
        }
        LogBodyParseResult::JsonObjectOrArray { value } => {
            o.insert_str("kind", JsValue::string("json_object_or_array"));
            o.insert_str("value", value);
        }
        LogBodyParseResult::JsonString { value } => {
            o.insert_str("kind", JsValue::string("json_string"));
            o.insert_str("value", JsValue::String(value));
        }
        LogBodyParseResult::JsonPrimitive { parsed } => {
            o.insert_str("kind", JsValue::string("json_primitive"));
            o.insert_str("parsed", parsed);
        }
    }
    JsValue::Object(o)
}

#[test]
fn body_parse_matches_node() {
    let cases = cases("body_parse");
    assert!(cases.len() > 40);
    for (input, output) in cases {
        let body = match &input {
            JsValue::Null => None,
            other => Some(string(other)),
        };
        let actual = body_parse_to_js(parse_log_body_for_ingestion(body.as_deref()));
        // Compared with key order: the vectors keep JavaScript's order, and so does JsObject.
        assert_eq!(
            actual,
            output,
            "body {:?}",
            body.map(|b| b.chars().take(80).collect::<String>())
        );
    }
}
