use std::fmt;

use serde::de::{self, Deserializer, IgnoredAny, MapAccess, SeqAccess, Visitor};
use serde::Deserialize;
use serde_json::value::RawValue;

use super::types::{
    deserialize_lenient_flag, deserialize_lenient_flag_or_false, empty_raw_object, trim_owned,
    Batch, Event, RawOptions,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JsonKind {
    Missing,
    Null,
    Number,
    Boolean,
    Array,
    Object,
}

impl JsonKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Missing => "missing",
            Self::Null => "null",
            Self::Number => "number",
            Self::Boolean => "boolean",
            Self::Array => "array",
            Self::Object => "object",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FieldTypeError {
    pub index: Option<usize>,
    pub field: &'static str,
    pub kind: JsonKind,
}

impl fmt::Display for FieldTypeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.index {
            Some(i) => write!(f, "batch[{i}].{}", self.field)?,
            None => f.write_str(self.field)?,
        }
        match self.kind {
            JsonKind::Missing => f.write_str(" is missing"),
            kind => write!(f, " must be a string, got {}", kind.as_str()),
        }
    }
}

/// Keeps only a non-string's JSON kind, so the 400 names the field without echoing the value.
#[derive(Debug, Default)]
enum JsonStr {
    #[default]
    Missing,
    Null,
    Str(String),
    Wrong(JsonKind),
}

impl<'de> Deserialize<'de> for JsonStr {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(JsonStrVisitor)
    }
}

struct JsonStrVisitor;

impl<'de> Visitor<'de> for JsonStrVisitor {
    type Value = JsonStr;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("any JSON value")
    }

    fn visit_str<E: de::Error>(self, v: &str) -> Result<JsonStr, E> {
        Ok(JsonStr::Str(v.to_owned()))
    }

    fn visit_string<E: de::Error>(self, v: String) -> Result<JsonStr, E> {
        Ok(JsonStr::Str(v))
    }

    fn visit_unit<E: de::Error>(self) -> Result<JsonStr, E> {
        Ok(JsonStr::Null)
    }

    fn visit_none<E: de::Error>(self) -> Result<JsonStr, E> {
        Ok(JsonStr::Null)
    }

    fn visit_bool<E: de::Error>(self, _: bool) -> Result<JsonStr, E> {
        Ok(JsonStr::Wrong(JsonKind::Boolean))
    }

    fn visit_i64<E: de::Error>(self, _: i64) -> Result<JsonStr, E> {
        Ok(JsonStr::Wrong(JsonKind::Number))
    }

    fn visit_u64<E: de::Error>(self, _: u64) -> Result<JsonStr, E> {
        Ok(JsonStr::Wrong(JsonKind::Number))
    }

    fn visit_f64<E: de::Error>(self, _: f64) -> Result<JsonStr, E> {
        Ok(JsonStr::Wrong(JsonKind::Number))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<JsonStr, A::Error> {
        while seq.next_element::<IgnoredAny>()?.is_some() {}
        Ok(JsonStr::Wrong(JsonKind::Array))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<JsonStr, A::Error> {
        while map.next_entry::<IgnoredAny, IgnoredAny>()?.is_some() {}
        Ok(JsonStr::Wrong(JsonKind::Object))
    }
}

/// Lenient mirror of [`Event`] so a wrong type gets a 400 naming the field; keep `Event`'s field order (serde also reads the array form).
#[derive(Deserialize)]
pub struct LenientEvent {
    #[serde(default)]
    event: JsonStr,
    #[serde(default)]
    uuid: JsonStr,
    #[serde(default)]
    distinct_id: JsonStr,
    #[serde(default)]
    timestamp: JsonStr,
    // `Option` without a default, as in `Event`, so a short array form still fails in serde.
    session_id: Option<JsonStr>,
    window_id: Option<JsonStr>,
    #[serde(default)]
    options: RawOptions,
    #[serde(default = "empty_raw_object")]
    properties: Box<RawValue>,
}

/// Lenient mirror of [`Batch`] so a wrong-typed `created_at` gets a 400 naming the field.
#[derive(Deserialize)]
pub struct LenientBatch {
    #[serde(default)]
    created_at: JsonStr,
    #[serde(default, deserialize_with = "deserialize_lenient_flag_or_false")]
    historical_migration: bool,
    #[serde(default, deserialize_with = "deserialize_lenient_flag")]
    capture_internal: Option<bool>,
    batch: Vec<LenientEvent>,
}

fn required(
    value: JsonStr,
    index: Option<usize>,
    field: &'static str,
) -> Result<String, FieldTypeError> {
    match value {
        JsonStr::Str(s) => Ok(s),
        JsonStr::Missing => Err(FieldTypeError {
            index,
            field,
            kind: JsonKind::Missing,
        }),
        JsonStr::Null => Err(FieldTypeError {
            index,
            field,
            kind: JsonKind::Null,
        }),
        JsonStr::Wrong(kind) => Err(FieldTypeError { index, field, kind }),
    }
}

fn optional(
    value: Option<JsonStr>,
    index: usize,
    field: &'static str,
) -> Result<Option<String>, FieldTypeError> {
    match value {
        None | Some(JsonStr::Null) | Some(JsonStr::Missing) => Ok(None),
        Some(JsonStr::Str(s)) => Ok(Some(s)),
        Some(JsonStr::Wrong(kind)) => Err(FieldTypeError {
            index: Some(index),
            field,
            kind,
        }),
    }
}

impl LenientEvent {
    fn into_event(self, index: usize) -> Result<Event, FieldTypeError> {
        let i = Some(index);
        Ok(Event {
            event: required(self.event, i, "event")?,
            uuid: trim_owned(required(self.uuid, i, "uuid")?),
            distinct_id: trim_owned(required(self.distinct_id, i, "distinct_id")?),
            timestamp: required(self.timestamp, i, "timestamp")?,
            session_id: optional(self.session_id, index, "session_id")?,
            window_id: optional(self.window_id, index, "window_id")?,
            options: self.options,
            properties: self.properties,
        })
    }
}

impl LenientBatch {
    /// Returns the [`Batch`] the strict parse would build, or the first non-string field (`created_at`, then events in order).
    pub fn into_batch(self) -> Result<Batch, FieldTypeError> {
        let created_at = required(self.created_at, None, "created_at")?;
        let batch = self
            .batch
            .into_iter()
            .enumerate()
            .map(|(index, event)| event.into_event(index))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Batch {
            created_at,
            historical_migration: self.historical_migration,
            capture_internal: self.capture_internal,
            batch,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde_json::{json, Value};

    const PII: &str = "alice@example.com";
    const BIG: u64 = 12345678901234567890;

    fn lenient_parse(body: &[u8]) -> Result<Result<Batch, FieldTypeError>, serde_json::Error> {
        serde_json::from_slice::<LenientBatch>(body).map(LenientBatch::into_batch)
    }

    fn valid_event() -> Value {
        json!({
            "event": "$pageview",
            "uuid": "019a0000-0000-7000-8000-000000000001",
            "distinct_id": "user-1",
            "timestamp": "2026-10-21T00:00:00.000Z",
        })
    }

    fn body_with(
        batch_fields: &[(&str, Option<Value>)],
        event_fields: &[(&str, Option<Value>)],
    ) -> Vec<u8> {
        let mut event = valid_event();
        for (key, value) in event_fields {
            match value {
                Some(v) => event[*key] = v.clone(),
                None => {
                    event.as_object_mut().unwrap().remove(*key);
                }
            }
        }
        let mut batch = json!({ "created_at": "2026-10-21T00:00:01.000Z", "batch": [event] });
        for (key, value) in batch_fields {
            match value {
                Some(v) => batch[*key] = v.clone(),
                None => {
                    batch.as_object_mut().unwrap().remove(*key);
                }
            }
        }
        serde_json::to_vec(&batch).unwrap()
    }

    fn kind_value(kind: JsonKind) -> Option<Value> {
        match kind {
            JsonKind::Missing => None,
            JsonKind::Null => Some(Value::Null),
            JsonKind::Number => Some(json!(BIG)),
            JsonKind::Boolean => Some(json!(true)),
            JsonKind::Array => Some(json!([PII])),
            JsonKind::Object => Some(json!({ "secret": PII })),
        }
    }

    #[rstest]
    fn required_field_errors_name_the_field_and_kind_only(
        #[values("created_at", "event", "uuid", "distinct_id", "timestamp")] field: &'static str,
        #[values(
            JsonKind::Missing,
            JsonKind::Null,
            JsonKind::Number,
            JsonKind::Boolean,
            JsonKind::Array,
            JsonKind::Object
        )]
        kind: JsonKind,
    ) {
        let (index, body) = if field == "created_at" {
            (None, body_with(&[(field, kind_value(kind))], &[]))
        } else {
            (Some(0), body_with(&[], &[(field, kind_value(kind))]))
        };

        let err = lenient_parse(&body).unwrap().unwrap_err();

        let text = err.to_string();
        assert!(
            !text.contains(PII) && !text.contains(&BIG.to_string()),
            "{text}"
        );
        assert_eq!(err, FieldTypeError { index, field, kind });
        let path = index.map_or(field.to_owned(), |i| format!("batch[{i}].{field}"));
        let expected = match kind {
            JsonKind::Missing => format!("{path} is missing"),
            _ => format!("{path} must be a string, got {}", kind.as_str()),
        };
        assert_eq!(text, expected);
    }

    #[rstest]
    fn optional_field_wrong_types_name_the_field_and_kind_only(
        #[values("session_id", "window_id")] field: &'static str,
        #[values(JsonKind::Number, JsonKind::Boolean, JsonKind::Array, JsonKind::Object)]
        kind: JsonKind,
    ) {
        let body = body_with(&[], &[(field, kind_value(kind))]);

        let err = lenient_parse(&body).unwrap().unwrap_err();

        assert_eq!(
            err,
            FieldTypeError {
                index: Some(0),
                field,
                kind
            }
        );
        assert_eq!(
            err.to_string(),
            format!("batch[0].{field} must be a string, got {}", kind.as_str())
        );
    }

    #[rstest]
    #[case::created_at_before_events(
        &[("created_at", Some(json!(1)))], &[("distinct_id", Some(json!(1)))], None, "created_at"
    )]
    #[case::field_order_within_an_event(
        &[], &[("timestamp", Some(json!(1))), ("distinct_id", Some(json!(1)))], Some(0), "distinct_id"
    )]
    fn first_problem_wins(
        #[case] batch_fields: &[(&str, Option<Value>)],
        #[case] event_fields: &[(&str, Option<Value>)],
        #[case] index: Option<usize>,
        #[case] field: &'static str,
    ) {
        let err = lenient_parse(&body_with(batch_fields, event_fields))
            .unwrap()
            .unwrap_err();
        assert_eq!((err.index, err.field), (index, field));
    }

    #[test]
    fn first_bad_event_in_batch_order_wins() {
        let mut bad = valid_event();
        bad["distinct_id"] = json!(7);
        let body = json!({
            "created_at": "2026-10-21T00:00:01.000Z",
            "batch": [valid_event(), bad.clone(), valid_event(), bad],
        });
        let err = lenient_parse(&serde_json::to_vec(&body).unwrap())
            .unwrap()
            .unwrap_err();
        assert_eq!(
            err.to_string(),
            "batch[1].distinct_id must be a string, got number"
        );
    }

    fn assert_same_batch(strict: &Batch, lenient: &Batch, body: &str) {
        assert_eq!(strict.created_at, lenient.created_at, "{body}");
        assert_eq!(
            strict.historical_migration, lenient.historical_migration,
            "{body}"
        );
        assert_eq!(strict.capture_internal, lenient.capture_internal, "{body}");
        assert_eq!(strict.batch.len(), lenient.batch.len(), "{body}");
        for (s, l) in strict.batch.iter().zip(&lenient.batch) {
            assert_eq!(s.event, l.event, "{body}");
            assert_eq!(s.uuid, l.uuid, "{body}");
            assert_eq!(s.distinct_id, l.distinct_id, "{body}");
            assert_eq!(s.timestamp, l.timestamp, "{body}");
            assert_eq!(s.session_id, l.session_id, "{body}");
            assert_eq!(s.window_id, l.window_id, "{body}");
            assert_eq!(s.options.0, l.options.0, "{body}");
            assert_eq!(s.properties.get(), l.properties.get(), "{body}");
        }
    }

    const EVENT: &str = r#""event":"e","uuid":"019a0000-0000-7000-8000-000000000001","distinct_id":"d","timestamp":"2026-10-21T00:00:00Z""#;

    #[rstest]
    #[case::minimal(true, format!(r#"{{"created_at":"c","batch":[{{{EVENT}}}]}}"#))]
    #[case::padded_ids(true, r#"{"created_at":"c","batch":[{"event":"e","uuid":"  019a0000-0000-7000-8000-000000000001\t","distinct_id":"\n user 1 \r","timestamp":"t"}]}"#.to_owned())]
    #[case::escapes_and_unicode(true, r#"{"created_at":"c\u00e9","batch":[{"event":"a \"q\" \\ \ud83d\ude00 é","uuid":"u","distinct_id":"\u0000x","timestamp":"t"}]}"#.to_owned())]
    #[case::null_session_and_window(true, format!(r#"{{"created_at":"c","batch":[{{{EVENT},"session_id":null,"window_id":null}}]}}"#))]
    #[case::string_session_and_window(true, format!(r#"{{"created_at":"c","batch":[{{{EVENT},"session_id":" s ","window_id":"w"}}]}}"#))]
    #[case::unknown_fields(true, format!(r#"{{"created_at":"c","extra":{{"a":[1]}},"batch":[{{{EVENT},"other":7}}]}}"#))]
    #[case::options_object(true, format!(r#"{{"created_at":"c","batch":[{{{EVENT},"options":{{"process_person_profile":"yes","x":[1]}}}}]}}"#))]
    #[case::options_not_object(true, format!(r#"{{"created_at":"c","batch":[{{{EVENT},"options":"nope"}}]}}"#))]
    #[case::options_null(true, format!(r#"{{"created_at":"c","batch":[{{{EVENT},"options":null}}]}}"#))]
    #[case::properties_nested(true, format!(r#"{{"created_at":"c","batch":[{{{EVENT},"properties":{{"a":{{"b":[1,2.5e300,null]}},"n":123456789012345678901234567890}}}}]}}"#))]
    #[case::properties_not_object(true, format!(r#"{{"created_at":"c","batch":[{{{EVENT},"properties":[1,2]}}]}}"#))]
    #[case::flags_set(true, format!(r#"{{"created_at":"c","historical_migration":true,"capture_internal":true,"batch":[{{{EVENT}}}]}}"#))]
    #[case::flags_unreadable(true, format!(r#"{{"created_at":"c","historical_migration":{{"x":1}},"capture_internal":"maybe","batch":[{{{EVENT}}}]}}"#))]
    #[case::flags_lenient_strings(true, format!(r#"{{"created_at":"c","historical_migration":"yes","capture_internal":0,"batch":[{{{EVENT}}}]}}"#))]
    #[case::empty_batch(true, r#"{"created_at":"c","batch":[]}"#.to_owned())]
    #[case::empty_strings(true, r#"{"created_at":"","batch":[{"event":"","uuid":"","distinct_id":"   ","timestamp":""}]}"#.to_owned())]
    #[case::many_events(true, format!(r#"{{"created_at":"c","batch":[{{{EVENT}}},{{{EVENT},"session_id":"s"}},{{{EVENT}}}]}}"#))]
    #[case::event_as_array(true, r#"{"created_at":"c","batch":[["e"," u ","d","t","s",null,{"cookieless_mode":true},{"p":1}]]}"#.to_owned())]
    #[case::event_as_short_array(true, r#"{"created_at":"c","batch":[["e","u","d","t","s","w"]]}"#.to_owned())]
    #[case::batch_as_array(true, format!(r#"["c",true,null,[{{{EVENT}}}]]"#))]
    #[case::numeric_distinct_id(false, r#"{"created_at":"c","batch":[{"event":"e","uuid":"u","distinct_id":12345678901234567890,"timestamp":"t"}]}"#.to_owned())]
    #[case::null_event(false, r#"{"created_at":"c","batch":[{"event":null,"uuid":"u","distinct_id":"d","timestamp":"t"}]}"#.to_owned())]
    #[case::missing_uuid(false, r#"{"created_at":"c","batch":[{"event":"e","distinct_id":"d","timestamp":"t"}]}"#.to_owned())]
    #[case::object_timestamp(false, r#"{"created_at":"c","batch":[{"event":"e","uuid":"u","distinct_id":"d","timestamp":{"a":"alice@example.com"}}]}"#.to_owned())]
    #[case::numeric_session_id(false, format!(r#"{{"created_at":"c","batch":[{{{EVENT},"session_id":5}}]}}"#))]
    #[case::array_window_id(false, format!(r#"{{"created_at":"c","batch":[{{{EVENT},"window_id":["w"]}}]}}"#))]
    #[case::missing_created_at(false, format!(r#"{{"batch":[{{{EVENT}}}]}}"#))]
    #[case::numeric_created_at(false, format!(r#"{{"created_at":1,"batch":[{{{EVENT}}}]}}"#))]
    #[case::missing_batch(false, r#"{"created_at":"c"}"#.to_owned())]
    #[case::batch_not_array(false, r#"{"created_at":"c","batch":"alice@example.com"}"#.to_owned())]
    #[case::event_not_object(false, r#"{"created_at":"c","batch":["alice@example.com"]}"#.to_owned())]
    #[case::duplicate_event_key(false, r#"{"created_at":"c","batch":[{"event":"e","uuid":"u","distinct_id":"d","distinct_id":"d","timestamp":"t"}]}"#.to_owned())]
    #[case::duplicate_batch_key(false, format!(r#"{{"created_at":"c","created_at":"c","batch":[{{{EVENT}}}]}}"#))]
    #[case::event_as_too_short_array(false, r#"{"created_at":"c","batch":[["e","u","d","t"]]}"#.to_owned())]
    #[case::syntax_error(false, r#"{"created_at":"c","batch":[{]}"#.to_owned())]
    #[case::truncated(false, r#"{"created_at":"c","batch":[{"event":"e""#.to_owned())]
    #[case::lone_surrogate(false, r#"{"created_at":"c","batch":[{"event":"e","uuid":"u","distinct_id":"\ud800","timestamp":"t"}]}"#.to_owned())]
    #[case::number_out_of_range(false, r#"{"created_at":"c","batch":[{"event":"e","uuid":"u","distinct_id":1e400,"timestamp":"t"}]}"#.to_owned())]
    #[case::trailing_garbage(false, format!(r#"{{"created_at":"c","batch":[{{{EVENT}}}]}} x"#))]
    fn lenient_parse_accepts_and_builds_exactly_what_the_strict_types_do(
        #[case] accepted: bool,
        #[case] body: String,
    ) {
        let strict = serde_json::from_slice::<Batch>(body.as_bytes());
        let lenient = lenient_parse(body.as_bytes());
        assert_eq!(strict.is_ok(), accepted, "strict parse of {body}");

        match (strict, lenient) {
            (Ok(strict), Ok(Ok(lenient))) => assert_same_batch(&strict, &lenient, &body),
            (Err(_), Err(_)) | (Err(_), Ok(Err(_))) => {}
            (strict, lenient) => panic!(
                "strict ok={} but lenient ok={} for {body}",
                strict.is_ok(),
                matches!(lenient, Ok(Ok(_)))
            ),
        }
    }
}
