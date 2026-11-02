//! `JSON.parse` and `JSON.stringify` with V8's results.

use thiserror::Error;

use super::number::write_number;
use super::{JsKey, JsObject, JsString, JsValue};

/// `JSON.parse` threw. The message is not part of any output, so it stays short.
#[derive(Debug, Error, PartialEq, Eq)]
#[error("invalid JSON at byte {0}")]
pub struct JsonError(pub usize);

/// `JSON.parse(text)`. Recursion depth is bounded by the input, as in V8, which handles the
/// nesting this consumer accepts (bodies up to the record size cap).
pub fn json_parse(text: &str) -> Result<JsValue, JsonError> {
    let mut parser = Parser {
        bytes: text.as_bytes(),
        text,
        pos: 0,
    };
    parser.skip_ws();
    let value = parser.value()?;
    parser.skip_ws();
    if parser.pos != parser.bytes.len() {
        return Err(JsonError(parser.pos));
    }
    Ok(value)
}

#[derive(Debug, Clone, PartialEq)]
pub enum JsonShape {
    /// The top-level keys in source order, repeats included. A string value is kept for each
    /// key the caller asked for, and `None` stands for any other value.
    Object(Vec<(JsString, Option<JsString>)>),
    Array,
    String(JsString),
    Primitive,
}

/// Accepts exactly the text `json_parse` accepts, and reports its shape.
pub fn json_parse_shape(
    text: &str,
    keep_value: impl Fn(&JsString) -> bool,
) -> Result<JsonShape, JsonError> {
    let mut parser = Parser {
        bytes: text.as_bytes(),
        text,
        pos: 0,
    };
    parser.skip_ws();
    let shape = match parser.bytes.get(parser.pos) {
        Some(b'{') => JsonShape::Object(parser.object_entries(keep_value)?),
        Some(b'[') => {
            parser.skip_value()?;
            JsonShape::Array
        }
        Some(b'"') => JsonShape::String(parser.string()?),
        _ => {
            parser.skip_value()?;
            JsonShape::Primitive
        }
    };
    parser.skip_ws();
    if parser.pos != parser.bytes.len() {
        return Err(JsonError(parser.pos));
    }
    Ok(shape)
}

struct Parser<'a> {
    bytes: &'a [u8],
    text: &'a str,
    pos: usize,
}

impl Parser<'_> {
    fn err<T>(&self) -> Result<T, JsonError> {
        Err(JsonError(self.pos))
    }

    /// JSON whitespace is only space, tab, line feed and carriage return; a BOM is an error.
    fn skip_ws(&mut self) {
        while let Some(b) = self.bytes.get(self.pos) {
            if matches!(b, b' ' | b'\t' | b'\n' | b'\r') {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn eat(&mut self, lit: &str) -> Result<(), JsonError> {
        if self.bytes[self.pos..].starts_with(lit.as_bytes()) {
            self.pos += lit.len();
            Ok(())
        } else {
            self.err()
        }
    }

    fn value(&mut self) -> Result<JsValue, JsonError> {
        match self.bytes.get(self.pos) {
            Some(b'{') => self.object(),
            Some(b'[') => self.array(),
            Some(b'"') => Ok(JsValue::String(self.string()?)),
            Some(b't') => self.eat("true").map(|_| JsValue::Bool(true)),
            Some(b'f') => self.eat("false").map(|_| JsValue::Bool(false)),
            Some(b'n') => self.eat("null").map(|_| JsValue::Null),
            Some(b'-' | b'0'..=b'9') => self.number(),
            _ => self.err(),
        }
    }

    fn object(&mut self) -> Result<JsValue, JsonError> {
        self.pos += 1;
        let mut object = JsObject::new();
        self.skip_ws();
        if self.bytes.get(self.pos) == Some(&b'}') {
            self.pos += 1;
            return Ok(JsValue::Object(object));
        }
        loop {
            self.skip_ws();
            if self.bytes.get(self.pos) != Some(&b'"') {
                return self.err();
            }
            let key = self.string()?;
            self.skip_ws();
            if self.bytes.get(self.pos) != Some(&b':') {
                return self.err();
            }
            self.pos += 1;
            self.skip_ws();
            let value = self.value()?;
            // A repeated key keeps its first position and takes the last value.
            object.insert(key, value);
            self.skip_ws();
            match self.bytes.get(self.pos) {
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(JsValue::Object(object));
                }
                _ => return self.err(),
            }
        }
    }

    fn array(&mut self) -> Result<JsValue, JsonError> {
        self.pos += 1;
        let mut items = Vec::new();
        self.skip_ws();
        if self.bytes.get(self.pos) == Some(&b']') {
            self.pos += 1;
            return Ok(JsValue::Array(items));
        }
        loop {
            self.skip_ws();
            items.push(self.value()?);
            self.skip_ws();
            match self.bytes.get(self.pos) {
                Some(b',') => self.pos += 1,
                Some(b']') => {
                    self.pos += 1;
                    return Ok(JsValue::Array(items));
                }
                _ => return self.err(),
            }
        }
    }

    fn object_entries(
        &mut self,
        keep_value: impl Fn(&JsString) -> bool,
    ) -> Result<Vec<(JsString, Option<JsString>)>, JsonError> {
        self.pos += 1;
        let mut entries = Vec::new();
        self.skip_ws();
        if self.bytes.get(self.pos) == Some(&b'}') {
            self.pos += 1;
            return Ok(entries);
        }
        loop {
            self.skip_ws();
            if self.bytes.get(self.pos) != Some(&b'"') {
                return self.err();
            }
            let key = self.string()?;
            self.skip_ws();
            if self.bytes.get(self.pos) != Some(&b':') {
                return self.err();
            }
            self.pos += 1;
            self.skip_ws();
            let value = if self.bytes.get(self.pos) == Some(&b'"') && keep_value(&key) {
                Some(self.string()?)
            } else {
                self.skip_value()?;
                None
            };
            entries.push((key, value));
            self.skip_ws();
            match self.bytes.get(self.pos) {
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(entries);
                }
                _ => return self.err(),
            }
        }
    }

    fn skip_value(&mut self) -> Result<(), JsonError> {
        match self.bytes.get(self.pos) {
            Some(b'{') => {
                self.pos += 1;
                self.skip_ws();
                if self.bytes.get(self.pos) == Some(&b'}') {
                    self.pos += 1;
                    return Ok(());
                }
                loop {
                    self.skip_ws();
                    if self.bytes.get(self.pos) != Some(&b'"') {
                        return self.err();
                    }
                    self.skip_string()?;
                    self.skip_ws();
                    if self.bytes.get(self.pos) != Some(&b':') {
                        return self.err();
                    }
                    self.pos += 1;
                    self.skip_ws();
                    self.skip_value()?;
                    self.skip_ws();
                    match self.bytes.get(self.pos) {
                        Some(b',') => self.pos += 1,
                        Some(b'}') => {
                            self.pos += 1;
                            return Ok(());
                        }
                        _ => return self.err(),
                    }
                }
            }
            Some(b'[') => {
                self.pos += 1;
                self.skip_ws();
                if self.bytes.get(self.pos) == Some(&b']') {
                    self.pos += 1;
                    return Ok(());
                }
                loop {
                    self.skip_ws();
                    self.skip_value()?;
                    self.skip_ws();
                    match self.bytes.get(self.pos) {
                        Some(b',') => self.pos += 1,
                        Some(b']') => {
                            self.pos += 1;
                            return Ok(());
                        }
                        _ => return self.err(),
                    }
                }
            }
            Some(b'"') => self.skip_string(),
            Some(b't') => self.eat("true"),
            Some(b'f') => self.eat("false"),
            Some(b'n') => self.eat("null"),
            // Every number the grammar accepts parses to a double, so only the grammar is checked.
            Some(b'-' | b'0'..=b'9') => self.scan_number().map(|_| ()),
            _ => self.err(),
        }
    }

    fn skip_string(&mut self) -> Result<(), JsonError> {
        self.pos += 1;
        loop {
            while let Some(&b) = self.bytes.get(self.pos) {
                if b == b'"' || b == b'\\' || b < 0x20 {
                    break;
                }
                self.pos += 1;
            }
            match self.bytes.get(self.pos) {
                Some(b'"') => {
                    self.pos += 1;
                    return Ok(());
                }
                Some(b'\\') => {
                    self.pos += 1;
                    let escape = *self.bytes.get(self.pos).ok_or(JsonError(self.pos))?;
                    self.pos += 1;
                    match escape {
                        b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't' => {}
                        b'u' => {
                            self.hex4()?;
                        }
                        _ => return self.err(),
                    }
                }
                _ => return self.err(),
            }
        }
    }

    fn digits(&mut self) -> usize {
        let start = self.pos;
        while matches!(self.bytes.get(self.pos), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
        self.pos - start
    }

    fn scan_number(&mut self) -> Result<usize, JsonError> {
        let start = self.pos;
        if self.bytes[self.pos] == b'-' {
            self.pos += 1;
        }
        match self.bytes.get(self.pos) {
            Some(b'0') => self.pos += 1,
            Some(b'1'..=b'9') => {
                self.digits();
            }
            _ => return self.err(),
        }
        if self.bytes.get(self.pos) == Some(&b'.') {
            self.pos += 1;
            if self.digits() == 0 {
                return self.err();
            }
        }
        if matches!(self.bytes.get(self.pos), Some(b'e' | b'E')) {
            self.pos += 1;
            if matches!(self.bytes.get(self.pos), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            if self.digits() == 0 {
                return self.err();
            }
        }
        Ok(start)
    }

    fn number(&mut self) -> Result<JsValue, JsonError> {
        let start = self.scan_number()?;
        // Rust parses decimal strings to the nearest f64, as V8 does.
        let n: f64 = self.text[start..self.pos]
            .parse()
            .map_err(|_| JsonError(start))?;
        Ok(JsValue::Number(n))
    }

    fn hex4(&mut self) -> Result<u16, JsonError> {
        let slice = self
            .bytes
            .get(self.pos..self.pos + 4)
            .ok_or(JsonError(self.pos))?;
        let s = std::str::from_utf8(slice).map_err(|_| JsonError(self.pos))?;
        if !s.bytes().all(|b| b.is_ascii_hexdigit()) {
            return self.err();
        }
        self.pos += 4;
        Ok(u16::from_str_radix(s, 16).expect("checked hex"))
    }

    fn string(&mut self) -> Result<JsString, JsonError> {
        self.pos += 1;
        let mut out = JsString::new();
        loop {
            let run_start = self.pos;
            while let Some(&b) = self.bytes.get(self.pos) {
                if b == b'"' || b == b'\\' || b < 0x20 {
                    break;
                }
                self.pos += 1;
            }
            out.push_str(&self.text[run_start..self.pos]);
            match self.bytes.get(self.pos) {
                Some(b'"') => {
                    self.pos += 1;
                    return Ok(out);
                }
                Some(b'\\') => {
                    self.pos += 1;
                    let escape = *self.bytes.get(self.pos).ok_or(JsonError(self.pos))?;
                    self.pos += 1;
                    match escape {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let unit = self.hex4()?;
                            out.push_code_unit(unit);
                        }
                        _ => return self.err(),
                    }
                }
                _ => return self.err(),
            }
        }
    }
}

pub fn json_stringify(value: &JsValue) -> String {
    let mut out = String::new();
    json_stringify_into(value, &mut out);
    out
}

pub fn json_stringify_into(value: &JsValue, out: &mut String) {
    match value {
        JsValue::Null => out.push_str("null"),
        JsValue::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        JsValue::Number(n) => {
            if n.is_finite() {
                write_number(*n, out)
            } else {
                out.push_str("null")
            }
        }
        JsValue::String(s) => quote_js_string(s, out),
        JsValue::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                json_stringify_into(item, out);
            }
            out.push(']');
        }
        JsValue::Object(object) => {
            out.push('{');
            for (i, (key, item)) in object.entries().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                match key {
                    JsKey::Index(n) => {
                        out.push('"');
                        out.push_str(itoa::Buffer::new().format(n));
                        out.push('"');
                    }
                    JsKey::Named(key) => quote_js_string(key, out),
                }
                out.push(':');
                json_stringify_into(item, out);
            }
            out.push('}');
        }
    }
}

fn push_escape(c: u32, out: &mut String) {
    use std::fmt::Write;
    match c {
        0x22 => out.push_str("\\\""),
        0x5C => out.push_str("\\\\"),
        0x08 => out.push_str("\\b"),
        0x0C => out.push_str("\\f"),
        0x0A => out.push_str("\\n"),
        0x0D => out.push_str("\\r"),
        0x09 => out.push_str("\\t"),
        _ => {
            let _ = write!(out, "\\u{c:04x}");
        }
    }
}

/// `JSON.stringify` of a string. Lone surrogates are written as `\udXXX`, as in well-formed
/// `JSON.stringify` (ES2019).
pub fn quote_js_string(s: &JsString, out: &mut String) {
    out.push('"');
    match s.as_str() {
        Some(text) => quote_str_body(text, out),
        None => {
            for unit in s.chars_or_surrogates() {
                match unit.as_char() {
                    Ok(c) => {
                        let mut buf = [0u8; 4];
                        quote_str_body(c.encode_utf8(&mut buf), out);
                    }
                    Err(surrogate) => push_escape(surrogate as u32, out),
                }
            }
        }
    }
    out.push('"');
}

fn quote_str_body(text: &str, out: &mut String) {
    let bytes = text.as_bytes();
    let mut run = 0;
    for (i, &b) in bytes.iter().enumerate() {
        if b < 0x20 || b == b'"' || b == b'\\' {
            out.push_str(&text[run..i]);
            push_escape(b as u32, out);
            run = i + 1;
        }
    }
    out.push_str(&text[run..]);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn roundtrip(text: &str) -> String {
        json_stringify(&json_parse(text).unwrap())
    }

    #[test]
    fn parse_matches_v8() {
        assert_eq!(
            roundtrip(r#"{"dup":1,"b":2,"dup":3}"#),
            r#"{"dup":3,"b":2}"#
        );
        assert_eq!(
            roundtrip(r#"{"b":1,"1":2,"0":3}"#),
            r#"{"0":3,"1":2,"b":1}"#
        );
        assert_eq!(
            roundtrip(r#"{"__proto__":{"x":1}}"#),
            r#"{"__proto__":{"x":1}}"#
        );
        assert_eq!(roundtrip("12345678901234567890"), "12345678901234567000");
        assert_eq!(roundtrip("-0"), "0");
        assert_eq!(roundtrip(" [1 , 2]\n"), "[1,2]");
        assert_eq!(roundtrip(r#""🚀""#), "\"🚀\"");
        assert_eq!(roundtrip(r#""\ud83d""#), r#""\ud83d""#);
        for bad in [
            "\u{feff}{}",
            "{\"a\":1,}",
            "{'a':1}",
            "01",
            "1.",
            ".5",
            "+1",
            "\"\t\"",
            "",
            "nul",
            "[1,]",
            "\u{a0}1",
            "NaN",
        ] {
            assert!(json_parse(bad).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn stringify_escapes_like_v8() {
        let s = JsValue::string("q\" b\\ \u{8}\u{c}\n\r\t \u{0} \u{1f} \u{7f} \u{2028}\u{2029} é");
        assert_eq!(
            json_stringify(&s),
            "\"q\\\" b\\\\ \\b\\f\\n\\r\\t \\u0000 \\u001f \u{7f} \u{2028}\u{2029} é\""
        );
    }

    #[test]
    fn stringify_numbers_like_v8() {
        for (n, expected) in [
            (1e21, "1e+21"),
            (1e-7, "1e-7"),
            (0.1 + 0.2, "0.30000000000000004"),
            (-0.0, "0"),
            (5e-324, "5e-324"),
            (9007199254740993.0, "9007199254740992"),
            (123e20, "1.23e+22"),
            (f64::NAN, "null"),
            (f64::INFINITY, "null"),
        ] {
            assert_eq!(json_stringify(&JsValue::Number(n)), expected);
        }
    }
}
