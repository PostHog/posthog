//! JSON as JavaScript reads it: `JSON.parse` of the message text, and `Number()` of a header. The index contract is
//! defined by what these accept.
//!
//! Numbers are doubles, as in JavaScript, so `5.0` and `5e0` are the integer 5. A string keeps a lone surrogate escape
//! as WTF-8, because JavaScript strings hold one: it sorts as a UTF-16 code unit and is written as U+FFFD, as
//! `Buffer.from` writes it. Containers deeper than a row needs are checked and not built, so a deep value cannot
//! exhaust the stack.

use std::borrow::Cow;
use std::cmp::Ordering;

/// Containers nested this deep or deeper are checked but not built. A row object, a moments array and a moment object
/// are the deepest containers a row reads.
const BUILT_CONTAINER_DEPTH: usize = 3;

#[derive(Debug, Clone, PartialEq)]
pub enum Json<'a> {
    Null,
    Bool(bool),
    Number(f64),
    String(JsString<'a>),
    Array(Vec<Json<'a>>),
    Object(Vec<(JsString<'a>, Json<'a>)>),
    DeepArray,
    DeepObject,
}

impl<'a> Json<'a> {
    /// The value of the last occurrence of `key`, as `JSON.parse` keeps the last of duplicate keys.
    pub fn field(fields: &'a [(JsString<'a>, Json<'a>)], key: &str) -> Option<&'a Json<'a>> {
        fields
            .iter()
            .rev()
            .find(|(name, _)| name.as_bytes() == key.as_bytes())
            .map(|(_, value)| value)
    }
}

/// A JavaScript string as WTF-8: UTF-8 that can also hold lone surrogates.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JsString<'a>(Cow<'a, [u8]>);

impl<'a> JsString<'a> {
    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }

    pub fn into_owned(self) -> JsString<'static> {
        JsString(Cow::Owned(self.0.into_owned()))
    }

    /// The UTF-8 that `Buffer.from` writes, with each lone surrogate as U+FFFD.
    pub fn to_utf8(&self) -> Cow<'_, [u8]> {
        let bytes = self.as_bytes();
        if !has_surrogate(bytes) {
            return Cow::Borrowed(bytes);
        }
        let mut out = Vec::with_capacity(bytes.len());
        let mut index = 0;
        while index < bytes.len() {
            if is_surrogate_at(bytes, index) {
                out.extend_from_slice("\u{fffd}".as_bytes());
                index += 3;
            } else {
                out.push(bytes[index]);
                index += 1;
            }
        }
        Cow::Owned(out)
    }

    pub fn utf16_len(&self) -> usize {
        Utf16Units::new(self.as_bytes()).count()
    }

    /// JavaScript's `<` on strings: UTF-16 code unit order, which differs from code point order.
    pub fn cmp_utf16(&self, other: &Self) -> Ordering {
        let (a, b) = (self.as_bytes(), other.as_bytes());
        let mut common = a.iter().zip(b).take_while(|(x, y)| x == y).count();
        while common > 0 && common < a.len() && is_continuation(a[common]) {
            common -= 1;
        }
        Utf16Units::new(&a[common..]).cmp(Utf16Units::new(&b[common..]))
    }
}

fn is_continuation(byte: u8) -> bool {
    byte & 0xC0 == 0x80
}

fn has_surrogate(bytes: &[u8]) -> bool {
    bytes
        .windows(2)
        .any(|pair| pair[0] == 0xED && pair[1] >= 0xA0)
}

fn is_surrogate_at(bytes: &[u8], index: usize) -> bool {
    bytes[index] == 0xED && bytes.get(index + 1).is_some_and(|next| *next >= 0xA0)
}

struct Utf16Units<'a> {
    bytes: &'a [u8],
    low: Option<u16>,
}

impl<'a> Utf16Units<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, low: None }
    }
}

impl Iterator for Utf16Units<'_> {
    type Item = u16;

    fn next(&mut self) -> Option<u16> {
        if let Some(low) = self.low.take() {
            return Some(low);
        }
        let (&lead, rest) = self.bytes.split_first()?;
        let (width, initial) = match lead {
            0x00..=0x7F => (1, u32::from(lead)),
            0xC0..=0xDF => (2, u32::from(lead & 0x1F)),
            0xE0..=0xEF => (3, u32::from(lead & 0x0F)),
            _ => (4, u32::from(lead & 0x07)),
        };
        let code_point = rest[..width - 1]
            .iter()
            .fold(initial, |acc, byte| (acc << 6) | u32::from(byte & 0x3F));
        self.bytes = &self.bytes[width..];
        if code_point < 0x10000 {
            return Some(code_point as u16);
        }
        let offset = code_point - 0x10000;
        self.low = Some(0xDC00 + (offset & 0x3FF) as u16);
        Some(0xD800 + (offset >> 10) as u16)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SyntaxError;

pub fn parse(text: &str) -> Result<Json<'_>, SyntaxError> {
    let mut parser = Parser {
        bytes: text.as_bytes(),
        pos: 0,
    };
    parser.whitespace();
    let value = parser.value(0)?;
    parser.whitespace();
    if parser.pos != parser.bytes.len() {
        return Err(SyntaxError);
    }
    Ok(value)
}

struct Parser<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<u8> {
        self.bytes.get(self.pos).copied()
    }

    fn whitespace(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.pos += 1;
        }
    }

    fn expect(&mut self, byte: u8) -> Result<(), SyntaxError> {
        if self.peek() == Some(byte) {
            self.pos += 1;
            Ok(())
        } else {
            Err(SyntaxError)
        }
    }

    fn value(&mut self, depth: usize) -> Result<Json<'a>, SyntaxError> {
        match self.peek().ok_or(SyntaxError)? {
            b'{' if depth >= BUILT_CONTAINER_DEPTH => {
                self.skip_container()?;
                Ok(Json::DeepObject)
            }
            b'[' if depth >= BUILT_CONTAINER_DEPTH => {
                self.skip_container()?;
                Ok(Json::DeepArray)
            }
            b'{' => self.object(depth),
            b'[' => self.array(depth),
            _ => self.scalar(),
        }
    }

    fn scalar(&mut self) -> Result<Json<'a>, SyntaxError> {
        match self.peek().ok_or(SyntaxError)? {
            b'"' => Ok(Json::String(self.string()?)),
            b't' => self.literal(b"true", Json::Bool(true)),
            b'f' => self.literal(b"false", Json::Bool(false)),
            b'n' => self.literal(b"null", Json::Null),
            b'-' | b'0'..=b'9' => Ok(Json::Number(self.number()?)),
            _ => Err(SyntaxError),
        }
    }

    fn literal(&mut self, word: &[u8], value: Json<'a>) -> Result<Json<'a>, SyntaxError> {
        if self.bytes[self.pos..].starts_with(word) {
            self.pos += word.len();
            Ok(value)
        } else {
            Err(SyntaxError)
        }
    }

    fn object(&mut self, depth: usize) -> Result<Json<'a>, SyntaxError> {
        self.pos += 1;
        self.whitespace();
        let mut fields = Vec::new();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(Json::Object(fields));
        }
        loop {
            let key = self.key()?;
            let value = self.value(depth + 1)?;
            fields.push((key, value));
            self.whitespace();
            match self.peek() {
                Some(b',') => {
                    self.pos += 1;
                    self.whitespace();
                }
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(Json::Object(fields));
                }
                _ => return Err(SyntaxError),
            }
        }
    }

    fn key(&mut self) -> Result<JsString<'a>, SyntaxError> {
        if self.peek() != Some(b'"') {
            return Err(SyntaxError);
        }
        let key = self.string()?;
        self.whitespace();
        self.expect(b':')?;
        self.whitespace();
        Ok(key)
    }

    fn array(&mut self, depth: usize) -> Result<Json<'a>, SyntaxError> {
        self.pos += 1;
        self.whitespace();
        let mut items = Vec::new();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(Json::Array(items));
        }
        loop {
            items.push(self.value(depth + 1)?);
            self.whitespace();
            match self.peek() {
                Some(b',') => {
                    self.pos += 1;
                    self.whitespace();
                }
                Some(b']') => {
                    self.pos += 1;
                    return Ok(Json::Array(items));
                }
                _ => return Err(SyntaxError),
            }
        }
    }

    /// Checks the array or object at the cursor without building it, with a stack in place of recursion.
    fn skip_container(&mut self) -> Result<(), SyntaxError> {
        // true for an object, false for an array.
        let mut open: Vec<bool> = Vec::new();
        loop {
            match self.peek().ok_or(SyntaxError)? {
                b'{' => {
                    self.pos += 1;
                    self.whitespace();
                    if self.peek() == Some(b'}') {
                        self.pos += 1;
                    } else {
                        open.push(true);
                        self.key()?;
                        continue;
                    }
                }
                b'[' => {
                    self.pos += 1;
                    self.whitespace();
                    if self.peek() == Some(b']') {
                        self.pos += 1;
                    } else {
                        open.push(false);
                        continue;
                    }
                }
                _ => {
                    self.scalar()?;
                }
            }
            loop {
                let Some(&is_object) = open.last() else {
                    return Ok(());
                };
                self.whitespace();
                match self.peek() {
                    Some(b',') => {
                        self.pos += 1;
                        self.whitespace();
                        if is_object {
                            self.key()?;
                        }
                        break;
                    }
                    Some(b'}') if is_object => {
                        self.pos += 1;
                        open.pop();
                    }
                    Some(b']') if !is_object => {
                        self.pos += 1;
                        open.pop();
                    }
                    _ => return Err(SyntaxError),
                }
            }
        }
    }

    fn number(&mut self) -> Result<f64, SyntaxError> {
        let start = self.pos;
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        match self.peek() {
            Some(b'0') => self.pos += 1,
            Some(b'1'..=b'9') => self.digits(),
            _ => return Err(SyntaxError),
        }
        if self.peek() == Some(b'.') {
            self.pos += 1;
            self.required_digits()?;
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            self.required_digits()?;
        }
        // The grammar above is a subset of what Rust parses, and both round to the nearest double.
        std::str::from_utf8(&self.bytes[start..self.pos])
            .ok()
            .and_then(|text| text.parse::<f64>().ok())
            .ok_or(SyntaxError)
    }

    fn digits(&mut self) {
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
    }

    fn required_digits(&mut self) -> Result<(), SyntaxError> {
        let start = self.pos;
        self.digits();
        if self.pos == start {
            return Err(SyntaxError);
        }
        Ok(())
    }

    fn string(&mut self) -> Result<JsString<'a>, SyntaxError> {
        self.pos += 1;
        let start = self.pos;
        loop {
            match self.peek().ok_or(SyntaxError)? {
                b'"' => {
                    let borrowed = &self.bytes[start..self.pos];
                    self.pos += 1;
                    return Ok(JsString(Cow::Borrowed(borrowed)));
                }
                b'\\' => break,
                0x00..=0x1F => return Err(SyntaxError),
                _ => self.pos += 1,
            }
        }
        let mut out = self.bytes[start..self.pos].to_vec();
        loop {
            match self.peek().ok_or(SyntaxError)? {
                b'"' => {
                    self.pos += 1;
                    return Ok(JsString(Cow::Owned(out)));
                }
                b'\\' => {
                    self.pos += 1;
                    self.escape(&mut out)?;
                }
                0x00..=0x1F => return Err(SyntaxError),
                byte => {
                    out.push(byte);
                    self.pos += 1;
                }
            }
        }
    }

    fn escape(&mut self, out: &mut Vec<u8>) -> Result<(), SyntaxError> {
        let byte = self.peek().ok_or(SyntaxError)?;
        self.pos += 1;
        let simple = match byte {
            b'"' => b'"',
            b'\\' => b'\\',
            b'/' => b'/',
            b'b' => 0x08,
            b'f' => 0x0C,
            b'n' => b'\n',
            b'r' => b'\r',
            b't' => b'\t',
            b'u' => {
                let unit = self.hex4()?;
                let code_point = if (0xD800..0xDC00).contains(&unit) {
                    match self.low_surrogate() {
                        Some(low) => 0x10000 + ((unit - 0xD800) << 10) + (low - 0xDC00),
                        None => unit,
                    }
                } else {
                    unit
                };
                push_wtf8(out, code_point);
                return Ok(());
            }
            _ => return Err(SyntaxError),
        };
        out.push(simple);
        Ok(())
    }

    fn low_surrogate(&mut self) -> Option<u32> {
        if !self.bytes[self.pos..].starts_with(b"\\u") {
            return None;
        }
        let saved = self.pos;
        self.pos += 2;
        match self.hex4() {
            Ok(low) if (0xDC00..0xE000).contains(&low) => Some(low),
            _ => {
                self.pos = saved;
                None
            }
        }
    }

    fn hex4(&mut self) -> Result<u32, SyntaxError> {
        let digits = self.bytes.get(self.pos..self.pos + 4).ok_or(SyntaxError)?;
        let mut value = 0;
        for digit in digits {
            value = (value << 4) | char::from(*digit).to_digit(16).ok_or(SyntaxError)?;
        }
        self.pos += 4;
        Ok(value)
    }
}

/// UTF-8 of a code point, with a surrogate written in the same three-byte form as any other BMP code point.
fn push_wtf8(out: &mut Vec<u8>, code_point: u32) {
    match code_point {
        0..=0x7F => out.push(code_point as u8),
        0x80..=0x7FF => out.extend_from_slice(&[
            0xC0 | (code_point >> 6) as u8,
            0x80 | (code_point & 0x3F) as u8,
        ]),
        0x800..=0xFFFF => out.extend_from_slice(&[
            0xE0 | (code_point >> 12) as u8,
            0x80 | ((code_point >> 6) & 0x3F) as u8,
            0x80 | (code_point & 0x3F) as u8,
        ]),
        _ => out.extend_from_slice(&[
            0xF0 | (code_point >> 18) as u8,
            0x80 | ((code_point >> 12) & 0x3F) as u8,
            0x80 | ((code_point >> 6) & 0x3F) as u8,
            0x80 | (code_point & 0x3F) as u8,
        ]),
    }
}

pub fn js_number(text: &str) -> f64 {
    let trimmed = text.trim_matches(is_js_whitespace);
    if trimmed.is_empty() {
        return 0.0;
    }
    match trimmed {
        "Infinity" | "+Infinity" => return f64::INFINITY,
        "-Infinity" => return f64::NEG_INFINITY,
        _ => {}
    }
    let radix = match trimmed.get(..2) {
        Some("0x" | "0X") => Some(16),
        Some("0o" | "0O") => Some(8),
        Some("0b" | "0B") => Some(2),
        _ => None,
    };
    if let Some(radix) = radix {
        let digits = &trimmed[2..];
        if digits.is_empty() || !digits.chars().all(|c| c.is_digit(radix)) {
            return f64::NAN;
        }
        return digits.chars().fold(0.0, |acc, c| {
            acc * f64::from(radix) + f64::from(c.to_digit(radix).unwrap_or(0))
        });
    }
    if is_decimal_literal(trimmed.as_bytes()) {
        trimmed.parse::<f64>().unwrap_or(f64::NAN)
    } else {
        f64::NAN
    }
}

fn is_decimal_literal(bytes: &[u8]) -> bool {
    let mut pos = usize::from(matches!(bytes.first(), Some(b'+' | b'-')));
    let count_digits = |pos: &mut usize| {
        let start = *pos;
        while bytes.get(*pos).is_some_and(u8::is_ascii_digit) {
            *pos += 1;
        }
        *pos - start
    };
    let mut mantissa = count_digits(&mut pos);
    if bytes.get(pos) == Some(&b'.') {
        pos += 1;
        mantissa += count_digits(&mut pos);
    }
    if mantissa == 0 {
        return false;
    }
    if matches!(bytes.get(pos), Some(b'e' | b'E')) {
        pos += 1;
        if matches!(bytes.get(pos), Some(b'+' | b'-')) {
            pos += 1;
        }
        if count_digits(&mut pos) == 0 {
            return false;
        }
    }
    pos == bytes.len()
}

fn is_js_whitespace(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n' | '\u{0B}' | '\u{0C}' | '\r' | ' ' | '\u{A0}' | '\u{1680}' | '\u{2000}'
            ..='\u{200A}'
                | '\u{2028}'
                | '\u{2029}'
                | '\u{202F}'
                | '\u{205F}'
                | '\u{3000}'
                | '\u{FEFF}'
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn string(text: &str) -> JsString<'static> {
        match parse(text).unwrap() {
            Json::String(value) => value.into_owned(),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn accepts_and_refuses_what_json_parse_does() {
        for valid in [
            "0",
            "-0",
            " \t\r\n{} ",
            "[]",
            "[1,[2,[3,[4,[5,{\"a\":[{}]}]]]]]",
            "{\"a\":{\"b\":{\"c\":{\"d\":[1,{\"e\":null}]}}}}",
            "\"\\u0000\\/\\b\"",
            "1.5e-3",
            "1E+2",
            "{\"a\":1,\"a\":2}",
            "\"\u{7f}é\"",
        ] {
            assert!(parse(valid).is_ok(), "{valid}");
        }
        for invalid in [
            "",
            " ",
            "01",
            "+1",
            "1.",
            ".5",
            "1e",
            "NaN",
            "Infinity",
            "[1,]",
            "{\"a\":1,}",
            "{'a':1}",
            "\"\t\"",
            "\"\\x41\"",
            "\"\\u12\"",
            "\u{feff}{}",
            "{} x",
            "[[[[[[1]]]]]",
            "[[[[[[1]]]]]]]",
            "{\"a\":{\"b\":{\"c\":{\"d\":[1,]}}}}",
            "{\"a\":{\"b\":{\"c\":{\"d\" 1}}}}",
            "tru",
            "nul",
        ] {
            assert_eq!(parse(invalid), Err(SyntaxError), "{invalid}");
        }
    }

    #[test]
    fn checks_deep_values_without_recursion() {
        let deep = format!("{}{}", "[".repeat(1_000_000), "]".repeat(1_000_000));
        assert_eq!(
            parse(&deep).unwrap(),
            Json::Array(vec![Json::Array(vec![Json::Array(vec![Json::DeepArray])])])
        );
        assert!(parse(&deep[1..]).is_err());
    }

    #[test]
    fn reads_numbers_as_doubles() {
        let number = |text: &str| match parse(text).unwrap() {
            Json::Number(value) => value,
            other => panic!("{other:?}"),
        };
        assert_eq!(number("5.0"), 5.0);
        assert_eq!(number("1e3"), 1000.0);
        assert_eq!(number("9007199254740993"), 9_007_199_254_740_992.0);
        assert!(number("-0").is_sign_negative());
        assert_eq!(number("1e400"), f64::INFINITY);
    }

    #[test]
    fn keeps_lone_surrogates_and_writes_them_as_replacement_characters() {
        assert_eq!(string("\"\\ud83d\\ude00\"").as_bytes(), "😀".as_bytes());
        let lone = string("\"a\\ud800b\\udc00\"");
        assert_eq!(lone.utf16_len(), 4);
        assert_eq!(&*lone.to_utf8(), "a\u{fffd}b\u{fffd}".as_bytes());
        assert_eq!(
            &*string("\"\\ud800\\ud800\\udc00\"").to_utf8(),
            "\u{fffd}𐀀".as_bytes()
        );
        assert_eq!(string("\"\\u00e9\\u20AC\"").as_bytes(), "é€".as_bytes());
    }

    #[test]
    fn orders_strings_by_utf16_code_units() {
        let cases = [
            ("\"a\"", "\"b\"", Ordering::Less),
            ("\"ab\"", "\"a\"", Ordering::Greater),
            // U+1F600 is the pair D83D DE00, which sorts before U+FFFD in UTF-16 and after it in UTF-8.
            ("\"😀\"", "\"\u{fffd}\"", Ordering::Less),
            ("\"x😀\"", "\"x\u{e000}\"", Ordering::Less),
            ("\"\\ud800\"", "\"\u{e000}\"", Ordering::Less),
            ("\"é\"", "\"é\"", Ordering::Equal),
        ];
        for (a, b, expected) in cases {
            assert_eq!(string(a).cmp_utf16(&string(b)), expected, "{a} {b}");
        }
    }

    #[test]
    fn reads_header_numbers_as_number_does() {
        let cases = [
            ("1794418509351", 1_794_418_509_351.0),
            (" 12\n", 12.0),
            ("", 0.0),
            ("12.0", 12.0),
            ("1e3", 1000.0),
            ("0x10", 16.0),
            ("-5", -5.0),
            ("+.5", 0.5),
            ("1.", 1.0),
        ];
        for (text, expected) in cases {
            assert_eq!(js_number(text), expected, "{text:?}");
        }
        for text in ["12abc", "1_000", "-0x10", "inf", ".", "1e", "0x"] {
            assert!(js_number(text).is_nan(), "{text:?}");
        }
        assert_eq!(js_number("-Infinity"), f64::NEG_INFINITY);
    }
}
