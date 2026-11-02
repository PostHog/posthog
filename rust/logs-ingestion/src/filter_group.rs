//! Port of `nodejs/src/logs/sampling/filter-group-match.ts`: the recursive AND/OR matcher for a
//! drop rule's `filter_group`, and the key lookup against log and span records.
//!
//! An attribute map in Node is a plain object, so `map[key]` also finds `Object.prototype`
//! members. A filter whose key is `constructor` or `toString` therefore reads a function, and
//! `__defineGetter__` makes the attribute decoder throw. `lookup_attribute` reproduces this.

use std::borrow::Cow;

use crate::attribute_value::decode_log_attribute_value;
use crate::avro::AvroMap;
use crate::js::{number_to_string, JsString, JsValue};
use crate::property_filter::coerce::{js_to_string_opt, JsTypeError};
use crate::property_filter::{match_property_filter, PropertyFilterLeaf};
use crate::record::LogRecord;

/// Past this depth a group never matches. `parse_filter_group` rejects deeper trees.
pub const MAX_FILTER_GROUP_DEPTH: usize = 16;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GroupType {
    And,
    Or,
}

#[derive(Debug, Clone)]
pub struct FilterGroupNode {
    pub group_type: GroupType,
    pub values: Vec<FilterNode>,
}

#[derive(Debug, Clone)]
pub enum FilterNode {
    Group(FilterGroupNode),
    Leaf(Box<PropertyFilterLeaf>),
}

/// A `Object.prototype` member that `map[key]` returns when the map has no own `key`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InheritedMember {
    /// `String(member)`.
    pub text: &'static str,
    /// `member.length`, which `decodeLogAttributeValue` reads first. `None` for `__proto__`.
    pub length: Option<u32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AttrLookup<'a> {
    Own(&'a str),
    Inherited(InheritedMember),
}

impl AttrLookup<'_> {
    pub fn text(&self) -> &str {
        match self {
            AttrLookup::Own(s) => s,
            AttrLookup::Inherited(m) => m.text,
        }
    }
}

/// The members of `Object.prototype` in Node 22.
pub fn inherited_member(key: &str) -> Option<InheritedMember> {
    let (text, length) = match key {
        "constructor" => ("function Object() { [native code] }", Some(1)),
        "__defineGetter__" => ("function __defineGetter__() { [native code] }", Some(2)),
        "__defineSetter__" => ("function __defineSetter__() { [native code] }", Some(2)),
        "hasOwnProperty" => ("function hasOwnProperty() { [native code] }", Some(1)),
        "__lookupGetter__" => ("function __lookupGetter__() { [native code] }", Some(1)),
        "__lookupSetter__" => ("function __lookupSetter__() { [native code] }", Some(1)),
        "isPrototypeOf" => ("function isPrototypeOf() { [native code] }", Some(1)),
        "propertyIsEnumerable" => ("function propertyIsEnumerable() { [native code] }", Some(1)),
        "toString" => ("function toString() { [native code] }", Some(0)),
        "valueOf" => ("function valueOf() { [native code] }", Some(0)),
        "toLocaleString" => ("function toLocaleString() { [native code] }", Some(0)),
        "__proto__" => ("[object Object]", None),
        _ => return None,
    };
    Some(InheritedMember { text, length })
}

pub fn lookup_attribute<'a>(map: &'a AvroMap, key: &str) -> Option<AttrLookup<'a>> {
    if let Some(v) = map.get(key) {
        // The log schemas hold string maps. A non-string value cannot come from a decode.
        return v.as_str().map(AttrLookup::Own);
    }
    inherited_member(key).map(AttrLookup::Inherited)
}

fn decoded_attr(map: Option<&AvroMap>, key: &JsKey) -> Result<Option<JsString>, JsTypeError> {
    let Some(map) = map else {
        return Ok(None);
    };
    let key = key.resolve()?;
    // A key with a lone surrogate cannot equal a decoded map key or a prototype member.
    let Some(key) = key.as_str() else {
        return Ok(None);
    };
    match lookup_attribute(map, key) {
        None => Ok(None),
        Some(AttrLookup::Own(raw)) => Ok(Some(decode_log_attribute_value(raw))),
        Some(AttrLookup::Inherited(member)) => {
            // `value.length >= 2 && value.startsWith(...)`: a function has no `startsWith`.
            if member.length.is_some_and(|n| n >= 2) {
                return Err(JsTypeError("value.startsWith is not a function"));
            }
            Ok(Some(JsString::from(member.text)))
        }
    }
}

/// A property key, converted with `String()` only when a lookup needs it, as `map?.[key]` does.
struct JsKey<'a>(Option<&'a JsValue>);

impl JsKey<'_> {
    fn resolve(&self) -> Result<Cow<'_, JsString>, JsTypeError> {
        match self.0 {
            Some(JsValue::String(s)) => Ok(Cow::Borrowed(s)),
            other => js_to_string_opt(other).map(Cow::Owned),
        }
    }
}

fn str_key<'a>(s: &'a JsValue) -> JsKey<'a> {
    JsKey(Some(s))
}

pub fn match_filter_group(
    group: &FilterGroupNode,
    record: &LogRecord,
) -> Result<bool, JsTypeError> {
    match_group_at(group, record, 0)
}

fn match_group_at(
    group: &FilterGroupNode,
    record: &LogRecord,
    depth: usize,
) -> Result<bool, JsTypeError> {
    if depth >= MAX_FILTER_GROUP_DEPTH || group.values.is_empty() {
        return Ok(false);
    }
    match group.group_type {
        GroupType::Or => {
            for child in &group.values {
                if match_one(child, record, depth + 1)? {
                    return Ok(true);
                }
            }
            Ok(false)
        }
        GroupType::And => {
            for child in &group.values {
                if !match_one(child, record, depth + 1)? {
                    return Ok(false);
                }
            }
            Ok(true)
        }
    }
}

fn match_one(node: &FilterNode, record: &LogRecord, depth: usize) -> Result<bool, JsTypeError> {
    match node {
        FilterNode::Group(g) => match_group_at(g, record, depth),
        FilterNode::Leaf(leaf) => {
            let value = lookup_record_value(leaf, record)?;
            match_property_filter(leaf, value.as_ref())
        }
    }
}

fn lookup_record_value(
    filter: &PropertyFilterLeaf,
    record: &LogRecord,
) -> Result<Option<JsString>, JsTypeError> {
    let key = JsKey(filter.key.as_ref());
    if filter.key_is("service_name") || filter.key_is("service.name") {
        if let Some(s) = record.service_name() {
            return Ok(Some(JsString::from(s)));
        }
        return decoded_attr(
            record.resource_attributes(),
            &str_key(&JsValue::string("service.name")),
        );
    }
    if filter.key_is("severity_text") || filter.key_is("level") || filter.key_is("severity_level") {
        if let Some(s) = record.severity_text() {
            return Ok(Some(JsString::from(s)));
        }
        if let Some(v) = decoded_attr(record.attributes(), &str_key(&JsValue::string("level")))? {
            return Ok(Some(v));
        }
        return decoded_attr(
            record.attributes(),
            &str_key(&JsValue::string("severity_text")),
        );
    }
    if filter.key_is("message") || filter.type_is("log") {
        return Ok(record.body().map(JsString::from));
    }
    if filter.type_is("span_attribute") {
        if filter.key_is("status_code") {
            return match record.status_code() {
                Some(code) => Ok(Some(JsString::from(number_to_string(code as f64)))),
                None => decoded_attr(record.attributes(), &key),
            };
        }
        if filter.key_is("name") {
            return match record.name() {
                Some(name) => Ok(Some(JsString::from(name))),
                None => decoded_attr(record.attributes(), &key),
            };
        }
        if filter.key_is("kind") {
            return match record.kind() {
                Some(kind) => Ok(Some(JsString::from(number_to_string(kind as f64)))),
                None => decoded_attr(record.attributes(), &key),
            };
        }
    }
    if filter.type_is("log_resource_attribute") || filter.type_is("span_resource_attribute") {
        return decoded_attr(record.resource_attributes(), &key);
    }
    if filter.type_is("log_attribute") || filter.type_is("span_attribute") {
        return decoded_attr(record.attributes(), &key);
    }
    if let Some(v) = decoded_attr(record.attributes(), &key)? {
        return Ok(Some(v));
    }
    decoded_attr(record.resource_attributes(), &key)
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::avro::AvroValue;
    use crate::js::json_parse;

    fn record(attrs: &[(&str, &str)]) -> LogRecord {
        LogRecord::from_value(AvroValue::Record(vec![
            (Arc::from("body"), AvroValue::String("hello".into())),
            (Arc::from("severity_text"), AvroValue::Null),
            (
                Arc::from("attributes"),
                AvroValue::Map(AvroMap::from_strings(attrs.iter().copied())),
            ),
        ]))
    }

    fn group(json: &str) -> FilterGroupNode {
        crate::sampling::parse_filter_group(&json_parse(json).unwrap())
            .unwrap()
            .unwrap()
    }

    #[test]
    fn prototype_members_resolve_like_a_plain_object() {
        let r = record(&[("level", "\"warn\"")]);
        let set = group(r#"{"type":"AND","values":[{"key":"constructor","operator":"is_set"}]}"#);
        assert_eq!(match_filter_group(&set, &r), Ok(true));
        let native = group(
            r#"{"type":"AND","values":[{"key":"toString","operator":"icontains","value":"native code"}]}"#,
        );
        assert_eq!(match_filter_group(&native, &r), Ok(true));
        let throws =
            group(r#"{"type":"AND","values":[{"key":"__defineGetter__","operator":"is_set"}]}"#);
        assert!(match_filter_group(&throws, &r).is_err());
        let level = group(
            r#"{"type":"AND","values":[{"key":"severity_level","operator":"exact","value":"WARN"}]}"#,
        );
        assert_eq!(match_filter_group(&level, &r), Ok(true));
    }

    #[test]
    fn a_non_string_key_is_converted_with_string() {
        let r = record(&[("1", "\"one\""), ("undefined", "\"u\"")]);
        let numeric =
            group(r#"{"type":"AND","values":[{"key":1,"operator":"exact","value":"one"}]}"#);
        assert_eq!(match_filter_group(&numeric, &r), Ok(true));
        let missing = group(r#"{"type":"AND","values":[{"operator":"exact","value":"u"}]}"#);
        assert_eq!(match_filter_group(&missing, &r), Ok(true));
    }
}
