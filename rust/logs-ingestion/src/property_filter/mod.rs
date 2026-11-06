//! Operators coerce with `String()` and `parseFloat` in the TypeScript order, because `String()` can throw and the caller then fails open.

pub mod coerce;
pub mod re2;

use std::sync::Arc;

use crate::js::{JsString, JsValue};

use self::coerce::{
    js_compare, js_ends_with, js_includes, js_parse_float, js_starts_with, js_to_lower,
    js_to_string, JsTypeError,
};
use self::re2::Re2;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Operator {
    Exact,
    IsNot,
    IsSet,
    IsNotSet,
    Icontains,
    NotIcontains,
    StartsWith,
    NotStartsWith,
    EndsWith,
    NotEndsWith,
    Regex,
    NotRegex,
    Gt,
    Gte,
    Lt,
    Lte,
    In,
    NotIn,
    /// Includes a non-string operator. It never matches.
    Unknown,
}

impl Operator {
    fn from_json(value: Option<&JsValue>) -> Operator {
        let name = match value {
            None | Some(JsValue::Null) => return Operator::Exact,
            Some(JsValue::String(s)) => s.as_str().unwrap_or(""),
            Some(_) => return Operator::Unknown,
        };
        match name {
            "exact" => Operator::Exact,
            "is_not" => Operator::IsNot,
            "is_set" => Operator::IsSet,
            "is_not_set" => Operator::IsNotSet,
            "icontains" => Operator::Icontains,
            "not_icontains" => Operator::NotIcontains,
            "starts_with" => Operator::StartsWith,
            "not_starts_with" => Operator::NotStartsWith,
            "ends_with" => Operator::EndsWith,
            "not_ends_with" => Operator::NotEndsWith,
            "regex" => Operator::Regex,
            "not_regex" => Operator::NotRegex,
            "gt" => Operator::Gt,
            "gte" => Operator::Gte,
            "lt" => Operator::Lt,
            "lte" => Operator::Lte,
            "in" => Operator::In,
            "not_in" => Operator::NotIn,
            _ => Operator::Unknown,
        }
    }
}

/// A leaf filter. Each field is `None` when the JavaScript property is `undefined`.
#[derive(Debug, Clone)]
pub struct PropertyFilterLeaf {
    pub key: Option<JsValue>,
    pub operator: Option<JsValue>,
    pub value: Option<JsValue>,
    pub filter_type: Option<JsValue>,
    op: Operator,
    /// `Some(None)` when the pattern failed to compile, so the leaf never matches.
    compiled_regex: Option<Option<Arc<Re2>>>,
}

impl PropertyFilterLeaf {
    pub fn from_json(node: &JsValue) -> PropertyFilterLeaf {
        let field = |name: &str| match node {
            JsValue::Object(o) => o.get(name).cloned(),
            _ => None,
        };
        let operator = field("operator");
        let value = field("value");
        let op = Operator::from_json(operator.as_ref());
        // `parseFilterGroup` compiles every leaf whose operator is literally 'regex' or 'not_regex', which equals compiling at match time.
        let compiled_regex = match operator.as_ref() {
            Some(JsValue::String(s)) if s == "regex" || s == "not_regex" => Some(match &value {
                None | Some(JsValue::Null) => None,
                Some(v) => compile_leaf_regex(v),
            }),
            _ => None,
        };
        PropertyFilterLeaf {
            key: field("key"),
            operator,
            value,
            filter_type: field("type"),
            op,
            compiled_regex,
        }
    }

    pub fn type_is(&self, name: &str) -> bool {
        matches!(&self.filter_type, Some(JsValue::String(s)) if s == name)
    }

    pub fn key_is(&self, name: &str) -> bool {
        matches!(&self.key, Some(JsValue::String(s)) if s == name)
    }

    pub fn value_count(&self) -> usize {
        match &self.value {
            None | Some(JsValue::Null) => 0,
            Some(JsValue::Array(items)) => items.len(),
            Some(_) => 1,
        }
    }
}

pub fn compile_leaf_regex(pattern: &JsValue) -> Option<Arc<Re2>> {
    let text = js_to_string(pattern).ok()?;
    Re2::new(text.bytes_wtf8(), "is").ok().map(Arc::new)
}

/// `override_value` is `String()` of the record value, or `None` for `undefined` and `null`.
pub fn match_property_filter(
    filter: &PropertyFilterLeaf,
    override_value: Option<&JsString>,
) -> Result<bool, JsTypeError> {
    let op = filter.op;
    if op == Operator::IsSet {
        return Ok(override_value.is_some_and(|v| !v.is_empty()));
    }
    if op == Operator::IsNotSet {
        return Ok(override_value.is_none_or(|v| v.is_empty()));
    }
    let Some(override_value) = override_value else {
        return Ok(false);
    };
    let value = match &filter.value {
        None | Some(JsValue::Null) => return Ok(false),
        Some(v) => v,
    };
    match op {
        Operator::Exact | Operator::In => match_exact(value, override_value),
        Operator::IsNot | Operator::NotIn => Ok(!match_exact(value, override_value)?),
        Operator::Icontains | Operator::NotIcontains => {
            let haystack = js_to_lower(override_value);
            let needle = js_to_lower(&js_to_string(value)?);
            let found = js_includes(&haystack, &needle);
            Ok(if op == Operator::Icontains {
                found
            } else {
                !found
            })
        }
        Operator::StartsWith | Operator::NotStartsWith => {
            let found = js_starts_with(
                &js_to_lower(override_value),
                &js_to_lower(&js_to_string(value)?),
            );
            Ok(if op == Operator::StartsWith {
                found
            } else {
                !found
            })
        }
        Operator::EndsWith | Operator::NotEndsWith => {
            let found = js_ends_with(
                &js_to_lower(override_value),
                &js_to_lower(&js_to_string(value)?),
            );
            Ok(if op == Operator::EndsWith {
                found
            } else {
                !found
            })
        }
        Operator::Regex | Operator::NotRegex => {
            let regex = match &filter.compiled_regex {
                Some(compiled) => compiled.clone(),
                None => compile_leaf_regex(value),
            };
            let Some(regex) = regex else {
                return Ok(false);
            };
            let found = regex.test(&override_value.to_utf8_lossy());
            Ok(if op == Operator::Regex { found } else { !found })
        }
        Operator::Gt | Operator::Gte | Operator::Lt | Operator::Lte => {
            compare_numeric(value, override_value, op)
        }
        Operator::IsSet | Operator::IsNotSet | Operator::Unknown => Ok(false),
    }
}

fn match_exact(value: &JsValue, override_value: &JsString) -> Result<bool, JsTypeError> {
    if is_truthy_or_falsy_value(value) {
        let expected = if is_true_value(value) {
            "true"
        } else {
            "false"
        };
        return Ok(js_to_lower(override_value) == expected);
    }
    if let JsValue::Array(items) = value {
        let wanted = js_to_lower(override_value);
        for item in items {
            if js_to_lower(&js_to_string(item)?) == wanted {
                return Ok(true);
            }
        }
        return Ok(false);
    }
    let value_text = js_to_lower(&js_to_string(value)?);
    Ok(value_text == js_to_lower(override_value))
}

fn is_boolean_word(v: &JsValue) -> bool {
    match v {
        JsValue::Bool(_) => true,
        JsValue::String(s) => matches!(s.as_str(), Some("true" | "True" | "false" | "False")),
        _ => false,
    }
}

fn is_truthy_or_falsy_value(v: &JsValue) -> bool {
    match v {
        JsValue::Array(items) if items.len() == 1 => is_boolean_word(&items[0]),
        other => is_boolean_word(other),
    }
}

fn is_true_value(v: &JsValue) -> bool {
    match v {
        JsValue::Bool(b) => *b,
        JsValue::String(s) => matches!(s.as_str(), Some("true" | "True")),
        JsValue::Array(items) if items.len() == 1 => is_true_value(&items[0]),
        _ => false,
    }
}

fn compare_numeric(
    value: &JsValue,
    override_value: &JsString,
    op: Operator,
) -> Result<bool, JsTypeError> {
    let parsed_value = match value {
        JsValue::Number(n) => *n,
        other => js_parse_float(&js_to_string(other)?),
    };
    if parsed_value.is_finite() {
        let override_num = js_parse_float(override_value);
        if override_num.is_finite() {
            return Ok(match op {
                Operator::Gt => override_num > parsed_value,
                Operator::Gte => override_num >= parsed_value,
                Operator::Lt => override_num < parsed_value,
                _ => override_num <= parsed_value,
            });
        }
    }
    let ord = js_compare(override_value, &js_to_string(value)?);
    Ok(match op {
        Operator::Gt => ord.is_gt(),
        Operator::Gte => ord.is_ge(),
        Operator::Lt => ord.is_lt(),
        _ => ord.is_le(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::js::json_parse;

    fn leaf(json: &str) -> PropertyFilterLeaf {
        PropertyFilterLeaf::from_json(&json_parse(json).unwrap())
    }

    fn m(json: &str, value: Option<&str>) -> Result<bool, JsTypeError> {
        let v = value.map(JsString::from);
        match_property_filter(&leaf(json), v.as_ref())
    }

    #[test]
    fn operators_follow_javascript_coercion() {
        let cases: &[(&str, Option<&str>, bool)] = &[
            (r#"{"operator":"is_set"}"#, Some(""), false),
            (r#"{"operator":"is_not_set"}"#, Some(""), true),
            (r#"{"value":"x"}"#, None, false),
            (r#"{"operator":"exact"}"#, Some("x"), false),
            (r#"{"value":"TRUE"}"#, Some("true"), true),
            (r#"{"value":"True"}"#, Some("TRUE"), true),
            (r#"{"value":[false]}"#, Some("False"), true),
            (r#"{"value":[null,"A"]}"#, Some("a"), true),
            (r#"{"value":[null]}"#, Some("null"), true),
            (r#"{"value":1e21}"#, Some("1E+21"), true),
            (
                r#"{"operator":"is_not","value":["a","b"]}"#,
                Some("c"),
                true,
            ),
            (
                r#"{"operator":"icontains","value":"ΣΑ"}"#,
                Some("xσα"),
                true,
            ),
            (r#"{"operator":"gt","value":"10"}"#, Some("9"), false),
            (r#"{"operator":"gt","value":"abc"}"#, Some("abd"), true),
            (r#"{"operator":"gt","value":"10"}"#, Some("9x"), false),
            (r#"{"operator":"gt","value":"10"}"#, Some("x"), true),
            (r#"{"operator":"lte","value":["5"]}"#, Some("5.0"), true),
            (r#"{"operator":"gte","value":true}"#, Some("true"), true),
            (r#"{"operator":"regex","value":"^A"}"#, Some("abc"), true),
            (
                r#"{"operator":"not_regex","value":"(?=a)"}"#,
                Some("abc"),
                false,
            ),
            (
                r#"{"operator":"regex","value":"(?=a)"}"#,
                Some("abc"),
                false,
            ),
            (r#"{"operator":5,"value":"x"}"#, Some("x"), false),
            (r#"{"operator":null,"value":"x"}"#, Some("X"), true),
        ];
        for (json, value, expected) in cases {
            assert_eq!(m(json, *value), Ok(*expected), "{json} on {value:?}");
        }
    }

    #[test]
    fn an_object_with_own_to_string_throws_where_javascript_throws() {
        assert!(m(r#"{"value":{"toString":1}}"#, Some("x")).is_err());
        assert!(m(r#"{"value":["x",{"toString":1}]}"#, Some("x")) == Ok(true));
        assert!(m(r#"{"value":[{"toString":1},"x"]}"#, Some("x")).is_err());
        assert_eq!(
            m(r#"{"operator":"regex","value":{"toString":1}}"#, Some("x")),
            Ok(false)
        );
    }
}
